#!/usr/bin/env python3
"""
Single source of truth for the candidate's identity, used by every career agent.
Everything comes from profile.json (built from the real CV). Nothing here invents claims:
a portfolio link only appears once profile.portfolio_url is filled in.
"""

import os, json, re

CAREER_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_FILE = os.path.join(CAREER_DIR, "profile.json")


def load_profile():
    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def name(profile=None):
    p = profile if profile is not None else load_profile()
    return (p.get("name") or "").lstrip("# ").strip() or "A.B.M. Ataullah"


def email(profile=None):
    p = profile if profile is not None else load_profile()
    return p.get("email", "")


def portfolio_url(profile=None):
    p = profile if profile is not None else load_profile()
    url = (p.get("portfolio_url") or "").strip()
    # never hand out a link that only works on this PC
    if re.search(r"localhost|127\.0\.0\.1", url):
        return ""
    return url


def job_text(job):
    return " ".join(str(job.get(k, "")) for k in ("title", "snippet", "desc", "description", "tags")).lower()


def pick_track(job, profile=None):
    """Return 'automation' or 'science' depending on which track's keywords the job matches more."""
    p = profile if profile is not None else load_profile()
    tracks = p.get("tracks") or {}
    if not tracks:
        return "automation"
    text = " " + job_text(job) + " "
    title = " " + str(job.get("title", "")).lower() + " "
    best, best_score = "automation", -1
    for key, t in tracks.items():
        score = sum(text.count(k) + 3 * title.count(k) for k in t.get("keywords", []))
        if score > best_score:
            best, best_score = key, score
    return best


def headline(job=None, profile=None):
    p = profile if profile is not None else load_profile()
    tr = (p.get("tracks") or {}).get(pick_track(job or {}, p)) or {}
    return tr.get("headline") or p.get("title", "")


def signature(profile=None):
    p = profile if profile is not None else load_profile()
    lines = [name(p)]
    for v in (p.get("email"), p.get("phone")):
        if v:
            lines.append(v)
    url = portfolio_url(p)
    if url:
        lines.append(f"Portfolio: {url}")
    for k, label in (("linkedin_url", "LinkedIn"), ("github_url", "GitHub")):
        if p.get(k):
            lines.append(f"{label}: {p[k]}")
    return "\n".join(lines)


def relevant_projects(job, profile=None, limit=3):
    """Projects ranked by keyword overlap with the job, restricted to the job's track when possible."""
    p = profile if profile is not None else load_profile()
    track = pick_track(job, p)
    text = job_text(job)
    projs = p.get("projects") or []

    def score(pr):
        s = sum(2 if k in text else 0 for k in pr.get("keywords", []))
        if track in pr.get("tracks", []):
            s += 5
        return s
    in_track = [pr for pr in projs if track in pr.get("tracks", [])]
    return sorted(in_track or projs, key=score, reverse=True)[:limit]
