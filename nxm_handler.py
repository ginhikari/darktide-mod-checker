#!/usr/bin/env python3
"""nxm:// protocol handler: catches "Mod Manager Download" clicks from the
Nexus Mods website, downloads the file via the Nexus API, and installs it
straight into the Darktide mods directory.

Registered as the x-scheme-handler/nxm default application. Nexus invokes
it with a single argv[1] like:
  nxm://warhammer40kdarktide/mods/663/files/12345?key=...&expires=...
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "nexus-mod-checker"
API_KEY = (CONFIG_DIR / "api_key").read_text().strip()
MOD_IDS_FILE = CONFIG_DIR / "mod_ids.txt"
LOG_FILE = CONFIG_DIR / "install.log"
API_BASE = "https://api.nexusmods.com/v1"
GAME_DOMAIN = "warhammer40kdarktide"

MODS_DIR = Path(
    "/home/ginhikari/.var/app/com.valvesoftware.Steam/.local/share/Steam"
    "/steamapps/common/Warhammer 40,000 DARKTIDE/mods"
)

NXM_RE = re.compile(
    r"^nxm://(?P<domain>[^/]+)/mods/(?P<mod_id>\d+)/files/(?P<file_id>\d+)\?(?P<query>.+)$"
)


def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with LOG_FILE.open("a") as f:
        f.write(f"[{ts}] {msg}\n")
    print(msg)


def notify(title, body, urgency="normal"):
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, title, body], check=False
        )
    except FileNotFoundError:
        pass


def api_get(path, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{API_BASE}{path}"
    if query:
        url += f"?{query}"
    req = urllib.request.Request(
        url, headers={"apikey": API_KEY, "User-Agent": "darktide-nxm-handler/1.0"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def parse_query(qs):
    parts = {}
    for kv in qs.split("&"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            parts[k] = v
    return parts


def download_file(url, dest_dir):
    dest_dir.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "darktide-nxm-handler/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename="?([^";]+)"?', cd)
        filename = m.group(1) if m else url.split("/")[-1].split("?")[0]
        dest = dest_dir / filename
        with dest.open("wb") as f:
            shutil.copyfileobj(resp, f)
    return dest


def extract_archive(archive_path, extract_to):
    extract_to.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["7z", "x", "-y", f"-o{extract_to}", str(archive_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"7z extraction failed: {result.stderr}")


def find_mod_folders(extracted_root):
    """A DMF-style mod is a folder containing a <name>.mod file. Some
    archives have the mod folder at the top level, some nest it one level
    deeper - search both."""
    found = []
    for mod_manifest in extracted_root.rglob("*.mod"):
        found.append(mod_manifest.parent)
    # de-duplicate while preserving order
    seen = set()
    unique = []
    for folder in found:
        if folder not in seen:
            seen.add(folder)
            unique.append(folder)
    return unique


def install_mod_folder(src_folder):
    dest = MODS_DIR / src_folder.name
    if dest.exists():
        backup = MODS_DIR / f"{src_folder.name}.bak-{int(time.time())}"
        log(f"backing up existing '{dest.name}' -> '{backup.name}'")
        dest.rename(backup)
    shutil.move(str(src_folder), str(dest))
    log(f"installed '{src_folder.name}' -> {dest}")
    return dest


def update_mod_ids_entry(mod_id, folder_name, timestamp):
    lines = []
    if MOD_IDS_FILE.exists():
        lines = MOD_IDS_FILE.read_text().splitlines()
    kept = [ln for ln in lines if not ln.strip().endswith(f"\t{mod_id}")]
    kept.append(f"{folder_name}-{timestamp}\t{mod_id}")
    MOD_IDS_FILE.write_text("\n".join(kept) + "\n")
    log(f"updated mod_ids.txt entry for mod {mod_id} (timestamp {timestamp})")


def main():
    if len(sys.argv) < 2:
        log("no nxm URL passed")
        sys.exit(1)

    nxm_url = sys.argv[1]
    log(f"received: {nxm_url}")

    m = NXM_RE.match(nxm_url)
    if not m:
        log(f"failed to parse nxm URL: {nxm_url}")
        notify("Darktide Mod Install", "Couldn't parse the nxm:// link", "critical")
        sys.exit(1)

    domain = m.group("domain")
    mod_id = m.group("mod_id")
    file_id = m.group("file_id")
    query = parse_query(m.group("query"))
    key = query.get("key")
    expires = query.get("expires")

    if domain != GAME_DOMAIN:
        log(f"ignoring nxm link for different game: {domain}")
        notify("Darktide Mod Install", f"Link is for '{domain}', not Darktide - ignored")
        sys.exit(0)

    try:
        notify("Darktide Mod Install", f"Fetching mod {mod_id}...")

        mod_info = api_get(f"/games/{domain}/mods/{mod_id}.json")
        mod_name = mod_info.get("name", f"mod {mod_id}")
        latest_ts = mod_info.get("updated_timestamp")

        links = api_get(
            f"/games/{domain}/mods/{mod_id}/files/{file_id}/download_link.json",
            key=key, expires=expires,
        )
        if not links:
            raise RuntimeError("no download mirrors returned")
        download_url = links[0]["URI"]

        with tempfile.TemporaryDirectory(prefix="darktide-mod-") as tmpdir:
            tmp = Path(tmpdir)
            log(f"downloading '{mod_name}' from {download_url[:80]}...")
            archive = download_file(download_url, tmp / "dl")
            log(f"downloaded {archive.name} ({archive.stat().st_size} bytes)")

            extract_dir = tmp / "extracted"
            extract_archive(archive, extract_dir)

            mod_folders = find_mod_folders(extract_dir)
            if not mod_folders:
                raise RuntimeError("no *.mod manifest found in the archive - unexpected layout")

            installed_names = []
            for folder in mod_folders:
                dest = install_mod_folder(folder)
                installed_names.append(dest.name)

            update_mod_ids_entry(mod_id, installed_names[0], latest_ts or int(time.time()))

        notify(
            "Darktide Mod Install",
            f"Installed/updated: {', '.join(installed_names)}",
        )
        log(f"done: {mod_name} ({', '.join(installed_names)})")

    except Exception as e:
        log(f"ERROR installing mod {mod_id}: {e}")
        notify("Darktide Mod Install", f"Failed: {e}", "critical")
        sys.exit(1)


if __name__ == "__main__":
    main()
