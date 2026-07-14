#!/usr/bin/env python3
"""Terminal UI for Darktide mods: lists everything installed, shows which
are active (present in mod_load_order.txt) vs inactive, and lets you
toggle them on/off. Load order among already-active mods is preserved;
newly-activated mods are appended to the end of the list.
"""
import curses
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
            attr = color
            if idx == cursor:
                attr |= curses.A_REVERSE
            stdscr.addstr(3 + i, 0, line[: w - 1].ljust(w - 1), attr)

        footer = " ↑/↓ or j/k: move   space/enter: toggle   s: save   q: quit "
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
