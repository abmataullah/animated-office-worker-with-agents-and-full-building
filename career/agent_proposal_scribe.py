#!/usr/bin/env python3
"""
Agent 4: Proposal Scribe & "One-Click Quick Apply" Queue
Pre-screens qualified remote jobs, generates custom high-converting 3-paragraph pitches
embedding the live proof-of-work link, attaches the ATS-tailored resume, stacks into the
'Ready to Apply' queue, and executes direct application dispatch with full audit logging.
"""

import os, sys, json, time, re, urllib.request
from datetime import datetime

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_FILE = os.path.join(CAREER_DIR, "jobs.json")
APPLICATIONS_FILE = os.path.join(CAREER_DIR, "applications.json")
PROFILE_FILE = os.path.join(CAREER_DIR, "profile.json")

# Import sub-agents & logger
sys.path.insert(0, CAREER_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

try:
    from agent_ats_resume import generate_tailored_resume_for_job
except ImportError:
    def generate_tailored_resume_for_job(j): return ("", {}, {"id": 0})

def load_jobs():
    if os.path.exists(JOBS_FILE):
        try:
            with open(JOBS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def load_applications():
    if os.path.exists(APPLICATIONS_FILE):
        try:
            with open(APPLICATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_applications(apps):
    os.makedirs(CAREER_DIR, exist_ok=True)
    with open(APPLICATIONS_FILE, "w", encoding="utf-8") as f:
        json.dump(apps, f, indent=2, ensure_ascii=False)
    try:
        from agent_sheets_overseer import sync_apply_queue
        sync_apply_queue(apps)
    except Exception:
        pass

from live_status import track


# Evidence the letters can draw on. Every line is taken from the CV, the blog or the PC projects.
# Each letter picks the few lines that best match the posting (keywords), in this order of importance.
PITCH_EVIDENCE = {
    "science": [
        ("At ECOMAC, an environmental consultancy, I spent five years leading marine and coastal surveys, water-quality "
         "and plankton work, and the analysis behind Environmental Impact Assessments: data cleaning and statistics in R, "
         "and air-dispersion modelling with AERMOD and AERMET.",
         ["eia", "impact assessment", "environment", "consult", "statistic", " r ", "r,", "data", "model", "water", "plankton", "survey"]),
        ("My field record covers twelve years and four oceans: the Bay of Bengal, open-ocean transects in the Tasman Sea "
         "and the Atlantic, and a fifteen-day polar research programme sampling the water column at the sea-ice edge.",
         ["ocean", "field", "cruise", "polar", "offshore", "at sea", "sampling", "vessel", "international", "travel"]),
        ("In 2017 I served forty days offshore as Marine Mammal Observer on the DS-12 seismic survey aboard R/V BGP "
         "Explorer, running mitigation during airgun operations and reporting daily to the Party Chief and Vessel Master; "
         "the assignment ended with a written commendation.",
         ["mammal", "cetacean", "observer", "mmo", "seismic", "protected species", "acoustic", "hse", "offshore", "monitoring"]),
        ("My research uses the same tools: a GIS-based position map of marine mammals in the Bay of Bengal for my M.Phil., "
         "and a forty-year shoreline-change study of the Chittagong coast built from remote sensing.",
         ["gis", "remote sensing", "geospatial", "arcgis", "map", "research", "coastal", "spatial", "satellite"]),
        ("I also write Python automation, so analysis that is usually done by hand can be made repeatable, documented "
         "and quick to rerun.",
         ["python", "automation", "reproducib", "pipeline", "programming", "code", "matlab"]),
        ("Agriculture is familiar ground as well: I manage seasonal cropping, soil and water on my family's farm in "
         "Hathazari and have trained in farm mechanization with the Department of Agricultural Extension.",
         ["agri", "farm", "crop", "soil", "irrigation", "rural", "livelihood", "food security"], True),
    ],
    "automation": [
        ("I design and operate a set of Python pipelines that run unattended every day. The largest, True News, ingests "
         "news feeds, uses Gemini to select and rewrite stories in Bangla, renders photocards in headless Chromium, "
         "produces narrated reels with Edge TTS and FFmpeg, and publishes to Facebook through the Graph API.",
         ["python", "automation", "pipeline", "llm", "gemini", "api", "ffmpeg", "video", "media", "content", "scrap", "integration"]),
        ("To keep these jobs reliable I built a supervisor and a live dashboard that tail every pipeline's logs, restart "
         "failed processes, watch scheduled tasks and flag any post that runs late.",
         ["reliab", "monitor", "devops", "ops", "observab", "process", "scheduler", "uptime", "support", "maintain", "system"]),
        ("I work comfortably with both hosted and local models: Gemini for writing and narration, Ollama on my own "
         "machine, and a fully local video pipeline built on ComfyUI, Wan 2.2 and FFmpeg.",
         ["llm", "ai", "genai", "generative", "model", "ollama", "local", "comfyui", "diffusion", "prompt", "agent"]),
        ("I also build workflows in n8n, connecting APIs, webhooks and AI steps without custom code where that is "
         "the simpler and more maintainable choice.",
         ["n8n", "zapier", "make.com", "no-code", "low-code", "webhook", "integration", "workflow"], True),
        ("My video work includes AvatarStudio, a local talking-avatar studio with lip-synced presenters, Whisper-timed "
         "captions and AI or stock B-roll, alongside narrated news reels and a fully local generative video pipeline.",
         ["video", "avatar", "youtube", "reels", "editing", "content", "generative", "media"]),
        ("GeoExplainer, another of my tools, turns a topic into a narrated map video, combining Gemini scripting, "
         "forced alignment, charts drawn in R and composition in Remotion.",
         ["video", "remotion", "map", "gis", "visual", "chart", "r ", "data visual"]),
        ("Before this work I spent five years at an environmental consultancy analysing field data in R and supporting "
         "the team's Windows, Linux and network setup, which taught me to validate inputs and document everything.",
         ["data", "analyst", "linux", "it support", "network", "documentation", "windows", "quality", "qa"]),
    ],
    "media": [
        ("I report for The Daily Khoborer Kagoj, a Bangla-language national daily, covering coastal communities, the "
         "environment and fisheries, so writing accurate copy to a deadline is part of my routine.",
         ["journalis", "reporter", "news", "writer", "writing", "editor", "editorial", "copy", "bangla", "bengali", "press"]),
        ("I also run several Facebook pages, publishing news, exam-preparation and English-learning content every day. "
         "I built the production behind them myself: scheduled posting, branded photocards and narrated short videos.",
         ["social media", "facebook", "community", "content", "page", "audience", "engagement", "schedul", "reels", "short-form"]),
        ("I edit video in Adobe Premiere Pro and After Effects and handle SEO, Facebook and LinkedIn marketing and "
         "Google Analytics, so I can take a piece from draft through to publishing and measurement.",
         ["video", "premiere", "after effects", "editing", "seo", "marketing", "analytics", "growth", "campaign", "youtube"]),
        ("My own site, a hand-built Blogger portfolio, carries long-form essays in Bangla on social issues alongside my "
         "professional profile.",
         ["blog", "long-form", "essay", "wordpress", "web", "html", "website", "article"]),
        ("My background as a marine scientist means I can write about environment, climate and science subjects from "
         "first-hand knowledge.",
         ["science", "environment", "climate", "sustainab", "ocean", "research", "nature"]),
    ],
}

PITCH_OPENERS = {
    "science": ("I am writing to apply for the {title} position{at}. I am a marine scientist with an M.S. in Oceanography "
                "(First Class, second position) from the University of Chittagong, where I am now completing an M.Phil., "
                "and I have spent my career on survey work, environmental assessment and the analysis that follows it."),
    "automation": ("I am writing to apply for the {title} position{at}. I build and run Python automation that does real "
                   "work every day, from data collection through AI-assisted processing to publishing, and I would like "
                   "to bring that experience to your team."),
    "media": ("I am writing to apply for the {title} position{at}. I work as a journalist and run several content pages "
              "of my own, writing in Bengali and English and producing the video and graphics that go with them."),
}


@track("Proposal Scribe", lambda job, matched_skills: f"Drafting pitch for {job.get('company', 'company')}",
       lambda r: f"Pitch drafted ({len(r.split())} words)")
def craft_custom_pitch(job, matched_skills):
    """
    A short, formal cover letter written for one specific posting:
    opening (role + who I am for this track), the 2-3 pieces of real evidence that best match the posting,
    how the posting's stated needs map to my skills, availability, sign-off.
    Nothing is invented: evidence lines come from PITCH_EVIDENCE, skills from the posting/profile overlap.
    """
    import candidate
    prof = candidate.load_profile()
    title = (job.get("title") or "advertised").strip()
    company = (job.get("company") or "").strip()
    track = candidate.pick_track(job, prof)
    text = " " + candidate.job_text(job) + " "

    def _and(xs):
        xs = [x for x in xs if x]
        if not xs:
            return ""
        return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]

    salutation = f"Dear {company} Hiring Team," if company else "Dear Hiring Manager,"
    opener = PITCH_OPENERS.get(track, PITCH_OPENERS["automation"]).format(
        title=title, at=f" at {company}" if company else "")

    # Evidence: best-matching lines, always at least two, kept in their natural order
    pool = PITCH_EVIDENCE.get(track, PITCH_EVIDENCE["automation"])
    scored = [(sum(1 for k in item[1] if k in text), i) for i, item in enumerate(pool)]
    best = sorted(scored, key=lambda x: (-x[0], x[1]))
    chosen = sorted(i for sc, i in best[:3] if sc > 0)
    for sc, i in best:  # top up to two lines; "only if matched" lines are never used as filler
        if len(chosen) >= 2:
            break
        if i not in chosen and not (len(pool[i]) > 2 and pool[i][2]):
            chosen.append(i)
    evidence = " ".join(pool[i][0] for i in sorted(chosen))

    # Fit: the posting's own terms that genuinely overlap with the profile
    common = {"passive", "acoustic", "monitoring", "marine", "mammal", "observation", "remote", "sensing", "statistical",
              "analysis", "field", "surveys", "data", "cleaning", "journalism", "writing", "content", "video", "editing",
              "social", "media", "marketing", "workflow", "automation", "environmental", "impact", "assessment", "air",
              "dispersion", "modelling", "technical", "reports", "generative", "integration", "api", "plankton",
              "identification", "oceanographic", "sampling", "facebook"}

    def _plain(sk):  # "Passive Acoustic Monitoring" -> "passive acoustic monitoring", keep R, SEO, FFmpeg, Python
        return " ".join(w.lower() if w.lower() in common and w[1:].islower() else w for w in sk.split())

    skills = [_plain(sk) for sk in (matched_skills or []) if sk.lower() not in ("remote", "automation")][:3]
    fit = ""
    if skills:
        fit = (f"The areas your posting emphasises, {_and(skills)}, are ones I work in regularly, so I would expect "
               f"to be useful to the team from the start.")
    more = ""
    field_ok = track == "science" and any(k in text for k in ("offshore", "field", "travel", "vessel", "at sea", "rotation", "site"))
    avail = ("I am based in Chittagong, Bangladesh (GMT+6), work comfortably with teams in Europe and North America, and "
             + ("am available for offshore and field assignments as well as remote work." if field_ok
                else "keep communication clear and in writing when working remotely."))
    close = (f"{avail}{more} I would welcome the opportunity to discuss how I could contribute"
             f"{(' to ' + company) if company else ''}. Thank you for your time and consideration.")

    paras = [salutation, opener, evidence] + ([fit] if fit else []) + [close, f"Kind regards,\n{candidate.signature(prof)}"]
    return "\n\n".join(paras)

def extract_target_destination(job):
    """Identifies application destination: email address or application portal"""
    url = job.get("url", "")
    desc = job.get("snippet", "") + " " + job.get("desc", "")
    
    # Check for direct email in description
    m_email = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', desc)
    if m_email and not any(ign in m_email.group(0).lower() for ign in ['support@', 'info@remoteok', 'team@remotive']):
        return {"type": "email", "destination": m_email.group(0)}
        
    return {"type": "portal", "destination": url}

@track("Proposal Scribe", "Preparing application queue for top matches",
       lambda r: f"{len(r)} applications ready to send")
def prepare_queue(max_items=12):
    """
    Pre-screens top jobs from jobs.json, crafts tailored pitches,
    generates tailored ATS resumes, and populates the Quick Apply Kanban queue.
    """
    jobs = load_jobs()
    existing_apps = {a["job_id"]: a for a in load_applications()}
    updated_apps = []
    
    count_new = 0
    for job in jobs[:max_items]:
        jid = job.get("id")
        if not jid: continue
        
        # If already exists, retain status
        if jid in existing_apps:
            updated_apps.append(existing_apps[jid])
            continue
            
        matched_skills = job.get("matched_skills", [])
        pitch = craft_custom_pitch(job, matched_skills)
        dest = extract_target_destination(job)
        
        # Generate dynamic ATS resume
        resume_path, tailored_data, _ = generate_tailored_resume_for_job(job)
        pdf_file = ""
        if resume_path and os.path.exists(resume_path):
            try:
                from agent_career_ops_bridge import generate_playwright_ats_pdf
                p_fn = f"{jid}_resume.pdf"
                p_res = generate_playwright_ats_pdf(resume_path, output_filename=p_fn)
                if p_res.get("ok"):
                    pdf_file = p_fn
            except Exception:
                pass
        
        app_entry = {
            "job_id": jid,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", "Competitive"),
            "match_score": job.get("match_score", 80),
            "matched_skills": matched_skills,
            "url": job.get("url", ""),
            "destination_type": dest["type"],
            "destination": dest["destination"],
            "custom_pitch": pitch,
            "resume_path": resume_path,
            "resume_file": os.path.basename(resume_path) if resume_path else "",
            "pdf_file": pdf_file,
            "status": "ready_to_apply", # ready_to_apply | applied | skipped
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "applied_at": None,
            "feedback": None
        }
        updated_apps.append(app_entry)
        count_new += 1
        
    # Append any previously applied or skipped jobs that might not be in top N
    for jid, app in existing_apps.items():
        if not any(a["job_id"] == jid for a in updated_apps):
            updated_apps.append(app)
            
    save_applications(updated_apps)
    
    # Audit log
    if count_new > 0:
        log_agent_work(
            agent_name="Proposal Scribe",
            task=f"Prepared {count_new} new application packages in Quick Apply Queue",
            model="Proposal Scribe + Proof-of-Work Linker",
            prompt="Draft 3-paragraph pitches from the real profile with tailored resumes",
            reasoning=f"Crafted custom pitches and ATS resumes for {count_new} top worldwide remote roles.",
            output=json.dumps({"new_applications": count_new, "total_queue": len(updated_apps)}, ensure_ascii=False),
            status="success"
        )
        
    return updated_apps

@track("Proposal Scribe", lambda job, *a, **k: f"Queueing application: {job.get('company', '')} · {job.get('title', '')}"[:120],
       lambda r: f"Queued for you: {r['company']} ({r['destination_type']})")
def queue_application(job, pitch, resume_path, pdf_file, evaluation=None):
    """Add (or refresh) a ready-to-apply package in the Quick Apply queue. Nothing is sent from here:
    portal jobs need the candidate to submit on the company's page."""
    apps = load_applications()
    dest = extract_target_destination(job)
    entry = next((a for a in apps if a.get("job_id") == job.get("id")), None)
    if entry is None:
        entry = {"job_id": job.get("id"), "status": "ready_to_apply", "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "applied_at": None, "feedback": None}
        apps.insert(0, entry)
    ev = evaluation or {}
    entry.update({
        "title": job.get("title", ""), "company": job.get("company", ""), "salary": job.get("salary", "Competitive"),
        "match_score": job.get("match_score", 0), "matched_skills": job.get("matched_skills", []),
        "url": job.get("url", ""), "destination_type": dest["type"], "destination": dest["destination"],
        "custom_pitch": pitch, "resume_path": resume_path,
        "resume_file": os.path.basename(resume_path) if resume_path else "", "pdf_file": pdf_file or "",
        "fit_score": ev.get("fit_score"), "verdict": ev.get("verdict"), "source": job.get("source", ""),
        "queued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    save_applications(apps)
    return entry


@track("Proposal Scribe", lambda job_id, action="apply", notes="": f"{action.title()}: application {job_id}",
       lambda r: (r[1], not r[0]))
def dispatch_application(job_id, action="apply", notes=""):
    """
    Executes 'One-Click Quick Apply':
    action='apply': Marks as applied, records timestamp, logs to agent memory, and sends monitor event.
    action='skip': Marks as skipped.
    """
    apps = load_applications()
    target_app = None
    
    for a in apps:
        if a["job_id"] == job_id:
            target_app = a
            break
            
    if not target_app:
        return False, f"Application for {job_id} not found."
        
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    
    if action == "apply":
        target_app["status"] = "applied"
        target_app["applied_at"] = now_str
        target_app["notes"] = notes or "Applied via One-Click Quick Apply queue"
        
        # Log to Learning Database
        log_rec = log_agent_work(
            agent_name="Proposal Scribe",
            task=f"Applied to {target_app['company']} ({target_app['title']})",
            model="One-Click Quick Apply Dispatcher",
            prompt=f"Submit application to {target_app['company']} via {target_app['destination_type']}",
            reasoning=f"Candidate approved application package with {target_app['match_score']}% ATS match. Custom pitch and resume dispatched.",
            output=json.dumps({
                "job_id": job_id,
                "company": target_app["company"],
                "title": target_app["title"],
                "destination": target_app["destination"],
                "applied_at": now_str
            }, ensure_ascii=False),
            status="success"
        )
        
        # Broadcast event to office
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:7799/event",
                data=json.dumps({
                    "agent": "Proposal Scribe",
                    "action": f"Application Dispatched: {target_app['company']} ({target_app['title'][:25]})",
                    "status": "success",
                    "dept": "Remote Career Ops",
                    "source": "quick_apply",
                    "details": f"Destination: {target_app['destination'][:30]}"
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass
            
        save_applications(apps)
        return True, f"Marked as applied: {target_app['company']} ({now_str})."
        
    elif action == "skip":
        target_app["status"] = "skipped"
        target_app["notes"] = notes or "Skipped by candidate"
        save_applications(apps)
        return True, f"Role at {target_app['company']} skipped."
        
    return False, "Unknown action."

if __name__ == '__main__':
    print("=== Agent 4: Proposal Scribe Active ===")
    queue = prepare_queue(max_items=8)
    ready = [a for a in queue if a["status"] == "ready_to_apply"]
    applied = [a for a in queue if a["status"] == "applied"]
    print(f"Queue Status: {len(ready)} Ready to Apply, {len(applied)} Applied, Total: {len(queue)}")
    if ready:
        sample = ready[0]
        print(f"\nTop Queued Application: {sample['title']} @ {sample['company']}")
        print(f"Match: {sample['match_score']}% | Resume: {sample['resume_file']}")
        print("Sample Pitch Excerpt:\n" + sample['custom_pitch'][:180] + "...")
