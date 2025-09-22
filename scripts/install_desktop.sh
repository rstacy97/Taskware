#!/usr/bin/env bash
set -euo pipefail

# Install a Taskware launcher into the user's Applications menu (Freedesktop)
# This script installs a wrapper and a .desktop entry under ~/.local

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_ID="taskware"
APP_NAME="Taskware"
LAUNCHER_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

mkdir -p "$LAUNCHER_DIR" "$DESKTOP_DIR"

# 1) Create wrapper that sets PYTHONPATH and launches the app
WRAPPER="$LAUNCHER_DIR/$APP_ID"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
PYTHONPATH="$PROJECT_DIR/src" exec python3 -m taskware "$@"
EOF
chmod +x "$WRAPPER"

echo "Installed launcher: $WRAPPER"

# 2) Create .desktop entry (uses a stock system icon unless you later provide one)
DESKTOP_FILE="$DESKTOP_DIR/$APP_ID.desktop"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=Linux task scheduler UI
Exec=$WRAPPER
Terminal=false
Categories=Utility;GTK;
Icon=applications-system
StartupNotify=true
EOF

echo "Installed desktop entry: $DESKTOP_FILE"

echo "Refreshing desktop database (if available)"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "Done. You can now find '$APP_NAME' in your Applications menu."
