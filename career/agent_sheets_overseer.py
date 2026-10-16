"""
Agent Supreme Overseer & Google Sheets Synchronizer (Agent 10)
Watches over every single step of the career pipeline and records telemetry into:
1. Google Sheets (via Google Sheets API or Google Apps Script Webhook).
2. Local Real-Time CSV Mirror: career/pipeline_tracker.csv (instant GDrive import/export).
3. JSON State Register: career/sheets_data.json.
"""

import os
import sys
import json
import time
import csv
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "sheets_config.json")
SHEETS_DATA_FILE = os.path.join(SCRIPT_DIR, "sheets_data.json")
CSV_FILE = os.path.join(SCRIPT_DIR, "pipeline_tracker.csv")

CSV_HEADERS = [
    "Job ID",
    "Company",
    "Role Title",
    "Match %",
    "Remote Verified",
    "Authenticity Check",
    "Current Stage",
    "Application Date",
    "Mail Status",
    "Recruiter Reply",
    "Interview Time (BST)",
    "Outcome",
    "Notes",
    "Last Updated"
]

def load_sheets_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"enabled": False, "spreadsheet_id": "", "webhook_sync_url": ""}

def load_all_records():
    if os.path.exists(SHEETS_DATA_FILE):
        try:
            with open(SHEETS_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_all_records(data):
    with open(SHEETS_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    # Also write out clean CSV mirror
    try:
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            for row in data.values():
                filtered = {k: row.get(k, "") for k in CSV_HEADERS}
                writer.writerow(filtered)
    except Exception as e:
        print(f"[SheetsOverseer] CSV export error: {e}")

from live_status import track


@track("Sheets Overseer", lambda company, stage, *a, **k: f"Tracker: {company} → {stage}"[:120],
       lambda r: "Tracker row updated")
def record_pipeline_stage(company, stage, notes="", role_title="Engineer", job_id=None, match_score=None, reply_category=None, outcome=None, is_remote=True, is_authentic=True):
    """
    Overseer method to log or update any step across the career lifecycle.
    """
    records = load_all_records()
    comp_key = str(company).strip()

    if comp_key not in records:
        records[comp_key] = {
            "Job ID": job_id or f"lead_{int(time.time()*1000)%100000}",
            "Company": company,
            "Role Title": role_title,
            "Match %": f"{match_score}%" if match_score else "85%",
            "Remote Verified": "100% Remote" if is_remote else "Check Location",
            "Authenticity Check": "Verified Live & Authentic" if is_authentic else "Pending Review",
            "Current Stage": stage,
            "Application Date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "Mail Status": "Prepared",
            "Recruiter Reply": reply_category or "Awaiting Response",
            "Interview Time (BST)": "Not Scheduled",
            "Outcome": outcome or "Active",
            "Notes": notes,
            "Last Updated": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        # Update existing record
        row = records[comp_key]
        row["Current Stage"] = stage
        row["Last Updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if notes:
            row["Notes"] = f"{row.get('Notes', '')} | {notes}".strip(" |")
        if reply_category:
            row["Recruiter Reply"] = reply_category.replace("_", " ").title()
        if outcome:
            row["Outcome"] = outcome.replace("_", " ").title()
        if stage.startswith("Interview"):
            row["Interview Time (BST)"] = notes

    save_all_records(records)

    # Attempt Live Google Sheets sync if enabled
    sync_to_google_sheets(records[comp_key])

    return records[comp_key]

def _post_rows(sheet, key, rows):
    """POST rows to the Apps Script web app (google_sheets_webhook.gs). Runs in a background thread
    so a slow or offline network never blocks the pipeline."""
    cfg = load_sheets_config()
    webhook = cfg.get("webhook_sync_url")
    if not (cfg.get("enabled") and webhook and rows):
        return False
    payload = json.dumps({"token": cfg.get("webhook_token", ""), "sheet": sheet, "key": key, "rows": rows},
                         ensure_ascii=False).encode("utf-8")

    def _send():
        try:
            req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                resp.read()
        except Exception as e:
            print(f"[SheetsOverseer] Google Sheets sync failed: {e}")
    import threading
    threading.Thread(target=_send, daemon=True).start()
    return True


def sync_to_google_sheets(row_dict):
    """Upsert one Pipeline Tracker row (keyed by Job ID) into the Google Sheet."""
    cfg = load_sheets_config()
    return _post_rows(cfg.get("sheet_name", "Pipeline Tracker"), "Job ID",
                      [{k: row_dict.get(k, "") for k in CSV_HEADERS}])


QUEUE_STATUS = {"ready_to_apply": "Ready to apply", "applied": "Applied", "skipped": "Skipped"}


def apply_queue_row(a):
    return {
        "Status": QUEUE_STATUS.get(a.get("status"), a.get("status", "")),
        "Company": a.get("company", ""), "Role": a.get("title", ""), "Track": a.get("track") or "",
        "Fit (of 5)": a.get("fit_score") or "", "Verdict": a.get("verdict") or "not audited",
        "Apply link": a.get("url", ""), "Destination": a.get("destination_type", ""),
        "Queued": a.get("queued_at") or a.get("created_at") or "", "Applied at": a.get("applied_at") or "",
        "Resume PDF": a.get("pdf_file") or "", "Notes": a.get("feedback") or a.get("notes") or "",
    }


def sync_apply_queue(apps):
    """Upsert the whole Apply Queue (keyed by Apply link) in one request."""
    cfg = load_sheets_config()
    return _post_rows(cfg.get("queue_sheet_name", "Apply Queue"), "Apply link",
                      [apply_queue_row(a) for a in apps if a.get("url")])

@track("Sheets Overseer", "Syncing pipeline tracker", lambda r: f"{r.get('total_tracked', 0)} leads tracked")
def get_sheets_overview():
    """
    Returns pipeline summary stats for the dashboard.
    """
    records = load_all_records()
    total = len(records)
    applied = sum(1 for r in records.values() if r.get("Current Stage", "").startswith("Applied") or r.get("Mail Status") == "Delivered")
    interviews = sum(1 for r in records.values() if "Interview" in r.get("Current Stage", ""))
    offers = sum(1 for r in records.values() if "Offer" in r.get("Outcome", ""))

    return {
        "total_tracked": total,
        "applied": applied,
        "interviews": interviews,
        "offers": offers,
        "records": list(records.values())[:50],
        "csv_path": CSV_FILE,
        "sheet_url": load_sheets_config().get("spreadsheet_url", ""),
        "live_sync": bool(load_sheets_config().get("enabled") and load_sheets_config().get("webhook_sync_url")),
    }

if __name__ == "__main__":
    print("Testing Sheets Overseer...")
    r = record_pipeline_stage("ScaleAI", "Application Sent (Via Mail)", "Space Grotesk ATS PDF resume attached", role_title="Senior Python Automation Engineer", match_score=92)
    print("Logged Row:", r)
    print("Summary:", get_sheets_overview())
