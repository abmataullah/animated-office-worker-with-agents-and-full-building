"""
Agent Inbox Reply Watcher (Agent 6)
Monitors email inbox for employer replies, parses incoming messages,
classifies sentiment (Interview Invitation, Assessment, Question, Rejection),
and routes actionable invitations to the Interview Liaison and Calendar Concierge.
"""

import os
import sys
import json
import time
import re
import urllib.request
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INBOX_LOG = os.path.join(SCRIPT_DIR, "inbox_messages.jsonl")
CONFIG_FILE = os.path.join(SCRIPT_DIR, "mail_config.json")

sys.path.insert(0, SCRIPT_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

def emit_office_event(agent="Agent 6 (Inbox Watcher)", action="Checking Inbox", status="info", details=""):
    try:
        payload = json.dumps({
            "agent": agent,
            "action": action,
            "status": status,
            "dept": "Career Ops",
            "source": "inbox_watcher",
            "details": details
        }).encode("utf-8")
        req = urllib.request.Request("http://localhost:7799/event", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            pass
    except Exception:
        pass

def classify_employer_email(subject, body):
    """
    Analyzes email text and classifies the type of employer reply.
    """
    text = (subject + " " + body).lower()

    if any(k in text for k in ["interview", "intro call", "chat with the team", "screening call", "phone screen", "zoom", "google meet", "calendly", "availability for a call", "free to chat"]):
        category = "interview_invitation"
        urgency = "high"
    elif any(k in text for k in ["take-home", "coding challenge", "assessment", "hackerrank", "technical task"]):
        category = "technical_assessment"
        urgency = "medium"
    elif any(k in text for k in ["salary expectation", "work authorization", "portfolio link", "when can you start", "more questions"]):
        category = "follow_up_inquiry"
        urgency = "medium"
    elif any(k in text for k in ["unfortunately", "other candidates", "not moving forward", "decided to pursue", "high volume of applicants"]):
        category = "rejection"
        urgency = "low"
    else:
        category = "general_response"
        urgency = "low"

    return category, urgency

from live_status import track


@track("Inbox Watcher", lambda sender, subject, body, company=None: f"Reading reply: {subject}"[:120],
       lambda r: f"Classified as {r.get('category', 'reply').replace('_', ' ')}")
def process_incoming_email(sender, subject, body, company=None):
    """
    Ingests and processes an incoming employer reply.
    """
    category, urgency = classify_employer_email(subject, body)
    
    # Extract company name if not explicitly provided
    if not company:
        # Heuristic: domain name or subject line
        comp_match = re.search(r"@([a-zA-Z0-9\-]+)\.", sender)
        company = comp_match.group(1).capitalize() if comp_match else "Company"

    msg_record = {
        "id": int(time.time() * 1000),
        "received_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sender": sender,
        "company": company,
        "subject": subject,
        "body": body,
        "category": category,
        "urgency": urgency,
        "status": "pending_reply" if category in ["interview_invitation", "follow_up_inquiry"] else "processed"
    }

    # Save to inbox log
    with open(INBOX_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg_record) + "\n")

    emit_office_event(
        action=f"Reply from {company}",
        status="success" if category == "interview_invitation" else "info",
        details=f"Type: {category.upper()} | From: {sender}"
    )

    log_agent_work(
        agent_name="Inbox Watcher",
        task=f"Classified reply from {company}: {category}",
        model="Classifier Engine",
        prompt=f"Subject: {subject}",
        reasoning=f"Identified {category} with {urgency} urgency from {sender}.",
        output=f"Category: {category} | Status: {msg_record['status']}",
        status="success"
    )

    action_result = {"processed": True, "category": category, "record": msg_record}

    # If it is an interview invitation, automatically coordinate with Interview Liaison & Calendar
    if category == "interview_invitation":
        try:
            from agent_interview_liaison import process_interview_offer
            rec, _ = process_interview_offer(company, sender, body, "Automation Engineer")
            action_result["interview_scheduled"] = rec
            action_result["status"] = "interview_routed"
        except Exception as e:
            action_result["interview_error"] = str(e)

    # Overseer hook: Update Google Sheets tracker
    try:
        from agent_sheets_overseer import record_pipeline_stage
        record_pipeline_stage(
            company=company,
            stage=f"Reply Received ({category.replace('_', ' ').title()})",
            notes=f"Subject: {subject[:40]} | Recipient: {sender}",
            reply_category=category
        )
    except Exception:
        pass

    return action_result

@track("Inbox Watcher", "Checking inbox for employer replies", lambda r: f"{len(r)} employer replies on file")
def get_recent_inbox_messages(limit=30):
    if not os.path.exists(INBOX_LOG):
        return []
    msgs = []
    with open(INBOX_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    msgs.append(json.loads(line))
                except Exception:
                    pass
    return msgs[-limit:]

if __name__ == "__main__":
    print("Testing Inbox Watcher...")
    res = process_incoming_email(
        sender="sarah.recruiter@scaleai.com",
        subject="Interview with ScaleAI - Next Steps",
        body="Hi Ataullah,\n\nWe were really impressed with your automation and video agent portfolio! Are you free Thursday at 10:00 AM EST for a 30-minute intro call?\n\nBest,\nSarah",
        company="ScaleAI"
    )
    print("Processed:", json.dumps(res, indent=2))
