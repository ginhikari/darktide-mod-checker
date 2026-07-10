#!/usr/bin/env python3
"""Check Nexus Mods for updates to installed Darktide mods."""
import json
import re
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nexus-mod-checker"
API_KEY = (CONFIG_DIR / "api_key").read_text().strip()
MOD_IDS_FILE = CONFIG_DIR / "mod_ids.txt"
GAME_DOMAIN = "warhammer40kdarktide"
API_BASE = "https://api.nexusmods.com/v1"

TIMESTAMP_RE = re.compile(r"(\d{9,10})(?:\.\d+)?$")


def load_installed():
    entries = []
    for line in MOD_IDS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        name, modid = line.split("\t")
        m = TIMESTAMP_RE.search(name)
        installed_ts = int(m.group(1)) if m else None
        entries.append((name, int(modid), installed_ts))
    return entries


def get_mod_info(mod_id):
    url = f"{API_BASE}/games/{GAME_DOMAIN}/mods/{mod_id}.json"
    req = urllib.request.Request(url, headers={"apikey": API_KEY, "User-Agent": "personal-update-checker/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def main():
    installed = load_installed()
    up_to_date = []
    outdated = []
    errors = []

    for name, modid, installed_ts in installed:
        try:
            info = get_mod_info(modid)
            latest_ts = info.get("updated_timestamp")
            entry = {
                "installed_folder": name,
                "mod_id": modid,
                "nexus_name": info.get("name"),
                "installed_timestamp": installed_ts,
                "latest_timestamp": latest_ts,
                "latest_version": info.get("version"),
            }
            if installed_ts is not None and latest_ts is not None and latest_ts > installed_ts:
                outdated.append(entry)
            else:
                up_to_date.append(entry)
        except urllib.error.HTTPError as e:
            errors.append(f"{name} (id {modid}): HTTP {e.code}")
        except Exception as e:
            errors.append(f"{name} (id {modid}): {e}")
        time.sleep(0.3)

    print(f"Checked {len(installed)} mods: {len(outdated)} outdated, {len(up_to_date)} up to date, {len(errors)} errors\n")

    if outdated:
        print("=== UPDATES AVAILABLE ===")
        for e in outdated:
            print(f"  {e['nexus_name']} (id {e['mod_id']}): installed {e['installed_timestamp']} -> latest {e['latest_timestamp']} ({e['latest_version']})")

    if errors:
        print("\n=== ERRORS ===")
        for e in errors:
            print(f"  {e}")

    if outdated:
        names = ", ".join(e["nexus_name"] or f"id {e['mod_id']}" for e in outdated[:5])
        more = f" and {len(outdated) - 5} more" if len(outdated) > 5 else ""
        body = f"{len(outdated)} Darktide mod(s) have updates: {names}{more}"
    else:
        body = "All Darktide mods are up to date."
    try:
        subprocess.run(["notify-send", "Darktide Mod Checker", body], check=False)
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
