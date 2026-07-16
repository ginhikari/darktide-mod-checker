#!/usr/bin/env python3
"""Terminal UI for Darktide mods: lists everything installed, shows which
are active (present in mod_load_order.txt) vs inactive, and lets you
toggle them on/off. Load order among already-active mods is preserved;
newly-activated mods are appended to the end of the list.

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
LOAD_ORDER_FILE = MODS_DIR / "mod_load_order.txt"
LOAD_ORDER_HEADER = (
    "-- ################################################################\n"
    "-- Enter user mod names below, separated by line.\n"
    "-- Order in the list determines the order in which mods are loaded.\n"
    "-- Do not rename a mod's folders.\n"
    "-- You do not need to include 'base' or 'dmf' mod folders.\n"
    "-- ################################################################\n"
)
ALWAYS_ON = {"base", "dmf"}

NEXUS_CONFIG_DIR = Path.home() / ".config" / "nexus-mod-checker"
NEXUS_API_KEY_FILE = NEXUS_CONFIG_DIR / "api_key"
NEXUS_MOD_IDS_FILE = NEXUS_CONFIG_DIR / "mod_ids.txt"
NEXUS_GAME_DOMAIN = "warhammer40kdarktide"
NEXUS_API_BASE = "https://api.nexusmods.com/v1"
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

    folders = [item.name for item in MODS_DIR.iterdir() if item.is_dir()]
    index = {}
    for folder in folders:
        norm_folder = _normalize(folder)
        if not norm_folder:
            continue
        for name, modid, installed_ts in entries:
            if _normalize(name).startswith(norm_folder):
                index[folder] = (modid, installed_ts)
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
    installed = {}
    for item in sorted(MODS_DIR.iterdir()):
        if item.is_dir() and item.name not in ALWAYS_ON:
            manifest = item / f"{item.name}.mod"
            if manifest.exists():
                installed[item.name] = True

    active_order = []
    broken = []
    if LOAD_ORDER_FILE.exists():
        for line in LOAD_ORDER_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("--"):
                continue
            active_order.append(line)
            if line not in installed:
                broken.append(line)

    active_set = set(active_order)
    # active mods first, in existing load order; then inactive-but-installed
    rows = [name for name in active_order if name in installed]
    rows += sorted(n for n in installed if n not in active_set)
    return rows, active_set, broken


def save_state(rows, active_set):
    lines = [name for name in rows if name in active_set]
    LOAD_ORDER_FILE.write_text(LOAD_ORDER_HEADER + "\n".join(lines) + "\n")


def fetch_updates(stdscr, rows, w):
    """Fetch update availability for all matchable rows, showing progress
    as it goes. Returns dict: row name -> (installed_ts, latest_ts,
    latest_version) for rows where an update is available.
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
                outdated[name] = (installed_ts, latest_ts, info.get("version"))
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

    rows, active_set, broken = load_state()
    dirty = False
    cursor = 0
    top = 0
    status = ""
    updates = {}

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        list_h = h - 4

        title = " Darktide Mods "
        stdscr.addstr(0, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
        active_count = sum(1 for r in rows if r in active_set)
        subtitle = f" {active_count} active / {len(rows)} installed "
        if broken:
            subtitle += f"  ({len(broken)} broken reference(s) in load order) "
        stdscr.addstr(1, max(0, (w - len(subtitle)) // 2), subtitle, curses.A_DIM)

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
                _, _, latest_version = updates[name]
                line += f"  (update: {latest_version})" if latest_version else "  (update available)"
            attr = color
            if name in updates:
                attr = curses.color_pair(3)
            if idx == cursor:
                attr |= curses.A_REVERSE
            stdscr.addstr(3 + i, 0, line[: w - 1].ljust(w - 1), attr)

        footer = " ↑/↓ or j/k: move   space/enter: toggle   s: save   u: check updates   q: quit "
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
                if name in active_set:
                    active_set.discard(name)
                else:
                    active_set.add(name)
                dirty = True
                status = "unsaved changes - press 's' to write mod_load_order.txt"
        elif key == ord("s"):
            save_state(rows, active_set)
            dirty = False
            status = f"saved to {LOAD_ORDER_FILE.name}"
        elif key == ord("u"):
            updates, status = fetch_updates(stdscr, rows, w)
        elif key == ord("q"):
            if dirty:
                stdscr.addstr(
                    2, 0,
                    "unsaved changes - press 'q' again to discard, 's' to save first"[: w - 1],
                    curses.color_pair(2) | curses.A_BOLD,
                )
                stdscr.refresh()
                confirm = stdscr.getch()
                if confirm == ord("q"):
                    break
                elif confirm == ord("s"):
                    save_state(rows, active_set)
                    break
            else:
                break


def main():
    if not MODS_DIR.exists():
        print(f"Darktide mods directory not found: {MODS_DIR}")
        raise SystemExit(1)
    curses.wrapper(run)


if __name__ == "__main__":
    main()
