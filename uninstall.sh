#!/usr/bin/env bash
# Stops and removes the TaskMate service. Your tasks.db is kept unless you pass --purge.
systemctl --user disable --now taskmate.service 2>/dev/null || true
pkill -f taskmate_indicator.py 2>/dev/null || true
rm -f "$HOME/.config/autostart/taskmate-indicator.desktop" "$HOME/.local/share/taskmate/taskmate_indicator.py" "$HOME/.local/share/taskmate/icon.svg"
rm -f "$HOME/.config/systemd/user/taskmate.service" "$HOME/.local/share/applications/taskmate.desktop"
systemctl --user daemon-reload
if [ "$1" = "--purge" ]; then rm -rf "$HOME/.local/share/taskmate"; echo "Removed TaskMate and all tasks."
else rm -f "$HOME/.local/share/taskmate/taskmate.py" "$HOME/.local/share/taskmate/page.html" "$HOME/.local/share/taskmate/taskmate_update.py"; echo "Removed TaskMate. Tasks kept in ~/.local/share/taskmate/tasks.db"; fi
