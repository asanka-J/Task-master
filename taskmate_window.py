#!/usr/bin/env python3
"""TaskMate desktop window: shows the TaskMate page in its own app window (no browser).
Only one window is opened; launching again brings the existing window to the front."""
import json, os, shutil, subprocess, sys
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gio, GLib

WebKit2 = None
for v in ("4.1", "4.0"):
    try:
        gi.require_version("WebKit2", v)
        from gi.repository import WebKit2
        break
    except (ValueError, ImportError):
        continue

PORT = int(os.environ.get("TASKMATE_PORT", "8765"))
URL = f"http://localhost:{PORT}/"
APP_ID = "io.github.asankaj.TaskMate"
APP_DIR = os.path.expanduser("~/.local/share/taskmate")
ICON = os.path.join(APP_DIR, "icon-app.svg")
STATE = os.path.expanduser("~/.config/taskmate/window.json")

def fallback_open():
    """No WebKit available: use a browser in app mode, or a normal tab as a last resort."""
    for b in ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        if shutil.which(b):
            subprocess.Popen([b, f"--app={URL}", "--class=taskmate"]); return
    subprocess.Popen(["xdg-open", URL])

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win:
            self.win.present(); return
        st = self.load_state()
        self.win = Gtk.ApplicationWindow(application=self, title="TaskMate")
        self.win.set_default_size(st.get("w", 900), st.get("h", 900))
        try:
            self.win.set_icon_from_file(ICON)
        except Exception:
            self.win.set_icon_name("checkbox-checked-symbolic")
        if st.get("max"): self.win.maximize()

        self.view = WebKit2.WebView()
        s = self.view.get_settings()
        s.set_enable_developer_extras(False)
        s.set_javascript_can_open_windows_automatically(False)
        self.view.connect("decide-policy", self.on_policy)
        self.view.connect("load-failed", self.on_fail)
        self.win.add(self.view)

        # Keyboard: Ctrl+R reload, Ctrl+W / Ctrl+Q close
        accel = Gtk.AccelGroup(); self.win.add_accel_group(accel)
        for key, fn in (("<Control>r", lambda *_: self.view.reload()),
                        ("F5", lambda *_: self.view.reload()),
                        ("<Control>w", lambda *_: self.win.close()),
                        ("<Control>q", lambda *_: self.win.close())):
            k, m = Gtk.accelerator_parse(key)
            accel.connect(k, m, 0, fn)

        self.win.connect("delete-event", self.save_state)
        self.view.load_uri(URL)
        self.win.show_all()

    def on_policy(self, view, decision, kind):
        # Meeting links and other outside pages open in the normal browser
        if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
            uri = decision.get_navigation_action().get_request().get_uri()
            if not uri.startswith(URL.rstrip("/")) and not uri.startswith(f"http://127.0.0.1:{PORT}"):
                subprocess.Popen(["xdg-open", uri]); decision.ignore(); return True
        return False

    def on_fail(self, view, event, uri, err):
        html = f"""<html><body style="font:15px system-ui;padding:40px;color:#444">
        <h2>TaskMate isn't running</h2><p>The background service didn't answer at {URL}.</p>
        <p>Start it with <code>systemctl --user start taskmate</code>, then press Ctrl+R.</p>
        <p>Retrying automatically…</p></body></html>"""
        view.load_alternate_html(html, uri, None)
        GLib.timeout_add_seconds(3, lambda: view.load_uri(URL) and False)
        return True

    def load_state(self):
        try: return json.load(open(STATE))
        except Exception: return {}

    def save_state(self, *_):
        try:
            os.makedirs(os.path.dirname(STATE), exist_ok=True)
            w, h = self.win.get_size()
            json.dump({"w": w, "h": h, "max": self.win.is_maximized()}, open(STATE, "w"))
        except Exception:
            pass
        return False

if __name__ == "__main__":
    if WebKit2 is None:
        fallback_open(); sys.exit(0)
    GLib.set_prgname("taskmate")
    GLib.set_application_name("TaskMate")
    sys.exit(App().run(sys.argv))
