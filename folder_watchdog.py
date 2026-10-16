#!/usr/bin/env python3
"""
Pillar 4: Automatic File & Export Watchdog
Monitors an 'exports/' folder for new video, image, or document exports.
Automatically alerts the office widget, logs the activity, and assigns
it to the correct department worker.
"""

import os, sys, time, json, urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WATCH_DIR = os.path.join(SCRIPT_DIR, "exports")
STATE_FILE = os.path.join(SCRIPT_DIR, "exports", ".watchdog_state.json")

def get_dept_and_agent_for_file(filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext in ('.mp4', '.mov', '.avi', '.mkv', '.webm'):
        return "Video Render Bay", "Geo Renderer", "video"
    elif ext in ('.png', '.jpg', '.jpeg', '.webp', '.psd'):
        return "Social Media Ops", "EP Image", "image"
    elif ext in ('.mp3', '.wav', '.m4a', '.aac'):
        return "Video Render Bay", "Free Studio", "audio"
    elif ext in ('.pdf', '.docx', '.csv', '.xlsx'):
        return "Remote Career Ops", "CV Analyst", "document"
    else:
        return "Operations", "Scheduler", "file"

def scan_once():
    """Scans the watch folder and alerts on newly detected files"""
    os.makedirs(WATCH_DIR, exist_ok=True)
    
    seen = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                seen = json.load(f)
        except Exception:
            pass

    current_files = os.listdir(WATCH_DIR)
    new_files = []
    
    for f in current_files:
        if f.startswith('.'):
            continue
        p = os.path.join(WATCH_DIR, f)
        if not os.path.isfile(p):
            continue
        mtime = os.path.getmtime(p)
        size_mb = round(os.path.getsize(p) / (1024 * 1024), 2)
        if f not in seen or seen[f] < mtime:
            seen[f] = mtime
            dept, agent, ftype = get_dept_and_agent_for_file(f)
            new_files.append((f, size_mb, dept, agent, ftype))

    # Save state
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f)

    for fname, size_mb, dept, agent, ftype in new_files:
        msg = f"New {ftype.title()} Export: {fname} ({size_mb} MB)"
        print(f"[WATCHDOG] {msg} -> Assigned to {agent} ({dept})")
        
        # Broadcast to Office Widget
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:7799/event",
                data=json.dumps({
                    "agent": agent,
                    "action": msg,
                    "status": "success",
                    "dept": dept,
                    "source": "watchdog",
                    "details": f"File: {os.path.join(WATCH_DIR, fname)}"
                }).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    return len(new_files)

if __name__ == '__main__':
    print(f"=== File & Export Watchdog Active ===")
    print(f"Monitoring folder: {WATCH_DIR}")
    detected = scan_once()
    print(f"Scan complete. {detected} new export(s) processed.")
