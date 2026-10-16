#!/usr/bin/env python3
"""
CLI helper to post live workflow events into the ABM Command Center Office Widget.
Usage:
  python send-event.py --agent "Facebook Engines" --action "Published Post #1024" --status success
  python send-event.py --agent "Geo Renderer" --action "Rendered Map of South Asia" --details "1080x1920 60fps"
"""

import sys, json, argparse, urllib.request, urllib.error

def send_event(agent="ABM", action="Task completed", status="info", dept="Operations", source="cli", details=""):
    url = "http://127.0.0.1:7799/event"
    payload = {
        "agent": agent,
        "action": action,
        "status": status,
        "dept": dept,
        "source": source,
        "details": details
    }
    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            res = json.loads(resp.read().decode('utf-8'))
            print(f"[OK] Event logged: #{res.get('event', {}).get('id')} -> {agent}: {action}")
            return True
    except Exception as e:
        print(f"[ERROR] Could not connect to Office Monitor on :7799 ({e})")
        return False

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Send event to ABM Office Command Center")
    parser.add_argument('--agent', default="ABM", help="Agent or service name")
    parser.add_argument('--action', required=True, help="Description of action performed")
    parser.add_argument('--status', default="info", choices=["info", "success", "warning", "error"])
    parser.add_argument('--dept', default="Operations", help="Department name")
    parser.add_argument('--source', default="cli", help="Source tool or service")
    parser.add_argument('--details', default="", help="Additional details or links")
    args = parser.parse_args()

    send_event(args.agent, args.action, args.status, args.dept, args.source, args.details)
