# TaskMate

A small task and meeting list for Ubuntu. Runs in the background, lives in the top bar, and opens in the browser.

- Day view: today, yesterday, tomorrow, any date
- Carry over unfinished tasks to today
- Meetings with reminders 10 minutes before and at start time
- Top-bar menu: add, complete, reorder, move to tomorrow
- Updates itself from this repo's GitHub Releases

## Install

```bash
curl -sL https://github.com/asanka-J/Task-master/releases/latest/download/taskmate.tar.gz | tar xz
cd taskmate && bash install.sh
```

Open http://localhost:8765, or click the icon in the top bar.

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
