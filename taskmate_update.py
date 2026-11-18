#!/usr/bin/env python3
"""TaskMate updater: checks GitHub Releases and installs a newer version.

  python3 taskmate_update.py --check     prints JSON {"current","latest","update","url"}
  python3 taskmate_update.py --install   downloads the latest release and runs install.sh

Config (~/.config/taskmate/config, simple KEY=value lines):
  TASKMATE_REPO=owner/repo          defaults to asanka-J/Task-master
  GITHUB_TOKEN=ghp_...              only needed if the repo is private
"""
import json, os, re, shutil, subprocess, sys, tarfile, tempfile, urllib.request

APP_DIR = os.path.expanduser("~/.local/share/taskmate")
CONFIG = os.path.expanduser("~/.config/taskmate/config")
ASSET = "taskmate.tar.gz"
DEFAULT_REPO = "asanka-J/Task-master"

def config():
    cfg = {"TASKMATE_REPO": DEFAULT_REPO}
    if os.path.exists(CONFIG):
        for line in open(CONFIG, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.strip().strip('"').strip("'")
    cfg.update({k: v for k, v in os.environ.items() if k in ("TASKMATE_REPO", "GITHUB_TOKEN")})
    return cfg

def current_version():
    for p in (os.path.join(APP_DIR, "VERSION"), os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")):
        if os.path.exists(p):
            return open(p).read().strip()
    return "0.0.0"

def vtuple(v):
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)

def request(url, token, accept="application/vnd.github+json"):
    h = {"Accept": accept, "User-Agent": "TaskMate-updater"}
    if token: h["Authorization"] = f"Bearer {token}"
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30)

def latest():
    cfg = config()
    repo = cfg.get("TASKMATE_REPO")
    if not repo:
        raise RuntimeError(f"No TASKMATE_REPO set in {CONFIG}")
    with request(f"https://api.github.com/repos/{repo}/releases/latest", cfg.get("GITHUB_TOKEN")) as r:
        rel = json.load(r)
    asset = next((a for a in rel.get("assets", []) if a["name"] == ASSET), None)
    return {"tag": rel["tag_name"], "notes": rel.get("body") or "",
            "asset_api": asset["url"] if asset else None, "tarball": rel["tarball_url"],
            "html": rel["html_url"], "token": cfg.get("GITHUB_TOKEN")}

def check():
    cur = current_version()
    rel = latest()
    return {"current": cur, "latest": rel["tag"].lstrip("v"),
            "update": vtuple(rel["tag"]) > vtuple(cur), "url": rel["html"]}

def install():
    rel = latest()
    if vtuple(rel["tag"]) <= vtuple(current_version()):
        print(f"Already up to date ({current_version()})"); return 0
    tmp = tempfile.mkdtemp(prefix="taskmate-update-")
    try:
        tgz = os.path.join(tmp, "release.tar.gz")
        if rel["asset_api"]:
            src = request(rel["asset_api"], rel["token"], "application/octet-stream")
        else:
            src = request(rel["tarball"], rel["token"])
        with src as r, open(tgz, "wb") as f:
            shutil.copyfileobj(r, f)
        out = os.path.join(tmp, "x")
        with tarfile.open(tgz) as tf:
            for m in tf.getmembers():  # refuse path tricks
                if m.name.startswith("/") or ".." in m.name.split("/") or m.issym() or m.islnk():
                    raise RuntimeError(f"Unsafe path in release archive: {m.name}")
            tf.extractall(out)
        found = None
        for root, _dirs, files in os.walk(out):
            if "install.sh" in files and "taskmate.py" in files:
                found = root; break
        if not found:
            raise RuntimeError("install.sh not found in release archive")
        with open(os.path.join(found, "VERSION"), "w") as f:
            f.write(rel["tag"].lstrip("v") + "\n")
        print(f"Installing TaskMate {rel['tag']}…", flush=True)
        return subprocess.call(["bash", os.path.join(found, "install.sh"), "--update"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    try:
        if "--install" in sys.argv:
            sys.exit(install())
        print(json.dumps(check()))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)
