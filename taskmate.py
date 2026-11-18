#!/usr/bin/env python3
"""TaskMate: a tiny self-hosted task + meeting list. Python stdlib only (no pip needed)."""
import json, os, sqlite3
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

DATA_DIR = os.path.expanduser(os.environ.get("TASKMATE_DATA", "~/.local/share/taskmate"))
DB = os.path.join(DATA_DIR, "tasks.db")
HOST = os.environ.get("TASKMATE_HOST", "0.0.0.0")
PORT = int(os.environ.get("TASKMATE_PORT", "8765"))
MEETING_AUTO_DONE_MIN = 60  # meetings are auto-completed this long after they start

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
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def task_id(self):
        try: return int(self.path.rstrip("/").split("/")[-1])
        except ValueError: return None

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, PAGE, "text/html; charset=utf-8")
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
        if self.path == "/api/tasks":
            b = self.body()
            title = (b.get("title") or "").strip()
            if not title:
                return self.send(400, '{"error":"title required"}')
            kind = "meeting" if b.get("kind") == "meeting" else "task"
            with db() as c:
                pos = c.execute("SELECT COALESCE(MAX(position),0)+1 FROM tasks").fetchone()[0]
                cur = c.execute(
                    """INSERT INTO tasks(title,notes,project,priority,due,position,created,kind,time,link)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (title, b.get("notes", ""), b.get("project", ""), int(b.get("priority", 2)),
                     b.get("due", ""), pos, datetime.now().isoformat(timespec="seconds"),
                     kind, b.get("time", ""), b.get("link", "")))
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
        if self.path == "/api/carryover":
            # Move every unfinished task dated before `to` onto `to`
            to = self.body().get("to") or datetime.now().strftime("%Y-%m-%d")
            with db() as c:
                n = c.execute("""UPDATE tasks SET due=? WHERE done=0 AND kind!='meeting'
                                 AND due!='' AND due<?""", (to, to)).rowcount
            return self.send(200, json.dumps({"moved": n}))
        self.send(404, '{"error":"not found"}')

    def do_PUT(self):
        tid = self.task_id()
        b = {k: v for k, v in self.body().items() if k in FIELDS}
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
