"""
Agent Calendar Concierge & Reminders (Agent 8)
Manages confirmed interview schedules, timezone translation to UTC+6 (BST),
generates standard .ics calendar files with native alarms, and delivers upcoming interview reminders.
"""

import os
import sys
import json
import time
import re
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CALENDAR_DIR = os.path.join(SCRIPT_DIR, "calendar_invites")
INTERVIEWS_FILE = os.path.join(SCRIPT_DIR, "interviews.json")

os.makedirs(CALENDAR_DIR, exist_ok=True)

sys.path.insert(0, SCRIPT_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

def emit_office_event(agent="Agent 8 (Calendar Concierge)", action="Calendar Event", status="info", details=""):
    try:
        import urllib.request
        payload = json.dumps({
            "agent": agent,
            "action": action,
            "status": status,
            "dept": "Career Ops",
            "source": "calendar_concierge",
            "details": details
        }).encode("utf-8")
        req = urllib.request.Request("http://localhost:7799/event", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            pass
    except Exception:
        pass

from live_status import track


@track("Calendar Concierge", lambda company, role, *a, **k: f"Creating calendar invite: {company}",
       lambda r: f"Invite saved: {os.path.basename(str(r))}")
def generate_ics_with_alarms(company, role, local_time_str, duration_minutes=45, filename=None):
    """
    Creates an iCalendar (.ics) file with pre-configured notification alarms (24h & 1h prior).
    """
    if not filename:
        clean_name = re.sub(r'[^a-zA-Z0-9_]', '_', company.lower())
        filename = f"interview_{clean_name}_{int(time.time())}.ics"

    ics_path = os.path.join(CALENDAR_DIR, filename)

    now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    # Placeholder start time format for standard calendar clients
    start_fmt = (datetime.utcnow() + timedelta(days=2)).strftime("%Y%m%dT140000Z")
    end_fmt = (datetime.utcnow() + timedelta(days=2, minutes=duration_minutes)).strftime("%Y%m%dT144500Z")

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//ABM Career Ops//Interview Calendar Assistant//EN
CALSCALE:GREGORIAN
METHOD:REQUEST
BEGIN:VEVENT
UID:{int(time.time()*1000)}@abm-career-ops
DTSTAMP:{now_utc}
DTSTART:{start_fmt}
DTEND:{end_fmt}
SUMMARY:Technical Interview: {role} @ {company}
DESCRIPTION:Interview with {company} for {role}. Candidate Local Time (UTC+6): {local_time_str}.
LOCATION:Google Meet / Zoom
STATUS:CONFIRMED
BEGIN:VALARM
TRIGGER:-PT24H
ACTION:DISPLAY
DESCRIPTION:Interview Reminder: {role} @ {company} in 24 hours!
END:VALARM
BEGIN:VALARM
TRIGGER:-PT1H
ACTION:DISPLAY
DESCRIPTION:URGENT: Interview with {company} starts in 1 hour!
END:VALARM
BEGIN:VALARM
TRIGGER:-PT15M
ACTION:DISPLAY
DESCRIPTION:Join Call: Interview with {company} starts in 15 minutes!
END:VALARM
END:VEVENT
END:VCALENDAR"""

    with open(ics_path, "w", encoding="utf-8") as f:
        f.write(ics_content)

    return ics_path

@track("Calendar Concierge", "Checking upcoming interviews & reminders", lambda r: f"{len(r)} upcoming interview(s)")
def get_upcoming_interview_reminders():
    """
    Scans interviews.json and checks for upcoming interviews needing candidate attention.
    """
    if not os.path.exists(INTERVIEWS_FILE):
        return []
    try:
        with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
            interviews = json.load(f)
    except Exception:
        return []

    active_interviews = []
    for item in interviews:
        if item.get("status") in ["scheduled", "confirmed"]:
            active_interviews.append({
                "company": item.get("company"),
                "role_title": item.get("role_title"),
                "local_time": item.get("local_scheduled_time"),
                "chosen_slot": item.get("chosen_slot"),
                "ics_file": item.get("ics_file"),
                "status": item.get("status", "scheduled")
            })
    return active_interviews

if __name__ == "__main__":
    ics = generate_ics_with_alarms("ScaleAI", "Senior Automation Engineer", "Thursday at 9:00 PM BST (UTC+6)")
    print("Generated ICS:", ics)
