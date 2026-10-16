#!/usr/bin/env python3
"""
Rebuild every ready-to-apply package (resume HTML + PDF + pitch) from the current profile.json.
Run after the CV/profile changes. Nothing is sent; only the queue entries are refreshed.
"""
import os, sys, json, time

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CAREER_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent_proposal_scribe import load_applications, save_applications, load_jobs, craft_custom_pitch
from agent_ats_resume import generate_tailored_resume_for_job
from agent_career_ops_bridge import generate_playwright_ats_pdf

# Senior engineering stacks the real CV has no evidence for: kept on record, moved out of the queue.
NOT_A_FIT = ("senior react", "senior back-end", "senior .net", "senior shopify", "senior ai engineer")


def main():
    jobs = {j.get("id"): j for j in load_jobs()}
    apps = load_applications()
    rebuilt = skipped = 0
    for app in apps:
        if app.get("status") != "ready_to_apply":
            continue
        title = (app.get("title") or "").lower()
        if not app.get("verdict") and any(k in title for k in NOT_A_FIT):
            app["status"] = "skipped"
            app["feedback"] = "Legacy lead queued before the strict audit; not a fit for the real CV."
            skipped += 1
            continue
        job = dict(jobs.get(app.get("job_id")) or {})
        job.setdefault("id", app.get("job_id"))
        for k in ("title", "company", "url", "salary", "match_score", "matched_skills"):
            job.setdefault(k, app.get(k))
        html_path, tailored, _ = generate_tailored_resume_for_job(job)
        pdf_name = f"{job['id']}_resume.pdf"
        res = generate_playwright_ats_pdf(html_path, output_filename=pdf_name)
        app.update({
            "custom_pitch": craft_custom_pitch(job, app.get("matched_skills") or []),
            "resume_path": html_path,
            "resume_file": os.path.basename(html_path),
            "pdf_file": pdf_name if res.get("ok") else "",
            "track": tailored.get("track"),
            "rebuilt_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        rebuilt += 1
        print(f"rebuilt  {app.get('company')} | {app.get('title')} | track={tailored.get('track')} | pdf={'ok' if res.get('ok') else 'FAILED'}")
    save_applications(apps)
    print(f"done: {rebuilt} rebuilt, {skipped} moved to skipped")


if __name__ == "__main__":
    main()
