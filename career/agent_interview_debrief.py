"""
Agent Interview Debrief & Success Tracker (Agent 9)
Proactively checks in with the candidate after interviews to record outcomes:
- Inquires: "How did your interview go? Did you succeed or move to the next stage?"
- Records: Offer Received, Next Round, Rejection, or Awaiting Feedback.
- Triggers congratulations, contract review prep, or pattern gap analysis.
- Synchronizes outcomes to Google Sheets.
"""

import os
import sys
import json
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INTERVIEWS_FILE = os.path.join(SCRIPT_DIR, "interviews.json")
DEBRIEF_LOG = os.path.join(SCRIPT_DIR, "interview_debriefs.jsonl")

sys.path.insert(0, SCRIPT_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

def emit_office_event(agent="Agent 9 (Interview Debrief)", action="Check-in", status="info", details=""):
    try:
        import urllib.request
        payload = json.dumps({
            "agent": agent,
            "action": action,
            "status": status,
            "dept": "Career Ops",
            "source": "interview_debrief",
            "details": details
        }).encode("utf-8")
        req = urllib.request.Request("http://localhost:7799/event", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            pass
    except Exception:
        pass

from live_status import track


@track("Interview Debrief", "Looking for finished interviews to debrief", lambda r: f"{len(r)} interview(s) awaiting debrief")
def get_pending_interview_checkins():
    """
    Returns list of interviews needing candidate check-in.
    """
    if not os.path.exists(INTERVIEWS_FILE):
        return []
    try:
        with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
            interviews = json.load(f)
    except Exception:
        return []

    pending = []
    for item in interviews:
        status = item.get("status", "scheduled")
        if status in ["scheduled", "awaiting_feedback", "in_progress"]:
            pending.append({
                "id": item.get("id"),
                "company": item.get("company"),
                "role_title": item.get("role_title"),
                "local_time": item.get("local_scheduled_time"),
                "status": status,
                "prompt_question": f"How did your interview with {item.get('company')} go? Did you receive an offer or move to the next stage?"
            })
    return pending

@track("Interview Debrief", lambda who, outcome, *a, **k: f"Logging outcome for {who}: {outcome}"[:120],
       lambda r: "Outcome recorded")
def record_interview_outcome(interview_id_or_company, outcome, notes="", offer_amount=None):
    """
    Records the outcome of an interview.
    Possible outcomes:
    - 'offer_received': Official offer extended!
    - 'next_round': Advanced to subsequent round.
    - 'awaiting_decision': Waiting for employer final decision.
    - 'not_selected': Constructive closing.
    """
    company_name = str(interview_id_or_company)

    # Update interviews.json
    interviews = []
    if os.path.exists(INTERVIEWS_FILE):
        try:
            with open(INTERVIEWS_FILE, "r", encoding="utf-8") as f:
                interviews = json.load(f)
        except Exception:
            pass

    updated = False
    for item in interviews:
        if str(item.get("id")) == str(interview_id_or_company) or item.get("company", "").lower() == str(interview_id_or_company).lower():
            item["status"] = outcome
            item["outcome_notes"] = notes
            item["outcome_date"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if offer_amount:
                item["offer_amount"] = offer_amount
            company_name = item.get("company", company_name)
            updated = True
            break

    if updated:
        with open(INTERVIEWS_FILE, "w", encoding="utf-8") as f:
            json.dump(interviews, f, indent=2, ensure_ascii=False)

    debrief_entry = {
        "timestamp": time.time(),
        "date_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "company": company_name,
        "outcome": outcome,
        "notes": notes,
        "offer_amount": offer_amount
    }

    with open(DEBRIEF_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(debrief_entry) + "\n")

    # Office Event & celebration/next step
    if outcome == "offer_received":
        action_msg = f"🎉 OFFER RECEIVED FROM {company_name.upper()}!"
        evt_status = "success"
    elif outcome == "next_round":
        action_msg = f"⚡ Advanced to Next Round: {company_name}"
        evt_status = "success"
    else:
        action_msg = f"Outcome Logged: {company_name} ({outcome})"
        evt_status = "info"

    emit_office_event(
        action=action_msg,
        status=evt_status,
        details=f"Outcome: {outcome.upper()} | Notes: {notes[:60]}"
    )

    log_agent_work(
        agent_name="Interview Debrief",
        task=f"Interview Outcome Recorded for {company_name}: {outcome}",
        model="Debrief & Negotiation Engine",
        prompt=f"Company: {company_name} | Outcome: {outcome}",
        reasoning=f"Candidate logged {outcome}. System updated state and synchronized with Google Sheets.",
        output=f"Status: {outcome} | Offer: {offer_amount or 'N/A'}",
        status="success"
    )

    # Sync to Google Sheets
    try:
        from agent_sheets_overseer import record_pipeline_stage
        record_pipeline_stage(
            company=company_name,
            stage=f"Interview Outcome: {outcome.replace('_', ' ').title()}",
            notes=f"Offer: {offer_amount or 'N/A'} | Notes: {notes}",
            outcome=outcome
        )
    except Exception:
        pass

    return {
        "ok": True,
        "company": company_name,
        "outcome": outcome,
        "message": f"Successfully logged outcome '{outcome}' for {company_name}."
    }

if __name__ == "__main__":
    print("Testing Interview Debrief check-in...")
    res = record_interview_outcome("ScaleAI", "offer_received", notes="Offered $95,000/yr full-time remote!", offer_amount="$95,000")
    print(res)
