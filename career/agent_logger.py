#!/usr/bin/env python3
"""
Agent Activity, Memory & Learning Logger
Permanently logs each agent's execution, reasoning, model used, output,
and provides a revision loop so you can review and train the agents.
"""

import os, json, time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, "agent_logs.jsonl")

def log_agent_work(agent_name, task, model="local-llm", prompt="", reasoning="", output="", status="success", revision_notes=""):
    """Record an agent's work session with full audit trail"""
    entry_id = int(time.time() * 1000)
    record = {
        "id": entry_id,
        "timestamp": time.time(),
        "time_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "agent": agent_name,
        "task": task,
        "model": model,
        "prompt": prompt,
        "reasoning": reasoning,
        "output": output,
        "status": status,  # "success", "needs_revision", "revised", "failed"
        "revision_notes": revision_notes
    }
    
    os.makedirs(SCRIPT_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        
    return record

def get_agent_logs(agent_name=None, limit=50):
    """Retrieve recent agent logs, optionally filtered by agent name"""
    if not os.path.exists(LOG_FILE):
        return []
        
    logs = []
    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if not agent_name or rec.get("agent") == agent_name:
                    logs.append(rec)
            except Exception:
                continue
                
    return logs[-limit:]

def revise_agent_work(log_id, feedback, updated_output=None):
    """Update a previous agent log with human correction/learning notes"""
    if not os.path.exists(LOG_FILE):
        return None
        
    records = []
    updated = None
    with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("id") == log_id:
                    rec["status"] = "revised"
                    rec["revision_notes"] = feedback
                    if updated_output is not None:
                        rec["output"] = updated_output
                    rec["revised_at"] = time.time()
                    updated = rec
                records.append(rec)
            except Exception:
                continue
                
    if updated:
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                
    return updated

if __name__ == '__main__':
    # Test logger
    t = log_agent_work(
        agent_name="System Setup",
        task="Initialize Agent Memory Logger",
        model="Python Engine",
        reasoning="Initialized audit database for career agents",
        output="Memory & Learning Logger ready.",
        status="success"
    )
    print("Logger initialized:", t["id"])
