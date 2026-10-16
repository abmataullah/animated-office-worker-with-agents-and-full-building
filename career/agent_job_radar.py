#!/usr/bin/env python3
"""
Agent 2: Continuous "Worldwide Remote" Job Radar
Aggregates live remote job boards (Remotive, Jobicy, RemoteOK, Himalayas, WeWorkRemotely),
applies strict '100% Worldwide Remote' filtering, weeds out ghost jobs (>21 days old)
and unpaid/equity-only scams, extracts salary ranges, computes ATS skill matches,
saves qualified jobs to career/jobs.json, and records an audit log to agent_logs.jsonl.
"""

import os, sys, json, time, re, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_FILE = os.path.join(CAREER_DIR, "profile.json")
JOBS_FILE = os.path.join(CAREER_DIR, "jobs.json")

# Import agent logger
sys.path.insert(0, CAREER_DIR)
try:
    from agent_logger import log_agent_work
except ImportError:
    def log_agent_work(*args, **kwargs): return {"id": int(time.time()*1000)}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
}

def load_profile():
    if os.path.exists(PROFILE_FILE):
        try:
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "technical_skills": ["Python", "Automation", "Video", "FFmpeg", "Node.js", "AI", "FastAPI", "React", "Docker", "DevOps"],
        "target_roles": ["Python Automation Engineer", "Video Specialist", "Workflow Developer", "AI Engineer", "Full Stack Developer"]
    }

def extract_salary(salary_raw, text_corpus):
    """
    Extracts hourly rates ($35-$100/hr) or annual salaries ($60k-$150k+).
    Returns formatted badge string or 'Competitive'.
    """
    corpus = f"{salary_raw or ''} {text_corpus or ''}"
    
    # Check hourly rate: e.g. $40 - $80 / hr, $50/hour, $35-$75/hr
    m_hour = re.search(r'\$(\d{2,3})(?:\s*-\s*\$?(\d{2,3}))?\s*(?:/|\s*per\s*)?(?:hr|hour)\b', corpus, re.IGNORECASE)
    if m_hour:
        if m_hour.group(2):
            return f"${m_hour.group(1)}-${m_hour.group(2)}/hr"
        return f"${m_hour.group(1)}/hr"
        
    # Check annual salary: e.g. $80k - $120k, $90,000 - $130,000, 100k - 140k USD
    m_k = re.search(r'\$(\d{2,3})k\s*-\s*\$?(\d{2,3})k\b', corpus, re.IGNORECASE)
    if m_k:
        return f"${m_k.group(1)}k-${m_k.group(2)}k/yr"
        
    m_ann = re.search(r'\$(\d{2,3}),000\s*-\s*\$?(\d{2,3}),000\b', corpus)
    if m_ann:
        return f"${m_ann.group(1)}k-${m_ann.group(2)}k/yr"

    if salary_raw and any(c.isdigit() for c in str(salary_raw)):
        clean = str(salary_raw).replace('None', '').strip()
        if len(clean) > 2:
            return clean

    return "Competitive"

def is_scam_or_ghost(title, desc, age_days=0):
    """
    Filters out ghost postings older than 21 days, unpaid internships,
    equity-only positions, and suspicious low-quality scam postings.
    """
    if age_days > 21:
        return True, f"Ghost Job (>21 days old: {age_days}d)"
        
    text = f"{title} {desc}".lower()
    
    scam_keywords = [
        "unpaid", "0% salary", "equity only", "commission only",
        "no salary", "pay after funding", "volunteer", "mlm",
        "earn crypto clicking", "whatsapp me to apply"
    ]
    for s in scam_keywords:
        if s in text:
            return True, f"Scam/Unpaid flag: '{s}'"
            
    return False, ""

def is_worldwide_remote(location_str, desc_str):
    """Strictly verify if job is open Worldwide/Anywhere and not restricted to US/EU"""
    loc = (location_str or '').lower().strip()
    desc = (desc_str or '').lower()
    
    # Negative filters - reject country-restricted, hybrid, or relocation roles
    restricted_keywords = [
        'us only', 'usa only', 'u.s. only', 'united states only', 'must be based in the us',
        'us citizen', 'us citizenship required', 'uk only', 'eu only', 'europe only',
        'canada only', 'germany only', 'australia only', 'hybrid', 'on-site', 'onsite',
        'relocation required', 'must reside in', 'authorized to work in the us',
        'green card required', 'work authorization required', 'security clearance required'
    ]
    for r in restricted_keywords:
        if r in loc or r in desc[:600]:
            return False
            
    # Open to anyone, or to the candidate's own region (Bangladesh / Asia)
    if re.search(r"worldwide|anywhere|global|all locations|\bbangladesh\b|\basia\b|\bapac\b", loc):
        return True
    # Otherwise the location must be a bare "remote": any leftover place name (e.g. "Remote - India",
    # "US Remote", "Europe · Remote") means the role is restricted to that country/region.
    leftover = re.sub(r"\b(100%|fully|full|remote|remotely|first|friendly|work from home|wfh|distributed|"
                      r"timezone|time zone|flexible|position|job|role|only)\b", " ", loc)
    return not re.search(r"[a-z]{2,}", leftover)

def calculate_match(job_title, job_tags, job_desc, profile):
    """Calculates fit score (0-100%) and returns matched skills"""
    skills = profile.get("technical_skills", []) + profile.get("creative_skills", [])
    target_roles = profile.get("target_roles", [])
    
    matched_skills = []
    combined_text = f"{job_title} {' '.join(job_tags)} {job_desc[:1500]}".lower()
    
    for s in skills:
        pattern = r'\b' + re.escape(s.lower()) + r'\b'
        if re.search(pattern, combined_text):
            matched_skills.append(s)
            
    # Base score on role title overlap
    title_lower = job_title.lower()
    score = 40
    for r in target_roles:
        words = [w for w in r.lower().split() if len(w) > 3]
        match_count = sum(1 for w in words if w in title_lower)
        if match_count >= 2:
            score += 35; break
        elif match_count == 1:
            score += 20; break
            
    # Boost by skill matches
    score += min(35, len(matched_skills) * 8)
    return min(99, score), list(set(matched_skills))

# --- Scrapers for 5 Boards ---

def fetch_remotive():
    jobs = []
    try:
        url = "https://remotive.com/api/remote-jobs?limit=30"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=9) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            now = datetime.now(timezone.utc)
            for item in data.get("jobs", []):
                pub_date_str = item.get("publication_date", "")
                age_days = 0
                if pub_date_str:
                    try:
                        dt = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
                        age_days = (now - dt).days
                    except Exception:
                        pass

                jobs.append({
                    "id": f"remotive_{item.get('id')}",
                    "title": item.get("title", ""),
                    "company": item.get("company_name", ""),
                    "url": item.get("url", ""),
                    "location": item.get("candidate_required_location", "Worldwide"),
                    "tags": item.get("tags", []),
                    "salary_raw": item.get("salary", ""),
                    "desc": item.get("description", ""),
                    "source": "Remotive",
                    "age_days": age_days
                })
    except Exception as e:
        print(f"[Remote Job Radar] Remotive note: {e}")
    return jobs

def fetch_jobicy():
    jobs = []
    try:
        url = "https://jobicy.com/api/v2/remote-jobs?count=25"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=9) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            now = datetime.now(timezone.utc)
            for item in data.get("jobs", []):
                pub_str = item.get("pubDate", "")
                age_days = 0
                if pub_str:
                    try:
                        dt = parsedate_to_datetime(pub_str)
                        age_days = (now - dt).days
                    except Exception:
                        pass

                jobs.append({
                    "id": f"jobicy_{item.get('id')}",
                    "title": item.get("jobTitle", ""),
                    "company": item.get("companyName", ""),
                    "url": item.get("url", ""),
                    "location": item.get("jobGeo", "Worldwide"),
                    "tags": [item.get("jobCategory", "")],
                    "salary_raw": str(item.get("annualSalaryMin", "")),
                    "desc": item.get("jobDescription", ""),
                    "source": "Jobicy",
                    "age_days": age_days
                })
    except Exception as e:
        print(f"[Remote Job Radar] Jobicy note: {e}")
    return jobs

def fetch_remoteok():
    jobs = []
    try:
        url = "https://remoteok.com/api"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=9) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            now = datetime.now(timezone.utc)
            for item in data[1:35]:  # Skip index 0 (header)
                if not isinstance(item, dict): continue
                epoch = item.get("epoch")
                age_days = 0
                if epoch:
                    try:
                        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
                        age_days = (now - dt).days
                    except Exception:
                        pass

                jobs.append({
                    "id": f"remoteok_{item.get('id')}",
                    "title": item.get("position", ""),
                    "company": item.get("company", ""),
                    "url": item.get("url", ""),
                    "location": item.get("location", "Worldwide"),
                    "tags": item.get("tags", []),
                    "salary_raw": item.get("salary", ""),
                    "desc": item.get("description", ""),
                    "source": "RemoteOK",
                    "age_days": age_days
                })
    except Exception as e:
        print(f"[Remote Job Radar] RemoteOK note: {e}")
    return jobs

def fetch_himalayas():
    jobs = []
    try:
        url = "https://himalayas.app/jobs/api?limit=25"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=9) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            now = datetime.now(timezone.utc)
            for item in data.get("jobs", []):
                pub_epoch = item.get("pub_date")
                age_days = 0
                if pub_epoch:
                    try:
                        dt = datetime.fromtimestamp(pub_epoch, tz=timezone.utc)
                        age_days = (now - dt).days
                    except Exception:
                        pass

                # Location handling
                restrictions = item.get("country_restrictions", [])
                loc = "Worldwide" if not restrictions else ", ".join(restrictions)

                # Salary range
                min_s = item.get("min_salary")
                max_s = item.get("max_salary")
                sal_str = ""
                if min_s and max_s:
                    sal_str = f"${min_s//1000}k-${max_s//1000}k/yr"

                jobs.append({
                    "id": f"himalayas_{item.get('id', item.get('slug'))}",
                    "title": item.get("title", ""),
                    "company": item.get("company_name", ""),
                    "url": item.get("application_url") or f"https://himalayas.app/jobs/{item.get('slug')}",
                    "location": loc,
                    "tags": item.get("categories", []),
                    "salary_raw": sal_str,
                    "desc": item.get("description", item.get("excerpt", "")),
                    "source": "Himalayas",
                    "age_days": age_days
                })
    except Exception as e:
        print(f"[Remote Job Radar] Himalayas note: {e}")
    return jobs

def fetch_weworkremotely():
    jobs = []
    try:
        url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=9) as resp:
            root = ET.fromstring(resp.read())
            now = datetime.now(timezone.utc)
            for item in root.findall('.//item')[:25]:
                title_full = item.find('title').text if item.find('title') is not None else ""
                link = item.find('link').text if item.find('link') is not None else ""
                desc = item.find('description').text if item.find('description') is not None else ""
                pub = item.find('pubDate').text if item.find('pubDate') is not None else ""
                
                # Split Title into Company: Role
                parts = title_full.split(":", 1)
                company = parts[0].strip() if len(parts) > 1 else "WWR Listing"
                role = parts[1].strip() if len(parts) > 1 else title_full
                
                age_days = 0
                if pub:
                    try:
                        dt = parsedate_to_datetime(pub)
                        age_days = (now - dt).days
                    except Exception:
                        pass

                jobs.append({
                    "id": f"wwr_{abs(hash(link)) % 1000000}",
                    "title": role,
                    "company": company,
                    "url": link,
                    "location": "Worldwide",
                    "tags": ["Programming", "Remote"],
                    "salary_raw": "",
                    "desc": desc,
                    "source": "WeWorkRemotely",
                    "age_days": age_days
                })
    except Exception as e:
        print(f"[Remote Job Radar] WeWorkRemotely note: {e}")
    return jobs

from live_status import track


@track("Job Radar", "Sweeping Remotive, RemoteOK, Jobicy, Himalayas & WWR",
       lambda r: f"Scanned {r[1]} postings → {len(r[0])} worldwide-remote matches")
def run_job_radar():
    """Main execution function for Agent 2: Continuous Worldwide Remote Radar"""
    start_time = time.time()
    profile = load_profile()
    
    # 1. Fetch raw remote postings across 5 boards
    raw_candidates = []
    raw_candidates.extend(fetch_remotive())
    raw_candidates.extend(fetch_jobicy())
    raw_candidates.extend(fetch_remoteok())
    raw_candidates.extend(fetch_himalayas())
    raw_candidates.extend(fetch_weworkremotely())
    
    total_scanned = len(raw_candidates)
    ghost_filtered = 0
    restricted_filtered = 0
    qualified_jobs = []
    
    # 2. Strict Worldwide + Ghost Job + Scam Filters + ATS Scoring
    for j in raw_candidates:
        if not j.get("title"): continue
        
        # Ghost / Scam filter (Skip >21 days old or unpaid scams)
        is_bad, bad_reason = is_scam_or_ghost(j["title"], j["desc"], j.get("age_days", 0))
        if is_bad:
            ghost_filtered += 1
            continue
            
        # Strict Worldwide Remote filter
        if not is_worldwide_remote(j["location"], j["desc"]):
            restricted_filtered += 1
            continue
            
        # Match against CV profile
        score, matched_skills = calculate_match(j["title"], j["tags"], j["desc"], profile)
        if score < 50:  # Match quality threshold
            continue
            
        clean_desc = re.sub(r'<[^>]+>', ' ', j["desc"])
        clean_desc = re.sub(r'\s+', ' ', clean_desc)[:280].strip() + "..."
        salary_extracted = extract_salary(j["salary_raw"], j["desc"])
        
        qualified_jobs.append({
            "id": j["id"],
            "title": j["title"],
            "company": j["company"],
            "url": j["url"],
            "location": j.get("location") or "Worldwide",
            "salary": salary_extracted,
            "has_salary_flag": salary_extracted != "Competitive",
            "match_score": score,
            "matched_skills": matched_skills,
            "snippet": clean_desc,
            "source": j["source"],
            "age_days": j.get("age_days", 0),
            "discovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "ready_to_apply"
        })
        
    # Sort by highest match score, then by salary transparency
    qualified_jobs.sort(key=lambda x: (x["match_score"], x["has_salary_flag"]), reverse=True)
    top_jobs = qualified_jobs[:30]

    # Keep roles found by the ATS sweep (stage 3) — the board scan alone must not erase them
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            previous = json.load(f)
        urls = {j["url"] for j in top_jobs}
        top_jobs += [j for j in previous if str(j.get("source", "")).startswith("ATS sweep")
                     and j.get("url") not in urls and is_worldwide_remote(j.get("location", ""), "")][:30]
    except Exception:
        pass

    # 3. Save to career/jobs.json
    os.makedirs(CAREER_DIR, exist_ok=True)
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(top_jobs, f, indent=2, ensure_ascii=False)
        
    duration = round(time.time() - start_time, 2)
    reasoning = (
        f"Scanned {total_scanned} live remote jobs from 5 boards (Remotive, Jobicy, RemoteOK, Himalayas, WeWorkRemotely) in {duration}s. "
        f"Filtered out {ghost_filtered} ghost/scam jobs and {restricted_filtered} location-restricted roles. "
        f"Selected top {len(top_jobs)} verified 100% Worldwide Remote roles. "
        f"Top match: {top_jobs[0]['match_score']}% ({top_jobs[0]['title']} @ {top_jobs[0]['company']} | {top_jobs[0]['salary']})."
    )
    
    # 4. Log to Learning Database
    log_rec = log_agent_work(
        agent_name="Job Radar",
        task=f"Worldwide Remote Radar Sweep ({len(top_jobs)} qualified jobs from 5 boards)",
        model="5-Board Aggregator + Scam Filter + ATS Matcher",
        prompt="Scan 5 boards (Remotive, Jobicy, RemoteOK, Himalayas, WWR), weed out ghost jobs >21d & US/EU only, extract salary.",
        reasoning=reasoning,
        output=json.dumps({
            "total_scanned": total_scanned,
            "ghost_or_scam_rejected": ghost_filtered,
            "location_restricted_rejected": restricted_filtered,
            "qualified_worldwide": len(top_jobs),
            "top_matches": [f"{j['title']} @ {j['company']} ({j['match_score']}% | {j['salary']})" for j in top_jobs[:5]]
        }, ensure_ascii=False),
        status="success"
    )
    
    # 5. Broadcast to Office Monitor
    top_badge = f"{top_jobs[0]['title'][:24]} ({top_jobs[0]['match_score']}%)" if top_jobs else "0 roles"
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:7799/event",
            data=json.dumps({
                "agent": "Job Radar",
                "action": f"5-Board Radar: {len(top_jobs)} verified Worldwide Remote roles found!",
                "status": "success",
                "dept": "Remote Career Ops",
                "source": "job_radar",
                "details": f"Top Match: {top_badge}"
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass
        
    return top_jobs, total_scanned, log_rec

if __name__ == '__main__':
    print("=== Agent 2: Continuous Worldwide Remote Radar Active ===")
    jobs, scanned, rec = run_job_radar()
    print(f"Total Scanned Across 5 Boards: {scanned} jobs")
    print(f"100% Worldwide Remote Matches: {len(jobs)} jobs")
    for j in jobs[:5]:
        print(f" - [{j['match_score']}% Match] {j['title']} @ {j['company']} | {j['salary']} ({j['source']})")
    print(f"Audit Log Record ID: #{rec['id']}")
