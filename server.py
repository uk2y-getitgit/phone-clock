"""
Phone Clock - PC 측 서버 (Windows)

- 폰 브라우저에 시계 + 단축키 화면(web/)을 제공합니다.
- 폰은 버튼의 'id'만 보내고, 실제로 무엇을 실행할지는 PC의 config.json에만 있습니다.
- USB(adb reverse) 접속은 127.0.0.1 로 들어오므로 토큰 없이 허용,
  Wi-Fi 접속은 config.json 의 token 이 일치해야만 실행됩니다.

외부 패키지 없이 파이썬 3.8+ 표준 라이브러리만 사용합니다.
"""
import ctypes
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

BASE = os.path.dirname(os.path.abspath(__file__))

# pythonw.exe(창 없이 실행)로 켜면 출력할 콘솔이 없으므로 server.log 에 기록합니다.
if sys.stdout is None or sys.stderr is None:
    _log_path = os.path.join(BASE, "server.log")
    if os.path.exists(_log_path) and os.path.getsize(_log_path) > 1_000_000:
        os.replace(_log_path, _log_path + ".old")
    sys.stdout = sys.stderr = open(_log_path, "a", encoding="utf-8", buffering=1)
    print(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} 서버 시작 (백그라운드) ----")

CONFIG_PATH = os.path.join(BASE, "config.json")
WEB_DIR = os.path.join(BASE, "web")
ICON_DIR = os.path.join(WEB_DIR, "icons")
ICON_SCRIPT = os.path.join(BASE, "tools", "extract_icons.ps1")
# 원본 경로 목록은 폰에서 보이지 않도록 web/ 밖에 둡니다
ICON_MANIFEST = os.path.join(BASE, "tools", "_icon_src.json")


# --------------------------------------------------------------------------- config
def load_config():
    if not os.path.exists(CONFIG_PATH):  # 처음 내려받았을 때: 예제 설정으로 시작
        shutil.copyfile(os.path.join(BASE, "config.example.json"), CONFIG_PATH)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    if cfg.get("allow_wifi") and not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(12)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        print("[i] Wi-Fi 접속용 토큰을 새로 만들어 config.json 에 저장했습니다.")
    return cfg


CONFIG = load_config()
CONFIG_MTIME = os.path.getmtime(CONFIG_PATH)


def current_config():
    """config.json 이 수정되면 서버 재시작 없이 다시 읽습니다."""
    global CONFIG, CONFIG_MTIME
    m = os.path.getmtime(CONFIG_PATH)
    if m != CONFIG_MTIME:
        try:
            CONFIG = load_config()
            CONFIG_MTIME = m
            print("[i] config.json 다시 읽음")
            refresh_icons(CONFIG)
        except Exception as e:  # 편집 중 잘못된 JSON 이면 기존 설정 유지
            print("[!] config.json 읽기 실패, 이전 설정 유지:", e)
    return CONFIG


# --------------------------------------------------------------------------- PC 아이콘
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_icon_lock = threading.Lock()


def icon_source(action):
    """버튼에 쓸 PC 아이콘의 원본 경로. 없으면 None (이모지 사용)."""
    if action.get("pc_icon") is False or not SAFE_ID.match(str(action.get("id", ""))):
        return None
    if action.get("icon_path"):
        return action["icon_path"]
    t = action.get("type")
    if t == "open":
        target = action.get("target", "")
        return None if re.match(r"^https?://", target, re.I) else target
    if t == "run":
        cmd = action.get("command")
        exe = cmd[0] if isinstance(cmd, list) and cmd else cmd
        if exe and not os.path.isabs(exe):
            exe = shutil.which(exe) or exe
        return exe
    return None


def icon_url(action):
    if not icon_source(action):
        return None
    png = os.path.join(ICON_DIR, action["id"] + ".png")
    if os.path.exists(png):
        return f"/icons/{action['id']}.png?v={int(os.path.getmtime(png))}"
    return None


def refresh_icons(cfg):
    """새로 추가되거나 경로가 바뀐 버튼의 아이콘만 백그라운드에서 추출합니다."""
    if os.name != "nt" or not os.path.exists(ICON_SCRIPT):
        return

    def work():
        with _icon_lock:
            try:
                with open(ICON_MANIFEST, encoding="utf-8") as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                manifest = {}
            jobs = []
            for a in cfg.get("actions", []):
                src = icon_source(a)
                if not src:
                    continue
                out = os.path.join(ICON_DIR, a["id"] + ".png")
                if manifest.get(a["id"]) != src or not os.path.exists(out):
                    jobs.append({"src": src, "out": out, "id": a["id"]})
            if not jobs:
                return
            os.makedirs(ICON_DIR, exist_ok=True)
            job_file = os.path.join(BASE, "tools", "_icon_jobs.json")
            with open(job_file, "w", encoding="utf-8") as f:
                json.dump(jobs, f, ensure_ascii=False)
            try:
                subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                "-File", ICON_SCRIPT, "-Jobs", job_file],
                               capture_output=True, timeout=120,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception as e:
                print("[!] 아이콘 추출 실패:", e)
                return
            finally:
                try:
                    os.remove(job_file)
                except OSError:
                    pass
            ok = 0
            for j in jobs:
                if os.path.exists(j["out"]) and os.path.getmtime(j["out"]) > time.time() - 180:
                    manifest[j["id"]] = j["src"]
                    ok += 1
                else:
                    print("[!] 아이콘을 가져오지 못함(이모지로 표시):", j["src"])
            with open(ICON_MANIFEST, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            print(f"[i] PC 아이콘 {ok}/{len(jobs)}개 추출")

    threading.Thread(target=work, daemon=True).start()


# --------------------------------------------------------------------------- 날씨 (Open-Meteo, API 키 불필요)
_weather_cache = {"key": None, "at": 0, "data": None}
_weather_lock = threading.Lock()


def get_weather(cfg):
    w = cfg.get("weather") or {}
    if not w.get("lat") or not w.get("lon"):
        return None
    key = (w["lat"], w["lon"])
    ttl = max(5, int(w.get("refresh_min", 10))) * 60
    with _weather_lock:
        c = _weather_cache
        if c["key"] == key and c["data"] and time.time() - c["at"] < ttl:
            return c["data"]
        q = urlencode({
            "latitude": w["lat"], "longitude": w["lon"], "timezone": "Asia/Seoul", "forecast_days": 1,
            "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,is_day",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        })
        try:
            req = Request("https://api.open-meteo.com/v1/forecast?" + q,
                          headers={"User-Agent": "phone-clock/1.0"})
            with urlopen(req, timeout=8) as r:
                j = json.load(r)
            cur, day = j["current"], j["daily"]
            data = {
                "name": w.get("name", ""),
                "temp": cur["temperature_2m"],
                "feels": cur["apparent_temperature"],
                "humidity": cur["relative_humidity_2m"],
                "code": cur["weather_code"],
                "is_day": cur.get("is_day", 1),
                "max": day["temperature_2m_max"][0],
                "min": day["temperature_2m_min"][0],
                "pop": day["precipitation_probability_max"][0],
                "updated": cur["time"][-5:],
            }
            c.update(key=key, at=time.time(), data=data)
        except Exception as e:
            print("[!] 날씨 조회 실패:", e)
            if c["key"] == key and c["data"]:  # 실패하면 직전 값 유지
                return c["data"]
            return None
        return c["data"]


# --------------------------------------------------------------------------- CPU / RAM
class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]


class _MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


_cpu_prev = None
_cpu_lock = threading.Lock()


def _ft(f):
    return (f.hi << 32) | f.lo


def get_stats():
    """CPU 사용률(직전 호출 대비)과 RAM 사용량. 외부 패키지 없이 Win32 API 사용."""
    global _cpu_prev
    k32 = ctypes.windll.kernel32
    idle, kern, user = _FILETIME(), _FILETIME(), _FILETIME()
    k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
    now = (_ft(idle), _ft(kern), _ft(user))
    with _cpu_lock:
        prev = _cpu_prev
        if prev is None:  # 첫 호출이면 잠깐 재서 계산
            time.sleep(0.25)
            prev = now
            k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
            now = (_ft(idle), _ft(kern), _ft(user))
        _cpu_prev = now
    d_idle = now[0] - prev[0]
    d_total = (now[1] - prev[1]) + (now[2] - prev[2])  # kernel 시간에 idle 포함
    cpu = 0.0 if d_total <= 0 else max(0.0, min(100.0, (1 - d_idle / d_total) * 100))

    m = _MEMSTAT()
    m.dwLength = ctypes.sizeof(_MEMSTAT)
    k32.GlobalMemoryStatusEx(ctypes.byref(m))
    total = m.ullTotalPhys / 2**30
    used = (m.ullTotalPhys - m.ullAvailPhys) / 2**30
    return {"cpu": round(cpu, 1), "ram": m.dwMemoryLoad,
            "ram_used_gb": round(used, 1), "ram_total_gb": round(total, 1)}


# --------------------------------------------------------------------------- key input
user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None

VK = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "printscreen": 0x2C, "prtsc": 0x2C, "capslock": 0x14,
    "volume_mute": 0xAD, "volume_down": 0xAE, "volume_up": 0xAF,
    "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2,
    "media_play_pause": 0xB3,
    "hangul": 0x15, "hanja": 0x19,
}
for i in range(1, 25):
    VK[f"f{i}"] = 0x6F + i
for c in "abcdefghijklmnopqrstuvwxyz0123456789":
    VK[c] = ord(c.upper())
VK.update({";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF, "`": 0xC0,
           "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE})

EXTENDED = {0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x24, 0x23, 0x21, 0x22, 0x5B}

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _send(inputs):
    arr = (INPUT * len(inputs))(*inputs)
    n = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if n != len(inputs):
        raise OSError(f"SendInput 실패 (err={ctypes.get_last_error()})")


def _key(vk, up=False):
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0)
    return INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags)))


def send_hotkey(combo):
    """'ctrl+shift+esc' 같은 조합을 누릅니다. 공백으로 구분하면 순서대로 여러 번 누릅니다."""
    for chord in combo.split():
        names = [p.strip().lower() for p in chord.split("+") if p.strip()]
        try:
            vks = [VK[n] for n in names]
        except KeyError as e:
            raise ValueError(f"알 수 없는 키: {e.args[0]}")
        _send([_key(v) for v in vks] + [_key(v, True) for v in reversed(vks)])
        time.sleep(0.03)


def type_text(text):
    """한글 포함 임의 문자열을 현재 포커스된 창에 입력합니다 (IME 상태와 무관)."""
    inputs = []
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        code = int.from_bytes(data[i:i + 2], "little")
        if code == 0x0A:  # 줄바꿈은 Enter 로
            inputs += [_key(0x0D), _key(0x0D, True)]
            continue
        for up in (False, True):
            inputs.append(INPUT(type=INPUT_KEYBOARD, u=_U(ki=KEYBDINPUT(
                wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)))))
    _send(inputs)


# --------------------------------------------------------------------------- 창 맨 앞으로
# Windows는 백그라운드 프로세스(이 서버)가 띄운 창이 앞으로 나오는 것을 막고 작업표시줄만
# 깜빡이게 합니다. 실행 직후 해당 창을 찾아 직접 맨 앞으로 올립니다.
if os.name == "nt":
    _u32 = ctypes.WinDLL("user32", use_last_error=True)
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _u32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _u32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _u32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _u32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _u32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _u32.IsWindowVisible.argtypes = [wintypes.HWND]
    _u32.IsIconic.argtypes = [wintypes.HWND]
    _u32.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
    _u32.GetWindow.restype = wintypes.HWND
    _u32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _u32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _u32.BringWindowToTop.argtypes = [wintypes.HWND]
    _u32.GetForegroundWindow.restype = wintypes.HWND
    _u32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _u32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    _u32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]


def _proc_name(pid, cache):
    if pid not in cache:
        name = ""
        h = _k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if _k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                name = os.path.basename(buf.value).lower()
            _k32.CloseHandle(h)
        cache[pid] = name
    return cache[pid]


def _top_windows():
    """보이는 최상위 창 목록 [(hwnd, 프로세스exe, 제목)] — 화면 앞쪽 창부터."""
    out, cache = [], {}

    def cb(hwnd, _):
        if _u32.IsWindowVisible(hwnd) and not _u32.GetWindow(hwnd, 4):  # GW_OWNER 없음
            n = _u32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                _u32.GetWindowTextW(hwnd, buf, n + 1)
                pid = wintypes.DWORD()
                _u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                out.append((hwnd, _proc_name(pid.value, cache), buf.value))
        return True

    _u32.EnumWindows(_WNDENUMPROC(cb), 0)
    return out


def _window_matcher(action):
    """버튼이 띄우는 창을 알아보는 함수. config 의 "window" 로 직접 지정할 수도 있습니다
    (예: "OneCommander.exe" = 프로세스 이름, 그 외 문자열 = 창 제목 일부)."""
    w = (action.get("window") or "").strip()
    if not w:
        t = action.get("type")
        if t == "run":
            cmd = action.get("command")
            w = os.path.basename((cmd[0] if isinstance(cmd, list) else str(cmd).split()[0]).strip('"'))
        elif t == "open":
            target = action.get("target", "")
            if target.lower().startswith("shell:appsfolder\\"):
                w = target.split("!")[0].split("\\")[-1].split("_")[0].split(".")[-1] + ".exe"
            elif os.path.isdir(target):  # 폴더 → 탐색기 창 제목 = 폴더 이름
                name = os.path.basename(os.path.normpath(target)).lower()
                return lambda p, title: p == "explorer.exe" and title.lower() == name
    if not w:
        return None
    w = w.lower()
    if w.endswith(".exe"):
        return lambda p, title: p == w
    return lambda p, title: w in title.lower()


def force_foreground(hwnd):
    if _u32.IsIconic(hwnd):
        _u32.ShowWindow(hwnd, 9)  # SW_RESTORE (최소화되어 있으면 복원)
    fg = _u32.GetForegroundWindow()
    me = _k32.GetCurrentThreadId()
    other = _u32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(other and other != me and _u32.AttachThreadInput(me, other, True))
    # Alt 키를 한 번 눌렀다 떼면 Windows가 '사용자가 조작 중'으로 보고 포커스 이동을 허용합니다
    _u32.keybd_event(0x12, 0, 0x1, 0)
    _u32.keybd_event(0x12, 0, 0x1 | 0x2, 0)
    _u32.BringWindowToTop(hwnd)
    ok = _u32.SetForegroundWindow(hwnd)
    if attached:
        _u32.AttachThreadInput(me, other, False)
    return bool(ok)


def bring_to_front_later(match, before, timeout=4.0):
    """실행 후 새로 생긴 창(없으면 기존 창)을 찾아 맨 앞으로 올립니다."""
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(0.25)
        wins = [w for w in _top_windows() if match(w[1], w[2])]
        new = [w for w in wins if w[0] not in before]
        fg = _u32.GetForegroundWindow()
        if any(w[0] == fg for w in wins) and (new or time.time() - start > 1.0):
            return  # 이미 맨 앞
        if new:
            force_foreground(new[0][0])
            return
        if wins and time.time() - start > 1.0:  # 이미 실행 중이던 프로그램
            force_foreground(wins[0][0])
            return


# --------------------------------------------------------------------------- actions
def run_action(action):
    t = action.get("type")
    match = _window_matcher(action) if os.name == "nt" and t in ("run", "open") else None
    if match:
        before = {w[0] for w in _top_windows()}
        _u32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY: 실행된 앱이 스스로 앞으로 나오도록 허용
    if t == "keys":
        send_hotkey(action["keys"])
    elif t == "text":
        type_text(action["text"])
    elif t == "run":
        cmd = action["command"]
        subprocess.Popen(cmd if isinstance(cmd, list) else [cmd],
                         cwd=action.get("cwd") or None,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    elif t == "open":
        os.startfile(action["target"])  # URL, 폴더, 파일 모두 기본 프로그램으로 열기
    else:
        raise ValueError(f"알 수 없는 type: {t}")
    if match:
        threading.Thread(target=bring_to_front_later, args=(match, before), daemon=True).start()


# --------------------------------------------------------------------------- http
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB_DIR, **kw)

    def log_message(self, fmt, *args):
        # 버튼 실행 기록만 남김 (2초마다 오는 CPU/RAM 요청 등은 생략)
        if "/api/run/" in str(args[0] if args else ""):
            sys.stderr.write("%s %s\n" % (self.client_address[0], fmt % args))

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # -- helpers
    def _is_local(self):
        return self.client_address[0] in ("127.0.0.1", "::1")

    def _authorized(self, cfg):
        if self._is_local():
            return True
        if not cfg.get("allow_wifi"):
            return False
        token = self.headers.get("X-Token") or \
            parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return bool(cfg.get("token")) and secrets.compare_digest(token, cfg["token"])

    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # -- routes
    def do_GET(self):
        cfg = current_config()
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            if not self._authorized(cfg):
                return self._json(401, {"ok": False, "error": "unauthorized"})
            if path == "/api/config":
                return self._json(200, {
                    "ok": True,
                    "clock": cfg.get("clock", {}),
                    "weather": bool((cfg.get("weather") or {}).get("lat")),
                    "weather_refresh_min": (cfg.get("weather") or {}).get("refresh_min", 10),
                    "pc_stats": (cfg.get("pc_stats") or {}).get("enabled", False),
                    "stats_refresh_sec": (cfg.get("pc_stats") or {}).get("refresh_sec", 2),
                    "actions": [{"id": a.get("id"), "label": a.get("label"),
                                 "icon": a.get("icon"), "img": icon_url(a)}
                                for a in cfg.get("actions", [])],
                })
            if path == "/api/ping":
                return self._json(200, {"ok": True, "time": time.time()})
            if path == "/api/weather":
                w = get_weather(cfg)
                return self._json(200 if w else 503, {"ok": bool(w), "weather": w})
            if path == "/api/stats":
                try:
                    return self._json(200, {"ok": True, **get_stats()})
                except Exception as e:
                    return self._json(500, {"ok": False, "error": str(e)})
            return self._json(404, {"ok": False})
        if not self._is_local() and not cfg.get("allow_wifi"):
            self.send_error(403)
            return
        return super().do_GET()

    def do_POST(self):
        cfg = current_config()
        path = urlparse(self.path).path
        if not path.startswith("/api/run/"):
            return self._json(404, {"ok": False})
        if not self._authorized(cfg):
            return self._json(401, {"ok": False, "error": "unauthorized"})
        aid = path[len("/api/run/"):]
        action = next((a for a in cfg.get("actions", []) if a.get("id") == aid), None)
        if not action:
            return self._json(404, {"ok": False, "error": "no such action"})
        try:
            run_action(action)
            return self._json(200, {"ok": True})
        except Exception as e:
            print("[!] 실행 실패:", aid, e)
            return self._json(500, {"ok": False, "error": str(e)})


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def find_adb():
    cand = [shutil.which("adb"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", "adb.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk", "platform-tools", "adb.exe")]
    return next((c for c in cand if c and os.path.exists(c)), None)


def adb_reverse_loop(port):
    """USB 로 연결된 폰이 있으면 20초마다 adb reverse 를 걸어 둡니다 (케이블을 다시 꽂아도 자동 복구)."""
    connected = False
    while True:
        adb = find_adb()
        if adb:
            try:
                r = subprocess.run([adb, "reverse", f"tcp:{port}", f"tcp:{port}"],
                                   capture_output=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                ok = r.returncode == 0
                if ok != connected:
                    print("[USB] 폰 연결됨 → http://localhost:%d" % port if ok else "[USB] 폰 연결 해제")
                    connected = ok
            except Exception:
                pass
        time.sleep(20)


def main():
    cfg = CONFIG
    port = int(cfg.get("port", 8765))
    host = "0.0.0.0" if cfg.get("allow_wifi") else "127.0.0.1"
    try:
        srv = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        print(f"[!] {port} 포트가 이미 사용 중입니다. 서버가 이미 실행 중인지 확인하세요.")
        return
    refresh_icons(cfg)
    threading.Thread(target=adb_reverse_loop, args=(port,), daemon=True).start()
    print("=" * 60)
    print(" Phone Clock 서버 실행 중  (종료: Ctrl+C)")
    print(f"  USB 연결  : 폰을 USB 디버깅으로 연결하면 자동 설정 → http://localhost:{port}")
    if cfg.get("allow_wifi"):
        print(f"  Wi-Fi 연결: http://{lan_ip()}:{port}/?token={cfg['token']}")
    print("=" * 60)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
