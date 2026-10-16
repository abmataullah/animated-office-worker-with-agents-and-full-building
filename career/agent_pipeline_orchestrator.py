"""
Master Career Pipeline Orchestrator
Coordinates the 10-stage autonomous job hunting workflow and reports every
stage to live_status so the Job Finder floor animates the real run:
[1. CV Sync] -> [2. Job Radar] -> [3. ATS Scout] -> [4. Fit Audit] ->
[5. Resume PDF] -> [6. Mail Dispatch] -> [7. Inbox] -> [8. Calendar] ->
[9. Debrief] -> [10. Sheets Overseer]
"""

import os
import sys
import json
import time
import threading

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_FILE = os.path.join(SCRIPT_DIR, "jobs.json")
SENT_LOG = os.path.join(SCRIPT_DIR, "sent_emails.jsonl")
FALLBACK_RESUME_HTML = os.path.join(SCRIPT_DIR, "resumes", "test_ai_eng_resume.html")

sys.path.insert(0, SCRIPT_DIR)
import live_status
from agent_logger import log_agent_work
from agent_job_radar import run_job_radar
from agent_career_ops_bridge import evaluate_job, scan_ats_boards, generate_playwright_ats_pdf, sync_profile
from agent_ats_resume import generate_tailored_resume_for_job
from agent_proposal_scribe import craft_custom_pitch, queue_application, load_applications, extract_target_destination
from agent_company_dossier import generate_company_dossier
from agent_mail_dispatcher import send_application_email, load_mail_config
from agent_inbox_watcher import get_recent_inbox_messages
from agent_calendar_concierge import get_upcoming_interview_reminders
from agent_interview_debrief import get_pending_interview_checkins
from agent_sheets_overseer import record_pipeline_stage, get_sheets_overview

_cycle_lock = threading.Lock()


def _already_sent():
    """Companies already handled: live emails sent, or a package already in the apply queue (any status)."""
    live = _mail_is_live()
    sent = {str(a.get("company", "")).strip().lower() for a in load_applications() if a.get("company")}
    try:
        with open(SENT_LOG, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if live and r.get("status") != "delivered_live":
                    continue
                sent.add(str(r.get("company", "")).strip().lower())
    except FileNotFoundError:
        pass
    return sent


def _mail_is_live():
    cfg = load_mail_config()
    pwd = cfg.get("smtp", {}).get("password", "")
    return cfg.get("enabled", False) and not cfg.get("test_mode", True) and "your_" not in pwd


def run_full_pipeline_cycle(max_eval_count=5, max_applications_per_cycle=2, trigger_live_ats_sweep=False,
                            trigger="manual", allow_live_mail=True):
    """Run one full cycle. Returns a summary dict; raises RuntimeError if a cycle is already running."""
    if not _cycle_lock.acquire(blocking=False):
        raise RuntimeError("A pipeline cycle is already running")
    if live_status.pipeline_is_running():  # e.g. a CLI run in another process
        _cycle_lock.release()
        raise RuntimeError("A pipeline cycle is already running")

    summary = {
        "timestamp": time.time(),
        "date_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "trigger": trigger,
        "steps_completed": [],
        "applications_dispatched": 0,
        "interviews_scheduled": 0,
        "new_jobs_found": 0,
    }
    steps = summary["steps_completed"]
    live_status.pipeline_begin(trigger)
    try:
        live_status.pipeline_stage(0)
        ok, msg = sync_profile()
        steps.append(f"Step 1 (CV & Profile): {msg}")

        live_status.pipeline_stage(1)
        radar_jobs, scanned, _ = run_job_radar()
        summary["new_jobs_found"] = len(radar_jobs)
        steps.append(f"Step 2 (Job Radar): scanned {scanned} postings, {len(radar_jobs)} remote matches")

        live_status.pipeline_stage(2)
        if trigger_live_ats_sweep:
            res = scan_ats_boards(ats_list="greenhouse,lever,ashby", since_days=7, limit=120)
            steps.append(f"Step 3 (ATS Scout): +{res.get('new_jobs_added', 0)} postings from ATS boards")
        else:
            live_status.start("ATS Scout", "Deep ATS sweep not requested this cycle")
            live_status.finish("ATS Scout", "Skipped (enable ATS sweep to run)")
            steps.append("Step 3 (ATS Scout): skipped")

        live_status.pipeline_stage(3)
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                all_jobs = json.load(f)
        except Exception:
            all_jobs = []
        sent = _already_sent()
        fresh, seen_companies = [], set(sent)
        for j in sorted(all_jobs, key=lambda j: j.get("match_score", 0), reverse=True):
            comp = str(j.get("company", "")).strip().lower()
            if comp and comp not in seen_companies:  # one application per company
                seen_companies.add(comp)
                fresh.append(j)

        qualified = []
        for j in fresh[:max_eval_count]:
            # Full job description (not the 2-line board snippet) so the A-H audit sees the real requirements
            ev = evaluate_job(j.get("url", ""), jd_text=None, title=j.get("title"))
            is_remote = "remote" in str(j.get("location", "")).lower() or j.get("remote", False) or ev.get("is_remote", False)
            is_authentic = ev.get("is_live", True) and not ev.get("possible_repost", False)
            verdict = ev.get("verdict", "Skip")
            passed = is_remote and is_authentic and verdict in ("Apply", "Review")
            record_pipeline_stage(company=j.get("company", "Company"), stage=f"Audited: {verdict}",
                                  notes=f"Fit {ev.get('fit_score')}/5.0 | Remote: {is_remote} | Live: {is_authentic}",
                                  role_title=j.get("title"), match_score=int(ev.get("fit_score", 0) * 20),
                                  is_remote=is_remote, is_authentic=is_authentic)
            if passed:
                qualified.append((j, ev))
        qualified.sort(key=lambda x: x[1].get("fit_score", 0), reverse=True)
        steps.append(f"Step 4 (Fit Audit): {len(qualified)}/{min(len(fresh), max_eval_count)} new roles rated Apply/Review on the full job description")

        live_status.pipeline_stage(4)
        prepared = []
        for job, ev in qualified[:max_applications_per_cycle]:
            try:
                html_path, _, _ = generate_tailored_resume_for_job(job)
            except Exception:
                html_path = FALLBACK_RESUME_HTML
            pdf = generate_playwright_ats_pdf(html_path, output_filename=f"{job.get('id')}_ats_resume.pdf")
            prepared.append((job, ev, html_path, pdf.get("filename") if pdf.get("ok") else ""))
        steps.append(f"Step 5 (Resume Builder): {sum(1 for p in prepared if p[3])}/{len(prepared)} tailored ATS PDFs")

        # Job boards route applications through the company's own page, so packages go to the apply
        # queue. Email is used only when the posting itself lists an address (never a guessed one).
        live_status.pipeline_stage(5)
        mail_live = _mail_is_live() and allow_live_mail
        queued = emailed = 0
        for job, ev, html_path, pdf_file in prepared:
            company = job.get("company", "Target Company")
            role = job.get("title", "Software Engineer")
            generate_company_dossier(company, role)
            pitch = craft_custom_pitch(job, job.get("matched_skills", []))
            entry = queue_application(job, pitch, html_path, pdf_file, ev)
            if entry["destination_type"] == "email" and mail_live:
                pdf_path = os.path.join(SCRIPT_DIR, "resumes", pdf_file) if pdf_file else None
                mail = send_application_email(recipient_email=entry["destination"], role_title=role, company=company,
                                              pitch_text=pitch, resume_pdf_path=pdf_path)
                if mail.get("ok"):
                    entry["status"] = "applied"
                    from agent_proposal_scribe import dispatch_application
                    dispatch_application(job.get("id"), action="apply", notes=f"Emailed {entry['destination']}")
                    emailed += 1
                record_pipeline_stage(company=company, stage="Application Emailed", role_title=role,
                                      notes=f"To {entry['destination']} (address from the posting)")
            else:
                queued += 1
                record_pipeline_stage(company=company, stage="Ready to Apply (queue)", role_title=role,
                                      notes=f"{entry['destination_type']}: {entry['destination'][:80]}",
                                      match_score=int(ev.get("fit_score", 0) * 20))
        summary["applications_dispatched"] = emailed
        summary["applications_queued"] = queued
        steps.append(f"Step 6 (Apply Queue): {queued} package(s) ready for you" + (f", {emailed} emailed" if emailed else ""))

        live_status.pipeline_stage(6)
        inbox = get_recent_inbox_messages(limit=5)
        steps.append(f"Step 7 (Inbox Watcher): {len(inbox)} employer replies on file")

        live_status.pipeline_stage(7)
        reminders = get_upcoming_interview_reminders()
        summary["interviews_scheduled"] = len(reminders)
        steps.append(f"Step 8 (Calendar Concierge): {len(reminders)} upcoming interviews")

        live_status.pipeline_stage(8)
        pending = get_pending_interview_checkins()
        steps.append(f"Step 9 (Interview Debrief): {len(pending)} awaiting outcome check-in")

        live_status.pipeline_stage(9)
        sheets = get_sheets_overview()
        steps.append(f"Step 10 (Sheets Overseer): {sheets.get('total_tracked', 0)} leads tracked")

        log_agent_work(
            agent_name="Pipeline Orchestrator",
            task=f"Executed full 10-stage career pipeline ({trigger})",
            model="Master Orchestration Loop",
            prompt="CV -> Radar -> ATS -> Audit -> Resume -> Mail -> Inbox -> Calendar -> Debrief -> Sheets",
            reasoning="All stages completed sequentially.",
            output=f"New matches: {len(radar_jobs)} | Queued: {queued} | Emailed: {emailed} | Interviews: {len(reminders)}",
            status="success",
        )
        live_status.pipeline_end(steps)
        return summary
    except Exception as e:
        live_status.pipeline_end(steps, error=str(e))
        raise
    finally:
        _cycle_lock.release()


def start_cycle_async(**kwargs):
    """Kick off a cycle in a background thread; returns False if one is already running."""
    if _cycle_lock.locked() or live_status.pipeline_is_running():
        return False

    def runner():
        try:
            run_full_pipeline_cycle(**kwargs)
        except Exception as e:
            print(f"[Pipeline] cycle error: {e}")

    threading.Thread(target=runner, daemon=True, name="career-cycle").start()
    return True


if __name__ == "__main__":
    print("Running one pipeline cycle...")
    print(json.dumps(run_full_pipeline_cycle(max_eval_count=2, max_applications_per_cycle=1), indent=2))
