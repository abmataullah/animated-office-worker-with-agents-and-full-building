#!/usr/bin/env python3
"""
Agent 1: CV & Profile Intel Analyst
Reads and parses CVs/Resumes (PDF, TXT, MD, DOCX), extracts core skills,
experience, project highlights, and strictly sets remote job conditions.
Saves to career/profile.json and records reasoning in agent_logs.jsonl.
"""

import os, sys, json, time, re, urllib.request
from agent_logger import log_agent_work

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
CV_DIR = os.path.join(CAREER_DIR, "cv")
PROFILE_FILE = os.path.join(CAREER_DIR, "profile.json")

def extract_text_from_file(file_path):
    """Extract clean text from PDF, TXT, or MD"""
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.txt', '.md', '.markdown'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()
    elif ext == '.pdf':
        try:
            import fitz
            doc = fitz.open(file_path)
            text = "\n".join([page.get_text() for page in doc])
            return text
        except Exception:
            try:
                import pdfplumber
                with pdfplumber.open(file_path) as pdf:
                    return "\n".join([page.extract_text() or '' for page in pdf.pages])
            except Exception as e:
                return f"Error reading PDF: {e}"
    elif ext == '.json':
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def call_ai_parser(raw_text):
    """Parse CV text into structured JSON using Ollama or fallback heuristic"""
    prompt = f"""You are an expert technical recruiter and ATS analyst. Analyze the following CV/resume text and extract a structured JSON profile.
Requirements:
- Target Job Mode MUST BE "100% Remote".
- Extract all programming languages, frameworks, creative tools, and automation tech.
- Identify the top 4 job titles the candidate is best suited for.
- List 3 standout accomplishments or projects.
- Extract top 20 ATS keywords.

Candidate CV Text:
{raw_text[:4000]}

Respond ONLY with valid JSON in this exact structure:
{{
  "name": "Candidate Name",
  "title": "Primary Professional Title",
  "remote_preference": "100% Remote Only",
  "min_hourly_rate": "$35/hr",
  "min_annual_salary": "$70,000",
  "target_roles": ["Title 1", "Title 2", "Title 3"],
  "technical_skills": ["Skill 1", "Skill 2"],
  "creative_skills": ["Skill 1", "Skill 2"],
  "automation_tools": ["Tool 1", "Tool 2"],
  "standout_projects": ["Project 1", "Project 2"],
  "ats_keywords": ["keyword1", "keyword2"]
}}"""

    # Try local Ollama first
    try:
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": "gemma4", "prompt": prompt, "stream": False, "format": "json"}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            reply = data.get('response', '')
            parsed = json.loads(reply)
            return parsed, "Ollama Gemma4 (Local AI)"
    except Exception:
        pass

    # Intelligent Fallback Parser
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    candidate_name = lines[0] if lines else "Candidate"
    
    # Skill keywords detection
    common_skills = [
        "Python", "JavaScript", "TypeScript", "Node.js", "Docker", "FFmpeg", "After Effects",
        "Premiere Pro", "Remotion", "n8n", "Ollama", "ComfyUI", "REST APIs", "FastAPI",
        "React", "HTML/CSS", "Git", "PostgreSQL", "Automation", "Motion Graphics"
    ]
    detected_skills = [s for s in common_skills if re.search(r'\b' + re.escape(s) + r'\b', raw_text, re.IGNORECASE)]
    if not detected_skills:
        detected_skills = ["Python", "Automation", "Video Production", "AI Workflows", "API Integration"]

    fallback_profile = {
        "name": candidate_name[:40],
        "title": "Full-Stack Automation & Video Workflow Engineer",
        "remote_preference": "100% Remote Only",
        "min_hourly_rate": "$35/hr",
        "min_annual_salary": "$70,000",
        "target_roles": [
            "Python Automation Engineer",
            "Video & Motion Graphics Specialist",
            "AI Agent & Workflow Developer",
            "Full-Stack Web Developer"
        ],
        "technical_skills": detected_skills,
        "creative_skills": ["Video Editing", "Motion Graphics", "Photocard Design", "Audio Sync"],
        "automation_tools": ["n8n", "FFmpeg", "Webhooks", "Local LLMs", "Selenium/Playwright"],
        "standout_projects": [
            "Autonomous Multi-Floor Command Center & Agent HUD",
            "Automated Video Rendering Pipeline (FFmpeg & Remotion)",
            "AI-Powered Social Media Distribution Engine"
        ],
        "ats_keywords": detected_skills + ["Remote", "Async Communication", "Workflow Optimization", "CI/CD", "RESTful APIs"]
    }
    return fallback_profile, "Heuristic Parser + Keyword Extractor"

from live_status import track


@track("CV Analyst", "Parsing CV into a skills profile",
       lambda r: f"Profile ready: {len((r[0] or {}).get('technical_skills', []))} skills extracted")
def run_cv_analyst(cv_file_path=None, direct_text=None):
    """Main execution function for Agent 1"""
    start_time = time.time()
    os.makedirs(CV_DIR, exist_ok=True)
    
    # 1. Locate CV document
    content = ""
    source_name = "Direct Input"
    if direct_text:
        content = direct_text
    elif cv_file_path and os.path.exists(cv_file_path):
        source_name = os.path.basename(cv_file_path)
        content = extract_text_from_file(cv_file_path)
    else:
        # Search CV directory for any file
        files = os.listdir(CV_DIR)
        if files:
            target_path = os.path.join(CV_DIR, files[0])
            source_name = files[0]
            content = extract_text_from_file(target_path)
            
    if not content:
        # Generate default starter CV template if empty
        template_path = os.path.join(CV_DIR, "candidate_cv.md")
        content = """# Software & Automation Engineer
Experienced developer specializing in Python, AI Agentic workflows, automated video rendering (FFmpeg/Remotion), and n8n webhooks.
## Core Skills
- Python, TypeScript, Node.js, REST APIs, FastAPI
- Video Editing, FFmpeg, Adobe After Effects, Motion Graphics
- Local AI / Ollama, Gemini API, Autonomous Agents, Task Orchestration
- Remote work experience, async team collaboration
## Standout Projects
1. Autonomous Agent Desktop Office & Mission Control
2. End-to-end Automated Video Pipeline with Dynamic Subtitles
3. Social Media Webhook Automation Engine (Meta Graph API)
"""
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(content)
        source_name = "candidate_cv.md (Auto-generated Starter Profile)"

    # 2. Parse and structure. A hand-curated profile (real CV + verified projects) is never
    # replaced by the heuristic parser; it only gets its timestamp refreshed.
    curated = None
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("curated"):
                curated = existing
        except Exception:
            pass
    if curated:
        parsed_profile, model_name = curated, "Curated profile (kept)"
    else:
        parsed_profile, model_name = call_ai_parser(content)
        parsed_profile["source_document"] = source_name
    parsed_profile["last_analyzed"] = time.strftime("%Y-%m-%d %H:%M:%S")

    # 3. Save profile.json
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(parsed_profile, f, indent=2, ensure_ascii=False)

    duration = round(time.time() - start_time, 2)
    reasoning = f"Parsed CV source '{source_name}' in {duration}s. Extracted {len(parsed_profile.get('technical_skills', []))} technical skills, {len(parsed_profile.get('target_roles', []))} target remote roles. Enforced '100% Remote Only' filter."
    
    # 4. Log to Learning Database
    log_record = log_agent_work(
        agent_name="CV Analyst",
        task=f"Parse CV & Build Target Remote Profile from {source_name}",
        model=model_name,
        prompt=f"Extract ATS skills and target roles from {source_name}",
        reasoning=reasoning,
        output=json.dumps(parsed_profile, ensure_ascii=False),
        status="success",
        revision_notes=""
    )

    # 5. Broadcast to Office Monitor Server
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:7799/event",
            data=json.dumps({
                "agent": "CV Analyst",
                "action": f"Profile Synced ({len(parsed_profile['technical_skills'])} skills, 100% Remote)",
                "status": "success",
                "dept": "Career Operations",
                "source": "cv_analyst",
                "details": f"Target Roles: {', '.join(parsed_profile.get('target_roles', [])[:2])}"
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass

    return parsed_profile, log_record

if __name__ == '__main__':
    prof, rec = run_cv_analyst()
    print("=== Agent 1: CV Analyst Complete ===")
    print(f"Candidate: {prof.get('name')} - {prof.get('title')}")
    print(f"Target Remote Roles: {', '.join(prof.get('target_roles', []))}")
    print(f"Skills Extracted: {', '.join(prof.get('technical_skills', []))}")
    print(f"Memory Log ID: #{rec['id']}")
