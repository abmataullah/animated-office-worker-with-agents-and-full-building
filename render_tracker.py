#!/usr/bin/env python3
"""
Pillar 1: Video Render & Build Pipeline Tracker
Wraps any FFmpeg, Remotion, After Effects, or Python render script.
Emits real-time start, progress, completion, and error states directly
to the Office Command Center on :7799.
"""

import sys, time, json, urllib.request
from contextlib import contextmanager

def emit_render_event(agent="Geo Renderer", action="Rendering video", status="info", dept="Video Render Bay", details=""):
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:7799/event",
            data=json.dumps({
                "agent": agent,
                "action": action,
                "status": status,
                "dept": dept,
                "source": "render_tracker",
                "details": details
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass

@contextmanager
def track_render(agent="Geo Renderer", job_name="Video Render", dept="Video Render Bay"):
    """Python context manager to wrap any render block"""
    start_time = time.time()
    emit_render_event(
        agent=agent,
        action=f"⚡ Started Render: \"{job_name}\"",
        status="info",
        dept=dept,
        details="Render pipeline running..."
    )
    try:
        yield
        duration = round(time.time() - start_time, 1)
        emit_render_event(
            agent=agent,
            action=f"✓ Export Complete: \"{job_name}\" ({duration}s)",
            status="success",
            dept=dept,
            details=f"Export finished successfully in {duration} seconds."
        )
    except Exception as e:
        duration = round(time.time() - start_time, 1)
        emit_render_event(
            agent=agent,
            action=f"✗ Render Failed: \"{job_name}\"",
            status="error",
            dept=dept,
            details=f"Failed after {duration}s: {str(e)}"
        )
        raise

if __name__ == '__main__':
    # CLI demo
    job = sys.argv[1] if len(sys.argv) > 1 else "Demo 4K Vertical Reel (60fps)"
    print(f"Tracking render: {job}")
    with track_render(agent="Geo Renderer", job_name=job):
        time.sleep(2.0) # Simulating render work
    print("Done! Check office widget for live status.")
