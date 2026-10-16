#!/usr/bin/env python3
"""
Agent 3: Dynamic ATS-Tailored Resume Generator
Analyzes specific job description keywords, dynamically re-orders candidate skills,
customizes executive summaries and experience highlights to match ATS scans,
and generates clean, professional ATS-friendly resumes (HTML + PDF export ready).
Logs every customized resume generation to agent_logs.jsonl.
"""

import os, sys, json, time, re
from datetime import datetime

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
RESUMES_DIR = os.path.join(CAREER_DIR, "resumes")
PROFILE_FILE = os.path.join(CAREER_DIR, "profile.json")

# Import logger
sys.path.insert(0, CAREER_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

from html import escape as _esc
import candidate


def load_profile():
    return candidate.load_profile()


def tailor_resume_data(job, profile):
    """Picks the career track that fits the job, then orders the candidate's real skills, projects
    and experience by relevance to the posting. Content is only selected and reordered, never invented."""
    job_title = job.get("title", "")
    company = job.get("company", "")
    desc = candidate.job_text(job)
    track = candidate.pick_track(job, profile)
    tr = (profile.get("tracks") or {}).get(track, {})

    # 1. Skill ordering by how often the posting mentions each skill (title hits weigh more)
    seen, all_skills = set(), []
    not_skills = {"remote", "documentation"}
    for sk in profile.get("technical_skills", []) + profile.get("ats_keywords", []):
        if sk.lower() not in seen and sk.lower() not in not_skills:
            seen.add(sk.lower())
            all_skills.append(sk)

    def skill_relevance(sk):
        pattern = r'(?<![a-z0-9])' + re.escape(sk.lower()) + r'(?![a-z0-9])'
        count = len(re.findall(pattern, desc))
        if re.search(pattern, job_title.lower()):
            count += 5
        if count == 0:  # loose match: "Marine Mammal Observation" vs "marine mammal observer"
            words = [w[:5] for w in re.findall(r"[a-z]+", sk.lower()) if len(w) > 3]
            if len(words) >= 2 and all(w in desc for w in words):
                count = 1
        return count

    sorted_skills = sorted(all_skills, key=skill_relevance, reverse=True)
    if track == "science":  # keep the science core near the top even when the posting is terse
        core = ["R", "Statistical Analysis", "Data Analysis", "Data Cleaning", "Environmental Impact Assessment",
                "AERMOD", "AERMET", "Air Dispersion Modelling", "Remote Sensing", "Field Surveys", "Oceanography",
                "Marine Science", "Technical Reports", "Python", "Excel (advanced)"]
    elif track == "media":
        core = ["Journalism", "Content Writing", "Bangla Writing", "SEO", "Social Media Marketing", "Facebook Marketing",
                "Video Editing", "Adobe Premiere Pro", "Adobe After Effects", "Google Analytics", "WordPress",
                "LinkedIn Marketing", "Generative AI", "Python", "Automation"]
    else:
        core = ["Python", "Automation", "Workflow Automation", "LLM", "Generative AI", "Gemini", "Ollama", "FFmpeg",
                "Playwright", "Puppeteer", "API Integration", "Facebook Graph API", "Node.js", "FastAPI", "Linux"]
    hits = [sk for sk in sorted_skills if skill_relevance(sk) > 0]
    primary = []
    for sk in hits + [c for c in core if c.lower() in seen] + sorted_skills:
        if sk not in primary:
            primary.append(sk)
    top_primary_skills = primary[:10]
    rest = [c for c in core if c.lower() in seen] + sorted_skills
    secondary_skills = list(dict.fromkeys(sk for sk in rest if sk not in top_primary_skills))[:12]

    # 2. Experience: real roles, bullets reordered so the most relevant come first
    def bullet_score(b):
        bl = b.lower()
        return (sum(1 for sk in top_primary_skills if sk.lower() in bl)
                + sum(1 for k in tr.get("keywords", []) if k.strip() and k.strip() in bl))

    # Only the roles this job cares about, and only their most relevant bullets.
    # Order of bullets inside a role is kept as written once the top ones are chosen.
    def keyword_hits(e):
        return sum(1 for k in e.get("keywords", []) if k in desc)

    experience = []
    roles = profile.get("experience", [])
    for e in roles:  # pass 1: main job + roles the posting actually asks about
        if e.get("only_if") and not any(k in desc for k in e["only_if"]):
            continue
        hits = keyword_hits(e)
        is_core = e.get("core") or track in e.get("core_for", [])
        if is_core or hits:
            if track in e.get("core_for", []) or (e.get("core") and track in ("science", "automation")):
                cap = 5
            else:
                cap = 3 if hits >= 2 else 2
            experience.append((e, cap))
    for e in roles:  # pass 2: same-track roles as one-line context, up to 4 roles in total
        if len(experience) >= 4:
            break
        if track in e.get("tracks", []) and not e.get("only_if") and all(e is not x for x, _ in experience):
            experience.append((e, 1))
    picked = []
    for e, cap in experience:
        bl = e.get("bullets", [])
        chosen = set(sorted(bl, key=bullet_score, reverse=True)[:cap])
        picked.append({**e, "bullets": [b for b in bl if b in chosen]})
    experience = sorted(picked, key=lambda e: e.get("sort", 0), reverse=True)

    research = profile.get("research", []) if track == "science" or any(k in desc for k in ("research", "gis", "remote sensing", "marine", "ocean")) else []
    projects = candidate.relevant_projects(job, profile, limit={"automation": 4, "media": 3}.get(track, 2))
    return {
        "name": candidate.name(profile),
        "headline": tr.get("headline") or profile.get("title", ""),
        "track": track,
        "email": profile.get("email", ""),
        "phone": profile.get("phone", ""),
        "location": profile.get("location", ""),
        "work_location": profile.get("work_location", ""),
        "portfolio_url": candidate.portfolio_url(profile),
        "linkedin_url": profile.get("linkedin_url", ""),
        "github_url": profile.get("github_url", ""),
        "summary": tr.get("summary", ""),
        "primary_skills": top_primary_skills,
        "secondary_skills": secondary_skills,
        "experience": experience,
        "experience_bullets": [b for e in experience for b in e["bullets"]],
        "projects": projects,
        "research": research,
        "education": profile.get("education", []),
        "certifications": profile.get("certifications", []),
        "languages": profile.get("languages", []),
        "company_target": company,
        "job_title_target": job_title,
    }


def _ul(items):
    return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


def generate_ats_html(tailored, job_id):
    """Single-column, ATS-scannable resume HTML (no tables, no icons, plain section headings)."""
    os.makedirs(RESUMES_DIR, exist_ok=True)
    clean_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(job_id))
    html_file = os.path.join(RESUMES_DIR, f"{clean_id}_resume.html")
    t = tailored

    contact = [x for x in (t["email"], t["phone"], t["location"]) if x]
    links = [(lbl, u) for lbl, u in (("Portfolio", t["portfolio_url"]), ("LinkedIn", t["linkedin_url"]),
                                      ("GitHub", t["github_url"])) if u]
    contact_html = " | ".join(_esc(c) for c in contact)
    if links:
        contact_html += " | " + " | ".join(f'{lbl}: <a href="{_esc(u)}">{_esc(u)}</a>' for lbl, u in links)

    exp_html = "".join(
        f'<div class="item"><div class="item-head"><span><strong>{_esc(e["role"])}</strong>, {_esc(e["org"])}</span>'
        f'<span class="dates">{_esc(e.get("dates", ""))}</span></div>'
        f'<div class="sub">{_esc(e.get("location", ""))}</div>{_ul(e["bullets"])}</div>'
        for e in t["experience"])
    proj_html = "".join(
        f'<div class="item"><div class="item-head"><strong>{_esc(pr["name"])}</strong></div>'
        f'<div class="sub">{_esc(pr.get("stack", ""))}</div>{_ul(pr.get("bullets", []))}</div>'
        for pr in t["projects"])
    research_html = _ul([r["title"] for r in t["research"]])
    edu_html = "".join(
        f'<div class="item"><div class="item-head"><span><strong>{_esc(ed["degree"])}</strong>, {_esc(ed["school"])}</span>'
        f'<span class="dates">{_esc(ed.get("dates", ""))}</span></div><div class="sub">{_esc(ed.get("result", ""))}</div></div>'
        for ed in t["education"])

    sections = {
        "experience": f"<h2>Professional Experience</h2>{exp_html}",
        "projects": f"<h2>Software &amp; Automation Projects</h2>{proj_html}" if proj_html else "",
        "research": f"<h2>Research</h2>{research_html}" if t["research"] else "",
    }
    order = {"automation": ["projects", "experience", "research"],
             "media": ["experience", "projects", "research"]}.get(t["track"], ["experience", "research", "projects"])
    body = "".join(sections[k] for k in order)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{_esc(t['name'])} - Resume</title>
  <style>
    @page {{ size: A4; margin: 14mm; }}
    body {{ font-family: Calibri, "Segoe UI", Arial, sans-serif; line-height: 1.4; color: #1a1a1a;
           max-width: 820px; margin: 0 auto; padding: 20px; background: #fff; font-size: 12.5px; }}
    .name {{ font-size: 24px; font-weight: 700; margin: 0 0 2px 0; }}
    .role {{ font-size: 14px; font-weight: 600; color: #2b4c7e; margin: 0 0 4px 0; }}
    .contact {{ font-size: 12px; color: #444; }}
    .contact a {{ color: #2b4c7e; text-decoration: none; }}
    .header {{ border-bottom: 2px solid #2b4c7e; padding-bottom: 10px; margin-bottom: 10px; }}
    h2 {{ font-size: 13px; font-weight: 700; color: #2b4c7e; text-transform: uppercase; letter-spacing: .6px;
          border-bottom: 1px solid #ddd; padding-bottom: 2px; margin: 14px 0 6px 0; }}
    p {{ margin: 0 0 6px 0; }}
    ul {{ margin: 2px 0 6px 18px; padding: 0; }}
    li {{ margin-bottom: 3px; }}
    .item {{ margin-bottom: 6px; }}
    .item-head {{ display: flex; justify-content: space-between; gap: 12px; }}
    .dates {{ color: #555; white-space: nowrap; }}
    .sub {{ color: #555; font-size: 11.5px; }}
  </style>
</head>
<body>
  <div class="header">
    <h1 class="name">{_esc(t['name'])}</h1>
    <div class="role">{_esc(t['headline'])}</div>
    <div class="contact">{contact_html}</div>
  </div>

  <h2>Professional Summary</h2>
  <p>{_esc(t['summary'])}</p>

  <h2>Skills</h2>
  <p><strong>Core:</strong> {_esc(", ".join(t['primary_skills']))}</p>
  <p><strong>Also:</strong> {_esc(", ".join(t['secondary_skills']))}</p>

  {body}

  <h2>Education</h2>
  {edu_html}

  <h2>Certifications</h2>
  {_ul(t['certifications'])}

  <h2>Languages</h2>
  <p>{_esc(", ".join(t['languages']))}. {_esc(t['work_location'])}</p>
</body>
</html>"""

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    return html_file

from live_status import track


@track("Resume Builder", lambda job: f"Tailoring resume for {job.get('company', '')} · {job.get('title', '')}"[:120],
       lambda r: f"Tailored resume: {os.path.basename(r[0])}")
def generate_tailored_resume_for_job(job):
    """Main Agent 3 entrypoint"""
    profile = load_profile()
    job_id = job.get("id", f"job_{int(time.time())}")
    tailored = tailor_resume_data(job, profile)
    html_path = generate_ats_html(tailored, job_id)
    
    # Log to Learning Database
    reasoning = (
        f"Analyzed job '{job.get('title')}' at {job.get('company')}. "
        f"Dynamically elevated top skills: {', '.join(tailored['primary_skills'][:4])}. "
        f"Used the '{tailored['track']}' track and compiled an ATS-ready resume to {os.path.basename(html_path)}."
    )
    
    log_rec = log_agent_work(
        agent_name="ATS Resume Generator",
        task=f"Generate tailored resume for {job.get('company')} ({job.get('title')})",
        model="ATS Keyword Ranker + HTML Synthesizer",
        prompt=f"Extract keywords from '{job.get('title')}' and reorder CV skills for max ATS score",
        reasoning=reasoning,
        output=json.dumps({
            "job_id": job_id,
            "company": job.get("company"),
            "resume_file": html_path,
            "top_skills": tailored["primary_skills"]
        }, ensure_ascii=False),
        status="success"
    )
    
    return html_path, tailored, log_rec

if __name__ == '__main__':
    sample_job = {
        "id": "test_ai_eng",
        "title": "Senior AI & Python Automation Engineer",
        "company": "ScaleAI Remote",
        "snippet": "We need Python, FastAPI, and AI workflow automation experts with Docker."
    }
    path, tail, rec = generate_tailored_resume_for_job(sample_job)
    print("=== Agent 3: ATS Resume Generator Active ===")
    print("Resume Generated at:", path)
    print("Top Skills Elevated:", tail["primary_skills"])
    print(f"Audit Log ID: #{rec['id']}")
