#!/usr/bin/env bash
# Stops and removes the TaskMate service. Your tasks.db is kept unless you pass --purge.
systemctl --user disable --now taskmate.service 2>/dev/null || true
pkill -f taskmate_indicator.py 2>/dev/null || true
pkill -f "taskmate_window.py" 2>/dev/null || true
# Remove the Super+Shift+T shortcut
if command -v gsettings >/dev/null; then
  L=$(gsettings get org.gnome.settings-daemon.plugins.media-keys custom-keybindings 2>/dev/null || true)
  if echo "$L" | grep -q taskmate-panel; then
    N=$(python3 -c 'import ast,sys
l=sys.argv[1].replace("@as ","").strip(); a=ast.literal_eval(l) if l not in ("","[]") else []
print(str([x for x in a if "taskmate-panel" not in x]))' "$L")
    gsettings set org.gnome.settings-daemon.plugins.media-keys custom-keybindings "$N" || true
  fi
fi
rm -f "$HOME/.config/autostart/taskmate-indicator.desktop" "$HOME/.local/share/taskmate/taskmate_indicator.py" "$HOME/.local/share/taskmate/icon.svg"
rm -f "$HOME/.config/systemd/user/taskmate.service" "$HOME/.local/share/applications/taskmate.desktop"
systemctl --user daemon-reload
if [ "$1" = "--purge" ]; then rm -rf "$HOME/.local/share/taskmate"; echo "Removed TaskMate and all tasks."
else rm -f "$HOME/.local/share/taskmate/taskmate.py" "$HOME/.local/share/taskmate/page.html" "$HOME/.local/share/taskmate/taskmate_update.py" "$HOME/.local/share/taskmate/taskmate_window.py" "$HOME/.local/share/taskmate/icon-app.svg"; echo "Removed TaskMate. Tasks kept in ~/.local/share/taskmate/tasks.db"; fi
