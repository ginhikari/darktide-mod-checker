# darktide-mod-checker

A small local tool that checks installed Warhammer 40,000: Darktide mods
against Nexus Mods for available updates, since the game has no Steam
Workshop and Vortex doesn't run reliably on Linux.

Runs on a cron schedule (every 2 days), compares each installed mod's
timestamp against the latest version on Nexus, and sends a desktop
notification summarizing what's outdated.

## How it works

- `mod_ids.txt` maps each installed mod's folder name (which encodes its
  Nexus mod ID and install timestamp) to that numeric mod ID.
- `check_updates.py` reads that file, queries the Nexus Mods API for each
  mod's current `updated_timestamp`, and compares it against what's
  installed.
- `run_check.sh` is the cron entry point — sets up the D-Bus session
  environment (needed for desktop notifications from cron) and runs the
  checker, logging output.

## Setup on a new machine

1. Generate a personal Nexus Mods API key: account Settings → API Keys
   (no Premium required for this — Premium is only needed for automated
   *downloads*, not update checks).
2. Save it to `~/.config/nexus-mod-checker/api_key` (not committed to this
   repo — keep it out of version control).
3. Copy `check_updates.py`, `run_check.sh`, and `mod_ids.txt` into
   `~/.config/nexus-mod-checker/`.
4. `chmod 600 ~/.config/nexus-mod-checker/api_key`
5. `chmod +x ~/.config/nexus-mod-checker/run_check.sh`
6. Add to crontab: `crontab -e`, then add:
   ```
   0 12 */2 * * /home/YOUR_USER/.config/nexus-mod-checker/run_check.sh
   ```
7. Requires `libnotify-bin` (`notify-send`) for desktop notifications.

## Known limitation

Nexus's API only provides direct file-download links to Premium accounts.
Without Premium, this tool tells you *which* mods have updates — actually
downloading the new file still means clicking "Download" on the mod's
Nexus page yourself.

## Regenerating `mod_ids.txt`

If your installed mod list changes, `mod_ids.txt` needs updating. Each line
is `<installed-folder-name>	<nexus-mod-id>` (tab-separated). The mod ID is
extracted from Vortex-style download folder names, which follow the
pattern `<Name>-<ModID>-<version>-<unixTimestamp>`.

## `nxm_handler.py` / `mod_tui.py` (superseded, kept for reference)

Two follow-on experiments toward closing the "known limitation" above
without needing Premium:

- **`nxm_handler.py`** — registers as the system's `nxm://` protocol
  handler. Clicking "Mod Manager Download" on a mod's Nexus page (instead
  of the plain download button) fires an `nxm://` link with a short-lived,
  single-use API token; this script catches it, resolves the real
  download URL via the Nexus API, extracts the archive, and installs it
  straight into the Darktide `mods/` folder — one click per mod instead
  of manual download-extract-move.
- **`mod_tui.py`** — a `curses` terminal UI listing every installed mod
  with active/inactive state (as tracked by `mods/mod_load_order.txt`),
  letting you toggle mods on/off without hand-editing that file.

Both worked, but ended up superseded by
[nomm](https://github.com/Allexio/nomm), a proper GUI mod manager that
covers this same ground (and more — full download automation, no
per-mod click required) more completely. Left here in case they're useful
as a lighter-weight reference, or if `nomm` ever stops being maintained.
Both hardcode this machine's paths (`/home/ginhikari/...`) rather than
deriving them — adjust before reusing elsewhere.
