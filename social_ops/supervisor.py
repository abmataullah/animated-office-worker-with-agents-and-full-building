"""
Social Ops supervisor — runs inside the monitor server.

For every Facebook page pipeline on this PC it:
  * tails the pipeline's own log and turns lines into live agent states
    (working / done / post / error) for the Social Media Ops floor,
  * keeps the pipeline's scheduler process alive (auto-revive, rate limited),
  * flags pages that are LATE (no post for longer than expected while in their posting window).
"""

import os
import re
import sys
import time
import threading
import subprocess

try:
    import psutil
except ImportError:  # monitor-server installs psutil on start
    psutil = None

PY = r"C:\Users\abmat\AppData\Local\Programs\Python\Python313\python.exe"
PYW = r"C:\Users\abmat\AppData\Local\Programs\Python\Python313\pythonw.exe"
AG = r"E:\Developed by antigravity"
USA = r"d:\my random work\Random Idea discussion\USA unfiltered\automation"
WG = AG + r"\The Wonderful Grpahics Motivation engine"

TS_BRACKET = (re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]"), "%Y-%m-%d %H:%M:%S")
TS_LOGGING = (re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d+"), "%Y-%m-%d %H:%M:%S")
TS_BST_12H = (re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{1,2}:\d{2}:\d{2} [AP]M) \(BST\)\]"), "%Y-%m-%d %I:%M:%S %p")

BOSS = "Social Ops Chief"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def R(pattern, agent, kind, text=None):
    """Log rule: regex -> (agent, kind, text template using {1}, {2}...)."""
    return (re.compile(pattern), agent, kind, text)


PIPELINES = [
    {
        "id": "truenews", "name": "True News", "short": "TN", "color": "#ef4444",
        "cwd": AG + r"\News and photocard for true news",
        "cmd": [PY, "run_pc_master.py"], "match": "run_pc_master.py",
        "log": AG + r"\News and photocard for true news\output\pc_master_publisher.log", "ts": TS_LOGGING,
        "window": (5, 23), "max_gap_h": 7,
        "slots": ["05:30", "08:30", "13:30", "17:00", "19:30", "21:00", "21:30"],
        "agents": ["News Curator", "Card Designer", "Bulletin Reels", "TN Publisher", "Telegram Bot"],
        "default_agent": "TN Publisher",
        "rules": [
            R(r"Scanning news feeds", "News Curator", "work", "Scanning Bangla news feeds…"),
            R(r"No unique stories met the threshold.*Highest found: (\d+)", "News Curator", "note", "Feeds quiet · best story scored {1}/75"),
            R(r"Anti-Duplicate Engine protected page: (\d+)", "News Curator", "note", "{1} duplicate stories rejected"),
            R(r"(?i)disaster|USGS|GDACS|cyclone alert", "News Curator", "work", "Checking disaster alerts"),
            R(r"\[(image_fetcher|photocard\w*|card\w*)\]", "Card Designer", "work", "Designing photocard"),
            R(r"(?i)rendering .*photocard|photocard .*render", "Card Designer", "work", "Rendering photocard"),
            R(r"Next peak reel broadcast in (.*?)\.", "Bulletin Reels", "note", "Next reel bulletin in {1}"),
            R(r"Peak Broadcast Window Reached|Initiating video synthesis", "Bulletin Reels", "work", "Producing 60s bulletin reel"),
            R(r"\[(video_renderer|audio_synthesizer)\]", "Bulletin Reels", "work", "Rendering reel audio/video"),
            R(r"Rendering (\d+)-story typewriter reel", "Bulletin Reels", "work", "Rendering {1}-story voiced reel"),
            R(r"Voiceover ready for (\d+)/(\d+) stories", "Bulletin Reels", "work", "Anchor voiceover ready ({1}/{2} stories)"),
            R(r"TTS voiceover failed \((\S+)\)", "Bulletin Reels", "error", "Voiceover failed ({1}) — retrying"),
            R(r"refusing to publish a silent reel", "Bulletin Reels", "error", "No voice — reel held back, will retry"),
            R(r"Soundtrack mix failed", "Bulletin Reels", "error", "Soundtrack mix failed — voice-only fallback used"),
            R(r"Pure Typewriter Reel rendered in ([\d.]+)s", "Bulletin Reels", "done", "Reel rendered in {1}s"),
            R(r"ReelScheduler\] Cycle finished with status: (\w+)", "Bulletin Reels", "done", "Reel cycle: {1}"),
            R(r"Cooldown active \((\w+)\): (\d+) minutes", "TN Publisher", "note", "Cooldown {2}m before next {1}"),
            # Every Facebook publish (card or reel) passes the gateway exactly once
            R(r"\[PublishGateway\].*Successfully published to Facebook! post_id=(\S+)", "TN Publisher", "post", "Published to Facebook ✓"),
            R(r"Successfully published Reel on Page", "Bulletin Reels", "done", "Reel live on Facebook"),
            R(r"Dispatched Facebook publish notification to Telegram", "Telegram Bot", "done", "Sent publish alert to admin"),
            R(r"\[TrueNewsTelegram\].*(getaddrinfo failed|connection attempt failed)", "Telegram Bot", "note", "Reconnecting to Telegram…"),
            R(r"Facebook authorization failed", "TN Publisher", "error", "Facebook token rejected"),
            R(r"\[ERROR\] \[([\w.]+)\] (.*)", None, "error", "{2}"),
        ],
    },
    {
        "id": "englishpro", "name": "English Pro Academy", "short": "EP", "color": "#f59e0b",
        "cwd": AG + r"\English Pro Academy",
        "cmd": [PYW, AG + r"\English Pro Academy\local_scheduler.py"], "match": r"English Pro Academy\local_scheduler.py",
        "log": AG + r"\English Pro Academy\scheduler.log", "ts": TS_BRACKET,
        "window": (8, 23), "max_gap_h": 9,
        "slots": ["08:30", "13:00", "20:00"],
        "agents": ["EP Publisher", "EP Designer", "AI Teacher", "Content Autopilot"],
        "default_agent": "EP Publisher",
        "rules": [
            R(r"Approved by Reach Filter for (Slot \d+: [^(]+)", "EP Publisher", "work", "Approved: {1}"),
            R(r"Publishing on Track (\d+): (.*)", "EP Publisher", "work", "Track {1}: {2}"),
            R(r"Rendering Video Reel", "EP Designer", "work", "Rendering spoken video reel"),
            R(r"Rendering Multi-Sentence Graphic Card", "EP Designer", "work", "Rendering 1080x1350 graphic card"),
            R(r"Uploading (photo|High-Resolution Graphic Card|video|reel)", "EP Publisher", "work", "Uploading to Facebook…"),
            R(r"(Photo|Video Reel) published! Post ID", "EP Publisher", "post", "{1} published to Facebook ✓"),
            R(r"First comment added automatically", "AI Teacher", "done", "Added the first comment"),
            R(r"Sleeping hours in Bangladesh", "EP Publisher", "note", "Page sleeping (00:30–07:45 BST)"),
            R(r"\[AI Teacher\] 🔍 Checking", "AI Teacher", "work", "Scanning comments for student answers"),
            R(r"\[AI Teacher\] ✅ Scan complete\. (\d+) posts", "AI Teacher", "note", "Checked {1} posts · no new comments"),
            R(r"\[AI Teacher\] 🎯 Found (\d+) new", "AI Teacher", "work", "Grading {1} new student comment(s)"),
            R(r"Successfully replied to (.*?)!", "AI Teacher", "done", "Replied to {1}"),
            R(r"\[Polite Autopilot\] Starting daily generation", "Content Autopilot", "work", "Generating daily content packages"),
            R(r"\[Processing\] (\S+): (.*)", "Content Autopilot", "work", "Building {1}: {2}"),
            R(r"Successfully created (\d+) daily", "Content Autopilot", "done", "Created {1} new content packages"),
            R(r"Ledger Updated", "Content Autopilot", "done", "Synced the published-posts ledger"),
            R(r"(?i)\b(error|failed|exception)\b(.*)", None, "error", "{1}{2}"),
        ],
    },
    {
        "id": "jobprep", "name": "10 Sec Job Prep", "short": "JP", "color": "#22c55e",
        "cwd": AG + r"\Job preparation",
        "cmd": [PYW, AG + r"\Job preparation\facebook_auto_scheduler.py"], "match": "facebook_auto_scheduler.py",
        "log": AG + r"\Job preparation\facebook_scheduler.log", "ts": TS_BST_12H,
        "window": (8, 23), "max_gap_h": 9,
        "slots": ["08:30", "13:00", "19:30"],
        "agents": ["Quiz Master", "Quiz Card Artist", "Quiz Reels", "JP Publisher", "Quiz Responder"],
        "default_agent": "JP Publisher",
        "rules": [
            R(r"Reach Filter Hold\] (.{0,90})", "JP Publisher", "note", "Holding: {1}"),
            R(r"Reach Filter Approved\] (.*?) active", "JP Publisher", "work", "Approved: {1}"),
            R(r"--- \[Post #(\d+): (.*?)\]", "Quiz Master", "done", "Picked questions for post #{1}"),
            R(r"Rendering (1-Question|2-in-1)", "Quiz Card Artist", "work", "Rendering {1} quiz photocard"),
            R(r"Generating 2-in-1 Video Reel", "Quiz Reels", "work", "Generating Bangla quiz reel"),
            R(r"Video Reel generation failed", "Quiz Reels", "error", "Reel generation failed — falling back to card"),
            # Each format ends with exactly one of these: dual card & reel -> "Cycle finished!", single quiz -> "Registered quiz post"
            R(r"Photocard Published! Post ID", "JP Publisher", "done", "Photocard uploaded"),
            R(r"Cycle finished! Stats: (\d+) Photocards, (\d+) Reels", "JP Publisher", "post", "Published ✓ ({1} cards · {2} reels total)"),
            R(r"Registered quiz post", "JP Publisher", "post", "Interactive quiz published ✓"),
            R(r"Comment posted!", "Quiz Responder", "done", "Posted the answer comment"),
            R(r"Comment bot error: (.*)", "Quiz Responder", "error", "{1}"),
            R(r"Post cycle did not publish", "JP Publisher", "error", "Post failed — retrying in 15 min"),
            R(r"(?i)(upload error|render error|exception|Error during post cycle)(.*)", None, "error", "{1}{2}"),
        ],
    },
    {
        "id": "usa", "name": "USA Unfiltered", "short": "US", "color": "#3b82f6",
        "cwd": USA,
        "cmd": [PYW, USA + r"\scheduler.py"], "match": r"USA unfiltered\automation\scheduler.py",
        "log": USA + r"\scheduler.log", "ts": TS_BRACKET,
        "window": (17, 9), "max_gap_h": 5,
        "slots": ["every 2h20m during US hours (17:00–09:00 BST)"],
        "agents": ["US News Fetcher", "US Reel Maker", "US Anchor", "US Publisher"],
        "default_agent": "US Reel Maker",
        "rules": [
            R(r"Fetching top 3 fresh breaking stories", "US News Fetcher", "work", "Fetching top US breaking stories"),
            R(r"\[\+\] Story (\d): \[([^\]]+)\] (.*)", "US News Fetcher", "done", "Story {1} ({2}): {3}"),
            R(r"Rendering full-bleed Story #(\d)", "US Reel Maker", "work", "Rendering story card #{1}"),
            R(r"Generating American anchor voiceover", "US Anchor", "work", "Recording anchor voiceover"),
            R(r"Assembling 1080x1920 MP4", "US Reel Maker", "work", "Assembling 1080x1920 reel"),
            R(r"Perfected 3-Story Reel successfully created", "US Reel Maker", "done", "3-story reel ready"),
            R(r"Publishing Reel to Facebook", "US Publisher", "work", "Uploading reel to Facebook…"),
            R(r"Reel published successfully! Video ID", "US Publisher", "post", "Reel published ✓"),
            R(r"Fallback photocard published", "US Publisher", "post", "Fallback photocard published ✓"),
            R(r"falling back to a photocard", "US Publisher", "work", "Reel failed — posting photocard instead"),
            R(r"Outside US active window", "US Publisher", "note", "Outside US hours — sleeping"),
            R(r"Sleeping for (\d+) minutes\. Next check at ~(.*?)\.\.\.", "US Publisher", "note", "Next cycle at {2}"),
            R(r"Error during publishing cycle: (.{0,80})", "US Anchor", "error", "{1}"),
        ],
    },
    {
        # Runs as a Windows scheduled task (run.py --post-now, 4x daily), not a daemon:
        # status comes from the task; never "revive" it, since starting the task publishes a post.
        "id": "growth", "name": "The Growth Mindset", "short": "GM", "color": "#a855f7",
        "task": "TheGrowthMindset_AutoPoster",
        "log": AG + r"\The Growth Mindset\logs\poster.log", "ts": TS_LOGGING,
        "window": (6, 23), "max_gap_h": 6,
        "slots": ["06:30", "11:30", "16:00", "20:30"],
        "agents": ["GM Curator", "GM Publisher"],
        "default_agent": "GM Publisher",
        "rules": [
            R(r"Starting Daily Post Execution Pipeline", "GM Curator", "work", "Starting the post pipeline"),
            R(r"Found queue post #(\S+): \"(.*?)\"", "GM Curator", "done", "Drive calendar: {2}"),
            R(r"Using curated vault for pillar: (\w+)", "GM Curator", "work", "Picking a {1} quote"),
            R(r"Selected Wisdom: \"(.*?)\" by (.*?) \[", "GM Curator", "done", "Quote by {2}"),
            R(r"Image card rendered at", "GM Publisher", "work", "Quote card rendered"),
            R(r"Uploading photo (\S+) to Facebook", "GM Publisher", "work", "Uploading {1}"),
            R(r"Successfully published to Facebook! Post ID", "GM Publisher", "post", "Quote card published ✓"),
            R(r"\[(ERROR|CRITICAL)\] (.*)", "GM Publisher", "error", "{2}"),
        ],
    },
    {
        "id": "political", "name": "Political Analytica", "short": "PA", "color": "#e11d48",
        "manual": True, "agents": ["PA Editor"], "slots": ["manual publishing"],
    },
]


def _parse_ts(line, ts_rule):
    rx, fmt = ts_rule
    m = rx.match(line)
    if not m:
        return None
    try:
        return time.mktime(time.strptime(m.group(1), fmt))
    except ValueError:
        return None


def _fill(tpl, m):
    out = tpl
    for i, g in enumerate(m.groups(), start=1):
        out = out.replace("{" + str(i) + "}", (g or "").strip())
    return out[:150]


class SocialSupervisor:
    def __init__(self, log_event=None):
        self.lock = threading.RLock()
        self.log_event = log_event or (lambda *a, **k: None)
        self.auto_revive = True
        self.agents = {}
        self.pipes = {}
        self.restarts = {}
        self.posts = []          # recent post events for the floor (packets)
        for p in PIPELINES:
            self.pipes[p["id"]] = {"running": False, "pid": None, "started": 0, "last_post": 0,
                                   "posts_today": 0, "last_lines": [], "last_error": "", "launched_at": 0,
                                   "today": time.strftime("%Y-%m-%d"), "offset": 0, "buf": b"", "last_ts": 0}
            for a in p["agents"]:
                self.agents[a] = {"state": "idle", "task": "", "result": "", "runs": 0, "started": 0,
                                  "ended": 0, "pipeline": p["id"]}
        self.agents[BOSS] = {"state": "idle", "task": "", "result": "Watching every page", "runs": 0,
                             "started": 0, "ended": 0, "pipeline": "ops"}
        self._seed_from_history()

    # ---------- log parsing ----------
    def _apply(self, p, line, ts, live):
        st = self.pipes[p["id"]]
        clean = line.strip()
        if not clean or set(clean) <= set("=-*"):
            return
        if live:
            st["last_lines"] = (st["last_lines"] + [re.sub(r"\s+", " ", clean)[:140]])[-6:]
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
        for rx, agent, kind, tpl in p["rules"]:
            m = rx.search(clean)
            if not m:
                continue
            agent = agent or p["default_agent"]
            text = _fill(tpl, m) if tpl else clean[:150]
            a = self.agents[agent]
            if kind == "work":
                if a["state"] != "working" or a["task"] != text:
                    a["runs"] += 1
                a.update(state="working", task=text, started=ts)
            elif kind == "note":
                a["result"] = text
                if a["state"] == "working":
                    a["task"] = text
            elif kind in ("done", "post", "error"):
                a.update(state="error" if kind == "error" else "done", result=text, ended=ts)
                a["runs"] += 1
                if kind == "error":
                    st["last_error"] = text
                if kind == "post":
                    st["last_post"] = max(st["last_post"], ts)
                    if day == time.strftime("%Y-%m-%d"):
                        st["posts_today"] += 1
                    if live:
                        self.posts = (self.posts + [{"pipeline": p["id"], "agent": agent, "ts": ts, "text": text}])[-20:]
            break

    def _read_new(self, p, seed=False):
        path = p.get("log")
        st = self.pipes[p["id"]]
        if not path or not os.path.exists(path):
            return
        size = os.path.getsize(path)
        if size < st["offset"]:  # rotated / truncated
            st["offset"], st["buf"] = 0, b""
        if seed:
            st["offset"] = max(0, size - 400_000)
        if size == st["offset"]:
            return
        with open(path, "rb") as f:
            f.seek(st["offset"])
            data = st["buf"] + f.read()
            st["offset"] = f.tell()
        lines = data.split(b"\n")
        st["buf"] = lines.pop()  # partial last line
        if seed and lines:
            lines = lines[1:]  # first line may be cut mid-way
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            ts = _parse_ts(line, p["ts"])
            if ts:
                st["last_ts"] = ts
            when = ts or (st["last_ts"] if seed else time.time())
            self._apply(p, line, when or time.time(), live=not seed)
        if seed:
            st["last_lines"] = [re.sub(r"\s+", " ", l.decode("utf-8", "replace").strip())[:140]
                                for l in lines if l.strip() and not set(l.strip()) <= set(b"=-*")][-6:]

    def _seed_from_history(self):
        for p in PIPELINES:
            if p.get("manual"):
                continue
            try:
                self._read_new(p, seed=True)
            except Exception as e:
                print(f"[SocialOps] seed {p['id']}: {e}")

    # ---------- processes ----------
    def _find_procs(self, p):
        if not psutil:
            return []
        needle = p["match"].lower()
        found = []
        # Read via methods, not proc.info: psutil shares Process objects between threads, so the
        # stats thread's process_iter(attrs=...) can overwrite .info mid-loop.
        for proc in psutil.process_iter():
            try:
                if proc.name().lower() not in ("python.exe", "pythonw.exe", "py.exe"):
                    continue
                cmd = " ".join(proc.cmdline() or []).lower()
                if needle in cmd and "supervisor" not in cmd:
                    found.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return found

    def _launch(self, p, reason):
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (survives our restarts)
        # Keep each scheduler's stderr: a crash that never reaches its own log still leaves a trace here
        os.makedirs(LOG_DIR, exist_ok=True)
        err = open(os.path.join(LOG_DIR, f"{p['id']}.stderr.log"), "a", encoding="utf-8")
        err.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} launched ({reason}) =====\n")
        err.flush()
        subprocess.Popen(p["cmd"], cwd=p["cwd"], creationflags=flags, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=err)
        err.close()
        now = time.time()
        self.pipes[p["id"]]["launched_at"] = now
        self.restarts.setdefault(p["id"], []).append(now)
        msg = f"{reason}: {p['name']}"
        b = self.agents[BOSS]
        b.update(state="done", result=msg, ended=now)
        b["runs"] += 1
        self.log_event(BOSS, msg, status="warning", dept="Social Media Ops", source="social_ops")
        print(f"[SocialOps] {msg}")

    @staticmethod
    def _query_task(name):
        """(exists, enabled_and_ready, last_result) for a Windows scheduled task."""
        try:
            out = subprocess.run(["schtasks", "/query", "/tn", name, "/fo", "csv", "/v"], capture_output=True,
                                 text=True, timeout=10, creationflags=0x08000000)
            if out.returncode != 0:
                return False, False, None
            import csv
            row = next(csv.DictReader(out.stdout.splitlines()))
            ok = row.get("Scheduled Task State", "") == "Enabled" and row.get("Status", "") in ("Ready", "Running")
            return True, ok, row.get("Last Result", "")
        except Exception:
            return False, False, None

    def check_processes(self, allow_launch=True):
        now = time.time()
        for p in PIPELINES:
            if p.get("manual"):
                continue
            st = self.pipes[p["id"]]
            if p.get("task"):
                exists, ok, last = self._query_task(p["task"])
                st["running"], st["pid"], st["started"] = ok, None, 0
                if not exists:
                    st["last_error"] = f"Scheduled task '{p['task']}' not found"
                elif not ok:
                    st["last_error"] = f"Scheduled task '{p['task']}' is disabled"
                elif last not in ("0", "267009", "267011", None, ""):  # 267009 running, 267011 never run yet
                    st["last_error"] = f"Last scheduled run exited with code {last}"
                continue
            procs = self._find_procs(p)
            if st["pid"] and not procs:
                # Record unexpected exits with a timestamp so a pattern (e.g. a tool killing python) can be traced
                msg = f"{p['name']} scheduler (pid {st['pid']}) stopped unexpectedly"
                print(f"[SocialOps] {time.strftime('%H:%M:%S')} {msg}")
                self.log_event(BOSS, msg, status="error", dept="Social Media Ops", source="social_ops")
            st["running"] = bool(procs)
            st["pid"] = procs[0].pid if procs else None
            try:
                st["started"] = procs[0].create_time() if procs else 0
            except Exception:
                st["started"] = 0
            if procs or not allow_launch or not self.auto_revive or now - st["launched_at"] < 90:
                continue
            recent = [t for t in self.restarts.get(p["id"], []) if now - t < 3600]
            self.restarts[p["id"]] = recent
            if len(recent) < 3:
                self._launch(p, "Revived stopped scheduler")
            elif not st["last_error"].startswith("Crash loop"):
                st["last_error"] = "Crash loop: 3 restarts in the last hour — check its log"

    def restart(self, pid_id):
        p = next((x for x in PIPELINES if x["id"] == pid_id and not x.get("manual")), None)
        if not p:
            return False, "unknown pipeline"
        if p.get("task"):
            return False, f"{p['name']} runs from Task Scheduler at {', '.join(p['slots'])} — nothing to restart"
        for proc in self._find_procs(p):
            try:
                proc.terminate()
                proc.wait(timeout=8)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._launch(p, "Restarted scheduler")
        return True, f"{p['name']} restarted"

    def revive_all(self):
        started = []
        for p in PIPELINES:
            if not p.get("manual") and not p.get("task") and not self._find_procs(p):
                self._launch(p, "Revived stopped scheduler")
                started.append(p["name"])
        return started

    # ---------- status ----------
    @staticmethod
    def _in_window(window, hour):
        a, b = window
        return a <= hour < b if a < b else (hour >= a or hour < b)

    def _next_slot(self, p):
        slots = [s for s in p.get("slots", []) if re.fullmatch(r"\d{2}:\d{2}", s)]
        if not slots:
            return (p.get("slots") or [""])[0]
        now = time.strftime("%H:%M")
        upcoming = [s for s in slots if s > now]
        return upcoming[0] if upcoming else f"{slots[0]} tomorrow"

    def pipeline_status(self, p):
        st = self.pipes[p["id"]]
        now = time.time()
        if p.get("manual"):
            return "manual"
        if not st["running"]:
            return "starting" if now - st["launched_at"] < 90 else "stopped"
        if p.get("task") and st["last_error"].startswith("Last scheduled run exited"):
            return "error"
        lt = time.localtime()
        if self._in_window(p["window"], lt.tm_hour) and st["last_post"] and now - st["last_post"] > p["max_gap_h"] * 3600:
            return "late"
        if st["last_error"] and self.agents[p.get("default_agent", "")]["state"] == "error":
            return "error"
        return "running"

    def tick(self):
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            for p in PIPELINES:
                if p.get("manual"):
                    continue
                st = self.pipes[p["id"]]
                if st["today"] != today:
                    st["today"], st["posts_today"] = today, 0
                try:
                    self._read_new(p)
                except Exception as e:
                    print(f"[SocialOps] tail {p['id']}: {e}")
            now = time.time()
            for a in self.agents.values():  # log lines are instants: a 'working' agent goes quiet after 45s
                if a["state"] == "working" and now - a["started"] > 45:
                    a["state"] = "idle"

    def snapshot(self):
        with self.lock:
            out = []
            for p in PIPELINES:
                st = self.pipes[p["id"]]
                out.append({
                    "id": p["id"], "name": p["name"], "short": p["short"], "color": p["color"],
                    "status": self.pipeline_status(p), "running": st["running"], "pid": st["pid"],
                    "uptime_s": int(time.time() - st["started"]) if st["started"] else 0,
                    "posts_today": st["posts_today"], "last_post": st["last_post"],
                    "next_slot": self._next_slot(p), "slots": p.get("slots", []),
                    "last_lines": st["last_lines"][-4:], "last_error": st["last_error"],
                    "agents": p["agents"], "manual": bool(p.get("manual")),
                })
            boss = self.agents[BOSS]
            alive = sum(1 for x in out if x["running"])
            auto = sum(1 for x in out if not x["manual"])
            boss["task"] = f"Supervising {alive}/{auto} schedulers"
            return {"now": time.time(), "auto_revive": self.auto_revive, "pipelines": out,
                    "agents": self.agents, "posts": self.posts[-10:]}

    def run_forever(self):
        boot = time.time()
        last_proc = 0
        while time.time() - boot < 60:  # report status at once, but give Startup entries 60s before reviving
            try:
                self.tick()
                with self.lock:
                    self.check_processes(allow_launch=False)
            except Exception as e:
                print(f"[SocialOps] boot error: {e}")
            time.sleep(5)
        while True:
            try:
                self.tick()
                if time.time() - last_proc > 30:
                    with self.lock:
                        self.check_processes()
                    last_proc = time.time()
            except Exception as e:
                print(f"[SocialOps] loop error: {e}")
            time.sleep(3)
