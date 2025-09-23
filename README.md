# Taskware

A modern GNOME/GTK app that unifies cron and systemd timers into a user-friendly, Ubuntu-first Task Scheduler with natural language scheduling, logging, and monitoring.

## Status
MVP scaffold: runnable GTK4 + libadwaita window with tabs for User/System jobs and backend stubs.

## Requirements (Ubuntu 22.04 LTS)
Install system packages:

```bash
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
```

Optional (dev tooling):
```bash
sudo apt install -y python3-venv python3-pip
```

## Setup
From the repository root:

```bash
# (Optional) create venv
python3 -m venv .venv
. .venv/bin/activate

# Install project (no extra deps required)
pip install -e .
```

### Optional (for AI helper window sizing)
Chromium or a Chromium-based browser is recommended so the AI helper window can open at a specific size/position reliably:

```bash
# One option on Ubuntu
sudo snap install chromium
```

Firefox works too, but some Wayland sessions ignore window size/position hints.

## Run

```bash
# Either via entrypoint
taskware

# Or module-style
python -m taskware
```

## Desktop launcher (GNOME Applications menu)

To add Taskware to your Applications menu with a desktop entry, use the provided helper script:

```bash
bash scripts/install_desktop.sh
```

What this does:

- Creates a user-local launcher script at `~/.local/bin/taskware-launch` that sets `PYTHONPATH=src` and runs `python3 -m taskware`.
- Installs a desktop entry at `~/.local/share/applications/taskware.desktop` so you can launch Taskware from the Activities/Applications menu.
- Refreshes the desktop database with `update-desktop-database` if available.

After installation, search for "Taskware" in your app launcher.

Uninstall (manual):

```bash
rm -f ~/.local/bin/taskware-launch
rm -f ~/.local/share/applications/taskware.desktop
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

## Project Structure
```
src/
  taskware/
    app.py
    __main__.py
    windows/
      main_window.py
      add_job_dialog.py
      salt_settings_dialog.py
    backend/
      __init__.py
      cron.py
      salt_exporter.py
```

## Features
- Natural-language scheduling with fallback parsing for times like "noon", "midnight", and compact AM/PM inputs (e.g., `5p`, `7:15a`).
- Weekday phrases including combined days (e.g., "every monday, wednesday and thursday") and biweekly ("every other tuesday").
- Schedule builder keeps UI and cron in sync and supports a time window for every minute / every N minutes / hourly modes.
- AI button next to the Command field opens a small external browser window to a cron command generator.
- Discreet Settings (gear icon) includes a Salt Integration dialog to export Taskware jobs as Salt states (SLS).

## AI Assistant
- Click the "AI" button on the Add Job dialog (next to the Command field).
  - If Chromium/Chrome/Brave is installed, Taskware opens a small app-style window (~686×765) near the right edge.
  - If only Firefox is present, Taskware requests a smaller sized window. Some Wayland setups may ignore these size/position hints.
  - The page cannot be embedded due to site security policies; it opens in the system browser by design.

Troubleshooting (AI window sizing)
- If Firefox opens full size or centered on Wayland, install Chromium for reliable sizing:
  - `sudo snap install chromium`

## Salt Integration (Optional)
- Open the gear icon in the main window to access Salt Integration settings.
- You can configure master URL/auth and generate SLS files for your current user jobs to a directory you choose.
- Exported SLS uses `cron.present`. Biweekly jobs include a lightweight wrapper script and a weekly cron entry.
- Future options may include push via `salt-api`, `salt-ssh`, or GitFS.

## Next Steps (Roadmap excerpt)
- Push-to-Salt flows via `salt-api` or `salt-ssh` (apply/remove, dry-run/test mode).
- Calendar/timeline view and job details with logs.
- Systemd timers via D-Bus and polkit flows.

## License
GPL-3.0-or-later
