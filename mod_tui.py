#!/usr/bin/env python3
"""Terminal UI for Darktide mods: lists everything installed and lets you
toggle them on/off.

This install runs AML (Automatic Mod Loader), which patches
mods/base/mod_manager.lua to scan every mod folder directly and compute
load order itself - it unconditionally ignores mod_load_order.txt. AML's
own documented way to disable a mod is to prepend an underscore to its
folder name, so that's what toggling here does: renames "Name" <->
"_Name" on disk. There is no separate save step - toggling immediately
renames the folder, since a half-applied rename set has no meaningful
"undo" the way an edited text file would.

Press 'u' to fetch update availability from Nexus Mods (same source as
check_updates.py / run_check.sh).
"""
import curses
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

MODS_DIR = Path(
    "/home/ginhikari/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    "/steamapps/common/Warhammer 40,000 DARKTIDE/mods"
)
ALWAYS_ON = {"base", "dmf"}

NEXUS_CONFIG_DIR = Path.home() / ".config" / "nexus-mod-checker"
NEXUS_API_KEY_FILE = NEXUS_CONFIG_DIR / "api_key"
NEXUS_MOD_IDS_FILE = NEXUS_CONFIG_DIR / "mod_ids.txt"
NEXUS_GAME_DOMAIN = "warhammer40kdarktide"
NEXUS_API_BASE = "https://api.nexusmods.com/v1"
NEXUS_MOD_URL = "https://www.nexusmods.com/{}/mods/{}"
TIMESTAMP_RE = re.compile(r"(\d{9,10})(?:\.\d+)?$")


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def load_nexus_index():
    """Map installed mod folder name -> (mod_id, installed_timestamp).

    mod_ids.txt lines look like 'SMOG Cleaner-847-1-1-1777899913\t847'
    (archive-style name with the mod id and a timestamp baked in). Folder
    names in MODS_DIR don't match that string exactly, so match by
    normalized prefix: the folder's normalized name has to be a prefix of
    the entry's normalized name.
    """
    if not NEXUS_MOD_IDS_FILE.exists():
        return {}

    entries = []
    for line in NEXUS_MOD_IDS_FILE.read_text().splitlines():
        line = line.strip()
        if not line or "\t" not in line:
            continue
        name, modid = line.split("\t")
        m = TIMESTAMP_RE.search(name)
        installed_ts = int(m.group(1)) if m else None
        entries.append((name, int(modid), installed_ts))

    display_names = {
        item.name.lstrip("_") for item in MODS_DIR.iterdir() if item.is_dir()
    }
    index = {}
    for display_name in display_names:
        norm_folder = _normalize(display_name)
        if not norm_folder:
            continue
        for name, modid, installed_ts in entries:
            if _normalize(name).startswith(norm_folder):
                index[display_name] = (modid, installed_ts)
                break
    return index


def fetch_mod_info(mod_id, api_key):
    url = f"{NEXUS_API_BASE}/games/{NEXUS_GAME_DOMAIN}/mods/{mod_id}.json"
    req = urllib.request.Request(
        url, headers={"apikey": api_key, "User-Agent": "darktide-mod-tui/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def load_state():
    """Scan MODS_DIR the way AML does: a folder is active if it doesn't
    start with '_' and contains a manifest matching its own (unprefixed)
    name. Returns (rows, active_set, dir_names) where dir_names maps
    display name -> actual on-disk folder name (so callers know exactly
    what to rename).
    """
    dir_names = {}
    active_set = set()
    for item in sorted(MODS_DIR.iterdir()):
        if not item.is_dir() or item.name in ALWAYS_ON:
            continue
        is_active = not item.name.startswith("_")
        display_name = item.name if is_active else item.name[1:]
        manifest = item / f"{display_name}.mod"
        if not manifest.exists():
            continue
        dir_names[display_name] = item.name
        if is_active:
            active_set.add(display_name)

    rows = sorted(dir_names, key=str.lower)
    return rows, active_set, dir_names


def toggle_mod(dir_names, display_name, want_active):
    """Rename display_name's folder to add/remove the leading underscore.
    Returns the error message on failure, or None on success.
    """
    current_dir_name = dir_names[display_name]
    is_active = not current_dir_name.startswith("_")
    if is_active == want_active:
        return None
    new_dir_name = display_name if want_active else f"_{display_name}"
    try:
        (MODS_DIR / current_dir_name).rename(MODS_DIR / new_dir_name)
    except OSError as e:
        return f"{display_name}: {e}"
    dir_names[display_name] = new_dir_name
    return None


def fetch_updates(stdscr, rows, w):
    """Fetch update availability for all matchable rows, showing progress
    as it goes. Returns dict: row name -> (installed_ts, latest_ts,
    latest_version, url) for rows where an update is available.
    """
    if not NEXUS_API_KEY_FILE.exists():
        return {}, f"no Nexus API key at {NEXUS_API_KEY_FILE}"

    api_key = NEXUS_API_KEY_FILE.read_text().strip()
    nexus_index = load_nexus_index()
    matched = [(name, modid, ts) for name, (modid, ts) in nexus_index.items() if name in rows]

    outdated = {}
    errors = 0
    for i, (name, modid, installed_ts) in enumerate(matched):
        msg = f" checking updates... {i + 1}/{len(matched)}: {name}"
        stdscr.addstr(2, 0, msg[: w - 1].ljust(w - 1), curses.color_pair(3))
        stdscr.refresh()
        try:
            info = fetch_mod_info(modid, api_key)
            latest_ts = info.get("updated_timestamp")
            if installed_ts is not None and latest_ts is not None and latest_ts > installed_ts:
                url = NEXUS_MOD_URL.format(NEXUS_GAME_DOMAIN, modid)
                outdated[name] = (installed_ts, latest_ts, info.get("version"), url)
        except Exception:
            errors += 1
        time.sleep(0.3)

    unmatched = len(rows) - len(matched)
    status = f"update check done: {len(outdated)} outdated, {len(matched)} checked"
    if unmatched:
        status += f", {unmatched} not in mod_ids.txt"
    if errors:
        status += f", {errors} error(s)"
    return outdated, status


def run(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_RED, -1)
    curses.init_pair(3, curses.COLOR_YELLOW, -1)

    rows, active_set, dir_names = load_state()
    cursor = 0
    top = 0
    status = ""
    updates = {}

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        list_h = h - 4

        title = " Darktide Mods (AML: toggling renames folders) "
        stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
        active_count = sum(1 for r in rows if r in active_set)
        subtitle = f" {active_count} active / {len(rows)} installed "
        stdscr.addstr(1, max(0, (w - len(subtitle)) // 2), subtitle, curses.A_DIM)

        if rows and rows[cursor] in updates:
            _, _, _, url = updates[rows[cursor]]
            stdscr.addstr(2, 0, f" {url}"[: w - 1].ljust(w - 1), curses.color_pair(3))

        if cursor < top:
            top = cursor
        elif cursor >= top + list_h:
            top = cursor - list_h + 1

        for i in range(list_h):
            idx = top + i
            if idx >= len(rows):
                break
            name = rows[idx]
            is_active = name in active_set
            mark = "[x]" if is_active else "[ ]"
            color = curses.color_pair(1) if is_active else curses.color_pair(2)
            line = f" {mark} {name}"
            if name in updates:
                _, _, latest_version, _ = updates[name]
                line += f"  (update: {latest_version})" if latest_version else "  (update available)"
            attr = color
            if name in updates:
                attr = curses.color_pair(3)
            if idx == cursor:
                attr |= curses.A_REVERSE
            stdscr.addstr(3 + i, 0, line[: w - 1].ljust(w - 1), attr)

        footer = " ↑/↓ or j/k: move   space/enter: toggle   r: rescan disk   u: check updates   q: quit "
        stdscr.addstr(h - 1, 0, footer[: w - 1], curses.A_DIM)
        if status:
            stdscr.addstr(h - 2, 0, status[: w - 1], curses.color_pair(3) | curses.A_BOLD)

        stdscr.refresh()
        key = stdscr.getch()

        if key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
            status = ""
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(rows) - 1, cursor + 1)
            status = ""
        elif key in (ord(" "), curses.KEY_ENTER, 10, 13):
            if rows:
                name = rows[cursor]
                want_active = name not in active_set
                error = toggle_mod(dir_names, name, want_active)
                if error:
                    status = f"rename failed: {error}"
                else:
                    if want_active:
                        active_set.add(name)
                    else:
                        active_set.discard(name)
                    state = "enabled" if want_active else "disabled"
                    status = f"{name}: {state} ({dir_names[name]})"
        elif key == ord("u"):
            updates, status = fetch_updates(stdscr, rows, w)
        elif key == ord("r"):
            rows, active_set, dir_names = load_state()
            cursor = min(cursor, max(0, len(rows) - 1))
            status = f"rescanned: {len(rows)} mods on disk"
        elif key == ord("q"):
            break


def main():
    if not MODS_DIR.exists():
        print(f"Darktide mods directory not found: {MODS_DIR}")
        raise SystemExit(1)
    curses.wrapper(run)


if __name__ == "__main__":
    main()
