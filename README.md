# TaskMate

A small task and meeting list for Ubuntu. Runs in the background, lives in the top bar, and opens in the browser.

- Day view: today, yesterday, tomorrow, any date
- Carry over unfinished tasks to today
- Meetings with reminders 10 minutes before and at start time
- Top-bar menu: add, complete, reorder, move to tomorrow
- Opens in its own app window (TaskMate in the app grid)
- Rich-text notes: bold, italic, lists, links
- Updates itself from this repo's GitHub Releases

## Install

```bash
curl -sL https://github.com/asanka-J/Task-master/releases/latest/download/taskmate.tar.gz | tar xz
cd taskmate && bash install.sh
```

Open TaskMate from the app grid or the top-bar icon. For a quick look, press **Super+Shift+T**, middle-click the top-bar icon, or choose **Show Panel** from its menu: a small panel with today's tasks, meetings and Add task / Add meeting buttons.

 It also works in a browser at http://localhost:8765.

By default TaskMate only accepts connections from this laptop. To use it from your phone on the same Wi-Fi:

```bash
bash install.sh --lan     # prints a private link with an access key; open it once on the phone
bash install.sh --local   # turn phone access off again
```

## Release a new version

```bash
git tag v1.1.0 && git push --tags
```

GitHub Actions builds `taskmate.tar.gz` and publishes the release. Installed copies show "Install update" in the top-bar menu.

## Uninstall

```bash
bash ~/.local/share/taskmate/uninstall.sh          # keeps your tasks
bash ~/.local/share/taskmate/uninstall.sh --purge  # deletes everything
```
