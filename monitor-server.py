#!/usr/bin/env python3
"""
ABM Office Monitor Server (Enterprise / Connected Edition)
Feeds live CPU/RAM/GPU/process data, file watchers, webhooks, and live events
to the Office Command Center Widget via HTTP.

Endpoints:
  GET  /stats    - Live system telemetry, processes, active renders, recent files, and events
  GET  /events   - Live event stream (webhook/system/agent logs)
  POST /event    - Ingest event webhook (from n8n, python scripts, git hooks, CLI)
  POST /cmd      - Execute real commands, launch services, open folders, shell execution
  GET  /         - Serves office-widget.html
"""

import json, time, subprocess, sys, os, glob, shutil, socket, threading, re, urllib.request, urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from datetime import datetime

# Prevent pythonw crashes when running without console
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(SCRIPT_DIR, 'monitor.log')

if sys.stdout is None or sys.stderr is None:
    try:
        f_log = open(LOG_FILE, 'a', encoding='utf-8', buffering=1)
        if sys.stdout is None: sys.stdout = f_log
        if sys.stderr is None: sys.stderr = f_log
    except Exception:
        pass

try:
    import psutil
except ImportError:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'psutil', '-q'])
    import psutil

PORT = 7799
CAREER_DIR = os.path.join(SCRIPT_DIR, 'career')
ASSETS_DIR = os.path.join(SCRIPT_DIR, 'assets')
LOCAL_HOSTS = {f'localhost:{PORT}', f'127.0.0.1:{PORT}'}
LOCAL_ORIGIN_RE = re.compile(r'^https?://(localhost|127\.0\.0\.1)(:\d+)?$')
WIDGET_HTML = os.path.join(SCRIPT_DIR, 'office-widget.html')
EVENTS_LOG = os.path.join(SCRIPT_DIR, 'events.jsonl')

KNOWN_PORTS = {
    3000: 'Node Dev',
    3001: 'OpenHands Dev Agent',
    5678: 'n8n',
    7860: 'Gradio',
    7880: 'EP Video',
    7890: 'EP Image',
    8000: 'FastAPI/Web',
    8080: 'Web Server',
    8085: 'Dify AI Platform',
    8088: 'Adobe CEP Bridge',
    8188: 'ComfyUI',
    11434: 'Ollama'
}

TARGET_WATCH_DIRS = [
    r"d:\cooking video making",
    r"d:\cooking video making\engine\projects",
    r"E:\Developed by antigravity\English Pro Academy",
    r"E:\Developed by antigravity\News and photocard for true news",
    r"E:\My video avatar creation\geo-explainer\outputs",

    r"d:\my random work\english pro image maker",
    r"d:\my random work\english pro video maker",
    r"d:\my random work\Story Video Maker",
    r"d:\my random work\Aziz English video",
    r"d:\my random work\Aziz N8n",
    r"d:\my random work\Adobe after effect or Premier pro control",
    r"d:\my random work\My video project",
    r"d:\my random work\Work Office creation",
    r"d:\my random work\dify",
    r"d:\my random work\openhands",
]


# Rolling live events queue
EVENTS = [
    {
        "id": 1,
        "t": time.time() - 120,
        "time_str": datetime.now().strftime("%H:%M:%S"),
        "agent": "ABM",
        "dept": "ABM Operations",
        "action": "Command Center Server v2 initialized & listening on :7799",
        "status": "success",
        "source": "system",
        "details": "Connected to host telemetry and process manager"
    }
]
_event_counter = 2

def log_event(agent, action, status="info", dept="Operations", source="system", details=""):
    global _event_counter
    evt = {
        "id": _event_counter,
        "t": time.time(),
        "time_str": datetime.now().strftime("%H:%M:%S"),
        "agent": agent,
        "dept": dept,
        "action": action,
        "status": status,
        "source": source,
        "details": details
    }
    _event_counter += 1
    EVENTS.append(evt)
    if len(EVENTS) > 150:
        EVENTS.pop(0)
    try:
        with open(EVENTS_LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(evt) + '\n')
    except Exception:
        pass
    return evt

def get_gpu():
    try:
        r = subprocess.run(
            ['nvidia-smi',
             '--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu',
             '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=3,
            creationflags=0x08000000
        )
        if r.returncode == 0:
            p = [x.strip() for x in r.stdout.strip().split(',')]
            return {
                'ok': True, 'name': p[0], 'util': int(p[1]),
                'vram_used': int(p[2]), 'vram_total': int(p[3]), 'temp': int(p[4])
            }
    except Exception:
        pass
    return {'ok': False}

_recent_files_cache = []

def scan_recent_files_once():
    global _recent_files_cache
    recent = []
    now = time.time()
    exts = ('.mp4', '.mov', '.png', '.jpg', '.jpeg', '.webp', '.wav', '.mp3', '.json', '.py')

    for d in TARGET_WATCH_DIRS:
        if not os.path.isdir(d):
            continue
        try:
            folder_name = os.path.basename(d)
            for entry in os.scandir(d):
                if entry.is_file() and entry.name.lower().endswith(exts):
                    try:
                        mtime = entry.stat().st_mtime
                        diff = now - mtime
                        if 0 <= diff <= 7200:  # files within last 2 hours
                            sz = entry.stat().st_size
                            recent.append({
                                'name': entry.name,
                                'path': entry.path,
                                'folder': folder_name,
                                'age_s': round(diff),
                                'size_mb': round(sz / (1024 * 1024), 2),
                                'type': 'video' if entry.name.lower().endswith(('.mp4','.mov')) else ('image' if entry.name.lower().endswith(('.png','.jpg','.webp')) else 'file')
                            })
                    except (OSError, PermissionError):
                        pass
        except Exception:
            continue

    recent.sort(key=lambda x: x['age_s'])
    _recent_files_cache = recent[:8]

def _file_scan_loop():
    while True:
        try:
            scan_recent_files_once()
        except Exception:
            pass
        time.sleep(20)

import threading
threading.Thread(target=_file_scan_loop, daemon=True).start()

def get_recent_files():
    return _recent_files_cache



def _proc_mem_mb(proc):
    """Lazy per-process memory lookup: only paid for the few processes we report on."""
    cache = []

    def get():
        if not cache:
            try:
                cache.append(proc.memory_info().rss // (1024 * 1024))
            except Exception:
                cache.append(0)
        return cache[0]
    return get


def _proc_create_time(proc):
    try:
        return proc.create_time()
    except Exception:
        return time.time()


def detect_video_renders():
    """Universal Video Render Detector & Progress Tracker across this PC.
    Detects Cooking Video Engine, Geo Explainer / Remotion, Story Video Maker,
    FFmpeg, and any other active rendering pipelines.
    """
    renders = []
    now = time.time()

    # 1. Cooking Video Engine (Wan 2.1 / Gemma4 / ComfyUI / PyTorch)
    cve_engine = r"d:\cooking video making\engine"
    cve_projects = os.path.join(cve_engine, "projects")
    if os.path.isdir(cve_projects):
        try:
            comfy_running = False
            for proc in psutil.process_iter(['name', 'cmdline']):
                try:
                    c = ' '.join(proc.info['cmdline'] or []).lower()
                    if 'comfyui' in c or 'run.py' in c or 'cve' in c:
                        comfy_running = True
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            logs_dir = os.path.join(cve_engine, "logs")
            all_logs = sorted(glob.glob(os.path.join(logs_dir, "*.log")), key=os.path.getmtime, reverse=True)
            render_logs = [f for f in all_logs if not os.path.basename(f).startswith('comfyui')]
            newest_log = render_logs[0] if render_logs else (all_logs[0] if all_logs else None)
            log_active = newest_log and (now - os.path.getmtime(newest_log) < 1800)

            for d in os.scandir(cve_projects):
                if not d.is_dir():
                    continue
                final_mp4 = os.path.join(d.path, f"{d.name}.mp4")
                if os.path.exists(final_mp4):
                    continue

                p_path = d.path
                script_path = os.path.join(p_path, "script.json")
                sb_path = os.path.join(p_path, "storyboard.json")

                # A) Long-form project (script.json with beats)
                if os.path.exists(script_path):
                    try:
                        with open(script_path, 'r', encoding='utf-8') as f:
                            sdata = json.load(f)
                        beats = sdata.get('beats', []) if isinstance(sdata, dict) else sdata
                        anim_beats = [b for b in beats if b.get('animate')]

                        narr_dir = os.path.join(p_path, "narration")
                        total_segs = 0
                        for b in anim_beats:
                            bid = b['id']
                            wav_p = os.path.join(narr_dir, f"beat_{bid:02d}.wav")
                            if os.path.exists(wav_p):
                                try:
                                    import wave
                                    with wave.open(wav_p, 'rb') as w:
                                        dur = w.getnframes() / float(w.getframerate())
                                    import math
                                    n = max(1, math.ceil((dur + 0.35) / 4.0))
                                    total_segs += min(n, b.get('max_segments', n))
                                except Exception:
                                    total_segs += max(1, round(b.get('duration', 5.0) / 4.0))
                            else:
                                total_segs += 1

                        clips_dir = os.path.join(p_path, "clips")
                        done_segs = 0
                        if os.path.isdir(clips_dir):
                            done_segs = len([f for f in os.listdir(clips_dir) if f.endswith('.mp4')])

                        pct = round((done_segs / total_segs * 100), 1) if total_segs > 0 else 0
                        pct = min(100.0, pct)

                        # Determine if THIS project is the active one
                        is_this_active = bool(log_active and comfy_running)
                        latest_step = f"Segment {done_segs}/{total_segs}"
                        if log_active and comfy_running:
                            try:
                                with open(newest_log, 'rb') as lf:
                                    lf.seek(max(0, os.path.getsize(newest_log) - 16384))
                                    raw = lf.read()
                                text = raw.replace(b'\x00', b'').decode('utf-8', errors='ignore')
                                tail_lines = text.splitlines()[-40:]
                                for line in reversed(tail_lines):
                                    line_clean = line.strip()
                                    if 'animate' in line_clean:
                                        clean = re.sub(r'\[.*?\]\s*', '', line_clean)
                                        if clean:
                                            latest_step = clean
                                            is_this_active = True
                                            break
                                    elif 'stage:' in line_clean:
                                        latest_step = line_clean
                                        is_this_active = True
                                        break
                            except Exception:
                                pass

                        # If not the currently running log, check if clips modified recently
                        if not is_this_active and os.path.isdir(clips_dir):
                            clip_files = glob.glob(os.path.join(clips_dir, "*.mp4"))
                            if clip_files:
                                newest_clip = max(clip_files, key=os.path.getmtime)
                                if now - os.path.getmtime(newest_clip) < 3600:
                                    is_this_active = True

                        if is_this_active or done_segs > 0:
                            renders.append({
                                'name': f"Cooking AI • {d.name}",
                                'engine': 'Cooking Video Engine',
                                'agent': 'Cooking AI',
                                'project': d.name,
                                'type': 'AI Long-Form Video (Wan 2.1)',
                                'progress': pct,
                                'completed': done_segs,
                                'total': total_segs,
                                'units': 'segs',
                                'step': latest_step,
                                'target': f"{d.name}.mp4",
                                'active': is_this_active,
                                'details': f"{done_segs}/{total_segs} segments ({pct}%) • {latest_step}"
                            })
                    except Exception:
                        pass

                # B) Short-form project (storyboard.json with shots)
                elif os.path.exists(sb_path):
                    try:
                        with open(sb_path, 'r', encoding='utf-8') as f:
                            sb = json.load(f)
                        shots = sb.get('shots', [])
                        n_shots = len(shots)
                        if n_shots > 0:
                            kf_dir = os.path.join(p_path, "keyframes")
                            clips_dir = os.path.join(p_path, "clips")
                            shots_dir = os.path.join(p_path, "shots")
                            foley_dir = os.path.join(p_path, "foley")

                            kf_done = len(glob.glob(os.path.join(kf_dir, "shot_*.png"))) if os.path.isdir(kf_dir) else 0
                            clips_done = len(glob.glob(os.path.join(clips_dir, "shot_*_48fps.mp4"))) if os.path.isdir(clips_dir) else 0
                            shots_done = len(glob.glob(os.path.join(shots_dir, "shot_*.mp4"))) if os.path.isdir(shots_dir) else 0
                            foley_done = len(glob.glob(os.path.join(foley_dir, "shot_*.wav"))) if os.path.isdir(foley_dir) else 0

                            pct = round(
                                (kf_done / n_shots * 15.0) +
                                (clips_done / n_shots * 65.0) +
                                (shots_done / n_shots * 5.0) +
                                (foley_done / n_shots * 10.0),
                                1
                            )

                            step = "Storyboard ready"
                            if foley_done > 0: step = f"Foley {foley_done}/{n_shots}"
                            elif shots_done > 0: step = f"Cutting {shots_done}/{n_shots}"
                            elif clips_done > 0: step = f"Animate {clips_done}/{n_shots}"
                            elif kf_done > 0: step = f"Keyframes {kf_done}/{n_shots}"

                            is_this_active = False
                            if log_active and newest_log and d.name in os.path.basename(newest_log):
                                is_this_active = True

                            if is_this_active or kf_done > 0:
                                renders.append({
                                    'name': f"Cooking AI • {d.name}",
                                    'engine': 'Cooking Video Engine',
                                    'agent': 'Cooking AI',
                                    'project': d.name,
                                    'type': 'AI Short-Form Reel (9:16)',
                                    'progress': pct,
                                    'completed': clips_done or kf_done,
                                    'total': n_shots,
                                    'units': 'shots',
                                    'step': step,
                                    'target': f"{d.name}.mp4",
                                    'active': is_this_active,
                                    'details': f"{pct}% complete • {step}"
                                })
                    except Exception:
                        pass
        except Exception:
            pass

    # 2. Geo Explainer / Remotion / Avatar Studio
    geo_path = r"E:\My video avatar creation\geo-explainer"
    if os.path.isdir(geo_path):
        try:
            glogs = sorted(glob.glob(os.path.join(geo_path, "logs", "*.log")), key=os.path.getmtime, reverse=True)
            if glogs and (now - os.path.getmtime(glogs[0]) < 300):
                newest = glogs[0]
                with open(newest, 'r', encoding='utf-8', errors='ignore') as gf:
                    lines = gf.readlines()[-15:]
                for line in reversed(lines):
                    if 'frame' in line.lower() or 'render' in line.lower():
                        renders.append({
                            'name': 'Geo Explainer • Map Video',
                            'engine': 'Remotion Geo Explainer',
                            'agent': 'Geo Renderer',
                            'project': os.path.basename(newest).replace('.log', ''),
                            'type': 'Remotion React Video',
                            'progress': 50,
                            'completed': 0,
                            'total': 0,
                            'units': 'frames',
                            'step': line.strip()[:40],
                            'target': 'geo_explainer.mp4',
                            'active': True,
                            'details': line.strip()
                        })
                        break
        except Exception:
            pass

    # 3. Running FFmpeg processes (active video exports)
    try:
        for proc in psutil.process_iter(['pid', 'name']):
            try:
                if (proc.info['name'] or '').lower() == 'ffmpeg.exe':
                    elapsed = round(now - _proc_create_time(proc))
                    cmd_tokens = proc.cmdline() or []
                    target_out = os.path.basename(cmd_tokens[-1]) if cmd_tokens else 'video.mp4'
                    mem = _proc_mem_mb(proc)()
                    renders.append({
                        'name': f"FFmpeg • {target_out[:25]}",
                        'engine': 'FFmpeg Encoder',
                        'agent': 'Geo Renderer',
                        'project': target_out,
                        'type': 'FFmpeg Direct Render',
                        'progress': min(95, max(10, elapsed // 3)),
                        'completed': elapsed,
                        'total': 0,
                        'units': 'sec',
                        'step': f"Encoding for {elapsed}s",
                        'target': target_out[:35],
                        'active': True,
                        'elapsed_s': elapsed,
                        'mem_mb': mem,
                        'details': f"FFmpeg active PID {proc.info['pid']} ({elapsed}s elapsed)"
                    })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:
        pass

    # 4. External Events from POST /event (Render Tracker webhook)
    for evt in reversed(EVENTS[-30:]):
        if evt.get('source') == 'render_tracker' and (now - evt.get('t', 0) < 600):
            action = evt.get('action', '')
            if 'Started Render' in action or 'Rendering' in action or 'progress' in evt:
                if not any(r.get('target') in action or r.get('agent') == evt.get('agent') for r in renders):
                    prog_val = evt.get('progress', 50)
                    renders.append({
                        'name': f"{evt.get('agent', 'Renderer')} • {evt.get('details', action)[:25]}",
                        'engine': 'Render Tracker Webhook',
                        'agent': evt.get('agent', 'Geo Renderer'),
                        'project': evt.get('details', action),
                        'type': 'Pipeline Job',
                        'progress': prog_val,
                        'completed': 0,
                        'total': 0,
                        'units': '%',
                        'step': action[:40],
                        'target': evt.get('details', 'video.mp4'),
                        'active': True,
                        'details': evt.get('details', action)
                    })

    # Sort active renders to top, highest progress first
    renders.sort(key=lambda r: (r.get('active', False), r.get('progress', 0)), reverse=True)
    return renders


def get_stats():
    cpu = psutil.cpu_percent(interval=0.2)
    ram = psutil.virtual_memory()

    procs = {}
    renders = detect_video_renders()

    # Only name+cmdline for every process: on Windows, memory/create_time/cpu for protected
    # processes fall back to a full process-table scan each (~50 ms), which made /stats take 20s+.
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            info = dict(proc.info)  # snapshot: psutil may rewrite .info from another thread
            n = (info.get('name') or '').lower()
            cmd = ' '.join(info.get('cmdline') or []).lower()
            mem = _proc_mem_mb(proc)

            def add(key, detail=None):
                if key not in procs:
                    procs[key] = {'running': True, 'mem_mb': 0, 'count': 0, 'details': []}
                procs[key]['mem_mb'] += mem()
                procs[key]['count'] += 1
                if detail and len(procs[key]['details']) < 4:
                    procs[key]['details'].append(detail)

            # --- AI & LLM ---
            if 'ollama' in n:
                add('ollama', 'Ollama LLM Host')
            if 'comfyui' in cmd or 'comfy' in cmd:
                add('comfyui', 'ComfyUI Stable Diffusion')
            
            # --- Node & n8n ---
            if n == 'node.exe':
                add('node')
                if 'n8n' in cmd:
                    add('n8n', 'n8n Workflow Automation')

            # --- Containers & DevOps ---
            if 'docker' in n or 'com.docker' in n:
                add('docker', 'Docker Engine')

            # --- Video Rendering & FFmpeg ---
            if n == 'ffmpeg.exe':
                add('ffmpeg')
                elapsed = time.time() - _proc_create_time(proc)
                # Try to extract output target from cmdline
                target_out = ''
                cmd_tokens = info.get('cmdline') or []
                if cmd_tokens:
                    target_out = os.path.basename(cmd_tokens[-1])
                renders.append({
                    'pid': proc.pid,
                    'elapsed_s': round(elapsed),
                    'target': target_out[:30],
                    'mem_mb': mem()
                })

            # --- Creative & Adobe Suite ---
            if 'afterfx.exe' in n:
                add('afterfx', 'Adobe After Effects')
            if 'adobe premiere pro.exe' in n or 'premiere' in n:
                add('premiere', 'Adobe Premiere Pro')
            if 'photoshop.exe' in n:
                add('photoshop', 'Adobe Photoshop')
            if 'illustrator.exe' in n:
                add('illustrator', 'Adobe Illustrator')
            if 'audition.exe' in n:
                add('audition', 'Adobe Audition')
            if 'blender.exe' in n:
                add('blender', 'Blender 3D')

            # --- IDEs & Code Editors ---
            if n == 'code.exe':
                add('vscode', 'Visual Studio Code')
            if 'cursor.exe' in n:
                add('cursor', 'Cursor AI Code Editor')
            if 'antigravity' in n or 'antigravity' in cmd:
                add('antigravity', 'Antigravity IDE')

            # --- Shells & Terminals ---
            if n in ('powershell.exe', 'pwsh.exe'):
                add('powershell')
            if n in ('cmd.exe', 'wt.exe', 'windowsterminal.exe'):
                add('terminal')
            if n == 'git.exe':
                add('git', 'Git CLI')

            # --- Python Services & MCPs ---
            if n in ('python.exe', 'pythonw.exe'):
                add('python')
                if 'uvicorn' in cmd or 'fastapi' in cmd:
                    add('fastapi', 'FastAPI Web Service')
                if 'gradio' in cmd:
                    add('gradio', 'Gradio App')
                if 'qgis_mcp' in cmd or 'qgis' in cmd:
                    add('qgis_mcp', 'QGIS Spatial MCP')
                if 'cmr-mcp' in cmd:
                    add('cmr_mcp', 'CMR MCP Agent')
                if 'tts' in cmd or 'indicf5' in cmd or 'piper' in cmd:
                    add('tts_voice', 'TTS Voice Generator')
                if 'cursortouch' in cmd or 'windows-mcp' in cmd:
                    add('windows_mcp', 'Windows Desktop MCP')
                if 'desktop-widget' in cmd:
                    add('widget_gui', 'Office Desktop Widget')

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Port listening scan
    ports = {}
    try:
        for c in psutil.net_connections(kind='tcp'):
            if c.status == 'LISTEN' and c.laddr.port in KNOWN_PORTS:
                ports[str(c.laddr.port)] = KNOWN_PORTS[c.laddr.port]
    except (psutil.AccessDenied, PermissionError):
        pass

    recent_files = get_recent_files()

    return {
        'cpu': round(cpu, 1),
        'ram': {
            'total_gb': round(ram.total / (1024**3), 1),
            'used_gb': round(ram.used / (1024**3), 1),
            'pct': round(ram.percent, 1)
        },
        'gpu': get_gpu(),
        'procs': procs,
        'ports': ports,
        'renders': renders,
        'recent_files': recent_files,
        'events': EVENTS[-20:],
        't': round(time.time())
    }

_cache = {'d': None, 't': 0}
_cache_lock = threading.Lock()


def stats_refresher():
    while True:
        try:
            d = get_stats()
            with _cache_lock:
                _cache['d'], _cache['t'] = d, time.time()
        except Exception as e:
            print(f"[Stats] refresh error: {e}")
        time.sleep(3)

OLLAMA_URL = "http://127.0.0.1:11434"
OLLAMA_APP = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Ollama", "ollama app.exe")


def ask_antigravity(prompt):
    """Answer free-text chat with the local Ollama model; never invent a reply when it is down."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            models = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return {'ok': False, 'msg': "Antigravity AI is offline: Ollama isn't running. Type 'start:ollama' (or pick it in Quick Action) and try again in ~30s."}
    if not models:
        return {'ok': False, 'msg': "Ollama is running but has no models installed (run: ollama pull gemma4)."}
    model = next((m for m in models if m.startswith("gemma4")), models[0])
    try:
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=json.dumps({
                "model": model, "stream": False, "keep_alive": -1,
                "prompt": ("You are Antigravity, the AI assistant of the user's office command center on their PC. "
                           f"Answer briefly and helpfully (max 3 sentences): {prompt}")
            }).encode('utf-8'),
            headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as r:  # first call may load the model into VRAM
            reply = json.loads(r.read().decode('utf-8')).get('response', '').strip()
    except Exception as e:
        return {'ok': False, 'msg': f"Antigravity AI ({model}) error: {e}"}
    if not reply:
        return {'ok': False, 'msg': f"Antigravity AI ({model}) returned an empty answer."}
    log_event('Antigravity', f"AI: {reply[:45]}...", status="success", source="user", details=reply)
    return {'ok': True, 'msg': reply, 'model': model}


def execute_command(target, cmd_str):
    """Execute real commands, launch services, open folders, or trigger webhooks"""
    cmd = (cmd_str or '').strip()
    tgt = (target or 'all').strip()

    # 1. Quick Launch Actions
    if cmd in ('open:n8n', 'launch:n8n') or (tgt == 'n8n' and cmd == 'open'):
        subprocess.Popen(['start', 'http://localhost:5678'], shell=True)
        log_event(tgt, "Opened n8n in browser (http://localhost:5678)", status="success", source="user")
        return {'ok': True, 'msg': 'Opened n8n at http://localhost:5678'}

    if cmd in ('stop:office', 'exit:office', 'shutdown:office', 'close:office'):
        log_event(tgt, "Shutting down Office Widget and Monitor Server...", status="warning", source="user")
        def _delayed_stop():
            time.sleep(0.8)
            subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*desktop-widget.pyw*' } | Stop-Process -Force -ErrorAction SilentlyContinue"], capture_output=True)
            os._exit(0)
        import threading
        threading.Thread(target=_delayed_stop, daemon=True).start()
        return {'ok': True, 'msg': 'Shutting down Office Widget and Server...'}

    if cmd in ('start:ollama', 'run:ollama', 'launch:ollama'):
        if not os.path.exists(OLLAMA_APP):
            return {'ok': False, 'msg': f"Ollama not found at {OLLAMA_APP}"}
        subprocess.Popen([OLLAMA_APP], creationflags=0x08000000 | 0x00000200, close_fds=True)
        log_event(tgt, "Started Ollama (local AI)", status="success", source="user")
        return {'ok': True, 'msg': 'Starting Ollama… AI chat will be ready in ~30 seconds.'}

    if cmd in ('open:comfyui', 'launch:comfyui') or (tgt == 'ComfyUI' and cmd == 'open'):

        subprocess.Popen(['start', 'http://localhost:8188'], shell=True)
        log_event(tgt, "Opened ComfyUI in browser (http://localhost:8188)", status="success", source="user")
        return {'ok': True, 'msg': 'Opened ComfyUI at http://localhost:8188'}

    # Dify AI Workflow Platform
    if cmd in ('open:dify', 'launch:dify') or (tgt.lower() == 'dify' and cmd == 'open'):
        subprocess.Popen(['start', 'http://localhost:8085'], shell=True)
        log_event(tgt, "Opened Dify in browser (http://localhost:8085)", status="success", source="user")
        return {'ok': True, 'msg': 'Opened Dify at http://localhost:8085'}

    if cmd in ('start:dify', 'run:dify'):
        dify_bat = r"d:\my random work\dify\start-dify.bat"
        subprocess.Popen(['cmd.exe', '/c', dify_bat], creationflags=0x08000000)
        log_event(tgt, "Triggered Dify Docker startup on port 8085", status="info", source="user")
        return {'ok': True, 'msg': 'Starting Dify Docker stack (port 8085)...'}

    if cmd in ('stop:dify',):
        dify_stop = r"d:\my random work\dify\stop-dify.bat"
        subprocess.Popen(['cmd.exe', '/c', dify_stop], creationflags=0x08000000)
        log_event(tgt, "Stopping Dify Docker stack", status="warning", source="user")
        return {'ok': True, 'msg': 'Stopping Dify Docker stack...'}

    # OpenHands Autonomous Dev Agent
    if cmd in ('open:openhands', 'launch:openhands') or (tgt.lower() == 'openhands' and cmd == 'open'):
        subprocess.Popen(['start', 'http://localhost:3001'], shell=True)
        log_event(tgt, "Opened OpenHands in browser (http://localhost:3001)", status="success", source="user")
        return {'ok': True, 'msg': 'Opened OpenHands at http://localhost:3001'}

    if cmd in ('start:openhands', 'run:openhands'):
        oh_bat = r"d:\my random work\openhands\start-openhands.bat"
        subprocess.Popen(['cmd.exe', '/c', oh_bat], creationflags=0x08000000)
        log_event(tgt, "Triggered OpenHands container startup on port 3001", status="info", source="user")
        return {'ok': True, 'msg': 'Starting OpenHands Autonomous Dev Agent (port 3001)...'}

    if cmd in ('stop:openhands',):
        oh_stop = r"d:\my random work\openhands\stop-openhands.bat"
        subprocess.Popen(['cmd.exe', '/c', oh_stop], creationflags=0x08000000)
        log_event(tgt, "Stopping OpenHands container", status="warning", source="user")
        return {'ok': True, 'msg': 'Stopping OpenHands container...'}

    if cmd in ('open:workspace', 'open:office') or cmd == 'explore':
        subprocess.Popen(['explorer.exe', SCRIPT_DIR])
        log_event(tgt, "Opened workspace in Windows Explorer", status="success", source="user")
        return {'ok': True, 'msg': f'Opened folder: {SCRIPT_DIR}'}

    if cmd.startswith('explore '):
        path = cmd.split('explore ', 1)[1].strip()
        if os.path.exists(path):
            subprocess.Popen(['explorer.exe', path])
            log_event(tgt, f"Opened {path} in Explorer", status="success", source="user")
            return {'ok': True, 'msg': f'Opened folder: {path}'}
        return {'ok': False, 'msg': f'Path not found: {path}'}

    # 1.3 Social Media Ops: the real page schedulers supervised by social_ops
    if cmd.lower().startswith('social:') and SOCIAL_OPS is not None:
        action = cmd.lower().split(':', 1)[1].strip()
        if action in ('status', 'stats', 'pages'):
            snap = SOCIAL_OPS.snapshot()
            parts = [f"{p['short']} {p['status']} ({p['posts_today']} today)" for p in snap['pipelines'] if not p['manual']]
            return {'ok': True, 'msg': 'Social Ops: ' + ' · '.join(parts)}
        if action in ('revive', 'start'):
            started = SOCIAL_OPS.revive_all()
            return {'ok': True, 'msg': f"Social Ops: started {', '.join(started)}" if started else 'Social Ops: every page scheduler is already running'}
        if action.startswith('restart'):
            ok, msg = SOCIAL_OPS.restart(action.replace('restart', '', 1).strip())
            return {'ok': ok, 'msg': f"Social Ops: {msg}"}

    # Legacy simulated social feed (kept for the old Social Hub modal commands)
    is_social = tgt.lower() in ('growth bot', 'facebook engines', 'english pro', 'social hub', 'usa news') or cmd.lower().startswith(('social:', 'post:', 'publish:'))
    if is_social or cmd.lower() in ('generate post', 'publish post', 'social stats', 'social metrics'):
        try:
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social'))
            from social_engine import generate_social_post, publish_queued_post, load_metrics
            if 'publish' in cmd.lower():
                post, m = publish_queued_post()
                msg = f"Published Post #{post['id'] % 10000} to Social Feed (Total: {m['total_posts']})"
                return {'ok': True, 'msg': msg, 'post': post, 'metrics': m}
            elif 'metric' in cmd.lower() or 'stat' in cmd.lower():
                m = load_metrics()
                msg = f"Followers: {m['followers']:,} | Total Posts: {m['total_posts']} | Today: {m['posts_today']}"
                return {'ok': True, 'msg': msg, 'metrics': m}
            else:
                topic = cmd.replace('social:generate', '').replace('social:', '').replace('post:', '').strip()
                post, rec = generate_social_post(topic=topic or "Autonomous AI Pipelines")
                msg = f"Growth Bot: Drafted Post #{post['id'] % 10000}: \"{post['hook'][:35]}...\""
                return {'ok': True, 'msg': msg, 'post': post, 'log_id': rec['id']}
        except Exception as e:
            return {'ok': False, 'msg': f"Social Ops error: {e}"}

    if cmd.lower() in ('watchdog:scan', 'scan exports', 'check exports'):
        try:
            from folder_watchdog import scan_once
            cnt = scan_once()
            msg = f"Watchdog scan complete. {cnt} new export(s) assigned to agents."
            return {'ok': True, 'msg': msg}
        except Exception as e:
            return {'ok': False, 'msg': f"Watchdog error: {e}"}

    # 1.4 Career Operations & Autonomous Multi-Agent Pipeline
    is_career = tgt.lower() in ('cv analyst', 'job radar', 'career bot', 'career ops', 'fit scorer', 'proposal scribe', 'interview liaison') or cmd.lower().startswith(('career:', 'cv:', 'job:'))
    cmd_l = cmd.lower()

    if is_career or any(k in cmd_l for k in ('radar', 'scan jobs', 'job search', 'career:scan')):
        sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
        if any(k in cmd_l for k in ('radar', 'scan jobs', 'job search', 'career:scan')):
            try:
                from agent_job_radar import run_job_radar
                jobs, total, rec = run_job_radar()
                msg = f"Remote Job Radar: Scanned {total} jobs across 5 boards · {len(jobs)} Worldwide Remote matches found!"
                return {'ok': True, 'msg': msg, 'jobs': jobs, 'log_id': rec['id']}
            except Exception as e:
                return {'ok': False, 'msg': f"Job Radar error: {e}"}

        elif any(k in cmd_l for k in ('queue', 'prepare apps', 'prepare queue', 'career:queue')):
            try:
                from agent_proposal_scribe import prepare_queue
                apps = prepare_queue()
                msg = f"Proposal Scribe: Prepared {len(apps)} customized applications in Quick Apply Queue."
                return {'ok': True, 'msg': msg, 'applications': apps}
            except Exception as e:
                return {'ok': False, 'msg': f"Queue error: {e}"}

        elif 'dossier' in cmd_l:
            try:
                from agent_company_dossier import generate_company_dossier
                parts = cmd.split(maxsplit=1)
                comp = parts[1] if len(parts) > 1 else "Target Company"
                doss, _, rec = generate_company_dossier(comp)
                msg = f"Company Dossier: Prepared 1-page tactical prep sheet for {comp}."
                return {'ok': True, 'msg': msg, 'dossier': doss, 'log_id': rec['id']}
            except Exception as e:
                return {'ok': False, 'msg': f"Dossier error: {e}"}

        elif 'interview' in cmd_l:
            try:
                from agent_interview_liaison import process_interview_offer
                parts = cmd.split(maxsplit=1)
                comp = parts[1] if len(parts) > 1 else "Hiring Company"
                sample_msg = f"Hi, are you free Thursday at 10:00 AM EST for an intro call regarding remote engineering at {comp}?"
                rec, lrec = process_interview_offer(comp, f"talent@{comp.lower().replace(' ', '')}.com", sample_msg)
                msg = f"Interview Liaison: Processed interview slot · Converted to {rec['local_scheduled_time']}."
                return {'ok': True, 'msg': msg, 'interview': rec, 'log_id': lrec['id']}
            except Exception as e:
                return {'ok': False, 'msg': f"Interview error: {e}"}

        else:
            try:
                from agent_cv_analyst import run_cv_analyst
                prof, rec = run_cv_analyst()
                msg = f"CV Analyst: Profile updated with {len(prof.get('technical_skills', []))} skills ({prof.get('remote_preference', '100% Remote')})"
                log_event('CV Analyst', msg, status="success", source="user")
                return {'ok': True, 'msg': msg, 'profile': prof, 'log_id': rec['id']}
            except Exception as e:
                return {'ok': False, 'msg': f"CV Analyst error: {e}"}

    # 1.45 Autonomous Faceless Video Agency Commands
    is_video = tgt.lower() in ('video agency', 'geo renderer', 'story animator', 'scriptwriter', 'video factory') or cmd.lower().startswith(('video:', 'produce:', 'faceless:', 'render:video'))
    if is_video:
        sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
        cmd_v = cmd.lower()
        if any(w in cmd_v for w in ('produce', 'make', 'create', 'generate')):
            parts = cmd.split(maxsplit=1)
            topic_str = parts[1] if len(parts) > 1 and not parts[1].startswith(':') else None
            try:
                from agency_orchestrator import produce_full_video
                res = produce_full_video(topic=topic_str)
                msg = f"Video Factory: Produced 9:16 Short '{res['video']['title']}' in {res['total_duration_s']}s ({res['video']['filename']})"
                return {'ok': True, 'msg': msg, 'video': res['video']}
            except Exception as e:
                return {'ok': False, 'msg': f"Video Factory error: {e}"}

        elif 'publish' in cmd_v:
            try:
                from agent_publisher import publish_video_item
                ok, msg = publish_video_item()
                return {'ok': ok, 'msg': msg}
            except Exception as e:
                return {'ok': False, 'msg': f"Publisher error: {e}"}

        elif any(w in cmd_v for w in ('scout', 'trend', 'topics')):
            try:
                from agent_trend_scout import run_trend_scout
                topics, lrec = run_trend_scout()
                msg = f"Trend Scout: Curated {len(topics)} viral video concepts (Top: '{topics[0]['title']}')"
                return {'ok': True, 'msg': msg, 'topics': topics}
            except Exception as e:
                return {'ok': False, 'msg': f"Trend Scout error: {e}"}

    # 1.5 Antigravity AI Agent & Maintenance Commands
    is_antigravity = tgt.lower() in ('antigravity', 'antigravity agent', 'ai agent') or cmd.lower().startswith(('antigravity:', 'ask:', 'chat:', 'maint:', 'maintain:'))
    clean_prompt = cmd
    for prefix in ('antigravity:', 'ask:', 'chat:', 'maint:', 'maintain:'):
        if clean_prompt.lower().startswith(prefix):
            clean_prompt = clean_prompt[len(prefix):].strip()

    if is_antigravity or cmd.lower() in ('maintenance', 'health', 'cleanup', 'clean', 'disk', 'system'):
        lower_prompt = clean_prompt.lower()
        
        # Clean Temp / Cache
        if any(w in lower_prompt for w in ('clean', 'cleanup', 'purge', 'cache')):
            cleaned = 0
            for root, dirs, files in os.walk(SCRIPT_DIR):
                if '__pycache__' in dirs:
                    import shutil
                    p = os.path.join(root, '__pycache__')
                    try: shutil.rmtree(p); cleaned += 1
                    except Exception: pass
            msg = f"Antigravity Maintenance: Cleaned {cleaned} cache folders. Workspace optimized."
            log_event('Antigravity', msg, status="success", source="user")
            return {'ok': True, 'msg': msg}

        # Disk Space Check
        if 'disk' in lower_prompt or 'storage' in lower_prompt:
            try:
                import shutil
                du = shutil.disk_usage(SCRIPT_DIR)
                free_gb = round(du.free / (1024**3), 1)
                total_gb = round(du.total / (1024**3), 1)
                msg = f"Antigravity Disk Audit: {free_gb} GB free of {total_gb} GB on drive."
                log_event('Antigravity', msg, status="success", source="user")
                return {'ok': True, 'msg': msg}
            except Exception as e:
                return {'ok': False, 'msg': f"Disk check error: {e}"}

        # Full System Health Diagnostic
        if any(w in lower_prompt for w in ('health', 'diagnostic', 'audit', 'telemetry')):
            stats = get_stats()
            g = stats.get('gpu', {})
            gpu_str = f", GPU {g.get('util')}%" if g.get('ok') else ""
            msg = f"Antigravity Diagnostics: CPU {stats.get('cpu')}%, RAM {stats.get('ram',{}).get('pct')}%{gpu_str}, {len(stats.get('procs',{}))} procs online."
            log_event('Antigravity', msg, status="success", source="user")
            return {'ok': True, 'msg': msg}

        # Check Ports & Services
        if any(w in lower_prompt for w in ('ports', 'services', 'daemon')):
            stats = get_stats()
            active_p = [f"{v} (:{k})" for k, v in stats.get('ports', {}).items()]
            msg = f"Services Active: {', '.join(active_p) if active_p else 'Core server active (:7799)'}"
            log_event('Antigravity', msg, status="success", source="user")
            return {'ok': True, 'msg': msg}

        # Free-form question → local AI
        return ask_antigravity(clean_prompt)

    # 2. Ping / Diagnostic commands
    if cmd == 'ping:ollama' or (tgt == 'Ollama' and cmd == 'status'):
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags", headers={'User-Agent': 'ABM-Office'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get('name') for m in data.get('models', [])]
                msg = f"Ollama Active. Models: {', '.join(models[:4])}"
                log_event(tgt, msg, status="success", source="user")
                return {'ok': True, 'msg': msg}
        except Exception as e:
            msg = f"Ollama offline or unreachable ({e})"
            log_event(tgt, msg, status="warning", source="user")
            return {'ok': False, 'msg': msg}

    if cmd == 'ping:n8n' or (tgt == 'n8n Bot' and cmd == 'status'):
        try:
            req = urllib.request.Request("http://localhost:5678/healthz", headers={'User-Agent': 'ABM-Office'})
            with urllib.request.urlopen(req, timeout=3) as resp:
                msg = "n8n Webhook Engine is Healthy (:5678)"
                log_event(tgt, msg, status="success", source="user")
                return {'ok': True, 'msg': msg}
        except Exception as e:
            msg = f"n8n not reachable on :5678 ({e})"
            log_event(tgt, msg, status="warning", source="user")
            return {'ok': False, 'msg': msg}

    # 3. Direct Shell Command (Prefixed with ! or 'cmd:' or recognized standard commands)
    is_shell = cmd.startswith('!') or cmd.startswith('cmd:') or cmd.startswith('run ') or cmd in ('git status', 'nvidia-smi', 'tasklist', 'dir')
    if is_shell:
        raw_cmd = cmd
        if raw_cmd.startswith('!'): raw_cmd = raw_cmd[1:].strip()
        elif raw_cmd.startswith('cmd:'): raw_cmd = raw_cmd[4:].strip()
        elif raw_cmd.startswith('run '): raw_cmd = raw_cmd[4:].strip()

        try:
            r = subprocess.run(
                raw_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=12,
                cwd=SCRIPT_DIR,
                creationflags=0x08000000
            )
            out = (r.stdout or r.stderr or 'Done with no output').strip()
            status = 'success' if r.returncode == 0 else 'error'
            log_event(tgt, f"Exec: {raw_cmd[:35]} (exit {r.returncode})", status=status, source="user", details=out[:200])
            return {'ok': (r.returncode == 0), 'msg': out[:400], 'exit_code': r.returncode}
        except subprocess.TimeoutExpired:
            log_event(tgt, f"Command timed out: {raw_cmd[:30]}", status="error", source="user")
            return {'ok': False, 'msg': 'Command timed out after 12s'}
        except Exception as e:
            log_event(tgt, f"Error: {e}", status="error", source="user")
            return {'ok': False, 'msg': str(e)}

    # 4. Anything else is a question for the Antigravity AI
    return ask_antigravity(cmd)

SOCIAL_OPS = None


def start_social_ops():
    global SOCIAL_OPS
    sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social_ops'))
    from supervisor import SocialSupervisor
    SOCIAL_OPS = SocialSupervisor(log_event=log_event)
    threading.Thread(target=SOCIAL_OPS.run_forever, daemon=True, name='social-ops').start()
    print("[SocialOps] supervising Facebook page schedulers")


def _career_import():
    if CAREER_DIR not in sys.path:
        sys.path.insert(0, CAREER_DIR)


def autopilot_loop():
    """Runs the career pipeline on a schedule; never sends live mail without approval."""
    _career_import()
    import live_status
    ap = live_status.set_autopilot(next_run=time.time() + 90)
    print(f"[Autopilot] enabled={ap['enabled']} every {ap['interval_min']} min, first run in 90s")
    while True:
        time.sleep(15)
        try:
            ap = live_status.snapshot()['autopilot']
            now = time.time()
            if not ap.get('enabled') or now < ap.get('next_run', 0) or live_status.pipeline_is_running():
                continue
            from agent_pipeline_orchestrator import start_cycle_async
            # pipeline_begin() pushes next_run forward, so a busy or failed start just retries next tick
            if start_cycle_async(max_eval_count=5, max_applications_per_cycle=2, trigger_live_ats_sweep=True,
                                 trigger='autopilot', allow_live_mail=False):
                live_status.set_autopilot(last_run=now)
                log_event('Pipeline Orchestrator', 'Autopilot started a career pipeline cycle',
                          status='info', dept='Job Finder', source='autopilot')
        except Exception as e:
            print(f"[Autopilot] error: {e}")


class ExclusiveThreadingServer(ThreadingHTTPServer):
    """Fail fast if another monitor already owns the port (Windows SO_REUSEADDR allows duplicates)."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    def _request_allowed(self):
        # Blocks drive-by requests from other websites and DNS-rebinding; CLI tools send no Origin.
        if self.headers.get('Host', '') not in LOCAL_HOSTS:
            return False
        origin = self.headers.get('Origin')
        return origin is None or bool(LOCAL_ORIGIN_RE.match(origin))

    def _reject(self):
        self.send_response(403)
        self.end_headers()

    def send_cors_headers(self):
        origin = self.headers.get('Origin')
        if origin and LOCAL_ORIGIN_RE.match(origin):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def send_json(self, obj, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_OPTIONS(self):
        if not self._request_allowed():
            return self._reject()
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()


    def do_GET(self):
        if not self._request_allowed():
            return self._reject()
        try:
            if self.path.split('?')[0] == '/social/live':
                if SOCIAL_OPS is None:
                    self.send_json({'ok': False, 'error': 'social ops not started'}, 503)
                else:
                    self.send_json(SOCIAL_OPS.snapshot())

            elif self.path.split('?')[0] == '/career/live':
                _career_import()
                import live_status
                self.send_json(live_status.snapshot())

            elif self.path == '/stats':
                now = time.time()
                if not _cache['d']:  # only before the background refresher's first pass
                    with _cache_lock:
                        if not _cache['d']:
                            _cache['d'], _cache['t'] = get_stats(), now
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(_cache['d']).encode())

            elif self.path == '/events':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'events': EVENTS[-35:]}).encode())

            elif self.path in ('/', '/index.html'):
                try:
                    with open(WIDGET_HTML, 'rb') as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(data)
                except FileNotFoundError:
                    self.send_response(404)
                    self.end_headers()

            elif self.path.startswith('/assets/'):
                clean_rel = self.path.split('?')[0].lstrip('/').replace('/', os.sep)
                asset_path = os.path.normpath(os.path.join(SCRIPT_DIR, clean_rel))
                if asset_path.startswith(ASSETS_DIR + os.sep) and os.path.isfile(asset_path):
                    content_type = 'image/jpeg' if asset_path.lower().endswith(('.jpg', '.jpeg')) else ('image/png' if asset_path.lower().endswith('.png') else 'application/octet-stream')
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_cors_headers()
                    self.end_headers()
                    with open(asset_path, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_response(404)
                    self.end_headers()

            elif self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'uptime': round(time.time()), 'version': '2.0'}).encode())

            elif self.path == '/agent_logs':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
                try:
                    from agent_logger import get_agent_logs
                    logs = get_agent_logs()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'logs': logs}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path in ('/career_profile', '/career/profile'):
                p_file = os.path.join(SCRIPT_DIR, 'career', 'profile.json')
                data = {}
                if os.path.exists(p_file):
                    with open(p_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'profile': data}).encode())

            elif self.path == '/social/metrics':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social'))
                try:
                    from social_engine import load_metrics
                    m = load_metrics()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'metrics': m}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path == '/social/posts':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social'))
                try:
                    from social_engine import load_posts
                    posts = load_posts()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'posts': posts}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path == '/portfolio':
                port_file = os.path.join(SCRIPT_DIR, 'career', 'portfolio.html')
                if os.path.exists(port_file):
                    with open(port_file, 'r', encoding='utf-8') as f:
                        html = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(html.encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()

            elif self.path == '/health':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'status': 'running', 'port': PORT, 'time': time.time()}).encode())

            elif self.path == '/career/jobs':
                j_file = os.path.join(SCRIPT_DIR, 'career', 'jobs.json')
                jobs = []
                if os.path.exists(j_file):
                    try:
                        with open(j_file, 'r', encoding='utf-8') as f:
                            jobs = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'jobs': jobs}).encode())

            elif self.path == '/career/applications':
                a_file = os.path.join(SCRIPT_DIR, 'career', 'applications.json')
                apps = []
                if os.path.exists(a_file):
                    try:
                        with open(a_file, 'r', encoding='utf-8') as f:
                            apps = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'applications': apps}).encode())

            elif self.path == '/career/interviews':
                i_file = os.path.join(SCRIPT_DIR, 'career', 'interviews.json')
                ints = []
                if os.path.exists(i_file):
                    try:
                        with open(i_file, 'r', encoding='utf-8') as f:
                            ints = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'interviews': ints}).encode())

            elif self.path == '/career/sheets/overview':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
                try:
                    from agent_sheets_overseer import get_sheets_overview
                    res = get_sheets_overview()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'overview': res}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path == '/career/interviews/pending_debrief':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
                try:
                    from agent_interview_debrief import get_pending_interview_checkins
                    res = get_pending_interview_checkins()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'pending': res}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path.startswith('/career/resumes'):
                res_dir = os.path.join(SCRIPT_DIR, 'career', 'resumes')
                req_name = os.path.basename(self.path.split('?')[0])
                target_f = None
                if req_name == 'latest' or not req_name or req_name == 'resumes':
                    if os.path.exists(res_dir):
                        htmls = [os.path.join(res_dir, x) for x in os.listdir(res_dir) if x.endswith('.html')]
                        if htmls:
                            htmls.sort(key=os.path.getmtime, reverse=True)
                            target_f = htmls[0]
                else:
                    cand = os.path.join(res_dir, req_name)
                    if os.path.exists(cand): target_f = cand

                if target_f and os.path.exists(target_f):
                    is_pdf = target_f.lower().endswith('.pdf')
                    content_type = 'application/pdf' if is_pdf else 'text/html; charset=utf-8'
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.send_cors_headers()
                    self.end_headers()
                    with open(target_f, 'rb') as f:
                        self.wfile.write(f.read())
                else:
                    self.send_response(404)
                    self.end_headers()

            elif self.path == '/video_agency/config':
                c_file = os.path.join(SCRIPT_DIR, 'video_agency', 'config.json')
                data = {}
                if os.path.exists(c_file):
                    try:
                        with open(c_file, 'r', encoding='utf-8') as f: data = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'config': data}).encode())

            elif self.path == '/video_agency/queue':
                q_file = os.path.join(SCRIPT_DIR, 'video_agency', 'pipeline_queue.json')
                queue = []
                if os.path.exists(q_file):
                    try:
                        with open(q_file, 'r', encoding='utf-8') as f: queue = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'queue': queue}).encode())

            elif self.path == '/video_agency/topics':
                t_file = os.path.join(SCRIPT_DIR, 'video_agency', 'topics.json')
                topics = []
                if os.path.exists(t_file):
                    try:
                        with open(t_file, 'r', encoding='utf-8') as f: topics = json.load(f)
                    except Exception: pass
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'topics': topics}).encode())

            elif self.path.startswith('/video_agency/videos/'):
                v_name = os.path.basename(self.path.split('?')[0])
                v_path = os.path.join(SCRIPT_DIR, 'video_agency', 'rendered', v_name)
                if os.path.exists(v_path) and os.path.isfile(v_path):
                    sz = os.path.getsize(v_path)
                    self.send_response(200)
                    self.send_header('Content-Type', 'video/mp4')
                    self.send_header('Content-Length', str(sz))
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_cors_headers()
                    self.end_headers()
                    with open(v_path, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
                else:
                    self.send_response(404)
                    self.end_headers()

            elif self.path == '/video_agency/list':
                r_dir = os.path.join(SCRIPT_DIR, 'video_agency', 'rendered')
                vids = []
                if os.path.exists(r_dir):
                    for fn in os.listdir(r_dir):
                        if fn.endswith('.mp4'):
                            fp = os.path.join(r_dir, fn)
                            st = os.stat(fp)
                            vids.append({
                                'filename': fn,
                                'url': f'/video_agency/videos/{fn}',
                                'size_mb': round(st.st_size / (1024 * 1024), 2),
                                'mtime': st.st_mtime,
                                'time_str': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(st.st_mtime))
                            })
                    vids.sort(key=lambda x: x['mtime'], reverse=True)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'videos': vids}).encode())

            elif self.path in ('/facebook/config', '/facebook/status'):
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
                try:
                    from agent_facebook_engine import load_facebook_config, verify_page_token
                    cfg = load_facebook_config()
                    is_valid, msg = False, "Not connected"
                    if cfg.get("page_id") and cfg.get("page_access_token"):
                        is_valid, msg = verify_page_token(cfg["page_id"], cfg["page_access_token"])
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    # Mask token for security
                    masked_token = (cfg.get("page_access_token", "")[:8] + "..." + cfg.get("page_access_token", "")[-6:]) if len(cfg.get("page_access_token", "")) > 15 else ""
                    self.wfile.write(json.dumps({
                        'ok': True,
                        'page_id': cfg.get('page_id', ''),
                        'token_masked': masked_token,
                        'has_token': bool(cfg.get('page_access_token')),
                        'token_valid': is_valid,
                        'status_msg': msg,
                        'default_hashtags': cfg.get('default_hashtags', []),
                        'auto_first_comment': cfg.get('auto_first_comment', True)
                    }).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            elif self.path == '/engine/download/status':
                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
                try:
                    from local_engine_downloader import get_status
                    st_data = get_status()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': True, 'download_status': st_data}).encode())
                except Exception as e:
                    self.send_response(500)
                    self.send_header('Content-Type', 'application/json')
                    self.send_cors_headers()
                    self.end_headers()
                    self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

            else:
                self.send_response(404)
                self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass


    def do_POST(self):
        if not self._request_allowed():
            return self._reject()
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else '{}'
        
        try:
            payload = json.loads(body) if body else {}
        except Exception:
            payload = {}

        if self.path == '/event':
            # Webhook Ingestion API
            agent = payload.get('agent', 'System')
            action = payload.get('action', 'Activity logged')
            status = payload.get('status', 'info')
            dept = payload.get('dept', 'Operations')
            source = payload.get('source', 'webhook')
            details = payload.get('details', '')

            evt = log_event(agent=agent, action=action, status=status, dept=dept, source=source, details=details)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'event': evt}).encode())

        elif self.path == '/cmd':
            # Command Execution API
            target = payload.get('target', 'all')
            cmd = payload.get('cmd', '')
            res = execute_command(target, cmd)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(res).encode())

        elif self.path == '/social/generate':
            topic = payload.get('topic', 'AI Automation')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social'))
            try:
                from social_engine import generate_social_post
                post, rec = generate_social_post(topic)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'post': post, 'log_id': rec['id']}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/social/publish':
            post_id = payload.get('id')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'social'))
            try:
                from social_engine import publish_queued_post
                post, m = publish_queued_post(post_id)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'post': post, 'metrics': m}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/agent_revise':
            log_id = payload.get('id')
            feedback = payload.get('feedback', '')
            updated_output = payload.get('output')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_logger import revise_agent_work
                rev = revise_agent_work(log_id, feedback, updated_output)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'revised': rev}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/upload_cv':
            import base64
            filename = payload.get('filename', 'uploaded_cv.txt')
            filename = os.path.basename(filename) or 'uploaded_cv.txt'
            file_data_b64 = payload.get('data')
            text_content = payload.get('text')

            cv_dir = os.path.join(SCRIPT_DIR, 'career', 'cv')
            os.makedirs(cv_dir, exist_ok=True)
            save_path = os.path.join(cv_dir, filename)

            try:
                if file_data_b64:
                    raw_bytes = base64.b64decode(file_data_b64)
                    with open(save_path, 'wb') as f:
                        f.write(raw_bytes)
                elif text_content:
                    with open(save_path, 'w', encoding='utf-8') as f:
                        f.write(text_content)
                else:
                    raise ValueError("No file content or text provided")

                sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
                from agent_cv_analyst import run_cv_analyst
                prof, log_rec = run_cv_analyst()

                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({
                    'ok': True,
                    'message': f"CV '{filename}' successfully saved & analyzed by Agent 1!",
                    'profile': prof,
                    'log_id': log_rec['id']
                }).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/scan':
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_job_radar import run_job_radar
                jobs, total, rec = run_job_radar()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'jobs': jobs, 'total': total, 'log_id': rec['id']}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/prepare_queue':
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_proposal_scribe import prepare_queue
                apps = prepare_queue()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'applications': apps}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/apply':
            job_id = payload.get('job_id')
            notes = payload.get('notes', '')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_proposal_scribe import dispatch_application
                ok, msg = dispatch_application(job_id, action="apply", notes=notes)
                self.send_response(200 if ok else 400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok, 'message': msg}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/skip':
            job_id = payload.get('job_id')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_proposal_scribe import dispatch_application
                ok, msg = dispatch_application(job_id, action="skip")
                self.send_response(200 if ok else 400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok, 'message': msg}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/interviews/schedule':
            comp = payload.get('company', 'Hiring Company')
            email = payload.get('email', 'talent@company.com')
            msg_text = payload.get('message', 'Are you free Thursday at 10:00 AM EST for an intro call?')
            title = payload.get('title', 'Senior Remote Engineer')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_interview_liaison import process_interview_offer
                rec, lrec = process_interview_offer(comp, email, msg_text, title)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'interview': rec, 'log_id': lrec['id']}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/dossier':
            comp = payload.get('company', 'Target Company')
            title = payload.get('title', 'Senior Remote Engineer')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_company_dossier import generate_company_dossier
                doss, _, lrec = generate_company_dossier(comp, title)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'dossier': doss, 'log_id': lrec['id']}).encode())
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)}, 500)

        elif self.path == '/career/career_ops/evaluate':
            url = payload.get('url', '')
            jd_text = payload.get('text', '')
            title = payload.get('title', '')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_career_ops_bridge import evaluate_job
                ev = evaluate_job(url, jd_text=jd_text, title=title)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(ev).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/career_ops/scan':
            ats = payload.get('ats', 'greenhouse,lever,ashby')
            since = int(payload.get('since', 3))
            limit = int(payload.get('limit', 25))
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_career_ops_bridge import scan_ats_boards
                res = scan_ats_boards(ats_list=ats, since_days=since, limit=limit)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(res).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/career_ops/generate_pdf':
            job_id = payload.get('job_id')
            html_f = payload.get('html_file')
            out_fn = payload.get('filename')
            res_dir = os.path.join(SCRIPT_DIR, 'career', 'resumes')
            
            target_html = None
            if html_f and os.path.exists(html_f):
                target_html = html_f
            elif html_f and os.path.exists(os.path.join(res_dir, html_f)):
                target_html = os.path.join(res_dir, html_f)
            elif job_id:
                cand = os.path.join(res_dir, f"{job_id}_resume.html")
                if os.path.exists(cand): target_html = cand
            
            if not target_html:
                htmls = [os.path.join(res_dir, x) for x in os.listdir(res_dir) if x.endswith('.html')]
                if htmls:
                    htmls.sort(key=os.path.getmtime, reverse=True)
                    target_html = htmls[0]

            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_career_ops_bridge import generate_playwright_ats_pdf
                if not target_html or not os.path.exists(target_html):
                    raise ValueError("No resume HTML found to convert to PDF")
                if not out_fn:
                    out_fn = f"{os.path.splitext(os.path.basename(target_html))[0]}.pdf"
                pdf_res = generate_playwright_ats_pdf(target_html, output_filename=out_fn)
                self.send_response(200 if pdf_res.get('ok') else 500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(pdf_res).encode())
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)}, 500)

        elif self.path == '/social/ops':
            if SOCIAL_OPS is None:
                self.send_json({'ok': False, 'error': 'social ops not started'}, 503)
                return
            action = payload.get('action')
            with SOCIAL_OPS.lock:
                if action == 'autorevive':
                    SOCIAL_OPS.auto_revive = bool(payload.get('enabled', True))
                    self.send_json({'ok': True, 'auto_revive': SOCIAL_OPS.auto_revive})
                elif action == 'revive':
                    self.send_json({'ok': True, 'started': SOCIAL_OPS.revive_all()})
                elif action == 'restart':
                    ok, msg = SOCIAL_OPS.restart(str(payload.get('id', '')))
                    self.send_json({'ok': ok, 'message': msg}, 200 if ok else 400)
                else:
                    self.send_json({'ok': False, 'error': 'unknown action'}, 400)

        elif self.path == '/career/autopilot':
            _career_import()
            try:
                import live_status
                fields = {}
                if 'enabled' in payload:
                    fields['enabled'] = bool(payload['enabled'])
                if 'interval_min' in payload:
                    fields['interval_min'] = max(5, int(payload['interval_min']))
                if payload.get('run_now'):
                    fields['next_run'] = time.time()
                elif fields.get('enabled'):
                    fields['next_run'] = time.time() + fields.get('interval_min', 30) * 60
                self.send_json({'ok': True, 'autopilot': live_status.set_autopilot(**fields)})
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)}, 500)

        elif self.path == '/career/pipeline/run_cycle' and payload.get('async'):
            _career_import()
            try:
                from agent_pipeline_orchestrator import start_cycle_async
                started = start_cycle_async(
                    max_eval_count=int(payload.get('max_eval_count', 5)),
                    max_applications_per_cycle=int(payload.get('max_applications', 2)),
                    trigger_live_ats_sweep=bool(payload.get('trigger_live_ats_sweep', False)),
                    trigger=str(payload.get('trigger', 'manual'))[:20])
                if started:
                    self.send_json({'ok': True, 'started': True})
                else:
                    self.send_json({'ok': False, 'error': 'A pipeline cycle is already running'}, 409)
            except Exception as e:
                self.send_json({'ok': False, 'error': str(e)}, 500)

        elif self.path == '/career/pipeline/run_cycle':
            max_eval = int(payload.get('max_eval_count', 3))
            max_apps = int(payload.get('max_applications', 1))
            sweep = bool(payload.get('trigger_live_ats_sweep', False))
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_pipeline_orchestrator import run_full_pipeline_cycle
                res = run_full_pipeline_cycle(max_eval_count=max_eval, max_applications_per_cycle=max_apps, trigger_live_ats_sweep=sweep)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'cycle_summary': res}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/inbox/simulate_reply':
            sender = payload.get('sender', 'recruiter@company.com')
            subject = payload.get('subject', 'Interview Invitation')
            body = payload.get('body', 'Hi Ataullah, we would love to interview you! Are you free Thursday at 10am EST?')
            company = payload.get('company', 'Hiring Company')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_inbox_watcher import process_incoming_email
                res = process_incoming_email(sender=sender, subject=subject, body=body, company=company)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'result': res}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/interviews/debrief':
            comp = payload.get('company')
            outcome = payload.get('outcome', 'offer_received')
            notes = payload.get('notes', '')
            offer_amount = payload.get('offer_amount')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'career'))
            try:
                from agent_interview_debrief import record_interview_outcome
                res = record_interview_outcome(comp, outcome=outcome, notes=notes, offer_amount=offer_amount)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'result': res}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/config/mail':
            cfg_path = os.path.join(SCRIPT_DIR, 'career', 'mail_config.json')
            try:
                cur = {}
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f: cur = json.load(f)
                cur.update(payload)
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(cur, f, indent=2)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'config': cur}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/career/config/sheets':
            cfg_path = os.path.join(SCRIPT_DIR, 'career', 'sheets_config.json')
            try:
                cur = {}
                if os.path.exists(cfg_path):
                    with open(cfg_path, 'r', encoding='utf-8') as f: cur = json.load(f)
                cur.update(payload)
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(cur, f, indent=2)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'config': cur}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/video_agency/produce':
            topic = payload.get('topic')
            voice = payload.get('voice')
            style = payload.get('style')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from agency_orchestrator import produce_full_video
                res = produce_full_video(topic=topic, voice=voice, style=style)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'result': res}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/video_agency/publish':
            vid_id = payload.get('video_id')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from agent_publisher import publish_video_item
                ok, msg = publish_video_item(vid_id)
                self.send_response(200 if ok else 400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': ok, 'message': msg}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/video_agency/config':
            cfg_path = os.path.join(SCRIPT_DIR, 'video_agency', 'config.json')
            try:
                with open(cfg_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/video_agency/stickman_generate':
            topic = payload.get('topic', 'Why Airplane Windows Are Curved')
            voice = payload.get('voice', 'en-US-ChristopherNeural')
            style = payload.get('style', 'style_2a')
            pub_fb = bool(payload.get('publish_to_facebook', False))
            first_c = payload.get('first_comment')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from agent_stickman_studio import create_stickman_video
                res = create_stickman_video(
                    topic=topic,
                    voice_name=voice,
                    visual_style=style,
                    publish_to_facebook=pub_fb,
                    first_comment=first_c
                )
                self.send_response(200 if res.get('ok') else 500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(res).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/facebook/config':
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from agent_facebook_engine import load_facebook_config, save_facebook_config
                cfg = load_facebook_config()
                if 'page_id' in payload: cfg['page_id'] = str(payload['page_id']).strip()
                if 'page_access_token' in payload and payload['page_access_token']:
                    cfg['page_access_token'] = str(payload['page_access_token']).strip()
                if 'default_hashtags' in payload: cfg['default_hashtags'] = payload['default_hashtags']
                if 'auto_first_comment' in payload: cfg['auto_first_comment'] = bool(payload['auto_first_comment'])
                save_facebook_config(cfg)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'message': 'Facebook configuration updated.'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/facebook/publish':
            vid_filename = payload.get('filename')
            desc = payload.get('description', 'Viral Stickman Animation Reel')
            c_text = payload.get('first_comment')
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from agent_facebook_engine import publish_facebook_reel
                v_path = os.path.join(SCRIPT_DIR, 'video_agency', 'rendered', vid_filename) if vid_filename else payload.get('video_path')
                res = publish_facebook_reel(video_path=v_path, description=desc, first_comment_text=c_text)
                self.send_response(200 if res.get('ok') else 400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps(res).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        elif self.path == '/engine/download/start':
            import threading
            sys.path.insert(0, os.path.join(SCRIPT_DIR, 'video_agency'))
            try:
                from local_engine_downloader import run_full_download
                t = threading.Thread(target=run_full_download, daemon=True)
                t.start()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': True, 'message': '45+ GB Local Engine Downloader launched in background.'}).encode())
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({'ok': False, 'error': str(e)}).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *a):
        pass

if __name__ == '__main__':
    print(f'=== ABM Office Connected Monitor Server v2.0 ===')
    print(f'Listening on: http://localhost:{PORT}/')
    print(f'Stats API:    http://localhost:{PORT}/stats')
    print(f'Webhook API:  http://localhost:{PORT}/event')
    print(f'Command API:  http://localhost:{PORT}/cmd\n')

    try:
        s = get_stats()
        print(f"CPU: {s['cpu']}% | RAM: {s['ram']['pct']}% | GPU: {'Detected' if s['gpu']['ok'] else 'None'}")
        print(f"Monitored Apps: {', '.join(sorted(s['procs'].keys())) or 'none'}")
        print(f"Active Ports: {', '.join(f':{k} ({v})' for k,v in s['ports'].items()) or 'none'}")
    except Exception as e:
        print(f"Startup scan note: {e}")

    try:
        server = ExclusiveThreadingServer(('127.0.0.1', PORT), Handler)
    except OSError as e:
        print(f"Port {PORT} is already in use - another monitor server is running. Exiting. ({e})")
        sys.exit(0)

    threading.Thread(target=stats_refresher, daemon=True, name='stats-refresher').start()
    threading.Thread(target=autopilot_loop, daemon=True, name='career-autopilot').start()
    try:
        start_social_ops()
    except Exception as e:
        print(f"[SocialOps] failed to start: {e}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
