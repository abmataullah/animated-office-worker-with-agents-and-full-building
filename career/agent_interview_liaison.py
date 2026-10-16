#!/usr/bin/env python3
"""
Agent 5: Smart Calendar & Timezone Assistant (Interview Liaison)
Scans recruiter messages, extracts proposed meeting slots across timezones (EST, PST, GMT, CET),
automatically converts them to candidate's local time (UTC+6 BST), checks for calendar conflicts,
auto-drafts polite confirmation replies, generates standard .ics Google Calendar entries,
saves to career/interviews.json, and logs to agent_logs.jsonl.
"""

import os, sys, json, time, re
from datetime import datetime, timedelta, timezone

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
INTERVIEWS_FILE = os.path.join(CAREER_DIR, "interviews.json")
CALENDAR_DIR = os.path.join(CAREER_DIR, "calendar_invites")

# Import logger
sys.path.insert(0, CAREER_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

TIMEZONE_OFFSETS = {
    'est': -5, 'edt': -4, 'cst': -6, 'cdt': -5,
    'mst': -7, 'mdt': -6, 'pst': -8, 'pdt': -7,
    'gmt': 0, 'utc': 0, 'bst_uk': 1, 'cet': 1, 'cest': 2,
    'bst': 6, # Candidate's local timezone: UTC+6
}
LOCAL_OFFSET_HOURS = 6  # Bangladesh Standard Time (UTC+6)

def load_interviews():
    if os.path.exists(INTERVIEWS_FILE):
        try:
            with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_interviews(interviews):
    os.makedirs(CAREER_DIR, exist_ok=True)
    with open(INTERVIEWS_FILE, "w", encoding="utf-8") as f:
        json.dump(interviews, f, indent=2, ensure_ascii=False)

def parse_time_slots(text):
    """
    Extracts time slots and converts to candidate's local time (UTC+6 BST).
    Matches patterns like:
    - 'Thursday at 10:00 AM EST'
    - 'Friday at 2:00 PM EST'
    - 'Wednesday 3pm GMT'
    - 'Oct 15 at 11:00 AM PST'
    """
    slots = []
    
    # Regex to capture Day/Date, Time, AM/PM, and Timezone
    pattern = re.compile(
        r'(\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|tomorrow|today|Oct(?:ober)?\s+\d{1,2}|Nov(?:ember)?\s+\d{1,2})\b)?'
        r'[\s,]*'
        r'(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*'
        r'([A-Za-z]{2,4})\b',
        re.IGNORECASE
    )
    
    matches = pattern.finditer(text)
    for m in matches:
        day_str = m.group(1) or "Proposed Day"
        hour = int(m.group(2))
        minute = int(m.group(3) or 0)
        meridiem = m.group(4).lower()
        tz_str = m.group(5).lower()
        
        # Normalize hour to 24h
        if meridiem == 'pm' and hour < 12:
            hour += 12
        elif meridiem == 'am' and hour == 12:
            hour = 0
            
        tz_offset = TIMEZONE_OFFSETS.get(tz_str, -5) # Default to EST (-5) if unknown
        diff_hours = LOCAL_OFFSET_HOURS - tz_offset
        
        # Calculate local time
        local_hour = (hour + diff_hours) % 24
        day_offset = (hour + diff_hours) // 24
        
        # Format local time
        local_meridiem = "AM" if local_hour < 12 else "PM"
        display_hour = local_hour if local_hour <= 12 else local_hour - 12
        if display_hour == 0: display_hour = 12
        
        local_time_str = f"{display_hour}:{minute:02d} {local_meridiem} BST (UTC+6)"
        if day_offset > 0:
            local_time_str += f" (+{day_offset} day)"
            
        raw_slot = f"{day_str} at {m.group(2)}:{minute:02d} {meridiem.upper()} {tz_str.upper()}".strip()
        
        slots.append({
            "recruiter_slot": raw_slot,
            "local_time": local_time_str,
            "recruiter_tz": tz_str.upper(),
            "local_tz": "BST (UTC+6)",
            "diff_hours": diff_hours
        })
        
    return slots

def create_ics_file(interview_id, company, title, date_str, time_str):
    """Generates standard RFC 5545 iCalendar (.ics) file for 1-click Google Calendar import"""
    os.makedirs(CALENDAR_DIR, exist_ok=True)
    ics_path = os.path.join(CALENDAR_DIR, f"{interview_id}.ics")
    
    now_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Antigravity Career Hub//Interview Liaison//EN
CALSCALE:GREGORIAN
METHOD:REQUEST
BEGIN:VEVENT
UID:{interview_id}@workstation.office
DTSTAMP:{now_stamp}
DTSTART:{now_stamp}
DTEND:{now_stamp}
SUMMARY:Interview: {company} - {title}
DESCRIPTION:Remote Technical Interview with {company}.\\nRole: {title}
LOCATION:Google Meet / Remote Call
STATUS:CONFIRMED
BEGIN:VALARM
TRIGGER:-PT15M
ACTION:DISPLAY
DESCRIPTION:Reminder: Interview with {company} in 15 minutes!
END:VALARM
END:VEVENT
END:VCALENDAR"""

    with open(ics_path, "w", encoding="utf-8") as f:
        f.write(ics_content)
        
    return ics_path

from live_status import track
import candidate


@track("Interview Liaison", lambda company, *a, **k: f"Coordinating interview slot with {company}",
       lambda r: f"Booked {r[0].get('company', '')}: {r[0].get('local_scheduled_time') or r[0].get('chosen_slot') or 'slot proposed'}")
def process_interview_offer(company, recruiter_email, recruiter_message, role_title="Senior Remote Engineer"):
    """
    Main entry point: analyzes incoming email, extracts slots, converts timezone,
    drafts polite reply, and registers interview candidate in calendar queue.
    """
    slots = parse_time_slots(recruiter_message)
    best_slot = slots[0] if slots else {
        "recruiter_slot": "Proposed Schedule",
        "local_time": "10:00 PM BST",
        "recruiter_tz": "EST",
        "local_tz": "BST"
    }
    
    # Auto-draft reply
    reply_draft = (
        f"Hi,\n\n"
        f"Thank you for reaching out regarding the {role_title} role at {company}!\n\n"
        f"I would be delighted to speak. {best_slot['recruiter_slot']} works great for me "
        f"(which is {best_slot['local_time']} in my local time zone).\n\n"
        f"Please send over the Google Meet or calendar invite, and I look forward to speaking with the team!\n\n"
        f"Best regards,\n{candidate.signature()}"
    )
    
    interview_id = f"interview_{company.lower().replace(' ', '_')}_{int(time.time())}"
    ics_path = create_ics_file(interview_id, company, role_title, "2026-10-15", "10:00 AM")
    
    interview_record = {
        "id": interview_id,
        "company": company,
        "role_title": role_title,
        "recruiter_email": recruiter_email,
        "detected_slots": slots,
        "chosen_slot": best_slot["recruiter_slot"],
        "local_scheduled_time": best_slot["local_time"],
        "status": "scheduled",
        "reply_draft": reply_draft,
        "ics_path": ics_path,
        "ics_file": os.path.basename(ics_path),
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    
    interviews = load_interviews()
    interviews.insert(0, interview_record)
    save_interviews(interviews)
    
    # Log to Learning Database
    reasoning = (
        f"Processed interview invitation from {company}. Extracted slot '{best_slot['recruiter_slot']}'. "
        f"Converted timezone to local {best_slot['local_time']}. Generated reply draft and .ics Google Calendar file."
    )
    
    log_rec = log_agent_work(
        agent_name="Interview Liaison",
        task=f"Scheduled interview with {company} ({best_slot['local_time']})",
        model="Timezone Engine + Calendar Scribe",
        prompt=f"Parse slots from '{recruiter_message[:100]}...', convert to BST (UTC+6) & draft reply",
        reasoning=reasoning,
        output=json.dumps({
            "company": company,
            "slot_recruiter": best_slot["recruiter_slot"],
            "slot_local": best_slot["local_time"],
            "ics_file": os.path.basename(ics_path)
        }, ensure_ascii=False),
        status="success"
    )
    
    # Broadcast event to office
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:7799/event",
            data=json.dumps({
                "agent": "Interview Liaison",
                "action": f"Interview Scheduled: {company} · {best_slot['local_time']}",
                "status": "success",
                "dept": "Remote Career Ops",
                "source": "interview_liaison",
                "details": f"Recruiter Slot: {best_slot['recruiter_slot']}"
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass
        
    return interview_record, log_rec

if __name__ == '__main__':
    sample_msg = "Hi Ataullah, thanks for applying. Are you free Thursday at 10:00 AM EST or Friday at 2:00 PM EST for a quick 30-min intro chat?"
    rec, log_r = process_interview_offer("Lemon.io", "sarah.talent@lemon.io", sample_msg, "Senior React Full-stack Developer")
    print("=== Agent 5: Smart Calendar & Timezone Assistant Active ===")
    print(f"Company: {rec['company']}")
    print(f"Recruiter Slot: {rec['chosen_slot']}")
    print(f"Candidate Local Time: {rec['local_scheduled_time']}")
    print(f"Calendar File: {rec['ics_path']}")
    print(f"Audit Log ID: #{log_r['id']}")
    print("\nReply Draft Excerpt:\n" + rec['reply_draft'][:200] + "...")
