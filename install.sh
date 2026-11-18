#!/usr/bin/env bash
# Installs TaskMate as a background service that starts automatically when you log in.
# Usage: bash install.sh                       (accessible from this PC + phone on same Wi-Fi)
#        bash install.sh --local               (this PC only)
#        bash install.sh --repo owner/name     (get updates from that GitHub repo's releases)
#        bash install.sh --update              (used by the updater; keeps your existing settings)
set -e
PORT="${TASKMATE_PORT:-8765}"
APP_DIR="$HOME/.local/share/taskmate"
UNIT_DIR="$HOME/.config/systemd/user"
CFG_DIR="$HOME/.config/taskmate"
HOST=""; REPO=""; UPDATE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --local) HOST="127.0.0.1" ;;
    --update) UPDATE=1 ;;
    --repo) REPO="$2"; shift ;;
  esac
  shift
done
# Keep the previous host setting unless told otherwise
if [ -z "$HOST" ] && [ -f "$UNIT_DIR/taskmate.service" ]; then
  HOST=$(sed -n 's/^Environment=TASKMATE_HOST=//p' "$UNIT_DIR/taskmate.service")
fi
HOST="${HOST:-0.0.0.0}"

mkdir -p "$APP_DIR" "$UNIT_DIR" "$CFG_DIR"
SRC="$(cd "$(dirname "$0")" && pwd)"
cp "$SRC/taskmate.py" "$SRC/page.html" "$SRC/taskmate_indicator.py" "$SRC/taskmate_update.py" \
   "$SRC/taskmate_window.py" "$SRC/icon.svg" "$SRC/icon-app.svg" "$SRC/VERSION" "$APP_DIR/"
cp "$SRC/install.sh" "$SRC/uninstall.sh" "$APP_DIR/" 2>/dev/null || true

if [ -n "$REPO" ]; then
  touch "$CFG_DIR/config"; chmod 600 "$CFG_DIR/config"
  grep -v '^TASKMATE_REPO=' "$CFG_DIR/config" > "$CFG_DIR/config.tmp" || true
  echo "TASKMATE_REPO=$REPO" >> "$CFG_DIR/config.tmp"; mv "$CFG_DIR/config.tmp" "$CFG_DIR/config"
fi

# System packages: top-bar icon (AppIndicator) and the app window (WebKitGTK)
PKGS=""
if ! python3 -c "import gi; gi.require_version('AyatanaAppIndicator3','0.1')" 2>/dev/null \
   && ! python3 -c "import gi; gi.require_version('AppIndicator3','0.1')" 2>/dev/null; then
  PKGS="$PKGS python3-gi gir1.2-ayatanaappindicator3-0.1"
fi
if ! python3 -c "import gi; gi.require_version('WebKit2','4.1')" 2>/dev/null \
   && ! python3 -c "import gi; gi.require_version('WebKit2','4.0')" 2>/dev/null; then
  if apt-cache show gir1.2-webkit2-4.1 >/dev/null 2>&1; then PKGS="$PKGS gir1.2-webkit2-4.1"; else PKGS="$PKGS gir1.2-webkit2-4.0"; fi
fi
if [ -n "$PKGS" ]; then
  if [ "$UPDATE" = 1 ] && ! sudo -n true 2>/dev/null; then
    echo "Note: missing packages ($PKGS). Run 'bash $APP_DIR/install.sh' in a terminal to add them."
  else
    echo "Installing system packages:$PKGS (needs sudo)..."
    sudo apt-get install -y $PKGS || echo "Could not install$PKGS. The window will fall back to your browser."
  fi
fi

cat > "$UNIT_DIR/taskmate.service" <<EOF
[Unit]
Description=TaskMate task list
After=network.target

[Service]
Environment=TASKMATE_HOST=$HOST
Environment=TASKMATE_PORT=$PORT
ExecStart=/usr/bin/python3 $APP_DIR/taskmate.py
Restart=on-failure

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable taskmate.service
systemctl --user restart taskmate.service
# Keep it running even when you're logged out / after reboot before login
loginctl enable-linger "$USER" 2>/dev/null || true

# Desktop launcher so it shows up in the Ubuntu app grid
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/taskmate.desktop" <<EOF
[Desktop Entry]
Name=TaskMate
Comment=My tasks and meetings
Exec=env TASKMATE_PORT=$PORT /usr/bin/python3 $APP_DIR/taskmate_window.py
Icon=$APP_DIR/icon-app.svg
Terminal=false
Type=Application
Categories=Office;ProjectManagement;
StartupWMClass=taskmate
StartupNotify=true
EOF
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# Start the top-bar icon on login, and start it now
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/taskmate-indicator.desktop" <<EOF
[Desktop Entry]
Name=TaskMate Indicator
Exec=env TASKMATE_PORT=$PORT /usr/bin/python3 $APP_DIR/taskmate_indicator.py
Type=Application
X-GNOME-Autostart-enabled=true
NoDisplay=true
EOF
# When run from the web page's updater there is no desktop session; the running
# top-bar icon notices the new VERSION and restarts itself instead.
if [ -n "$DISPLAY$WAYLAND_DISPLAY" ]; then
  pkill -f taskmate_indicator.py 2>/dev/null || true
  sleep 1
  TASKMATE_PORT=$PORT nohup /usr/bin/python3 "$APP_DIR/taskmate_indicator.py" >/dev/null 2>&1 &
  disown || true
fi

echo
echo "TaskMate $(cat "$APP_DIR/VERSION") is running."
[ "$UPDATE" = 1 ] && exit 0
echo "  Open it from the app grid (TaskMate) or the top-bar icon."
echo "  In a browser: http://localhost:$PORT"
if [ "$HOST" = "0.0.0.0" ]; then
  IP=$(hostname -I | awk '{print $1}')
  echo "  On your phone (same Wi-Fi): http://$IP:$PORT"
  if command -v ufw >/dev/null && sudo -n ufw status 2>/dev/null | grep -q "Status: active"; then
    echo "  Firewall is on. To allow phone access run: sudo ufw allow $PORT/tcp"
  fi
fi
echo "  Your tasks are saved in: $APP_DIR/tasks.db"
R=$(sed -n 's/^TASKMATE_REPO=//p' "$CFG_DIR/config" 2>/dev/null || true); R="${R:-asanka-J/Task-master}"
echo "  Updates from: https://github.com/$R/releases"
