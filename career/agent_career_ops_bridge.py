"""
Agent Career-Ops Bridge
Integrates career-ops-hq/career-ops (Node.js engine) with the Python Career Hub and Office Widget.

Capabilities:
1. Evaluate Job URL: Runs fetch-jd/browser-extract + A-H evaluation + ghost/repost check.
2. Ingest ATS Board Scanner: Runs scan-ats-full.mjs and imports fresh high-signal postings to jobs.json.
3. Playwright ATS PDF Generation: Compiles tailored HTML resumes into ATS-compliant PDFs using Chromium.
4. Profile Synchronization: Keeps career/profile.json synced with career-ops/config/profile.yml and cv.md.
"""

import os
import sys
import json
import time
import shutil
import subprocess
import urllib.request
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORK_OFFICE_DIR = os.path.dirname(SCRIPT_DIR)
CAREER_OPS_DIR = os.path.join(SCRIPT_DIR, "career-ops")
JOBS_FILE = os.path.join(SCRIPT_DIR, "jobs.json")
PROFILE_FILE = os.path.join(SCRIPT_DIR, "profile.json")
RESUMES_DIR = os.path.join(SCRIPT_DIR, "resumes")
OUTPUT_DIR = os.path.join(CAREER_OPS_DIR, "output")

os.makedirs(RESUMES_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

def emit_office_event(agent="Career-Ops Bridge", action="Activity", status="info", dept="Career Ops", details=""):
    """Emits an event to the local office widget telemetry."""
    try:
        payload = json.dumps({
            "agent": agent,
            "action": action,
            "status": status,
            "dept": dept,
            "source": "career_ops_bridge",
            "details": details
        }).encode("utf-8")
        req = urllib.request.Request("http://127.0.0.1:7799/event", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            pass
    except Exception:
        pass


def run_node_cmd(args, cwd=CAREER_OPS_DIR, timeout=35):
    """Executes a Node.js script in career-ops directory."""
    try:
        proc = subprocess.run(
            ["node"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "Timeout expired running node script"
    except Exception as e:
        return -1, "", str(e)


from live_status import track
import candidate


@track("CV Analyst", "Syncing CV profile into career-ops", lambda r: (r[1], not r[0]))
def sync_profile():
    """Syncs career/profile.json into career-ops config/profile.yml if profile.json exists."""
    if not os.path.exists(PROFILE_FILE):
        return False, "profile.json not found"

    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            prof = json.load(f)

        name = prof.get("name", "Software & Automation Engineer").lstrip("#").strip()
        title = prof.get("title", "Full-Stack Automation & Video Workflow Engineer")
        target_roles = prof.get("target_roles", ["Automation Engineer", "Full-Stack Developer"])
        skills = prof.get("technical_skills", ["Python", "TypeScript", "Node.js"])

        yml_path = os.path.join(CAREER_OPS_DIR, "config", "profile.yml")
        os.makedirs(os.path.dirname(yml_path), exist_ok=True)

        yml_lines = [
            "# Auto-synced from career/profile.json",
            "candidate:",
            f'  full_name: "{name}"',
            f'  title: "{title}"',
            f'  email: "{prof.get("email", "")}"',
            f'  phone: "{prof.get("phone", "")}"',
            f'  location: "{prof.get("location", "Remote")}"',
            f'  portfolio_url: "{candidate.portfolio_url(prof)}"',
            f'  remote_preference: "{prof.get("remote_preference", "100% Remote Only")}"',
            f'  min_annual_salary: "{prof.get("min_annual_salary", "")}"',
            "",
            "target_roles:",
            "  primary:"
        ]
        for tr in target_roles:
            yml_lines.append(f'    - "{tr}"')

        yml_lines.extend([
            "",
            "skills:",
            "  technical:"
        ])
        for sk in skills:
            yml_lines.append(f'    - "{sk}"')

        with open(yml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(yml_lines) + "\n")

        return True, "Profile synced to career-ops/config/profile.yml"
    except Exception as e:
        return False, str(e)


def extract_job_details(url):
    """
    Fetches JD from public ATS API (Greenhouse, Lever, Ashby, Workday, etc.)
    or headlessly using browser-extract.mjs.
    """
    # 1. Try fast ATS API fetch
    rc, out, _ = run_node_cmd(["fetch-jd.mjs", url], timeout=15)
    if rc == 0 and out:
        lines = out.split("\n", 1)
        title = lines[0].strip() if len(lines) > 0 else "Position"
        text = lines[1].strip() if len(lines) > 1 else out
        return {"url": url, "title": title, "text": text, "source": "ats_api"}

    # 2. Try browser extraction
    rc, out, _ = run_node_cmd(["browser-extract.mjs", url, "--mode", "jd", "--timeout", "12000"], timeout=20)
    if rc == 0 and out:
        try:
            data = json.loads(out)
            return {
                "url": url,
                "title": data.get("title", "Position"),
                "text": data.get("text", ""),
                "source": "browser_extract"
            }
        except Exception:
            pass

    # 3. Fallback: simple http fetch
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Strip tags for basic text
            clean_text = re.sub(r"<[^>]+>", " ", html)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            # Try to grab title
            title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
            title = title_match.group(1).strip() if title_match else "Target Role"
            return {"url": url, "title": title, "text": clean_text[:8000], "source": "http_fallback"}
    except Exception as e:
        return {"url": url, "title": "External Role", "text": f"Could not extract body: {e}", "source": "error"}


@track("Fit Auditor", lambda url, jd_text=None, title=None: f"Auditing remote fit: {(title or url)[:70]}",
       lambda r: f"{r.get('score_band')} · {r.get('verdict')}")
def evaluate_job(url, jd_text=None, title=None):
    """
    Performs full A-H Evaluation on the job listing:
    - Liveness check
    - Fit score (1.0 to 5.0)
    - Keyword match & skill breakdown
    - Remote/work-auth check
    - Tactical pitch formulation
    """
    emit_office_event("Agent 2 (Radar)", "Evaluating Job URL", "busy", "Career Ops", f"Target: {url}")

    # 1. Fetch details if not provided
    if not jd_text:
        extracted = extract_job_details(url)
        jd_text = extracted.get("text", "")
        if not title:
            title = extracted.get("title", "Position")

    title_clean = title or "Job Listing"

    # 2. Check liveness
    is_live = True
    rc, out, _ = run_node_cmd(["check-liveness.mjs", url, "--no-record"], timeout=10)
    if rc == 0 and ("410" in out or "404" in out or "closed" in out.lower()):
        is_live = False

    # 3. Load candidate profile for match scoring
    prof = {}
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                prof = json.load(f)
        except Exception:
            pass

    target_skills = prof.get("technical_skills", ["Python", "TypeScript", "Node.js", "FFmpeg", "After Effects", "FastAPI", "Ollama", "REST APIs"])
    ats_keywords = prof.get("ats_keywords", target_skills)

    text_lower = (jd_text + " " + title_clean).lower()
    matched_skills = [sk for sk in target_skills if sk.lower() in text_lower]
    matched_keywords = [kw for kw in ats_keywords if kw.lower() in text_lower]

    match_ratio = len(matched_skills) / max(len(target_skills) * 0.45, 1)
    # Fit score between 1.0 and 5.0
    raw_score = 2.0 + (match_ratio * 3.0)
    fit_score = round(min(max(raw_score, 1.5), 5.0), 1)

    # Remote detection
    is_remote = bool(re.search(r"\b(remote|anywhere|distributed|work from home|telecommute)\b", text_lower))

    # Work auth / sponsorship flags
    no_sponsorship = bool(re.search(r"\b(no sponsorship|us citizen|green card only|security clearance)\b", text_lower))

    # Repost / ghost detector heuristics
    repost_flag = bool(re.search(r"\b(reposted|re-posted|30\+ days ago)\b", text_lower))

    # Recommendation
    if not is_live:
        rec = "DO NOT APPLY: Posting confirmed closed / inactive."
        verdict = "Closed"
    elif no_sponsorship and not is_remote:
        rec = "BLOCKED: Work-auth constraint (requires on-site clearance/sponsorship blocker)."
        verdict = "Blocked"
    elif fit_score >= 4.0:
        rec = "STRONG FIT (Tier 1): Tailor resume and dispatch application immediately."
        verdict = "Apply"
    elif fit_score >= 3.0:
        rec = "MODERATE FIT (Tier 2): Secondary opportunity, worth a targeted cover letter."
        verdict = "Review"
    else:
        rec = "LOW FIT: Core requirements diverge from primary automation & development focus."
        verdict = "Skip"

    # Tactical pitch angle
    tactical_pitch = (
        f"Emphasize autonomous agent architecture, Python background daemons, "
        f"and programmatic video/workflow orchestration ({', '.join(matched_skills[:4])})."
    )

    evaluation = {
        "ok": True,
        "url": url,
        "title": title_clean,
        "is_live": is_live,
        "fit_score": fit_score,
        "score_band": f"{fit_score}/5.0",
        "verdict": verdict,
        "recommendation": rec,
        "is_remote": is_remote,
        "no_sponsorship_blocker": no_sponsorship,
        "possible_repost": repost_flag,
        "matched_skills": matched_skills,
        "matched_keywords_count": len(matched_keywords),
        "tactical_pitch": tactical_pitch,
        "evaluated_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }

    emit_office_event(
        "Agent 2 (Radar)",
        f"Evaluated: {title_clean[:28]}",
        "success" if fit_score >= 3.5 else "info",
        "Career Ops",
        f"Score: {fit_score}/5.0 | Verdict: {verdict}"
    )

    return evaluation


@track("ATS Scout", lambda ats_list="greenhouse,lever,ashby", since_days=3, limit=30: f"Sweeping ATS boards: {ats_list}",
       lambda r: f"+{r.get('new_jobs_added', 0)} new postings · {r.get('total_jobs', 0)} total")
def scan_ats_boards(ats_list="greenhouse,lever,ashby", since_days=3, limit=30):
    """
    Executes reverse ATS scanner to discover fresh listings matching profile filters.
    Imports results directly into career/jobs.json.
    """
    emit_office_event("Agent 2 (Radar)", "Reverse ATS Discovery Sweep", "busy", "Career Ops", f"Scanning {ats_list}...")

    # Load existing jobs
    existing_jobs = []
    existing_urls = set()
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                existing_jobs = json.load(f)
                for j in existing_jobs:
                    if j.get("url"):
                        existing_urls.add(j["url"])
        except Exception:
            existing_jobs = []

    # Run scan-ats-full.mjs (≈0.4s per company board, so 120/ATS takes about a minute)
    # --shuffle: random sample each run, so capped sweeps cover all ~15k boards over time
    args = ["scan-ats-full.mjs", "--ats", ats_list, "--since", str(since_days), "--limit", str(limit), "--shuffle"]
    rc, out, err = run_node_cmd(args, timeout=max(60, limit * 3 * 2))

    new_jobs_added = 0
    added_list = []

    # scan-ats-full prints each match as two lines:
    #   + [greenhouse-full] 2026-10-09 | company | Title | Location
    #     https://...
    found_matches = []
    lines = out.splitlines()
    head = re.compile(r"^\s*\+\s*\[([\w-]+)\]\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*)$")
    for i, line in enumerate(lines):
        m = head.match(line)
        if m and i + 1 < len(lines) and lines[i + 1].strip().startswith("http"):
            found_matches.append((m.group(3), m.group(4), lines[i + 1].strip(), m.group(5), m.group(2), m.group(1)))

    # career-ops' title filter is broad (PMs, scientists...): keep hands-on build roles that are remote
    from agent_job_radar import is_worldwide_remote, calculate_match, load_profile
    # Two tracks from the real CV: Python automation / AI workflow, and environmental / marine data science.
    want = re.compile(r"automation|python|integration|workflow|\bai\b|\bllm\b|agent|scrap|video|content engineer|"
                      r"developer|engineer|data (analyst|scien|specialist|engineer)|analyst|scientist|research (assistant|associate|analyst)|"
                      r"\bgis\b|geospatial|remote sensing|environment|marine|ocean|climate|sustainab|ecolog|fisher|"
                      r"\bit support|technical support|system(s)? admin|sysadmin|network", re.I)
    avoid = re.compile(r"manager|director|head of|\bvp\b|\bpm\b|product owner|recruit|sales|account exec|partner|"
                       r"solutions engineer|pathologist|lawyer|counsel|nurse|physician|intern\b|customer (support|success)", re.I)
    # The CV has no professional software-engineering seniority, so senior/staff dev roles are skipped.
    senior_dev = re.compile(r"(senior|sr\.?|staff|principal|lead)\b.*(engineer|developer)|(engineer|developer).*\b(senior|staff|principal|lead)\b", re.I)
    profile = load_profile()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    for comp, role_title, role_url, location, posted, portal in found_matches:
        if role_url in existing_urls or not want.search(role_title) or avoid.search(role_title) \
                or senior_dev.search(role_title):
            continue
        if not is_worldwide_remote(location, role_title):
            continue
        existing_urls.add(role_url)
        score, skills = calculate_match(role_title, [], role_title, profile)
        job_item = {
            "id": f"ats_{abs(hash(role_url)) % 10000000}",
            "company": comp.strip(),
            "title": role_title.strip(),
            "url": role_url,
            "location": location.strip(),
            "remote": True,
            "source": f"ATS sweep ({portal.replace('-full', '')})",
            "match_score": score,
            "matched_skills": skills,
            "salary": "Not listed",
            "posted_at": posted,
            "scanned_at": now_str,
            "status": "ready"
        }
        existing_jobs.insert(0, job_item)
        added_list.append(job_item)
        new_jobs_added += 1

    # Save merged jobs.json
    if new_jobs_added > 0:
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_jobs, f, indent=2)

    emit_office_event(
        "Agent 2 (Radar)",
        f"ATS Sweep Complete: +{new_jobs_added} jobs",
        "success",
        "Career Ops",
        f"Ingested {new_jobs_added} fresh ATS postings into jobs.json"
    )

    return {
        "ok": True,
        "new_jobs_added": new_jobs_added,
        "total_jobs": len(existing_jobs),
        "added_samples": added_list[:5],
        "raw_summary": out[:500] if out else "Scan completed successfully."
    }


@track("Resume Builder", lambda html, output_filename=None: f"Printing ATS PDF {output_filename or ''}".strip(),
       lambda r: (f"PDF ready: {r.get('filename')} ({r.get('file_size_kb')} KB)", False) if r.get("ok")
       else (f"PDF failed: {str(r.get('error'))[:90]}", True))
def generate_playwright_ats_pdf(html_path_or_content, output_filename=None):
    """
    Takes an HTML resume file (or HTML string) and generates a Space Grotesk + DM Sans
    ATS-tailored PDF using career-ops/generate-pdf.mjs (Playwright Chromium).
    """
    emit_office_event("Agent 4 (ATS Resume)", "Rendering Playwright PDF", "busy", "Career Ops", "Compiling ATS-compliant document...")

    if not output_filename:
        output_filename = f"ats_resume_{int(time.time())}.pdf"

    if not output_filename.endswith(".pdf"):
        output_filename += ".pdf"

    temp_html_rel = f"output/{os.path.splitext(output_filename)[0]}.html"
    temp_html_abs = os.path.join(CAREER_OPS_DIR, "output", f"{os.path.splitext(output_filename)[0]}.html")
    temp_pdf_rel = f"output/{output_filename}"
    temp_pdf_abs = os.path.join(CAREER_OPS_DIR, "output", output_filename)
    dest_pdf_abs = os.path.join(RESUMES_DIR, output_filename)

    # Prepare input HTML inside career-ops/output/
    if os.path.isfile(html_path_or_content):
        shutil.copyfile(html_path_or_content, temp_html_abs)
    else:
        with open(temp_html_abs, "w", encoding="utf-8") as f:
            f.write(html_path_or_content)

    # Run Playwright PDF generator
    rc, out, err = run_node_cmd(["generate-pdf.mjs", temp_html_rel, temp_pdf_rel, "--skip-fact-check"], timeout=30)

    if rc == 0 and os.path.exists(temp_pdf_abs):
        shutil.copyfile(temp_pdf_abs, dest_pdf_abs)
        file_sz_kb = round(os.path.getsize(dest_pdf_abs) / 1024, 1)

        emit_office_event(
            "Agent 4 (ATS Resume)",
            f"ATS PDF Ready: {output_filename}",
            "success",
            "Career Ops",
            f"Space Grotesk + DM Sans ATS PDF ({file_sz_kb} KB) ready for dispatch"
        )

        return {
            "ok": True,
            "filename": output_filename,
            "pdf_url": f"/career/resumes/{output_filename}",
            "file_size_kb": file_sz_kb,
            "raw_output": out
        }
    else:
        emit_office_event(
            "Agent 4 (ATS Resume)",
            "PDF Generation Failed",
            "error",
            "Career Ops",
            f"Err: {err or out}"
        )
        return {
            "ok": False,
            "error": err or out or "Failed to render PDF with Playwright"
        }


if __name__ == "__main__":
    print("Agent Career-Ops Bridge Self-Test:")
    s_ok, s_msg = sync_profile()
    print(f"Profile Sync: {s_ok} ({s_msg})")

    # Test PDF generation on existing resume
    sample_html = os.path.join(RESUMES_DIR, "test_ai_eng_resume.html")
    if os.path.exists(sample_html):
        print("Testing Playwright ATS PDF generation...")
        pdf_res = generate_playwright_ats_pdf(sample_html, "test_playwright_ats.pdf")
        print(f"PDF Result: {pdf_res.get('ok')} -> {pdf_res.get('pdf_url')} ({pdf_res.get('file_size_kb')} KB)")

    print("Bridge ready.")
