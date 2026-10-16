# ABM Command Center: animated office of agents

A pixel-art, isometric "office building" that runs on the desktop and animates from real activity on the PC. Every floor is a department, and every worker is an agent or automation that is actually running. When a pipeline renders, publishes, fails or waits, its worker shows it.

## Floors
- **Engineering / main floors:** processes, renders and events streamed from the local monitor server.
- **💼 Job Finder:** a 14-agent career pipeline. It scans ATS job boards, audits each posting, picks a career track per job, writes a tailored ATS resume (HTML + PDF) and a formal cover letter, queues the package for one-click applying, and tracks everything in Google Sheets. Rooms open their panels: Radar, Lab, Outbox, Interviews and Command.
- **📣 Social Media Ops:** 22 agents mirroring the Facebook page pipelines (news, exam prep, English learning, US news reels, motivation calendar, and an editorial photocard workflow). A supervisor tails each pipeline's log, restarts crashed publishers, watches scheduled tasks and flags late posts.

## Pieces
| File | Role |
|---|---|
| `office-widget.html` | Canvas renderer: isometric floors, agent sprites, HUDs, command bar |
| `monitor-server.py` | Local HTTP server on `127.0.0.1:7799` (local-only request guard), stats, events, career and social APIs, optional local AI chat via Ollama |
| `desktop-widget.pyw` | pywebview desktop window with a watchdog that restarts the server |
| `social_ops/supervisor.py` | Log tailing, keep-alive, schedule and late-post detection for the page pipelines |
| `career/` | Career agents, `live_status.py` status bus, `candidate.py` identity helper, `rebuild_queue.py` |
| `career/google_sheets_webhook.gs` | Apps Script web app for live Google Sheets sync |

## Run
```bat
start-widget.bat        :: desktop window (starts the monitor server too)
start-monitor.bat       :: server only, then open http://127.0.0.1:7799
stop-office.bat
```
Requires Python 3.11+ with `psutil` and `pywebview`. The career pipeline also uses `python-docx` and `openpyxl`, plus Node for the ATS scanner and PDF renderer (career-ops, installed separately into `career/career-ops`).

## Configure the Job Finder
1. Copy `career/profile.example.json` to `career/profile.json` and fill in your real experience, projects and tracks. Resumes and letters only select and reorder what is in this file. They never invent claims.
2. Optional live Sheets sync: copy `career/sheets_config.example.json` to `career/sheets_config.json`, deploy `google_sheets_webhook.gs` as a web app, and set the same random token in both files.

Personal data (profile, applications, CVs, resumes, tracker data) and all secrets are git-ignored.
