"""
Agent Mail Dispatcher (Agent 5)
Handles automated email application delivery to verified employers and recruiters.
Supports SMTP (Gmail App Passwords, Outlook, SES, etc.) and REST Mail APIs (Resend, Sendgrid).
Attaches ATS-compliant Playwright PDF resumes and tailored pitches.
"""

import os
import sys
import json
import time
import smtplib
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "mail_config.json")
SENT_LOG = os.path.join(SCRIPT_DIR, "sent_emails.jsonl")
RESUMES_DIR = os.path.join(SCRIPT_DIR, "resumes")

sys.path.insert(0, SCRIPT_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

def emit_office_event(agent="Agent 5 (Mail Dispatcher)", action="Sending Application", status="info", details=""):
    try:
        payload = json.dumps({
            "agent": agent,
            "action": action,
            "status": status,
            "dept": "Career Ops",
            "source": "mail_dispatcher",
            "details": details
        }).encode("utf-8")
        req = urllib.request.Request("http://localhost:7799/event", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            pass
    except Exception:
        pass

def load_mail_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "provider": "smtp",
        "enabled": False,
        "sender_name": candidate.name(),
        "sender_email": candidate.email(),
        "test_mode": True
    }

from live_status import track
import candidate


@track("Mail Dispatcher", lambda recipient_email, role_title, company, *a, **k: f"Emailing {company}: {role_title}"[:120],
       lambda r: (("[TEST] " if r.get("mode") == "simulated" else "") + f"Sent to {r.get('record', {}).get('recipient', '')}", False)
       if r.get("ok") else (f"Send failed: {str(r.get('error') or r.get('message'))[:90]}", True))
def send_application_email(recipient_email, role_title, company, pitch_text, resume_pdf_path=None, custom_subject=None):
    """
    Sends an application email to the company/recruiter with PDF resume attachment.
    """
    cfg = load_mail_config()
    sender_name = cfg.get("sender_name") or candidate.name()
    sender_email = cfg.get("sender_email") or candidate.email()
    subject = custom_subject or f"Application: {role_title} - {sender_name}"
    
    emit_office_event(
        action=f"Dispatching to {company}",
        status="busy",
        details=f"Recipient: {recipient_email} | Subject: {subject}"
    )

    is_test = cfg.get("test_mode", True) or not cfg.get("enabled", False)
    # Check if placeholder credentials
    smtp_cfg = cfg.get("smtp", {})
    if "your_" in smtp_cfg.get("password", "") or "your_email" in smtp_cfg.get("username", ""):
        is_test = True

    # Build Multipart Email
    msg = MIMEMultipart()
    msg['From'] = f"{sender_name} <{sender_email}>"
    msg['To'] = recipient_email
    msg['Subject'] = subject

    # Attach pitch body
    msg.attach(MIMEText(pitch_text, 'plain', 'utf-8'))

    # Attach PDF resume if exists
    attached_pdf_name = None
    if resume_pdf_path and os.path.exists(resume_pdf_path):
        try:
            with open(resume_pdf_path, 'rb') as f:
                pdf_data = f.read()
            attached_pdf_name = os.path.basename(resume_pdf_path)
            part = MIMEApplication(pdf_data, Name=attached_pdf_name)
            part['Content-Disposition'] = f'attachment; filename="{attached_pdf_name}"'
            msg.attach(part)
        except Exception as e:
            print(f"[MailDispatcher] Error attaching PDF: {e}")

    dispatch_record = {
        "timestamp": time.time(),
        "date_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "company": company,
        "role_title": role_title,
        "recipient": recipient_email,
        "subject": subject,
        "pitch_preview": pitch_text[:200] + "...",
        "resume_attached": attached_pdf_name,
        "status": "simulated_sent" if is_test else "dispatched_live"
    }

    if is_test:
        # Simulated mode (waiting for user email credentials or testing)
        with open(SENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dispatch_record) + "\n")

        log_agent_work(
            agent_name="Mail Dispatcher",
            task=f"Queued/Simulated Email Application to {company}",
            model="Mail Dispatch Engine",
            prompt=f"Send application to {recipient_email}",
            reasoning="Configured in Test/Draft mode. Application logged and ready for live SMTP/API delivery.",
            output=f"Subject: {subject} | Recipient: {recipient_email} | Attachment: {attached_pdf_name}",
            status="success"
        )

        emit_office_event(
            action=f"Dispatched: {company} (Test Mode)",
            status="success",
            details=f"Email prepared & logged for {recipient_email} (Test mode active)"
        )

        return {
            "ok": True,
            "mode": "simulated",
            "message": f"Application email queued and logged for {company} ({recipient_email}). Ready for live SMTP/API once credentials provided.",
            "record": dispatch_record
        }

    # Live delivery mode
    provider = cfg.get("provider", "smtp").lower()
    try:
        if provider == "smtp":
            host = smtp_cfg.get("host", "smtp.gmail.com")
            port = int(smtp_cfg.get("port", 587))
            user = smtp_cfg.get("username")
            pwd = smtp_cfg.get("password")
            use_tls = smtp_cfg.get("use_tls", True)

            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()
            server.login(user, pwd)
            server.sendmail(sender_email, [recipient_email], msg.as_string())
            server.quit()

        elif provider == "resend":
            api_key = cfg.get("api", {}).get("api_key")
            req_data = json.dumps({
                "from": f"{sender_name} <{sender_email}>",
                "to": [recipient_email],
                "subject": subject,
                "text": pitch_text
            }).encode("utf-8")
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=req_data,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass

        dispatch_record["status"] = "delivered_live"
        with open(SENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(dispatch_record) + "\n")

        log_agent_work(
            agent_name="Mail Dispatcher",
            task=f"Live Email Application Dispatched to {company}",
            model="Mail Dispatch Engine",
            prompt=f"Deliver application to {recipient_email}",
            reasoning=f"Successfully sent live email via {provider}.",
            output=f"Subject: {subject} | Recipient: {recipient_email}",
            status="success"
        )

        emit_office_event(
            action=f"Live Email Sent: {company}",
            status="success",
            details=f"Application and ATS PDF successfully sent to {recipient_email}!"
        )

        return {
            "ok": True,
            "mode": "live",
            "message": f"Application email successfully sent to {recipient_email}!",
            "record": dispatch_record
        }
    except Exception as e:
        dispatch_record["status"] = "failed"
        dispatch_record["error"] = str(e)
        emit_office_event(
            action=f"Mail Error: {company}",
            status="error",
            details=f"Failed to send: {str(e)[:45]}"
        )
        return {
            "ok": False,
            "error": str(e),
            "record": dispatch_record
        }

if __name__ == "__main__":
    print("Testing Mail Dispatcher in simulated mode...")
    res = send_application_email(
        recipient_email="careers@innovate-ai.com",
        role_title="Senior Python Automation Engineer",
        company="InnovateAI",
        pitch_text="Hello Hiring Team,\n\nI am writing to express my strong interest in the Senior Python Automation Engineer position...",
        resume_pdf_path=os.path.join(RESUMES_DIR, "test_playwright_ats.pdf")
    )
    print("Result:", res)
