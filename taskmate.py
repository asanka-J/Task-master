#!/usr/bin/env python3
"""TaskMate: a tiny self-hosted task + meeting list. Python stdlib only (no pip needed)."""
import hmac, ipaddress, json, os, re, shutil, socket, sqlite3, subprocess, sys
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlsplit, parse_qs

DATA_DIR = os.path.expanduser(os.environ.get("TASKMATE_DATA", "~/.local/share/taskmate"))
DB = os.path.join(DATA_DIR, "tasks.db")
HOST = os.environ.get("TASKMATE_HOST", "127.0.0.1")   # this laptop only unless installed with --lan
PORT = int(os.environ.get("TASKMATE_PORT", "8765"))
MEETING_AUTO_DONE_MIN = 60   # meetings are auto-completed this long after they start
MAX_BODY = 1_000_000         # largest request body accepted (bytes)
CONFIG = os.path.expanduser("~/.config/taskmate/config")
COOKIE = "tm_key"
HERE = os.path.dirname(os.path.abspath(__file__))
UPDATER = os.path.join(HERE, "taskmate_update.py")

def version():
    try: return open(os.path.join(HERE, "VERSION")).read().strip()
    except OSError: return "0.0.0"

def start_update():
    """Run the updater outside this service, so restarting the service doesn't kill it."""
    logpath = os.path.join(DATA_DIR, "update.log")
    cmd = [sys.executable, UPDATER, "--install"]
    if shutil.which("systemd-run"):
        unit = f"taskmate-update-{int(datetime.now().timestamp())}"
        r = subprocess.run(["systemd-run", "--user", "--collect", "--quiet", "--unit", unit,
                            "-p", f"StandardOutput=file:{logpath}", "-p", "StandardError=inherit"] + cmd,
                           capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return
    # Fallback: detached process (may be stopped if the service restarts before it finishes)
    subprocess.Popen(cmd, stdout=open(logpath, "w"), stderr=subprocess.STDOUT, start_new_session=True)

def access_key():
    """Key that other devices (your phone) must present. Set by install.sh --lan."""
    try:
        for line in open(CONFIG, encoding="utf-8"):
            if line.startswith("TASKMATE_ACCESS_KEY="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""

LOCAL_NAMES = {"localhost", socket.gethostname().lower(), socket.gethostname().lower() + ".local"}

def host_ok(host_header):
    """Only accept requests addressed to this machine by IP or its own name.
    Blocks DNS-rebinding attacks, which use a domain name the attacker controls."""
    h = (host_header or "").strip().lower()
    if h.startswith("["):
        h = h[1:h.find("]")]
    elif h.count(":") == 1:
        h = h.split(":")[0]
    if h in LOCAL_NAMES:
        return True
    try:
        ipaddress.ip_address(h); return True
    except ValueError:
        return False

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LINK_RE = re.compile(r"^https?://", re.I)

def clean_fields(b):
    """Validate and normalise task fields. Returns (dict, error)."""
    out = {}
    for k, v in b.items():
        if k not in FIELDS: continue
        if k in ("title", "notes", "project", "link"):
            if not isinstance(v, str): return None, f"{k} must be text"
            v = v.strip() if k != "notes" else v
            if len(v) > (200_000 if k == "notes" else 2000): return None, f"{k} is too long"
            if k == "link" and v and not LINK_RE.match(v):
                return None, "Meeting link must start with http:// or https://"
        elif k == "due":
            if v and not (isinstance(v, str) and DATE_RE.match(v)): return None, "due must be YYYY-MM-DD"
        elif k == "time":
            if v and not (isinstance(v, str) and TIME_RE.match(v)): return None, "time must be HH:MM"
        elif k == "kind":
            if v not in ("task", "meeting"): return None, "kind must be task or meeting"
        elif k == "priority":
            try: v = int(v)
            except (TypeError, ValueError): return None, "priority must be 1, 2 or 3"
            if v not in (1, 2, 3): return None, "priority must be 1, 2 or 3"
        else:  # done, position, notified
            try: v = int(v)
            except (TypeError, ValueError): return None, f"{k} must be a number"
        out[k] = v
    return out, None

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            notes TEXT DEFAULT '',
            project TEXT DEFAULT '',
            priority INTEGER DEFAULT 2,
            due TEXT DEFAULT '',
            done INTEGER DEFAULT 0,
            position INTEGER DEFAULT 0,
            created TEXT,
            completed TEXT DEFAULT '')""")
        have = {r[1] for r in c.execute("PRAGMA table_info(tasks)")}
        for col, ddl in [("kind", "TEXT DEFAULT 'task'"), ("time", "TEXT DEFAULT ''"),
                         ("link", "TEXT DEFAULT ''"), ("notified", "INTEGER DEFAULT 0")]:
            if col not in have:
                c.execute(f"ALTER TABLE tasks ADD COLUMN {col} {ddl}")

FIELDS = ("title", "notes", "project", "priority", "due", "done", "position",
          "kind", "time", "link", "notified")

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = -1
        if n < 0 or n > MAX_BODY:
            raise ValueError("request too large")
        data = json.loads(self.rfile.read(n) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data

    def is_local_client(self):
        try: return ipaddress.ip_address(self.client_address[0].split("%")[0]).is_loopback
        except ValueError: return False

    def guard(self, write):
        """Security checks for every request. Returns True if the request may continue."""
        # 1. Only answer to our own host names / IPs (stops DNS rebinding)
        if not host_ok(self.headers.get("Host")):
            self.send(403, '{"error":"unknown host"}'); return False
        # 2. Other devices need the access key (cookie, or ?key= once to set it)
        if not self.is_local_client():
            key = access_key()
            q = parse_qs(urlsplit(self.path).query)
            given = (q.get("key") or [""])[0]
            if key and given and hmac.compare_digest(given, key):
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"{COOKIE}={key}; Max-Age=31536000; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", "0")
                self.end_headers(); return False
            cookie = ""
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE: cookie = v
            if not key or not hmac.compare_digest(cookie, key):
                self.send(401, "<p style='font:16px system-ui;padding:30px'>TaskMate: open the link with your access key "
                                "(shown by <code>bash install.sh --lan</code>).</p>", "text/html; charset=utf-8")
                return False
        # 3. Changes must come from TaskMate itself, not from another website
        if write:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc.lower() != (self.headers.get("Host") or "").lower():
                self.send(403, '{"error":"cross-site request blocked"}'); return False
            if (self.headers.get("Sec-Fetch-Site") or "same-origin") not in ("same-origin", "none"):
                self.send(403, '{"error":"cross-site request blocked"}'); return False
            # A JSON content type forces browsers to ask permission first for cross-site calls
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                self.send(415, '{"error":"Content-Type must be application/json"}'); return False
        return True

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ValueError, json.JSONDecodeError) as e:
            try: self.send(400, json.dumps({"error": str(e)}))
            except Exception: pass

    def task_id(self):
        try: return int(self.path.rstrip("/").split("/")[-1])
        except ValueError: return None

    def do_GET(self):
        if not self.guard(write=False): return
        self.path = urlsplit(self.path).path
        if self.path in ("/", "/index.html"):
            return self.send(200, PAGE, "text/html; charset=utf-8")
        if self.path == "/api/version":
            return self.send(200, json.dumps({"version": version()}))
        if self.path.startswith("/api/tasks"):
            now = datetime.now()
            cutoff = (now - timedelta(minutes=MEETING_AUTO_DONE_MIN)).strftime("%Y-%m-%d %H:%M")
            with db() as c:
                c.execute("""UPDATE tasks SET done=1, completed=? WHERE kind='meeting' AND done=0
                             AND due!='' AND time!='' AND (due||' '||time) < ?""",
                          (now.isoformat(timespec="seconds"), cutoff))
                rows = c.execute("SELECT * FROM tasks ORDER BY done, position, id").fetchall()
            return self.send(200, json.dumps([dict(r) for r in rows]))
        self.send(404, '{"error":"not found"}')

    def do_POST(self):
        if not self.guard(write=True): return
        if self.path == "/api/tasks":
            b, err = clean_fields(self.body())
            if err: return self.send(400, json.dumps({"error": err}))
            title = b.get("title", "")
            if not title:
                return self.send(400, '{"error":"title required"}')
            with db() as c:
                pos = c.execute("SELECT COALESCE(MAX(position),0)+1 FROM tasks").fetchone()[0]
                cur = c.execute(
                    """INSERT INTO tasks(title,notes,project,priority,due,position,created,kind,time,link)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (title, b.get("notes", ""), b.get("project", ""), b.get("priority", 2),
                     b.get("due", ""), pos, datetime.now().isoformat(timespec="seconds"),
                     b.get("kind", "task"), b.get("time", ""), b.get("link", "")))
            return self.send(201, json.dumps({"id": cur.lastrowid}))
        if self.path == "/api/reorder":
            # Reorder only the given ids among the slots they already occupy,
            # so reordering one day's list doesn't disturb other days.
            want = []
            for x in self.body().get("ids", []):
                if int(x) not in want: want.append(int(x))
            with db() as c:
                full = [r[0] for r in c.execute("SELECT id FROM tasks ORDER BY position, id")]
                present = set(full)
                want = [x for x in want if x in present]
                wset = set(want)
                slots = [i for i, x in enumerate(full) if x in wset]
                for k, i in enumerate(slots):
                    full[i] = want[k]
                for pos, tid in enumerate(full):
                    c.execute("UPDATE tasks SET position=? WHERE id=?", (pos, tid))
            return self.send(200, '{"ok":true}')
        if self.path == "/api/update/check":
            try:
                r = subprocess.run([sys.executable, UPDATER, "--check"], capture_output=True, text=True, timeout=60)
                return self.send(200, r.stdout or '{"error":"no response from updater"}')
            except Exception as e:
                return self.send(200, json.dumps({"error": str(e)}))
        if self.path == "/api/update/install":
            try:
                start_update()
                return self.send(200, json.dumps({"started": True, "from": version()}))
            except Exception as e:
                return self.send(500, json.dumps({"error": str(e)}))
        if self.path == "/api/carryover":
            # Move every unfinished task dated before `to` onto `to`
            to = self.body().get("to") or datetime.now().strftime("%Y-%m-%d")
            if not (isinstance(to, str) and DATE_RE.match(to)):
                return self.send(400, '{"error":"to must be YYYY-MM-DD"}')
            with db() as c:
                n = c.execute("""UPDATE tasks SET due=? WHERE done=0 AND kind!='meeting'
                                 AND due!='' AND due<?""", (to, to)).rowcount
            return self.send(200, json.dumps({"moved": n}))
        self.send(404, '{"error":"not found"}')

    def do_PUT(self):
        if not self.guard(write=True): return
        tid = self.task_id()
        b, err = clean_fields(self.body())
        if err: return self.send(400, json.dumps({"error": err}))
        if "title" in b and not b["title"]: b["title"] = "Untitled"
        if tid is None or not b:
            return self.send(400, '{"error":"bad request"}')
        with db() as c:
            old = c.execute("SELECT due, time FROM tasks WHERE id=?", (tid,)).fetchone()
            if old is None:
                return self.send(404, '{"error":"not found"}')
            # Meeting moved to a new date/time: allow reminders to fire again
            if "notified" not in b and (b.get("due", old["due"]), b.get("time", old["time"])) != (old["due"], old["time"]):
                b["notified"] = 0
            if "done" in b:
                b["completed"] = datetime.now().isoformat(timespec="seconds") if b["done"] else ""
            sets = ",".join(f"{k}=?" for k in b)
            c.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*b.values(), tid))
        self.send(200, '{"ok":true}')

    def do_DELETE(self):
        if not self.guard(write=True): return
        tid = self.task_id()
        with db() as c:
            if self.path == "/api/tasks/completed":
                c.execute("DELETE FROM tasks WHERE done=1")
            elif tid is not None:
                c.execute("DELETE FROM tasks WHERE id=?", (tid,))
        self.send(200, '{"ok":true}')

PAGE = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "page.html"), encoding="utf-8").read()

if __name__ == "__main__":
    init_db()
    srv = ThreadingHTTPServer((HOST, PORT), H)
    print(f"TaskMate running on http://{HOST}:{PORT}  (data: {DB})", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass
