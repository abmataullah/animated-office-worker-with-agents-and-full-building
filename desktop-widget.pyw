"""
ABM Command Center - Desktop Widget
Launches the office widget as a desktop-embedded widget (behind other windows).
Starts the monitor server automatically if not running.
"""
import subprocess, sys, os, time, socket, threading, ctypes
from ctypes import wintypes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MONITOR_SCRIPT = os.path.join(SCRIPT_DIR, 'monitor-server.py')
PORT = 7799
URL = f'http://localhost:{PORT}/'
TITLE = 'ABM Command Center'

user32 = ctypes.windll.user32

HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_THICKFRAME = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_monitor():
    if not is_port_open(PORT):
        subprocess.Popen(
            [sys.executable, MONITOR_SCRIPT],
            creationflags=0x08000000,
            cwd=SCRIPT_DIR
        )
        for _ in range(20):
            time.sleep(0.5)
            if is_port_open(PORT):
                return True
        return False
    return True

def monitor_watchdog():
    """While the widget is open, bring the monitor server back if it ever dies (it hosts the live
    office data and supervises the page schedulers). A duplicate start exits on its own."""
    misses = 0
    while True:
        time.sleep(20)
        if is_port_open(PORT):
            misses = 0
            continue
        misses += 1
        if misses >= 2:  # down for ~40s, not just a restart in progress
            subprocess.Popen([sys.executable, MONITOR_SCRIPT], creationflags=0x08000000, cwd=SCRIPT_DIR)
            misses = 0
            time.sleep(30)


def make_desktop_widget():
    """Ensure the window has taskbar presence and is brought to front."""
    time.sleep(1)
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd:
        return

    # Ensure it appears on taskbar so the user knows it is running
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    exstyle = (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle)

    # Bring window to foreground on launch so user sees it right away
    user32.SetForegroundWindow(hwnd)
    user32.ShowWindow(hwnd, 5)  # SW_SHOW

class WidgetApi:
    def close(self):
        import webview
        try:
            if webview.windows:
                webview.windows[0].destroy()
        except Exception:
            pass
        return {'ok': True}

def main():
    import webview

    if not start_monitor():
        ctypes.windll.user32.MessageBoxW(
            0, "Could not start the monitor server.\nMake sure Python and psutil are installed.",
            TITLE, 0x10
        )
        return

    threading.Thread(target=make_desktop_widget, daemon=True).start()
    threading.Thread(target=monitor_watchdog, daemon=True).start()

    window = webview.create_window(
        TITLE,
        URL,
        width=1280,
        height=800,
        min_size=(900, 580),
        resizable=True,
        on_top=False,
        frameless=False,
        background_color='#080706',
        js_api=WidgetApi()
    )
    webview.start(gui='edgechromium')

if __name__ == '__main__':
    main()

