#!/usr/bin/env python3
"""TaskMate top-bar indicator for Ubuntu (GNOME AppIndicator).
Shows today's tasks and meetings, meeting reminders (10 min before and at start),
carry-over of unfinished tasks, and quick add for today/tomorrow."""
import json, os, re, shutil, subprocess, sys, threading, urllib.request
from datetime import date, datetime, timedelta
import gi
gi.require_version("Gtk", "3.0")
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AI
except (ValueError, ImportError):
    gi.require_version("AppIndicator3", "0.1")
    from gi.repository import AppIndicator3 as AI
from gi.repository import Gtk, GLib

PORT = int(os.environ.get("TASKMATE_PORT", "8765"))
BASE = f"http://127.0.0.1:{PORT}"
ICON = os.path.expanduser("~/.local/share/taskmate/icon.svg")
MAX_ITEMS = 12
REMIND_BEFORE_MIN = 10
APP_DIR = os.path.expanduser("~/.local/share/taskmate")
UPDATER = os.path.join(APP_DIR, "taskmate_update.py")
UPDATE_EVERY_HOURS = 6
PN = {1: "High", 2: "Medium", 3: "Low"}
SOUND = next((s for s in ("/usr/share/sounds/freedesktop/stereo/message-new-instant.oga",
                          "/usr/share/sounds/freedesktop/stereo/bell.oga",
                          "/usr/share/sounds/freedesktop/stereo/complete.oga") if os.path.exists(s)), None)

def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3) as r:
        return json.loads(r.read() or b"null")

from html.parser import HTMLParser
from html import escape as html_escape

class _Text(HTMLParser):
    def __init__(self): super().__init__(); self.out = []
    def handle_starttag(self, tag, attrs):
        if tag in ("br", "p", "div", "li", "ul", "ol"): self.out.append(" ")
        if tag == "li": self.out.append("• ")
    def handle_data(self, d): self.out.append(d)

def plain(html):
    """Rich-text notes (HTML) as plain text for menus and notifications."""
    if not html or "<" not in html: return html or ""
    p = _Text(); p.feed(html)
    return re.sub(r"\s+", " ", "".join(p.out)).strip()

def open_link(url):
    """Open only http(s) links; never hand other schemes to the system."""
    if re.match(r"^https?://", url or "", re.I):
        subprocess.Popen(["xdg-open", url])

def short(s, n=46):
    return s if len(s) <= n else s[: n - 1] + "…"

def iso(d): return d.isoformat()
def today(): return date.today()

def start_of(t):
    if not (t["due"] and t["time"]): return None
    try: return datetime.strptime(f"{t['due']} {t['time']}", "%Y-%m-%d %H:%M")
    except ValueError: return None

def plural(n, w): return f"{n} {w}{'' if n == 1 else 's'}"

def dur(mins, compact=False):
    h, m = divmod(mins, 60)
    if compact:
        return " ".join(x for x in (f"{h}h" if h else "", f"{m}m" if m else "") if x) or "0m"
    return " ".join(x for x in (plural(h, "hour") if h else "", plural(m, "min") if m else "") if x)

def rel(t, compact=False):
    s = start_of(t)
    if not s: return ""
    secs = (s - datetime.now()).total_seconds()
    if secs < 0:
        m = int(-secs // 60)
        return "now" if m < 1 else (f"{dur(m, True)} ago" if compact else f"started {dur(m)} ago")
    m = int(-(-secs // 60))  # ceil
    if m <= 1: return "now" if compact else "starting now"
    if m < 24 * 60: return f"in {dur(m, compact)}"
    if t["due"] == iso(today() + timedelta(days=1)): return f"tomorrow {t['time']}"
    return s.strftime("%a %d %b ") + t["time"]

def nice_day(d):
    t = today()
    if d == iso(t): return "today"
    if d == iso(t - timedelta(days=1)): return "yesterday"
    if d == iso(t + timedelta(days=1)): return "tomorrow"
    try: return datetime.strptime(d, "%Y-%m-%d").strftime("%a %d %b")
    except ValueError: return d

def parse_time(s):
    s = s.strip().lower()
    if not s: return ""
    m = re.fullmatch(r"(\d{1,2})(?:[:.]?(\d{2}))?\s*(am|pm)?", s)
    if not m: return None
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h < 12: h += 12
    if ap == "am" and h == 12: h = 0
    return f"{h:02d}:{mi:02d}" if h < 24 and mi < 60 else None

def parse_date(s):
    s = s.strip().lower()
    if s in ("", "none", "no date"): return ""
    if s == "today": return iso(today())
    if s == "tomorrow": return iso(today() + timedelta(days=1))
    try: return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError: return None

# ---------- notifications ----------
_HAS_ACTIONS = None
def has_actions():
    global _HAS_ACTIONS
    if _HAS_ACTIONS is None:
        try:
            out = subprocess.run(["notify-send", "--help"], capture_output=True, text=True, timeout=3).stdout
            _HAS_ACTIONS = "--action" in out
        except Exception:
            _HAS_ACTIONS = False
    return _HAS_ACTIONS

def notify(title, body, urgent=False, link="", sound=False):
    if not shutil.which("notify-send"): return
    args = ["notify-send", "-a", "TaskMate", "-i", ICON if os.path.exists(ICON) else "appointment-soon",
            "-u", "critical" if urgent else "normal", "--", title, body]
    if sound and SOUND and shutil.which("paplay"):
        subprocess.Popen(["paplay", SOUND], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if link and not re.match(r"^https?://", link, re.I):
        link = ""
    if link and has_actions():
        def run():
            try:
                r = subprocess.run(args[:1] + ["-A", "join=Join meeting", "--wait"] + args[1:],
                                   capture_output=True, text=True)
                if r.stdout.strip() == "join":
                    open_link(link)
            except Exception:
                pass
        threading.Thread(target=run, daemon=True).start()
    else:
        subprocess.Popen(args)

class Indicator:
    def __init__(self):
        icon = ICON if os.path.exists(ICON) else "checkbox-checked-symbolic"
        self.ind = AI.Indicator.new("taskmate", icon, AI.IndicatorCategory.APPLICATION_STATUS)
        self.ind.set_status(AI.IndicatorStatus.ACTIVE)
        self.ind.set_title("TaskMate")
        self.tasks = []
        self.last_day = None
        self.update = None        # dict from updater --check when a newer version exists
        self.updating = False
        self.started_version = self.version()
        self.refresh()
        GLib.timeout_add_seconds(30, self.refresh)
        GLib.timeout_add_seconds(15, self.tick)
        GLib.timeout_add_seconds(60, lambda: self.check_updates() and False)
        GLib.timeout_add_seconds(UPDATE_EVERY_HOURS * 3600, self.check_updates)

    # ---------- updates ----------
    def check_updates(self, manual=False):
        if not os.path.exists(UPDATER): return True
        def run():
            try:
                r = subprocess.run(["/usr/bin/python3", UPDATER, "--check"], capture_output=True, text=True, timeout=60)
                info = json.loads(r.stdout or "{}")
            except Exception as e:
                info = {"error": str(e)}
            GLib.idle_add(self._update_checked, info, manual)
        threading.Thread(target=run, daemon=True).start()
        return True

    def _update_checked(self, info, manual):
        if info.get("update"):
            new = not self.update or self.update.get("latest") != info["latest"]
            self.update = info
            if new or manual:
                notify(f"TaskMate {info['latest']} is available",
                       f"You have {info['current']}. Click the TaskMate icon and choose Install update.")
        else:
            self.update = None
            if manual:
                notify("TaskMate update check", info.get("error") or f"You're on the latest version ({info.get('current')}).")
        self.refresh()
        return False

    def install_update(self):
        if self.updating: return
        self.updating = True
        self.refresh()
        notify("Updating TaskMate…", "This takes a few seconds.")
        log = os.path.join(APP_DIR, "update.log")
        # New session so the update survives this indicator being restarted by install.sh
        subprocess.Popen(["/usr/bin/python3", UPDATER, "--install"], stdout=open(log, "w"),
                         stderr=subprocess.STDOUT, start_new_session=True)
        def done_check():
            # If we're still alive after 2 minutes the update probably failed
            self.updating = False
            notify("TaskMate update may have failed", f"See {log}")
            self.refresh()
            return False
        GLib.timeout_add_seconds(120, done_check)

    # ---------- data ----------
    def groups(self):
        T = iso(today())
        ts = [t for t in self.tasks if t["kind"] != "meeting"]
        return {
            "today": [t for t in ts if not t["done"] and t["due"] == T],
            "carry": [t for t in ts if not t["done"] and t["due"] and t["due"] < T],
            "anytime": [t for t in ts if not t["done"] and not t["due"]],
            "meetings": sorted([t for t in self.tasks if t["kind"] == "meeting" and not t["done"] and t["due"] and t["due"] <= iso(today() + timedelta(days=1))],
                               key=lambda t: (t["due"], t["time"])),
        }

    def update_label(self):
        g = self.groups()
        lbl = str(len(g["today"]) + len(g["carry"]))
        if g["carry"]: lbl += f" (+{len(g['carry'])})"
        now = datetime.now()
        upcoming = [m for m in g["meetings"] if start_of(m) and start_of(m) > now - timedelta(minutes=5)
                    and start_of(m) - now < timedelta(hours=12)]
        if upcoming:
            m = upcoming[0]
            lbl += f"   {short(m['title'], 18)} {rel(m, True)}"
        self.ind.set_label(lbl, "99 (9 late)  ·  Meeting name here in 11h 59m")

    # ---------- reminders ----------
    def tick(self):
        if self.version() != self.started_version:
            # A new version was installed (e.g. from the web page): restart into it
            os.execv(sys.executable, [sys.executable, os.path.join(APP_DIR, "taskmate_indicator.py")])
        try:
            self.tasks = api("GET", "/api/tasks")
        except Exception:
            return True
        now = datetime.now()
        for t in self.tasks:
            if t["kind"] != "meeting" or t["done"]: continue
            s = start_of(t)
            if not s: continue
            mins = (s - now).total_seconds() / 60
            n = t.get("notified") or 0
            if not n & 2 and -15 < mins <= 0:
                notify(f"Starting now: {t['title']}", plain(t["notes"]) or "Your meeting is starting.",
                       urgent=True, link=t["link"], sound=True)
                self.set_notified(t, n | 3)
            elif not n & 1 and 0 < mins <= REMIND_BEFORE_MIN:
                notify(f"{t['title']} {rel(t)}", f"Starts at {t['time']}" + (f"\n{plain(t['notes'])}" if t["notes"] else ""),
                       link=t["link"], sound=True)
                self.set_notified(t, n | 1)
        # Morning nudge about unfinished tasks
        d = iso(today())
        if self.last_day and self.last_day != d:
            carry = self.groups()["carry"]
            if carry:
                notify(f"{plural(len(carry), 'unfinished task')} from earlier",
                       "Open TaskMate in the top bar to move them to today.")
            self.refresh()
        self.last_day = d
        self.update_label()
        return True

    def set_notified(self, t, n):
        t["notified"] = n
        try: api("PUT", f"/api/tasks/{t['id']}", {"notified": n})
        except Exception: pass

    # ---------- menu ----------
    def item(self, menu, label, cb=None, sensitive=True):
        mi = Gtk.MenuItem(label=label)
        mi.set_sensitive(sensitive)
        if cb: mi.connect("activate", lambda *_: cb())
        menu.append(mi)
        return mi

    def sep(self, menu): menu.append(Gtk.SeparatorMenuItem())

    def refresh(self):
        menu = Gtk.Menu()
        try:
            self.tasks = api("GET", "/api/tasks")
        except Exception:
            self.ind.set_label("!", "99")
            self.item(menu, "TaskMate service is not running", sensitive=False)
            self.item(menu, "Start service", self.start_service)
            self.item(menu, "Retry", self.refresh)
            self.sep(menu)
            self.item(menu, "Quit indicator", Gtk.main_quit)
            menu.show_all(); self.ind.set_menu(menu)
            return True
        if self.last_day is None: self.last_day = iso(today())
        self.update_label()
        g = self.groups()
        T = iso(today())
        done_today = [t for t in self.tasks if t["kind"] != "meeting" and t["done"]
                      and (t["due"] == T or (t["completed"] or "")[:10] == T)]
        todo = g["today"] + g["anytime"]

        # Header: one quiet line
        left = len(g["today"])
        head = "Nothing left today" if not left else f"{left} left today"
        if done_today: head += f", {len(done_today)} done"
        panel = self.item(menu, "Show Panel", self.open_panel)
        try: self.ind.set_secondary_activate_target(panel)   # middle-click the icon
        except Exception: pass
        self.sep(menu)
        self.item(menu, head, sensitive=False)

        if self.update and not self.updating:
            self.item(menu, f"Update to {self.update['latest']}…", self.install_update)

        # Meetings: time first, like a calendar
        now = datetime.now()
        upcoming = [m for m in g["meetings"] if start_of(m) and start_of(m) > now - timedelta(minutes=30)]
        if upcoming:
            self.sep(menu)
            for m in upcoming[:4]:
                day = "" if m["due"] == T else "Tomorrow "
                mi = Gtk.MenuItem(label=f"{day}{m['time']}   {short(m['title'], 34)}")
                sub = Gtk.Menu()
                self.item(sub, rel(m).capitalize(), sensitive=False)
                if re.match(r"^https?://", m["link"] or "", re.I):
                    self.item(sub, "Join Meeting", lambda l=m["link"]: open_link(l))
                self.item(sub, "Edit…", lambda tt=m: self.dialog(tt))
                self.item(sub, "Delete", lambda i=m["id"]: self.delete(i))
                mi.set_submenu(sub); menu.append(mi)

        # Tasks: the list itself, next one first
        if todo:
            self.sep(menu)
            for t in todo[:MAX_ITEMS]:
                menu.append(self.task_item(t, todo, anytime=not t["due"]))
            if len(todo) > MAX_ITEMS:
                self.item(menu, f"{len(todo) - MAX_ITEMS} more…", self.open_web)

        if g["carry"]:
            self.sep(menu)
            mi = Gtk.MenuItem(label=f"{plural(len(g['carry']), 'task')} from earlier")
            sub = Gtk.Menu()
            self.item(sub, "Move All to Today", self.carry_all)
            self.sep(sub)
            for t in g["carry"][:MAX_ITEMS]:
                ti = Gtk.MenuItem(label=short(t["title"], 40))
                ts = Gtk.Menu()
                self.item(ts, "Move to Today", lambda i=t["id"]: self.set_due(i, T))
                self.item(ts, "Mark as Done", lambda i=t["id"]: self.done(i))
                self.item(ts, "Delete", lambda i=t["id"]: self.delete(i))
                ti.set_submenu(ts); sub.append(ti)
            mi.set_submenu(sub); menu.append(mi)

        self.sep(menu)
        self.item(menu, "New Task…", lambda: self.dialog(due=T))
        self.item(menu, "Open TaskMate", self.open_web)
        self.sep(menu)
        if self.updating:
            self.item(menu, "Updating…", sensitive=False)
        elif not self.update:
            self.item(menu, "Check for Updates", lambda: self.check_updates(manual=True))
        self.item(menu, "Quit", Gtk.main_quit)
        menu.show_all()
        self.ind.set_menu(menu)
        return True

    def version(self):
        try: return open(os.path.join(APP_DIR, "VERSION")).read().strip()
        except OSError: return "?"

    def task_item(self, t, siblings, anytime=False, prefix=None):
        # Plain title; high priority gets a quiet marker. Submenu stays short so the list never jumps.
        mark = "!  " if t["priority"] == 1 else ""
        mi = Gtk.MenuItem(label=mark + short(t["title"], 44))
        sub = Gtk.Menu()
        self.item(sub, "Mark as Done", lambda i=t["id"]: self.done(i))
        ids = [x["id"] for x in siblings]
        if t["id"] in ids and ids.index(t["id"]) > 0:
            self.item(sub, "Do Next", lambda i=t["id"]: self.move(i, "top", ids))
        if anytime:
            self.item(sub, "Do Today", lambda i=t["id"]: self.set_due(i, iso(today())))
        else:
            self.item(sub, "Move to Tomorrow", lambda i=t["id"]: self.set_due(i, iso(today() + timedelta(days=1))))
        self.item(sub, "Edit…", lambda tt=t: self.dialog(tt))
        self.item(sub, "Delete", lambda i=t["id"]: self.delete(i))
        mi.set_submenu(sub)
        return mi

    # ---------- actions ----------
    def act(self, fn):
        try: fn()
        except Exception as e: print("TaskMate:", e)
        self.refresh()

    def done(self, tid): self.act(lambda: api("PUT", f"/api/tasks/{tid}", {"done": 1}))
    def undone(self, tid): self.act(lambda: api("PUT", f"/api/tasks/{tid}", {"done": 0}))
    def delete(self, tid): self.act(lambda: api("DELETE", f"/api/tasks/{tid}"))
    def set_due(self, tid, d): self.act(lambda: api("PUT", f"/api/tasks/{tid}", {"due": d}))
    def carry_all(self): self.act(lambda: api("POST", "/api/carryover", {"to": iso(today())}))

    def move(self, tid, where, ids=None):
        if ids is None:
            g = self.groups(); ids = [t["id"] for t in g["today"] + g["anytime"]]
        ids = list(ids)
        i = ids.index(tid); ids.pop(i)
        j = {"top": 0, "bottom": len(ids), "up": max(0, i - 1), "down": min(len(ids), i + 1)}[where]
        ids.insert(j, tid)
        self.act(lambda: api("POST", "/api/reorder", {"ids": ids}))

    def open_panel(self):
        win = os.path.join(APP_DIR, "taskmate_window.py")
        if os.path.exists(win):
            subprocess.Popen(["/usr/bin/python3", win, "--panel"], env={**os.environ, "TASKMATE_PORT": str(PORT)})

    def open_web(self):
        win = os.path.join(APP_DIR, "taskmate_window.py")
        if os.path.exists(win):
            subprocess.Popen(["/usr/bin/python3", win], env={**os.environ, "TASKMATE_PORT": str(PORT)})
        else:
            subprocess.Popen(["xdg-open", f"http://localhost:{PORT}"])

    def start_service(self):
        subprocess.call(["systemctl", "--user", "start", "taskmate.service"])
        GLib.timeout_add_seconds(1, lambda: self.refresh() and False)

    # ---------- add / edit dialog ----------
    def dialog(self, task=None, due=None, kind="task"):
        kind = task["kind"] if task else kind
        d = Gtk.Dialog(title=("Edit " if task else "Add ") + ("meeting" if kind == "meeting" else "task"), flags=0)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save" if task else "Add", Gtk.ResponseType.OK)
        d.set_default_response(Gtk.ResponseType.OK)
        d.set_keep_above(True)
        d.set_position(Gtk.WindowPosition.CENTER)
        g = Gtk.Grid(column_spacing=8, row_spacing=8, margin=12)
        d.get_content_area().add(g)

        kind_cb = Gtk.ComboBoxText()
        kind_cb.append("task", "Task"); kind_cb.append("meeting", "Meeting")
        kind_cb.set_active_id(kind)
        title = Gtk.Entry(activates_default=True, width_chars=40)
        date_e = Gtk.Entry(activates_default=True, placeholder_text="YYYY-MM-DD, or leave empty")
        dbox = Gtk.Box(spacing=4)
        dbox.pack_start(date_e, True, True, 0)
        for lbl, val in (("Today", lambda: iso(today())), ("Tomorrow", lambda: iso(today() + timedelta(days=1))), ("None", lambda: "")):
            b = Gtk.Button(label=lbl)
            b.connect("clicked", lambda _b, v=val: date_e.set_text(v()))
            dbox.pack_start(b, False, False, 0)
        time_e = Gtk.Entry(activates_default=True, placeholder_text="e.g. 14:30 or 2:30pm")
        project = Gtk.Entry(activates_default=True, placeholder_text="optional")
        prio = Gtk.ComboBoxText()
        for k in (1, 2, 3): prio.append(str(k), PN[k])
        link = Gtk.Entry(activates_default=True, placeholder_text="Zoom / Meet / Teams link (optional)")
        notes = Gtk.Entry(activates_default=True, placeholder_text="optional")
        err = Gtk.Label(xalign=0); err.get_style_context().add_class("error")

        title.set_text(task["title"] if task else "")
        date_e.set_text(task["due"] if task else (due if due is not None else iso(today())))
        time_e.set_text(task["time"] if task else "")
        project.set_text(task["project"] if task else "")
        prio.set_active_id(str(task["priority"] if task else 2))
        link.set_text(task["link"] if task else "")
        orig_notes = task["notes"] if task else ""
        notes.set_text(plain(orig_notes))
        if "<" in orig_notes:
            notes.set_tooltip_text("These notes have formatting. Edit them in the TaskMate window to keep it.")

        rows = [("Type", kind_cb), ("Title", title), ("Date", dbox), ("Time", time_e),
                ("Project", project), ("Priority", prio), ("Link", link), ("Notes", notes)]
        labels = {}
        for r, (lbl, w) in enumerate(rows):
            l = Gtk.Label(label=lbl, xalign=0); labels[lbl] = (l, w)
            g.attach(l, 0, r, 1, 1); g.attach(w, 1, r, 1, 1)
        g.attach(err, 1, len(rows), 1, 1)

        def sync(*_):
            m = kind_cb.get_active_id() == "meeting"
            for k in ("Time", "Link"):
                labels[k][0].set_visible(m); labels[k][1].set_visible(m)
            labels["Priority"][0].set_visible(not m); labels["Priority"][1].set_visible(not m)
        kind_cb.connect("changed", sync)
        d.show_all(); sync()
        title.grab_focus()
        d.present()

        while True:
            if d.run() != Gtk.ResponseType.OK: break
            k = kind_cb.get_active_id()
            dd = parse_date(date_e.get_text())
            tm = parse_time(time_e.get_text()) if k == "meeting" else ""
            if not title.get_text().strip(): err.set_text("Please enter a title."); continue
            if dd is None: err.set_text("Date must be YYYY-MM-DD, today or tomorrow."); continue
            if k == "meeting" and not tm: err.set_text("Please enter a start time, e.g. 14:30."); continue
            if k == "meeting" and not dd: dd = iso(today())
            lk = link.get_text().strip()
            if k == "meeting" and lk and not re.match(r"^https?://", lk, re.I):
                if "://" in lk or lk.lower().startswith(("javascript:", "file:", "data:")):
                    err.set_text("Meeting link must start with https://"); continue
                lk = "https://" + lk; link.set_text(lk)
            body = {"title": title.get_text().strip(), "kind": k, "due": dd, "time": tm,
                    "project": project.get_text().strip(), "priority": int(prio.get_active_id()),
                    "link": lk if k == "meeting" else "",
                    # Keep formatted notes as they are unless the text was changed here
                    "notes": orig_notes if notes.get_text() == plain(orig_notes) else notes.get_text()}
            if task: self.act(lambda: api("PUT", f"/api/tasks/{task['id']}", body))
            else: self.act(lambda: api("POST", "/api/tasks", body))
            break
        d.destroy()

if __name__ == "__main__":
    Indicator()
    Gtk.main()
