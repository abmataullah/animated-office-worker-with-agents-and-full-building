"""
Live status bus for the Job Finder floor.
Every career agent reports start/finish/failure here; the office widget polls
GET /career/live and animates the matching worker in real time.
State lives in a JSON file so CLI runs and the server share one view.
"""

import os, json, time, threading, functools

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "live_status.json")

ROSTER = [
    "Pipeline Orchestrator", "CV Analyst", "Job Radar", "ATS Scout", "Fit Auditor",
    "Resume Builder", "Proposal Scribe", "Mail Dispatcher", "Inbox Watcher",
    "Interview Liaison", "Calendar Concierge", "Interview Debrief",
    "Sheets Overseer", "Company Dossier",
]

PIPELINE_STAGES = [
    ("CV & Profile Sync", "CV Analyst"),
    ("Job Radar Sweep", "Job Radar"),
    ("ATS Board Scan", "ATS Scout"),
    ("Remote & Fit Audit", "Fit Auditor"),
    ("ATS Resume PDF", "Resume Builder"),
    ("Apply Queue", "Proposal Scribe"),
    ("Inbox Watch", "Inbox Watcher"),
    ("Calendar Reminders", "Calendar Concierge"),
    ("Interview Debrief", "Interview Debrief"),
    ("Sheets Sync", "Sheets Overseer"),
]

# Names other modules log under -> roster name
ALIASES = {
    "ATS Resume Generator": "Resume Builder",
    "Agent 4 (ATS Resume)": "Resume Builder",
    "Agent 2 (Radar)": "Job Radar",
    "Agent 5 (Mail Dispatcher)": "Mail Dispatcher",
    "Agent 6 (Inbox Watcher)": "Inbox Watcher",
    "Agent 8 (Calendar Concierge)": "Calendar Concierge",
    "Agent 9 (Interview Debrief)": "Interview Debrief",
}

_lock = threading.RLock()


def canonical(name):
    return ALIASES.get(name, name)


def _blank():
    return {
        "agents": {n: {"state": "idle", "task": "", "result": "", "runs": 0,
                       "started": 0, "ended": 0} for n in ROSTER},
        "pipeline": {"running": False, "stage_idx": -1, "stage": "", "started": 0,
                     "ended": 0, "cycles": 0, "last_summary": [], "trigger": ""},
        "autopilot": {"enabled": True, "interval_min": 180, "next_run": 0, "last_run": 0},
    }


def _read():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _blank()
    base = _blank()
    for k in base:
        data.setdefault(k, base[k])
    for n in ROSTER:
        data["agents"].setdefault(n, base["agents"][n])
    return data


def _write(data):
    tmp = STATUS_FILE + f".{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    for _ in range(20):
        try:
            os.replace(tmp, STATUS_FILE)
            return
        except PermissionError:  # reader holds the file open on Windows
            time.sleep(0.02)
    try:
        os.remove(tmp)
    except OSError:
        pass


def update(mutator):
    with _lock:
        data = _read()
        mutator(data)
        _write(data)
        return data


def start(agent, task):
    agent = canonical(agent)

    def m(d):
        a = d["agents"].setdefault(agent, _blank()["agents"][ROSTER[0]].copy())
        a.update(state="working", task=str(task)[:140], started=time.time())
        a["runs"] = a.get("runs", 0) + 1
    update(m)


def finish(agent, result="", error=False):
    agent = canonical(agent)

    def m(d):
        a = d["agents"].setdefault(agent, _blank()["agents"][ROSTER[0]].copy())
        a.update(state="error" if error else "done", result=str(result)[:160], ended=time.time())
    update(m)


def track(agent, task, summarize=None):
    """Decorator: mark agent working for the call, then done/error with a summary."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            label = task(*args, **kwargs) if callable(task) else task
            start(agent, label)
            try:
                res = fn(*args, **kwargs)
            except Exception as e:
                finish(agent, f"Failed: {e}", error=True)
                raise
            is_err = False
            try:
                summary = summarize(res) if summarize else "Completed"
                if isinstance(summary, tuple):
                    summary, is_err = summary
            except Exception:
                summary = "Completed"
            finish(agent, summary, error=bool(is_err))
            return res
        return wrapper
    return deco


BOSS = "Pipeline Orchestrator"


def pipeline_begin(trigger="manual"):
    def m(d):
        now = time.time()
        d["pipeline"].update(running=True, stage_idx=-1, stage="Starting cycle",
                             started=now, trigger=trigger, last_summary=[])
        b = d["agents"][BOSS]
        b.update(state="working", task=f"Starting 10-stage cycle ({trigger})", started=now)
        b["runs"] = b.get("runs", 0) + 1
        ap = d["autopilot"]
        if ap.get("enabled"):  # any cycle (manual or scheduled) restarts the autopilot countdown
            ap["next_run"] = now + max(5, int(ap.get("interval_min", 30))) * 60
    update(m)


def pipeline_stage(idx):
    name, agent = PIPELINE_STAGES[idx]

    def m(d):
        d["pipeline"].update(stage_idx=idx, stage=name)
        d["agents"][BOSS]["task"] = f"Stage {idx + 1}/{len(PIPELINE_STAGES)}: {name} → {agent}"
    update(m)


def pipeline_end(summary_lines, error=None):
    def m(d):
        now = time.time()
        p = d["pipeline"]
        p.update(running=False, ended=now, stage_idx=len(PIPELINE_STAGES) if not error else p.get("stage_idx", -1),
                 stage="Cycle failed" if error else "Cycle complete",
                 last_summary=list(summary_lines)[-12:] + ([f"ERROR: {error}"] if error else []))
        if not error:
            p["cycles"] = p.get("cycles", 0) + 1
        d["agents"][BOSS].update(state="error" if error else "done", ended=now,
                                 result=f"Cycle failed: {error}"[:160] if error else f"Cycle #{p['cycles']} complete")
    update(m)


def pipeline_is_running(stale_after=600):
    p = _read()["pipeline"]
    return bool(p.get("running")) and time.time() - p.get("started", 0) < stale_after


def set_autopilot(**fields):
    def m(d):
        d["autopilot"].update({k: v for k, v in fields.items() if v is not None})
    return update(m)["autopilot"]


def _load_json(name, default):
    try:
        with open(os.path.join(SCRIPT_DIR, name), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _count_lines(name, status=None):
    try:
        with open(os.path.join(SCRIPT_DIR, name), "r", encoding="utf-8", errors="ignore") as f:
            if status is None:
                return sum(1 for line in f if line.strip())
            return sum(1 for line in f if line.strip() and json.loads(line).get("status") == status)
    except Exception:
        return 0


def kpis():
    jobs = _load_json("jobs.json", [])
    apps = _load_json("applications.json", [])
    ints = _load_json("interviews.json", [])
    tracker = _load_json("sheets_data.json", {})
    outcomes = [str(v.get("outcome") or v.get("stage") or "").lower() for v in tracker.values()] if isinstance(tracker, dict) else []
    skipped = {a.get("job_id") for a in apps if a.get("status") == "skipped"}
    top = sorted((j for j in jobs if j.get("id") not in skipped and not j.get("not_a_fit")),
                 key=lambda j: j.get("match_score", 0), reverse=True)[:8]
    return {
        "jobs_found": len(jobs),
        "strong_matches": sum(1 for j in jobs if j.get("match_score", 0) >= 70),
        "queued": sum(1 for a in apps if a.get("status") == "ready_to_apply"),
        # Real applications only: ones you marked applied + emails actually delivered (test-mode sends excluded)
        "applied": sum(1 for a in apps if a.get("status") == "applied") + _count_lines("sent_emails.jsonl", "delivered_live"),
        "replies": _count_lines("inbox_messages.jsonl"),
        "interviews": len(ints),
        "offers": sum(1 for o in outcomes if "offer" in o),
        "tracked": len(tracker) if isinstance(tracker, dict) else 0,
        "top_jobs": [{"title": j.get("title", ""), "company": j.get("company", ""),
                      "score": j.get("match_score", 0), "source": j.get("source", "")} for j in top],
        "next_interview": next(({"company": i.get("company"), "when": i.get("local_scheduled_time") or i.get("chosen_slot")}
                                for i in ints if i.get("status") == "scheduled"), None),
    }


def snapshot():
    with _lock:
        d = _read()
    d["now"] = time.time()
    d["stages"] = [{"name": n, "agent": a} for n, a in PIPELINE_STAGES]
    d["kpis"] = kpis()
    return d
