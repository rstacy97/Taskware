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
    backend/
      __init__.py
      cron.py
```

## Next Steps (Roadmap excerpt)
- Add crontab parsing/writing for user jobs.
- Add natural language → cron conversion.
- Introduce systemd timers via D-Bus and polkit flows.
- Calendar/timeline view and job details with logs.

## License
GPL-3.0-or-later
