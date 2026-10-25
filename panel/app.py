
"""QQ bot stack component."""












import argparse
import collections
import functools
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import tempfile
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from flask import Flask, Response, jsonify, render_template_string, request














_LOCAL_NO_PROXY = "127.0.0.1,localhost,::1,"
for _k in ("no_proxy", "NO_PROXY"):
    _cur = os.environ.get(_k, "").strip()
    os.environ[_k] = f"{_cur},{_LOCAL_NO_PROXY}" if _cur else _LOCAL_NO_PROXY




IS_WIN = (os.name == "nt")
if IS_WIN:
    import procutil   
    import winutil    
else:
    procutil = None
    winutil = None



BOT_DATA_DIR = os.environ.get("BOT_DATA_DIR", "")


if not BOT_DATA_DIR:
    BOT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "local-data")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_DIR = os.path.join(BASE_DIR, "panel")



try:
    import proactive  
except Exception as _proactive_err:  
    proactive = None
    print(f"[面板] proactive 模块加载失败（联网找话题会不可用）："
          f"{type(_proactive_err).__name__}: {_proactive_err}")


def panel_log(msg):
    """QQ bot stack component."""










    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [面板] {msg}", flush=True)



MONITOR_DIR = os.path.join(BASE_DIR, "qq-monitor")


MONITOR_CONFIG = os.path.join(MONITOR_DIR, "config",
                              "config.json" if IS_WIN else "config.linux.json")



if IS_WIN and os.path.exists(os.path.join(MONITOR_DIR, "config", "config.win.json")):
    MONITOR_CONFIG = os.path.join(MONITOR_DIR, "config", "config.win.json")
MONITOR_RULES = os.path.join(MONITOR_DIR, "rules")

NAPCAT_HOME = os.path.join(BASE_DIR, "NapCat.Shell.Windows.OneKey", "NapCat.44498.Shell")


def _napcat_version_dir() -> str:
    """QQ bot stack component."""






    ver_root = os.path.join(NAPCAT_HOME, "versions")
    try:
        with open(os.path.join(ver_root, "config.json"), encoding="utf-8-sig") as f:
            cur = str((json.load(f) or {}).get("curVersion") or "")
        if cur and os.path.isdir(os.path.join(ver_root, cur)):
            return cur
    except Exception:
        pass
    try:
        cands = sorted(d for d in os.listdir(ver_root)
                       if os.path.isdir(os.path.join(ver_root, d)))
        if cands:
            return cands[-1]
    except OSError:
        pass
    return "9.9.33-52230"


NAPCAT_CONFIG = os.path.join(
    NAPCAT_HOME, "versions", _napcat_version_dir(), "resources", "app", "napcat", "config"
)

MAIBOT_KEY = os.environ.get("MAIBOT_HOME") or os.path.join(BASE_DIR, "bot", "MaiBotOneKey")
MAIBOT_PY = os.environ.get("BOT_PYTHON") or sys.executable
MAIBOT_DIR = os.path.join(MAIBOT_KEY, "modules", "MaiBot")
MAIBOT_CONFIG = os.path.join(MAIBOT_DIR, "config", "bot_config.toml")
MAIBOT_MODEL_CONFIG = os.path.join(MAIBOT_DIR, "config", "model_config.toml")
MAIBOT_ENV = os.path.join(MAIBOT_DIR, ".env")
ADAPTER_DIR = os.path.join(MAIBOT_KEY, "modules", "MaiBot-Napcat-Adapter")
ADAPTER_CONFIG = os.path.join(ADAPTER_DIR, "config.toml")




ADAPTER_RETIRED_MSG = ("旧适配器（MaiBot-Napcat-Adapter）已退役并删除（2026-10-01）："
                       "QQ 接入看 SnowLuma（:5099），发言群名单在「群聊开关」里改。")




SNOWLUMA_PLUGIN_CONFIG = os.path.join(MAIBOT_DIR, "plugins", "snowluma-adapter", "config.toml")


def chat_list_config():
    """QQ bot stack component."""
    if snowluma_mode() and os.path.exists(SNOWLUMA_PLUGIN_CONFIG):
        return SNOWLUMA_PLUGIN_CONFIG
    return ADAPTER_CONFIG


def chat_list_owner():
    """QQ bot stack component."""
    return "SnowLuma 适配器插件" if chat_list_config() == SNOWLUMA_PLUGIN_CONFIG else "麦麦适配器（NapCat）"
MAIBOT_LOGS = os.path.join(MAIBOT_DIR, "logs")
MONITOR_LOGS = os.path.join(MONITOR_DIR, "logs")




HMML_BACKEND_DIR = os.path.join(MAIBOT_KEY, "modules", "HMML2Backend")
HMML_PANEL_DIR = os.path.join(MAIBOT_KEY, "modules", "HMML2Panel")
def _find_node():
    """QQ bot stack component."""






    found = shutil.which("node")
    if found:
        return found
    if os.name == "nt":
        p = os.path.join(MAIBOT_KEY, "runtime", "nodejs", "node.exe")
        if os.path.exists(p):
            return p
    return os.path.join(MAIBOT_KEY, "runtime", "nodejs", "node.exe")


MAIBOT_NODE = _find_node()
HMML_URL = "http://127.0.0.1:7998"
MONITOR_BASE = "http://127.0.0.1:8080"










OLLAMA_EXE = os.path.join(os.path.expanduser("~"), "AppData", "Local",
                          "Programs", "Ollama", "ollama.exe")
OLLAMA_MODELS = os.environ.get("OLLAMA_MODELS") or os.path.join(os.path.expanduser("~"), ".ollama", "models")
OLLAMA_HOST = "127.0.0.1:11434"




_CREATE_NO_WINDOW = 0x08000000



_SPAWN_HELPER = (
    "import subprocess,sys;"
    "p=subprocess.Popen(['cmd','/c',sys.argv[1]],creationflags=0x08000000,close_fds=True);"
    "open(sys.argv[2],'w').write(str(p.pid))"
)



PANEL_LOGS = os.path.join(PANEL_DIR, "logs")
CAPTURE_MAX_BYTES = 8 * 1024 * 1024




def _default_services():
    return {
        "monitor": {"label": "监控告警系统", "cwd": MONITOR_DIR, "cmd": [sys.executable, "src/main.py", "-c", "config/config.win.json"], "port": 8080, "ready_port": 8080, "webui": "http://127.0.0.1:8080", "log": MONITOR_LOGS, "desc": "消息记录、检索与可选 AI 审核。"},
        "maibot": {"label": "麦麦核心（可选）", "cwd": MAIBOT_DIR, "cmd": [MAIBOT_PY, "bot.py"], "port": 8000, "ready_port": 8000, "webui": "http://127.0.0.1:8001", "log": MAIBOT_LOGS, "desc": "需先自行安装与配置 MaiBot，单独启停。"},
        "panel": {"label": "统一控制台", "cwd": PANEL_DIR, "cmd": [sys.executable, "app.py"], "port": 8090, "ready_port": 8090, "webui": "http://127.0.0.1:8090", "log": PANEL_LOGS, "desc": "当前网页控制台。"},
    }





START_ORDER = ["monitor", "panel"]

STOP_ORDER = ["monitor", "panel"]


SERVICES_FILE = os.path.join(PANEL_DIR, "services.json")




NAPCAT_ARGS_FILE = os.path.join(PANEL_DIR, "napcat_args.txt")







SNOWLUMA_FLAG = os.path.join(PANEL_DIR, "snowluma_mode.flag")


def snowluma_mode():
    """QQ bot stack component."""
    return os.path.exists(SNOWLUMA_FLAG)


SNOWLUMA_BLOCK_MSG = ("SnowLuma 模式：已挡下启动 NapCat/适配器 —— 它俩会跟 SnowLuma 抢 QQ 号，"
                      "或与 snowluma-adapter 双链路重复入站。确要回 NapCat："
                      "先删 panel/snowluma_mode.flag")






WIN_LAUNCHERS = {
    "maibot": "maiwin_launcher.ps1",
    "monitor": "monwin_launcher.ps1",
    "panel": "panelwin_launcher.ps1",
}


def decode_output(raw) -> str:
    """QQ bot stack component."""







    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def win_launcher_action(key, action):
    """QQ bot stack component."""
    ps1 = os.path.join(PANEL_DIR, "tools", WIN_LAUNCHERS[key])
    if not os.path.exists(ps1):
        return False, f"找不到启动器: {ps1}"
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", ps1, "-Action", action],
                            capture_output=True, timeout=300)
    except Exception as e:  
        return False, f"{action} 失败: {type(e).__name__}: {e}"
    _out = decode_output(r.stdout) + decode_output(r.stderr)
    lines = [ln.strip() for ln in _out.splitlines() if ln.strip()]
    tail = " / ".join(lines[-2:])
    return r.returncode == 0, (tail[:220] or f"{action} 已下发")




MAIBOT_DB = os.path.join(MAIBOT_DIR, "data", "MaiBot.db")

FAVORABILITY_FILE = os.path.join(MAIBOT_DIR, "data", "favorability.json")

LOCAL_STORE = os.path.join(MAIBOT_DIR, "data", "local_store.json")


CG_PROMPTS_FILE = os.path.join(MAIBOT_DIR, "data", "cg_prompts.json")


KEYWORD_FILE = os.path.join(BASE_DIR, "qq-monitor", "config", "keyword_reply.json")


QUIRKY_MAX_CHARS_DEFAULT = 0      

CG_PROVIDERS = ("pollinations", "siliconflow")


def napcat_extra_args():
    try:
        with open(NAPCAT_ARGS_FILE, encoding="utf-8") as f:
            return [ln.strip() for ln in f
                    if ln.strip() and not ln.strip().startswith("#")]
    except Exception:
        return []


def load_services():
    return _default_services()


SERVICES = load_services()
_PROCS = {}          
_LOCK = threading.Lock()
_MONITOR_CONFIG_LOCK = threading.RLock()
_START_ALL_LOCK = threading.Lock()   
_SNOWLUMA_LOCK = threading.Lock()    
_SNOWLUMA_RESULT = [None]            
_TREND_CACHE = [None, None]          


_HEALTH_DEQUE = collections.deque(maxlen=1440)
_HEALTH_LAST = [0.0]


def _health_tick(states):
    """QQ bot stack component."""
    now = time.time()
    if now - _HEALTH_LAST[0] < 60:
        return
    _HEALTH_LAST[0] = now
    _HEALTH_DEQUE.append((now, dict(states)))




_NETSTAT_ERR = [None]     
_NETSTAT_CACHE = {"t": 0.0, "data": {}}
_NETSTAT_TTL = 1.0        


def list_listening(force=False):
    """QQ bot stack component."""






    now = time.time()
    if not force and now - _NETSTAT_CACHE["t"] < _NETSTAT_TTL:
        return _NETSTAT_CACHE["data"]
    result = {}
    if not IS_WIN:
        
        try:
            out = decode_output(subprocess.run(["ss", "-ltnpH"], capture_output=True,
            timeout=20).stdout)
        except Exception as e:
            _NETSTAT_ERR[0] = repr(e)
            return _NETSTAT_CACHE["data"] if _NETSTAT_CACHE["data"] else result
        _NETSTAT_ERR[0] = None
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                port = int(parts[3].rsplit(":", 1)[-1])
            except ValueError:
                continue
            m = re.search(r"pid=(\d+)", line)
            result[port] = int(m.group(1)) if m else 0
        _NETSTAT_CACHE["t"] = now
        _NETSTAT_CACHE["data"] = result
        return result
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=20,
                             creationflags=_CREATE_NO_WINDOW).stdout
    except Exception as e:
        _NETSTAT_ERR[0] = repr(e)
        return _NETSTAT_CACHE["data"] if _NETSTAT_CACHE["data"] else result
    _NETSTAT_ERR[0] = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING":
            try:
                port = int(parts[1].rsplit(":", 1)[-1])
                result[port] = int(parts[4])
            except ValueError:
                continue
    _NETSTAT_CACHE["t"] = now
    _NETSTAT_CACHE["data"] = result
    return result


def port_open(port, host="127.0.0.1", timeout=0.6, force=False):
    """QQ bot stack component."""














    if not port:
        return False
    port = int(port)
    if _NETSTAT_ERR[0] is None:
        if force:
            list_listening(force=True)
        if port in list_listening():
            return True
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def pid_on_port(port):
    """QQ bot stack component."""
    if not port:
        return None
    return list_listening().get(int(port))


def pid_alive(pid):
    if not pid:
        return False
    if not IS_WIN:
        return os.path.isdir(f"/proc/{int(pid)}")
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=10,
                             creationflags=_CREATE_NO_WINDOW).stdout
        return str(pid) in out
    except Exception:
        return False


def kill_tree(pid):
    return False


def napcat_webui_url():
    """QQ bot stack component."""



    cfg_file = (os.path.join(BOT_DATA_DIR, "napcat", "config", "webui.json")
                if not IS_WIN else os.path.join(NAPCAT_CONFIG, "webui.json"))
    try:
        with open(cfg_file, encoding="utf-8") as f:
            tok = json.load(f).get("token", "")
        return f"http://127.0.0.1:6099/webui?token={tok}" if tok else "http://127.0.0.1:6099/webui"
    except Exception:
        return "http://127.0.0.1:6099/webui"


def service_status(key, force=False):
    svc = SERVICES[key]
    port = svc.get("port")
    proc = _PROCS.get(key)
    pid = None
    if proc and proc.poll() is None:
        pid = proc.pid
    if port and force:
        list_listening(force=True)
    if pid is None:
        
        pid = pid_on_port(port)
    running = port_open(port) or (pid is not None and pid_alive(pid))
    return {
        "key": key,
        "label": svc["label"],
        "desc": svc.get("desc", ""),
        "port": port,
        "webui": napcat_webui_url() if key == "napcat" else svc.get("webui", ""),
        "webui_label": "打开 NapCat WebUI（扫码登录）" if key == "napcat" else "打开详细面板",
        "running": bool(running),
        "pid": pid if running else None,
        "managed": proc is not None and proc.poll() is None,
        
        
        
        "auto": bool(svc.get("auto", True)),
    }


def wait_for_port(port, timeout=90, interval=1.5):
    """QQ bot stack component."""
    if not port:
        return True
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(port, force=True):
            return True
        time.sleep(interval)
    return port_open(port, force=True)






LINUX_UNITS = {"maibot": "qq-maibot", "adapter": "qq-adapter",
               "monitor": "qq-monitor", "panel": "qq-panel"}


def _run_lines(cmd, lines=200, timeout=60):
    """QQ bot stack component."""
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        out = decode_output(r.stdout) + decode_output(r.stderr)
        
        
        
        out = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", out)
        return [ln for ln in out.splitlines() if ln.strip()][-lines:]
    except Exception as e:
        return [f"(执行 {' '.join(str(c) for c in cmd[:3])}… 失败: {type(e).__name__}: {e})"]


def linux_service_action(key, action):
    """QQ bot stack component."""
    
    
    compose = os.path.join(BOT_DATA_DIR, "deploy", "linux", "docker-compose.yml")
    try:
        if key == "napcat":
            verb = {"start": ["up", "-d", "napcat"], "stop": ["stop", "napcat"],
                    "restart": ["restart", "napcat"]}.get(action, ["up", "-d", "napcat"])
            r = subprocess.run(["docker", "compose", "-f", compose] + verb,
            capture_output=True, timeout=300)
        elif key in LINUX_UNITS:
            r = subprocess.run(["systemctl", action, LINUX_UNITS[key]],
            capture_output=True, timeout=120)
        else:
            return False, f"Linux 模式下 {key} 没有对应的 systemd 单元"
    except Exception as e:
        return False, f"{action} 失败: {type(e).__name__}: {e}"
    tail = " / ".join([ln for ln in (decode_output(r.stdout) + decode_output(r.stderr)).splitlines() if ln.strip()][-2:])
    return r.returncode == 0, (tail[:180] or f"{action} 已下发")


def start_service(key, detached=True):
    if key not in WIN_LAUNCHERS:
        return False, "公开版仅管理本仓库 monitor/panel 和可选 MaiBot。"
    return win_launcher_action(key, "start")


def kill_napcat_group():
    return False


def kill_stale_launcher(key, min_age_sec=15):
    return 0


def stop_service(key):
    if key not in WIN_LAUNCHERS:
        return False, "公开版仅管理本仓库 monitor/panel 和可选 MaiBot。"
    return win_launcher_action(key, "stop")





def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def uses_crlf(path):
    """QQ bot stack component."""




    try:
        with open(path, "rb") as f:
            return b"\r\n" in f.read()
    except OSError:
        return False


def save_text_if_changed(path, original, new_text):
    """QQ bot stack component."""




    if new_text == original:
        return False
    write_text(path, new_text.replace("\n", "\r\n") if uses_crlf(path) else new_text)
    return True


def _section_re(section):
    
    return re.compile(rf"^\[\[?{re.escape(section)}\]\]?[ \t]*(?:#.*)?$", re.M)






_SECTION_LINE = re.compile(r"^\[\[?([^\[\]\r\n]+)\]\]?[ \t]*(?:#.*)?$", re.M)
_VALUE_HEAD = None


def _multiline_spans(text):
    """QQ bot stack component."""




    spans = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            i = n if j == -1 else j + 1
            continue
        if text.startswith('"""', i) or text.startswith("'''", i):
            delim = text[i:i + 3]
            j = i + 3
            while True:
                k = text.find(delim, j)
                if k == -1:
                    spans.append((i, n))
                    return spans
                if delim == '"""':
                    b = k - 1
                    while b >= i and text[b] == "\\":
                        b -= 1
                    if (k - 1 - b) % 2 == 1:      
                        j = k + 1
                        continue
                spans.append((i, k + 3))
                i = k + 3
                break
            continue
        if c in ('"', "'"):                         
            j = i + 1
            while j < n:
                if c == '"' and text[j] == "\\":
                    j += 2
                    continue
                if text[j] == c or text[j] == "\n":
                    break
                j += 1
            i = j + 1
            continue
        i += 1
    return spans


def _inside(spans, pos):
    return any(a < pos < b for a, b in spans)


def _section_span(text, section):
    """QQ bot stack component."""
    if not section:
        return 0, len(text)
    spans = _multiline_spans(text)
    heads = [m for m in _SECTION_LINE.finditer(text) if not _inside(spans, m.start())]
    for idx, m in enumerate(heads):
        if m.group(1).strip() == section:
            start = m.end()
            return start, (heads[idx + 1].start() if idx + 1 < len(heads) else len(text))
    return None, None


def _value_span(text, key, section=None):
    """QQ bot stack component."""



    s0, s1 = _section_span(text, section)
    if s0 is None:
        return None
    spans = _multiline_spans(text)
    pat = re.compile(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*", re.M)
    for m in pat.finditer(text, s0, s1):
        if _inside(spans, m.start()):
            continue
        vs = m.end()
        for delim in ('"""', "'''"):
            if text.startswith(delim, vs):
                for a, b in spans:
                    if a == vs:
                        return vs, b
                return None
        
        eol = text.find("\n", vs)
        if eol == -1:
            eol = len(text)
        line = text[vs:eol]
        cut, in_str, i = len(line), None, 0
        while i < len(line):
            c = line[i]
            if in_str:
                if in_str == '"' and c == "\\":
                    i += 2
                    continue
                if c == in_str:
                    in_str = None
            elif c in ('"', "'"):
                in_str = c
            elif c == "#":
                cut = i
                break
            i += 1
        return vs, vs + len(line[:cut].rstrip())
    return None


def toml_get(text, key, section=None):
    """QQ bot stack component."""
    sp = _value_span(text, key, section)
    if sp is None:
        return None
    return text[sp[0]:sp[1]].strip() or None


def toml_set(text, key, value_literal, section=None):
    """QQ bot stack component."""




    sp = _value_span(text, key, section)
    if sp is None:
        return text, False
    old_raw = text[sp[0]:sp[1]]
    if old_raw == value_literal:
        return text, True
    
    
    try:
        if parse_literal(old_raw) == parse_literal(value_literal):
            return text, True
    except Exception:
        pass
    return text[:sp[0]] + value_literal + text[sp[1]:], True


_TOML_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "b": "\b", "f": "\f"}


def _unescape_toml_basic(body):
    """QQ bot stack component."""




    return re.sub(r"\\(.)", lambda m: _TOML_ESCAPES.get(m.group(1), m.group(1)), body)


def _strip_ml_leading_newline(body):
    """QQ bot stack component."""
    if body.startswith("\r\n"):
        return body[2:]
    if body.startswith("\n"):
        return body[1:]
    return body


def parse_literal(raw):
    """QQ bot stack component."""
    if raw is None:
        return None
    raw = raw.strip()
    
    if raw.startswith('"""') and raw.endswith('"""') and len(raw) >= 6:
        body = _strip_ml_leading_newline(raw[3:-3])
        body = re.sub(r"\\\r?\n[ \t]*", "", body)     
        return _unescape_toml_basic(body)
    if raw.startswith("'''") and raw.endswith("'''") and len(raw) >= 6:
        return _strip_ml_leading_newline(raw[3:-3])
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return _unescape_toml_basic(raw[1:-1])
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        
        return raw[1:-1]
    if raw.lower() in ("true", "false"):
        return raw.lower() == "true"
    if raw.startswith("[") or raw.startswith("{"):
        try:
            import tomllib
            return tomllib.loads(f"x = {raw}")["x"]
        except Exception:
            return raw
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def to_literal(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(to_literal(v) for v in value) + "]"
    s = str(value)
    if "\n" in s or "\r" in s:
        
        
        
        
        body = s.replace("\r\n", "\n").replace("\r", "\n")
        body = body.replace("\\", "\\\\").replace('"""', '\\"""')
        return '"""' + body + '"""'
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'




MAIBOT_FIELDS = [
    ("bot", "qq_account", "机器人 QQ 号", "str"),
    ("bot", "nickname", "机器人昵称", "str"),
    ("bot", "alias_names", "别名列表（数组）", "list"),
    
    
    
    
    
    ("personality", "personality", "人格设定", "text"),
    ("personality", "behavior_style", "行为准则（决定何时插话、何时安静）", "text"),
    ("personality", "reply_style", "说话风格", "text"),
    ("chat", "max_context_size", "上下文条数", "int"),
    ("chat.reply_timing", "talk_value", "群聊主动发言意愿 (0~1)", "float"),
    ("chat.reply_timing", "private_talk_value", "私聊主动发言意愿 (0~1)", "float"),
    ("chat.reply_timing", "mentioned_bot_reply", "@ 时必定回复", "bool"),
    ("emoji", "emoji_send_num", "单次可用表情包数量", "int"),
    ("emoji", "steal_emoji", "偷表情包", "bool"),
    ("voice", "enable_asr", "语音识别", "bool"),
]


def maibot_config_get():
    text = read_text(MAIBOT_CONFIG)
    out = []
    for section, key, label, kind in MAIBOT_FIELDS:
        raw = toml_get(text, key, section)
        out.append({
            "section": section, "key": key, "label": label, "kind": kind,
            "value": parse_literal(raw), "raw": raw,
        })
    return out


def maibot_config_set(items):
    original = read_text(MAIBOT_CONFIG)
    text = original
    changed, failed = [], []
    for it in items:
        section, key, kind = it.get("section"), it.get("key"), it.get("kind", "str")
        if not key:
            continue
        value = it.get("value")
        if kind == "list" and isinstance(value, str):
            value = [v.strip() for v in re.split(r"[,，]", value) if v.strip()]
        if kind in ("int",):
            try:
                value = int(float(value))
            except (TypeError, ValueError):
                failed.append(key)
                continue
        if kind in ("float",):
            try:
                value = float(value)
            except (TypeError, ValueError):
                failed.append(key)
                continue
        if kind == "bool":
            value = bool(value)
        text, ok = toml_set(text, key, to_literal(value), section)
        (changed if ok else failed).append(key)
    wrote, err = write_toml_checked(MAIBOT_CONFIG, original, text)
    if err:
        return [], failed, err
    return changed, failed, ""


ADAPTER_FIELDS = [
    ("chat", "group_list_type", "群聊名单模式 (whitelist/blacklist)", "str"),
    ("chat", "group_list", "群聊名单（数组）", "list"),
    ("chat", "private_list_type", "私聊名单模式", "str"),
    ("chat", "private_list", "私聊名单（数组）", "list"),
    ("chat", "ban_user_id", "全局禁止名单（数组）", "list"),
    ("chat", "enable_poke", "启用戳一戳", "bool"),
    ("chat", "ban_qq_bot", "屏蔽 QQ 官方机器人", "bool"),
    ("voice", "use_tts", "语音回复 TTS", "bool"),
    ("napcat_server", "host", "NapCat 监听地址", "str"),
    ("napcat_server", "port", "NapCat 端口", "int"),
    ("maibot_server", "host", "麦麦地址", "str"),
    ("maibot_server", "port", "麦麦端口", "int"),
]


def adapter_config_get():
    
    
    if not os.path.isfile(ADAPTER_CONFIG):
        return []
    text = read_text(ADAPTER_CONFIG)
    out = []
    for section, key, label, kind in ADAPTER_FIELDS:
        raw = toml_get(text, key, section)
        out.append({"section": section, "key": key, "label": label, "kind": kind,
                    "value": parse_literal(raw), "raw": raw})
    return out


def adapter_config_set(items):
    
    if not os.path.isfile(ADAPTER_CONFIG):
        return [], [str((it or {}).get("key") or "") for it in (items or [])], ADAPTER_RETIRED_MSG
    original = read_text(ADAPTER_CONFIG)
    text = original
    changed, failed = [], []
    for it in items:
        section, key, kind = it.get("section"), it.get("key"), it.get("kind", "str")
        value = it.get("value")
        if kind == "list" and isinstance(value, str):
            value = [v.strip() for v in re.split(r"[,，]", value) if v.strip()]
        if kind == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                failed.append(key)
                continue
        if kind == "bool":
            value = bool(value)
        text, ok = toml_set(text, key, to_literal(value), section)
        (changed if ok else failed).append(key)
    wrote, err = write_toml_checked(ADAPTER_CONFIG, original, text)
    if err:
        return [], failed, err
    return changed, failed, ""







MODEL_TASK_LABELS = {
    "qa": "问答专用（问答 问题内容）",
    "replyer": "首要回复模型（也用于表达方式学习）",
    "planner": "决策模型（决定什么时候该回复）",
    "utils": "通用组件模型（表情包/取名/关系/情绪等，必须配）",
    "utils_small": "轻量组件模型（调用量大，建议用小而快的）",
    "tool_use": "工具调用模型（必须支持 function calling）",
    "vlm": "图像识别模型",
    "voice": "语音识别模型",
    "embedding": "嵌入模型（记忆检索必须）",
    "lpmm_entity_extract": "LPMM 实体提取模型",
    "lpmm_rdf_build": "LPMM 关系构建模型",
    "lpmm_qa": "LPMM 问答模型",
}

PROVIDER_FIELDS = ["name", "base_url", "api_key", "client_type",
                   "max_retry", "timeout", "retry_interval"]
MODEL_FIELDS = ["model_identifier", "name", "api_provider", "price_in", "price_out"]


def _tomlkit():
    try:
        import tomlkit
        return tomlkit
    except ImportError as e:
        raise RuntimeError(
            "缺少 tomlkit，无法编辑 API 管理配置。请执行：python -m pip install tomlkit"
        ) from e


def _load_model_doc():
    return _tomlkit().parse(read_text(MAIBOT_MODEL_CONFIG))


def _as_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _as_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def model_config_get():
    doc = _load_model_doc()
    providers = []
    for p in doc.get("api_providers", []):
        d = {k: str(p.get(k, "") or "") for k in ("name", "base_url", "api_key", "client_type")}
        d["max_retry"] = _as_int(p.get("max_retry", 2), 2)
        d["timeout"] = _as_int(p.get("timeout", 30), 30)
        d["retry_interval"] = _as_int(p.get("retry_interval", 10), 10)
        providers.append(d)
    models = []
    for m in doc.get("models", []):
        d = {k: str(m.get(k, "") or "") for k in ("model_identifier", "name", "api_provider")}
        d["price_in"] = _as_float(m.get("price_in", 0))
        d["price_out"] = _as_float(m.get("price_out", 0))
        models.append(d)
    tasks = []
    tcfg = doc.get("model_task_config", {})
    for name in tcfg:
        t = tcfg[name]
        tasks.append({
            "name": name,
            "label": MODEL_TASK_LABELS.get(name, name),
            "model_list": [str(x) for x in t.get("model_list", [])],
            "temperature": (_as_float(t["temperature"]) if "temperature" in t else None),
            "max_tokens": (_as_int(t["max_tokens"]) if "max_tokens" in t else None),
        })
    
    order = list(MODEL_TASK_LABELS)
    tasks.sort(key=lambda t: order.index(t["name"]) if t["name"] in order else 999)
    return {"providers": providers, "models": models, "tasks": tasks,
            "path": MAIBOT_MODEL_CONFIG, "model_names": [m["name"] for m in models],
            "warnings": _model_config_warnings(providers, models, tasks)}


def _model_config_warnings(providers, models, tasks):
    """QQ bot stack component."""




    warn = []
    used = {str(m.get("api_provider", "")) for m in models}
    
    by_base = {}
    for p in providers:
        if p.get("base_url"):
            by_base.setdefault(p["base_url"], []).append(p["name"])
    for base, names in by_base.items():
        if len(names) > 1:
            warn.append({
                "level": "warn",
                "text": f"有 {len(names)} 个提供商指向同一个地址（{'、'.join(names)}）：{base}。"
                        f"多半是重复添加，建议只留一个。",
            })
    
    idle = [p["name"] for p in providers if p["name"] not in used]
    if idle:
        warn.append({"level": "info",
                     "text": f"这些提供商没有任何模型在用：{'、'.join(idle)}。"})
    
    ph = [p["name"] for p in providers
          if p["name"] in used and ("your-" in p.get("api_key", "").lower()
                                    or not p.get("api_key", "").strip())]
    if ph:
        warn.append({"level": "error",
                     "text": f"这些提供商的 API Key 还是占位符/空的：{'、'.join(ph)}，被模型引用时会调用失败。"})
    
    known = {p["name"] for p in providers}
    broken = [m["name"] for m in models if str(m.get("api_provider", "")) not in known]
    if broken:
        warn.append({"level": "error",
                     "text": f"这些模型指向了不存在的提供商：{'、'.join(broken)}，麦麦会启动失败。"})
    
    names = {m["name"] for m in models}
    for t in tasks:
        bad = [x for x in t["model_list"] if x not in names]
        if bad:
            warn.append({"level": "error",
                         "text": f"角色「{t.get('label') or t['name']}」引用了不存在的模型：{'、'.join(bad)}。"})
    return warn


def _provider_index(doc, name):
    for i, p in enumerate(doc.get("api_providers", [])):
        if str(p.get("name", "")) == name:
            return i
    return None


def model_provider_save(data):
    """QQ bot stack component."""




    tk = _tomlkit()
    doc = _load_model_doc()
    name = (data.get("name") or "").strip()
    if not name:
        return False, "提供商名称不能为空"
    old_name = (data.get("old_name") or "").strip()
    idx = _provider_index(doc, old_name) if old_name else None
    if idx is None:
        idx = _provider_index(doc, name)
    
    
    dup = _provider_index(doc, name)
    if dup is not None and dup != idx:
        return False, (f"已经有一个叫「{name}」的提供商了（第 {dup + 1} 个），换个名字吧。"
                       f"两个同名提供商没法区分，改配置时会改错那一个。")
    fields = {
        "name": name,
        "base_url": (data.get("base_url") or "").strip(),
        "api_key": (data.get("api_key") or "").strip(),
        "client_type": (data.get("client_type") or "openai").strip(),
        "max_retry": _as_int(data.get("max_retry"), 2),
        "timeout": _as_int(data.get("timeout"), 30),
        "retry_interval": _as_int(data.get("retry_interval"), 10),
    }
    if idx is None:
        if "api_providers" not in doc:
            doc["api_providers"] = tk.aot()
        doc["api_providers"].append(fields)
        note = f"已新增提供商 {name}"
    else:
        prov = doc["api_providers"][idx]
        for k, v in fields.items():
            prov[k] = v
        note = f"已更新提供商 {name}"
        if old_name and old_name != name:
            n = 0
            for m in doc.get("models", []):
                if str(m.get("api_provider", "")) == old_name:
                    m["api_provider"] = name
                    n += 1
            if n:
                note += f"，并同步更新了 {n} 个模型的归属"
    save_text_if_changed(MAIBOT_MODEL_CONFIG, read_text(MAIBOT_MODEL_CONFIG), tk.dumps(doc))
    return True, note


def model_provider_delete(name):
    tk = _tomlkit()
    doc = _load_model_doc()
    idx = _provider_index(doc, name)
    if idx is None:
        return False, f"找不到提供商 {name}"
    used = [str(m.get("name", "")) for m in doc.get("models", [])
            if str(m.get("api_provider", "")) == name]
    if used:
        return False, (f"提供商 {name} 还被这些模型引用，不能删：{'、'.join(used)}。"
                       f"请先删掉或改归属这些模型。")
    doc["api_providers"].pop(idx)
    save_text_if_changed(MAIBOT_MODEL_CONFIG, read_text(MAIBOT_MODEL_CONFIG), tk.dumps(doc))
    return True, f"已删除提供商 {name}"


def _model_index(doc, name):
    for i, m in enumerate(doc.get("models", [])):
        if str(m.get("name", "")) == name:
            return i
    return None


def model_save(data):
    tk = _tomlkit()
    doc = _load_model_doc()
    name = (data.get("name") or "").strip()
    if not name:
        return False, "模型名称不能为空"
    provider = (data.get("api_provider") or "").strip()
    if provider and _provider_index(doc, provider) is None:
        return False, f"提供商 {provider} 不存在，请先在「API 提供商」里添加"
    old_name = (data.get("old_name") or "").strip()
    idx = _model_index(doc, old_name) if old_name else None
    if idx is None:
        idx = _model_index(doc, name)
    
    dup = _model_index(doc, name)
    if dup is not None and dup != idx:
        return False, f"已经有一个叫「{name}」的模型了，换个名字吧"
    fields = {
        "model_identifier": (data.get("model_identifier") or name).strip(),
        "name": name,
        "api_provider": provider,
        "price_in": _as_float(data.get("price_in"), 0),
        "price_out": _as_float(data.get("price_out"), 0),
    }
    if idx is None:
        if "models" not in doc:
            doc["models"] = tk.aot()
        doc["models"].append(fields)
        note = f"已新增模型 {name}"
    else:
        mod = doc["models"][idx]
        for k, v in fields.items():
            mod[k] = v
        note = f"已更新模型 {name}"
        if old_name and old_name != name:
            n = 0
            for tname in doc.get("model_task_config", {}):
                t = doc["model_task_config"][tname]
                if "model_list" in t and old_name in [str(x) for x in t["model_list"]]:
                    t["model_list"] = [name if str(x) == old_name else str(x)
                                       for x in t["model_list"]]
                    n += 1
            if n:
                note += f"，并同步更新了 {n} 个角色的模型列表"
    save_text_if_changed(MAIBOT_MODEL_CONFIG, read_text(MAIBOT_MODEL_CONFIG), tk.dumps(doc))
    return True, note


def model_delete(name):
    tk = _tomlkit()
    doc = _load_model_doc()
    idx = _model_index(doc, name)
    if idx is None:
        return False, f"找不到模型 {name}"
    used = [tname for tname in doc.get("model_task_config", {})
            if name in [str(x) for x in doc["model_task_config"][tname].get("model_list", [])]]
    if used:
        labels = [MODEL_TASK_LABELS.get(t, t) for t in used]
        return False, (f"模型 {name} 还被这些角色使用，不能删：{'、'.join(labels)}。"
                       f"请先把这些角色的模型换掉。")
    doc["models"].pop(idx)
    save_text_if_changed(MAIBOT_MODEL_CONFIG, read_text(MAIBOT_MODEL_CONFIG), tk.dumps(doc))
    return True, f"已删除模型 {name}"


def model_task_save(data):
    """QQ bot stack component."""
    tk = _tomlkit()
    doc = _load_model_doc()
    name = (data.get("name") or "").strip()
    tcfg = doc.get("model_task_config")
    if tcfg is None or name not in tcfg:
        return False, f"配置里没有角色 {name}"
    names = [str(x) for x in (data.get("model_list") or []) if str(x).strip()]
    known = {str(m.get("name", "")) for m in doc.get("models", [])}
    unknown = [x for x in names if x not in known]
    if unknown:
        return False, f"这些模型不在模型列表里：{'、'.join(unknown)}"
    if not names and name not in {"learner", "expression_use", "mid_memory", "emoji"}:
        return False, "至少要给这个角色选一个模型"
    t = tcfg[name]
    t["model_list"] = names
    if data.get("temperature") not in (None, ""):
        t["temperature"] = _as_float(data.get("temperature"))
    if data.get("max_tokens") not in (None, ""):
        t["max_tokens"] = _as_int(data.get("max_tokens"))
    note = f"{MODEL_TASK_LABELS.get(name, name)} → {'、'.join(names) if names else '继承默认模型'}"
    save_text_if_changed(MAIBOT_MODEL_CONFIG, read_text(MAIBOT_MODEL_CONFIG), tk.dumps(doc))
    return True, f"已更新 {note}"








def _napcat_http(path, payload=None, timeout=30):
    """QQ bot stack component."""
    base = http_url = None
    tok = ""
    try:
        with open(MONITOR_CONFIG, encoding="utf-8") as f:
            nap = (json.load(f) or {}).get("napcat", {})
        http_url = nap.get("http_url", "http://127.0.0.1:3000")
        tok = (nap.get("token") or "").strip()
    except Exception:
        http_url = "http://127.0.0.1:3000"
    url = http_url.rstrip("/") + path
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")   
    body = json.dumps(payload or {}).encode("utf-8")
    with urllib.request.urlopen(req, body, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def napcat_groups():
    """QQ bot stack component."""
    try:
        d = _napcat_http("/get_group_list")
        if str(d.get("status")) not in ("ok", "200"):
            return None
        out = []
        for g in d.get("data") or []:
            try:
                out.append({"group_id": int(g.get("group_id")),
                            "group_name": g.get("group_name") or "",
                            "member_count": int(g.get("member_count") or 0)})
            except (TypeError, ValueError):
                continue
        return sorted(out, key=lambda x: x["group_id"])
    except Exception:
        return None


def adapter_group_mode():
    """QQ bot stack component."""




    return (toml_get(read_text(chat_list_config()), "group_list_type", "chat") or "blacklist").strip('"')


def adapter_group_list():
    raw = toml_get(read_text(chat_list_config()), "group_list", "chat")
    v = parse_literal(raw)
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            continue
    return out


def monitor_group_list():
    try:
        with open(MONITOR_CONFIG, encoding="utf-8") as f:
            return [int(x) for x in (json.load(f).get("napcat", {}) or {}).get("monitor_groups", [])]
    except Exception:
        return []


def group_switches_get():
    monitored = set(monitor_group_list())
    mode = adapter_group_mode()
    listed = set(adapter_group_list())

    def speaks(gid):
        return (gid not in listed) if mode != "whitelist" else (gid in listed)

    groups = napcat_groups()
    napcat_ok = groups is not None
    if not napcat_ok:
        
        ids = sorted(monitored | listed)
        groups = [{"group_id": g, "group_name": "", "member_count": 0} for g in ids]

    
    known = {g["group_id"] for g in groups}
    for gid in sorted((monitored | listed) - known):
        groups.append({"group_id": gid, "group_name": "（不在机器人群列表里）", "member_count": 0})

    out = []
    for g in groups:
        gid = g["group_id"]
        out.append({**g, "monitored": gid in monitored, "speak": speaks(gid)})
    return {"groups": out, "mode": mode, "napcat_ok": napcat_ok,
            "monitor_path": MONITOR_CONFIG, "adapter_path": ADAPTER_CONFIG,
            
            
            "chat_path": chat_list_config(), "chat_owner": chat_list_owner()}









TALK_VALUE_FALLBACK = 0.2      


def talk_strength_get():
    """QQ bot stack component."""
    out = {"default": TALK_VALUE_FALLBACK, "enable": True, "by_group": {}, "error": ""}
    try:
        tk = _tomlkit()
        doc = tk.parse(read_text(MAIBOT_CONFIG))
        rt = (doc.get("chat") or {}).get("reply_timing") or {}
        try:
            out["default"] = float(rt.get("talk_value") or TALK_VALUE_FALLBACK)
        except (TypeError, ValueError):
            pass
        out["enable"] = bool(rt.get("enable_talk_value_rules", True))
        for rule in (rt.get("talk_value_rules") or []):
            try:
                if str(rule.get("rule_type")) != "group":
                    continue
                item = str(rule.get("item_id") or "").strip()
                if not item.isdigit():
                    continue            
                if str(rule.get("time") or "").strip() not in ("", "*"):
                    continue            
                                        
                out["by_group"][item] = float(rule.get("value"))
            except Exception:
                continue
    except Exception as e:  
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def talk_strength_set(by_group):
    """QQ bot stack component."""




    if not isinstance(by_group, dict):
        return False, "数据格式不对（应该是一个 {群号: 强度} 的对象）"
    clean = {}
    for gid, v in by_group.items():
        gid = str(gid).strip()
        if not gid:
            continue
        if not gid.isdigit():
            return False, f"群号不对：{gid!r}"
        if v in (None, ""):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            return False, f"群 {gid} 的强度不是数字：{v!r}"
        if not 0 <= f <= 1:
            return False, f"群 {gid} 的强度要 0~1 之间（收到 {f}）"
        clean[gid] = round(f, 3)

    try:
        tk = _tomlkit()
    except RuntimeError as e:
        return False, str(e)
    original = read_text(MAIBOT_CONFIG)
    try:
        doc = tk.parse(original)
        rt = doc["chat"]["reply_timing"]
        kept = []
        for rule in (rt.get("talk_value_rules") or []):
            try:
                if str(rule.get("rule_type")) == "group" and str(rule.get("item_id") or "").strip().isdigit() \
                        and str(rule.get("time") or "").strip() in ("", "*"):
                    
                    continue
            except Exception:  
                pass
            kept.append(rule)
        for gid, f in sorted(clean.items()):
            row = tk.table()
            row["platform"] = "qq"
            row["item_id"] = gid
            row["rule_type"] = "group"
            row["time"] = "*"
            row["value"] = f
            kept.append(row)
        rt["talk_value_rules"] = kept
        rt["enable_talk_value_rules"] = True
        new_text = tk.dumps(doc)
    except Exception as e:  
        return False, f"改配置失败：{type(e).__name__}: {e}"

    wrote, err = write_toml_checked(MAIBOT_CONFIG, original, new_text)
    if err:
        return False, err
    if not wrote:
        return True, "没有变化，无需保存"
    return True, (f"已保存 {len(clean)} 个群的发言强度（0~1）；没填的群用全局默认。"
                  f"⚠️ 麦麦只在**启动时**读这份配置 —— 要让新强度生效，得重启麦麦（控制台「服务控制」里点一下）")


def compute_group_targets(items, mode):
    """QQ bot stack component."""





    want_mon, want_listed = [], []
    for it in items or []:
        try:
            gid = int(it.get("group_id"))
        except (TypeError, ValueError):
            continue
        if it.get("monitored"):
            want_mon.append(gid)
        
        speak = bool(it.get("speak"))
        if mode == "whitelist":
            if speak:
                want_listed.append(gid)
        else:
            if not speak:
                want_listed.append(gid)
    return sorted(want_mon), sorted(want_listed)


def group_switches_set(items):
    """QQ bot stack component."""





    mode = adapter_group_mode()
    want_mon, want_listed = compute_group_targets(items, mode)

    if not want_mon:
        return False, "至少要监控一个群（监控系统的配置要求 monitor_groups 非空）"

    notes = []
    
    try:
        with open(MONITOR_CONFIG, encoding="utf-8") as f:
            mcfg = json.load(f)
        old_mon = sorted(int(x) for x in (mcfg.get("napcat", {}) or {}).get("monitor_groups", []))
        if old_mon != want_mon:
            
            lost = sorted(set(old_mon) - set(want_mon))
            if lost:
                panel_log(f"监控群减少：{old_mon} -> {want_mon}（不再监控 {lost}）")
            added = sorted(set(want_mon) - set(old_mon))
            qq = (mcfg.get("alert", {}) or {}).get("qq", {}) or {}
            payload = {
                "monitor_groups": want_mon,
                "qq_recipients": qq.get("recipient_user_ids", []),   
                "qq_alert_enabled": bool(qq.get("enabled", True)),
            }
            if (mcfg.get("storage", {}) or {}).get("export_dir"):
                payload["export_dir"] = mcfg["storage"]["export_dir"]
            r = urllib.request.Request(MONITOR_BASE + "/api/system/config", method="POST")
            r.add_header("Content-Type", "application/json")
            tok = monitor_access_token()
            if tok:
                r.add_header("X-Access-Token", tok)
            with urllib.request.urlopen(r, json.dumps(payload).encode("utf-8"), timeout=60) as resp:
                d = json.loads(resp.read().decode("utf-8"))
            if not d.get("success"):
                return False, f"监控群保存失败：{d.get('error') or d}"
            detail = []
            if added:
                detail.append(f"新增监控 {added}")
            if lost:
                detail.append(f"取消监控 {lost}")
            notes.append(f"监控群已更新并**立即生效**（共 {len(want_mon)} 个"
                         + ("；" + "，".join(detail) if detail else "") + "）")
        else:
            notes.append("监控群无变化")
    except Exception as e:
        panel_log(f"更新监控群失败：{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return False, f"更新监控群失败：{type(e).__name__}: {e}"

    
    try:
        target = chat_list_config()
        original = read_text(target)
        text, ok = toml_set(original, "group_list", to_literal(want_listed), "chat")
        if not ok:
            return False, f"配置里找不到 chat.group_list，写法可能变了：{target}"
        changed = save_text_if_changed(target, original, text)
        if changed:
            notes.append(f"发言群已保存到「{chat_list_owner()}」（{len(want_listed)} 个在"
                         f"{('白' if mode == 'whitelist' else '黑')}名单里），"
                         + ("**插件没热加载的话要重启麦麦**" if target == SNOWLUMA_PLUGIN_CONFIG
                            else "**需重启「麦麦适配器」才生效**"))
        else:
            notes.append("发言群无变化")
    except Exception as e:
        panel_log(f"更新发言群失败：{type(e).__name__}: {e}\n{traceback.format_exc()}")
        return False, f"更新发言群失败：{type(e).__name__}: {e}"

    return True, "；".join(notes)


def _norm_localhost(url):
    """QQ bot stack component."""





    s = str(url or "").strip()
    if s.startswith("http://localhost"):
        return "http://127.0.0.1" + s[len("http://localhost"):]
    if s.startswith("https://localhost"):
        return "https://127.0.0.1" + s[len("https://localhost"):]
    return s


def monitor_config_get():
    with open(MONITOR_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    ai = cfg.get("ai_review", {})
    sec = cfg.get("secondary_ai_review", {})
    qq = cfg.get("alert", {}).get("qq", {})
    comp = cfg.get("chat_companion", {})
    return {
        "monitor_groups": cfg.get("napcat", {}).get("monitor_groups", []),
        "qq_enabled": qq.get("enabled", False),
        "qq_recipients": qq.get("recipient_user_ids", []),
        "export_dir": cfg.get("storage", {}).get("export_dir", ""),
        "ai_enabled": ai.get("enabled", True),
        "ai_model": ai.get("model", ""),
        "ai_base": _norm_localhost(ai.get("api_base", "")),
        "ai_interval": ai.get("review_interval_minutes", 5),
        "ai_prompt": ai.get("system_prompt", ""),
        "secondary_enabled": sec.get("enabled", True),
        "secondary_model": sec.get("model", ""),
        "secondary_base": _norm_localhost(sec.get("api_base", "")),
        
        "companion_enabled": comp.get("enabled", False),
        "companion_model": comp.get("model", ""),
        "companion_base": _norm_localhost(comp.get("api_base", "")),
        "companion_bot_name": comp.get("bot_name", ""),
        "companion_cooldown": comp.get("cooldown_seconds", 10),
        
        "repeater_enabled": (cfg.get("repeater", {}) or {}).get("enabled", False),
        "repeater_cooldown": (cfg.get("repeater", {}) or {}).get("cooldown_seconds", 1800),
        "auto_cleanup": cfg.get("storage", {}).get("auto_cleanup_enabled", False),
    }


def _monitor_config_transaction(func):
    @functools.wraps(func)
    def locked(*args, **kwargs):
        with _MONITOR_CONFIG_LOCK:
            return func(*args, **kwargs)
    return locked


@_monitor_config_transaction
def save_monitor_config(cfg):
    """QQ bot stack component."""







    cfg.setdefault("storage", {})["auto_cleanup_enabled"] = False
    fd, tmp = tempfile.mkstemp(prefix=".monitor-", suffix=".tmp",
                               dir=os.path.dirname(os.path.abspath(MONITOR_CONFIG)))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, MONITOR_CONFIG)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@_monitor_config_transaction
def monitor_config_set(data):
    if data.get("auto_cleanup"):
        return False, "禁止自动删除聊天记录"
    with open(MONITOR_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    nap = cfg.setdefault("napcat", {})
    sto = cfg.setdefault("storage", {})
    ai = cfg.setdefault("ai_review", {})
    sec = cfg.setdefault("secondary_ai_review", {})
    qq = cfg.setdefault("alert", {}).setdefault("qq", {})

    def ids(v):
        if isinstance(v, str):
            v = re.split(r"[,，\s]+", v)
        out = []
        for x in v or []:
            try:
                n = int(str(x).strip())
                if n > 0 and n not in out:
                    out.append(n)
            except (TypeError, ValueError):
                continue
        return out

    if "monitor_groups" in data:
        nap["monitor_groups"] = ids(data["monitor_groups"])
    if "qq_enabled" in data:
        qq["enabled"] = bool(data["qq_enabled"])
    if "qq_recipients" in data:
        qq["recipient_user_ids"] = ids(data["qq_recipients"])
    if data.get("export_dir"):
        sto["export_dir"] = str(data["export_dir"]).strip()
    if "ai_enabled" in data:
        ai["enabled"] = bool(data["ai_enabled"])
    for k, j in (("ai_model", "model"), ("ai_base", "api_base"), ("ai_prompt", "system_prompt")):
        if data.get(k) not in (None, ""):
            ai[j] = _norm_localhost(data[k]) if j == "api_base" else data[k]
    if data.get("ai_interval"):
        try:
            ai["review_interval_minutes"] = max(1, int(data["ai_interval"]))
        except (TypeError, ValueError):
            pass
    if "secondary_enabled" in data:
        sec["enabled"] = bool(data["secondary_enabled"])
    for k, j in (("secondary_model", "model"), ("secondary_base", "api_base")):
        if data.get(k) not in (None, ""):
            sec[j] = _norm_localhost(data[k]) if j == "api_base" else data[k]

    
    comp = cfg.setdefault("chat_companion", {})
    if "companion_enabled" in data:
        comp["enabled"] = bool(data["companion_enabled"])
    for k, j in (("companion_model", "model"), ("companion_base", "api_base"),
                 ("companion_bot_name", "bot_name")):
        if data.get(k) not in (None, ""):
            comp[j] = _norm_localhost(data[k]) if j == "api_base" else data[k]
    if data.get("companion_cooldown") not in (None, ""):
        try:
            comp["cooldown_seconds"] = max(0, int(data["companion_cooldown"]))
        except (TypeError, ValueError):
            pass
    if "auto_cleanup" in data:
        sto["auto_cleanup_enabled"] = False

    
    rep = cfg.setdefault("repeater", {})
    if "repeater_enabled" in data:
        rep["enabled"] = bool(data["repeater_enabled"])
    if data.get("repeater_cooldown") not in (None, ""):
        try:
            rep["cooldown_seconds"] = max(0, int(data["repeater_cooldown"]))
        except (TypeError, ValueError):
            pass

    if not nap.get("monitor_groups"):
        return False, "至少要有一个监控群"
    save_monitor_config(cfg)
    return True, "监控配置已保存"


@_monitor_config_transaction
def monitor_export_dir_set(target):
    with open(MONITOR_CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("storage", {})["export_dir"] = target
    save_monitor_config(cfg)











def cg_prompts_get():
    """QQ bot stack component."""
    with open(CG_PROMPTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def cg_prompts_set(data):
    """QQ bot stack component."""
    if not isinstance(data, dict):
        return False, "数据格式不对（应该是一个 JSON 对象）"

    def seg(key):
        v = data.get(key)
        if v is None:
            data[key] = {}
        elif not isinstance(v, dict):
            raise ValueError(f"{key} 段格式不对（应该是一个对象）")
        return data[key]

    def str_list(val, label):
        """QQ bot stack component."""
        if not isinstance(val, list):
            raise ValueError(f"{label} 必须是数组（页面上是一行逗号分隔，存盘是数组）")
        out = []
        for idx, it in enumerate(val, 1):
            if not isinstance(it, str) or not it.strip():
                raise ValueError(f"{label} 第 {idx} 项必须是非空文本")
            out.append(it.strip())
        return out

    def size_of(val, label):
        """QQ bot stack component."""
        s = str(val or "").strip()
        if s and not re.match(r"^\d+[xX]\d+$", s):
            raise ValueError(f"{label} 必须是 数字x数字（比如 1280x720），留空表示用全局宽高")
        return s

    try:
        ident = seg("identity")
        call = seg("callname")
        cg = seg("cg")
    except ValueError as e:
        return False, str(e)
    sticker = data.get("sticker")
    if sticker is None:
        sticker = data["sticker"] = {}
    elif not isinstance(sticker, dict):
        return False, "sticker 段格式不对（应该是一个对象）"

    model = str(cg.get("model") or "").strip()
    if not model:
        return False, "生图模型（cg.model）不能为空"
    cg["model"] = model
    provider = str(cg.get("provider") or "").strip()
    if provider not in CG_PROVIDERS:
        return False, "生图后端（cg.provider）只能是 " + " 或 ".join(CG_PROVIDERS)
    cg["provider"] = provider

    
    for name, lo in (("width", 1), ("height", 1), ("step", 0),
                     ("start_favor", 0), ("daily_limit", 0)):
        try:
            n = int(str(cg.get(name)).strip())
        except (TypeError, ValueError):
            return False, f"cg.{name} 必须是整数（收到的是 {cg.get(name)!r}）"
        if n < lo:
            return False, f"cg.{name} 不能小于 {lo}（现在是 {n}）"
        cg[name] = n

    
    for name in ("min_favor", "penalty_no_choice", "pending_seconds"):
        if ident.get(name) not in (None, ""):
            try:
                ident[name] = max(0, int(str(ident[name]).strip()))
            except (TypeError, ValueError):
                return False, f"identity.{name} 必须是整数"
    
    
    if "help" in ident:
        help_txt = ident.get("help")
        if not isinstance(help_txt, str):
            return False, "菜单解释（identity.help）必须是文本"
        if not help_txt.strip():
            return False, "菜单解释（identity.help）不能为空"
    
    
    if "admin_help" in ident:
        ah = ident.get("admin_help")
        if ah not in (None, "") and not isinstance(ah, str):
            return False, "管理员专属那几行（identity.admin_help）必须是文本（留空就是不显示）"
    
    if "help_keywords" in ident:
        kws = ident.get("help_keywords")
        if not isinstance(kws, list):
            return False, "菜单触发词（identity.help_keywords）必须是数组"
        for idx, kw in enumerate(kws, 1):
            if not isinstance(kw, str) or not kw.strip():
                return False, f"菜单触发词（identity.help_keywords）第 {idx} 项必须是非空文本"
        ident["help_keywords"] = [kw.strip() for kw in kws]
    
    
    if ident.get("options") is not None and not isinstance(ident.get("options"), dict):
        return False, "身份选项（identity.options）必须是一个对象"
    
    
    opts = ident.get("options")
    if isinstance(opts, dict):
        for key, opt in opts.items():
            if not isinstance(opt, dict):
                continue  
            try:
                if "aliases" in opt:
                    opt["aliases"] = str_list(opt["aliases"], f"身份 {key} 的别名 aliases")
                for name in ("chibi", "chibi_negative"):
                    if name in opt and not isinstance(opt[name], str):
                        return False, f"身份 {key} 的 {name} 必须是文本"
                sub = opt.get("cg")
                if sub is None:
                    continue
                if not isinstance(sub, dict):
                    return False, f"身份 {key} 的 cg 段格式不对（应该是一个对象）"
                for name in ("prompt", "negative"):
                    if name in sub and not isinstance(sub[name], str):
                        return False, f"身份 {key} 的 cg.{name} 必须是文本"
                if "size" in sub:
                    sub["size"] = size_of(sub["size"], f"身份 {key} 的 cg.size")
                
                
                
                if "scenes" in sub:
                    scenes = sub["scenes"]
                    if not isinstance(scenes, dict):
                        return False, f"身份 {key} 的场景追加词 cg.scenes 必须是一个对象（场景名 → 追加提示词）"
                    for sname, sval in scenes.items():
                        if not isinstance(sname, str) or not sname.strip():
                            return False, f"身份 {key} 的 cg.scenes 里有空场景名，场景名必须是非空文本"
                        if not isinstance(sval, str):
                            return False, f"身份 {key} 的场景「{sname}」的追加提示词必须是文本"
                    
                    sub["scenes"] = {sname: sval.strip() for sname, sval in scenes.items()}
                
                
                
                if "sd_params" in sub and not isinstance(sub["sd_params"], dict):
                    return False, f"身份 {key} 的 sd_params 必须是一个对象"
            except ValueError as e:
                return False, str(e)

    if call.get("max_len") not in (None, ""):
        try:
            call["max_len"] = max(1, int(str(call["max_len"]).strip()))
        except (TypeError, ValueError):
            return False, "callname.max_len 必须是整数"

    stages = cg.get("stages")
    if not isinstance(stages, list):
        return False, "cg.stages 必须是数组（一档一条）"
    for i, st in enumerate(stages, 1):
        if not isinstance(st, dict):
            return False, f"cg.stages 第 {i} 档格式不对（应该是一个对象）"
        if not str(st.get("prompt") or "").strip():
            return False, f"cg.stages 第 {i} 档的画面提示词是空的"
        for name, lo in (("level", 1), ("min_favor", 0)):
            try:
                n = int(str(st.get(name)).strip())
            except (TypeError, ValueError):
                return False, f"cg.stages 第 {i} 档的 {name} 必须是整数"
            if n < lo:
                return False, f"cg.stages 第 {i} 档的 {name} 不能小于 {lo}"
            st[name] = n

    
    
    for name in ("min_favor", "daily_limit", "cooldown_seconds"):
        if sticker.get(name) not in (None, ""):
            try:
                n = int(str(sticker[name]).strip())
            except (TypeError, ValueError):
                return False, f"sticker.{name} 必须是整数（收到的是 {sticker.get(name)!r}）"
            if n < 0:
                return False, f"sticker.{name} 不能是负数（现在是 {n}）"
            sticker[name] = n
    try:
        if "keywords" in sticker:
            sticker["keywords"] = str_list(sticker["keywords"], "表情包触发词 sticker.keywords")
        if "size" in sticker:
            sticker["size"] = size_of(sticker["size"], "表情包尺寸 sticker.size")
    except ValueError as e:
        return False, str(e)
    for name in ("caption", "fallback"):
        if name in sticker and not isinstance(sticker[name], str):
            return False, f"sticker.{name} 必须是文本"

    def mutate(d):
        
        
        d.clear()
        d.update(data)

    ok, msg = _admin_write_json(CG_PROMPTS_FILE, mutate)
    if not ok:
        return False, msg
    return True, "CG 与身份提示词已保存（麦麦按文件时间自动重读，不用重启）"


def keyword_reply_get():
    """QQ bot stack component."""
    try:
        with open(KEYWORD_FILE, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {
            "_说明": "监控还没启动过，这个文件是页面上的默认值；点「保存」就写进 "
                     + KEYWORD_FILE,
            "cooldown_seconds": 60, "enabled": False, "groups": [], "mention": False,
            "quirky_file": "", "max_chars": QUIRKY_MAX_CHARS_DEFAULT,
            "rules": [],
        }


def keyword_reply_set(data):
    """QQ bot stack component."""
    if not isinstance(data, dict):
        return False, "数据格式不对（应该是一个 JSON 对象）"

    def text_of(v, label, limit):
        t = str(v if v is not None else "").strip()
        if not t:
            raise ValueError(f"{label} 不能空着")
        if len(t) > limit:
            raise ValueError(f"{label} 太长了（最多 {limit} 字，现在 {len(t)}）")
        
        
        
        
        if "?" in t and not re.search(r"[\u4e00-\u9fffA-Za-z0-9]", t):
            raise ValueError(f"{label} 里只有问号、没有中文/字母数字（收到 {t[:16]!r}）—— "
                             f"像是编码坏了。**先在浏览器里按 F5 刷新页面**，重新填好再保存。")
        return t

    try:
        cd = int(str(data.get("cooldown_seconds") if data.get("cooldown_seconds") not in (None, "")
                      else 0).strip() or 0)
        if cd < 0:
            raise ValueError("冷却秒数不能是负数")
        groups = []
        for g in (data.get("groups") or []):
            g = str(g).strip()
            if not g:
                continue
            if not g.isdigit():
                raise ValueError(f"群号只能是数字（收到 {g!r}）")
            groups.append(int(g))
        rules = []
        for i, r in enumerate(data.get("rules") or []):
            if not isinstance(r, dict):
                raise ValueError(f"第 {i + 1} 条规则格式不对（应该是一个对象）")
            kws = []
            for k in (r.get("keywords") or []):
                if str(k).strip():
                    kws.append(text_of(k, f"第 {i + 1} 条的触发词", 40))
            if not kws:
                raise ValueError(f"第 {i + 1} 条规则一个触发词都没有")
            
            
            
            
            
            
            
            
            
            
            
            
            
            _RTYPES = ("text", "quirky", "food", "learn", "mylearn", "favor", "sing", "groupon", "study", "reflect")
            _raw_type = str(r.get("type") or "text").strip().lower()
            rtype = _raw_type if _raw_type in _RTYPES else "text"
            prefix = str(r.get("prefix") or "").strip()
            if len(prefix) > 40:
                raise ValueError(f"第 {i + 1} 条的前缀太长了（最多 40 字，现在 {len(prefix)}）")
            rule = {
                "enabled": r.get("enabled", True) is not False,
                "keywords": kws,
            }
            
            if str(r.get("id") or "").strip():
                rule["id"] = str(r["id"]).strip()
            if rtype != "text":
                
                rule["type"] = rtype
                rule["prefix"] = prefix
                rule["reply"] = ""
                rule["require_at_bot"] = r.get("require_at_bot") is not False
                
                rule["mention"] = r.get("mention") is True
            else:
                rule["reply"] = text_of(r.get("reply"), f"第 {i + 1} 条的回复内容", 500)
            rules.append(rule)
        if not rules:
            raise ValueError("至少要有一条规则")
        qf = str(data.get("quirky_file") or "").strip()
        if qf and not os.path.isabs(qf):
            raise ValueError(f"怪话库路径要写绝对路径（收到 {qf!r}）")
        
        try:
            with open(KEYWORD_FILE, encoding="utf-8") as _f:
                _old_kwr = json.load(_f)
        except Exception:  
            _old_kwr = {}
        admins = data.get("admins")
        if not isinstance(admins, list) or not admins:
            admins = [str(a).strip() for a in (_old_kwr.get("admins") or []) if str(a).strip()]
        ff = str(data.get("favor_file") or _old_kwr.get("favor_file") or "").strip()
        mc = int(str(data.get("max_chars") if data.get("max_chars") not in (None, "")
                     else QUIRKY_MAX_CHARS_DEFAULT).strip() or 0)
        if mc < 0:
            raise ValueError("怪话最长字数不能是负数（0 = 不限）")
    except ValueError as e:
        return False, str(e)

    new = {
        "enabled": data.get("enabled", True) is not False,
        "mention": data.get("mention", False) is True,
        "cooldown_seconds": cd,
        "groups": groups,
        "quirky_file": qf,
        "max_chars": mc,
        "admins": admins,
        "favor_file": ff,
        
        "learn_max_chars": int(str(data.get("learn_max_chars")
                                   or _old_kwr.get("learn_max_chars") or 500).strip() or 500),
        "learn_pic_max_mb": float(str(data.get("learn_pic_max_mb")
                                      or _old_kwr.get("learn_pic_max_mb") or 5.0).strip() or 5.0),
        "learn_admins_only": bool(data.get("learn_admins_only",
                                           _old_kwr.get("learn_admins_only", False))),
        "rules": rules,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    def mutate(d):
        
        d.clear()
        d.update(new)
        d["_说明"] = ("关键词自动回复：群里有人提到 keywords 里任意一个词，就把 reply **原样**发出去"
                      "（不过模型、不改一个字）。一条消息只回一条（按 rules 顺序取第一条命中的）。"
                      "type=text（默认）发 reply；type=quirky 从怪话库随机挑一条发"
                      "（reply 留空、用 prefix 加前缀、require_at_bot 默认 true = 必须真 @ 机器人）。"
                      "enabled=总开关；mention=true 时回复前会真 @ 提问的人；cooldown_seconds="
                      "同一个群里同一条规则的冷却秒数；groups 留空=所有群生效。"
                      "quirky_file=怪话库路径（留空=麦麦的 data/quirky_lines.json）；"
                      "max_chars=超过这个字数的怪话不发（防刷屏）；**填 0 = 不限，长文也照发**。改完热重载，不用重启。")

    ok, msg = _admin_write_json(KEYWORD_FILE, mutate)
    if not ok:
        return False, msg
    return True, ("关键词回复已保存（监控按文件时间自动重读，**立即生效**；"
                  f"共 {len(rules)} 条规则）")


def rules_get():
    out = {}
    for name in ("keywords.txt", "banned_words.txt"):
        p = os.path.join(MONITOR_RULES, name)
        out[name] = read_text(p) if os.path.exists(p) else ""
    return out


def rules_set(data):
    for name in ("keywords.txt", "banned_words.txt"):
        if name in data:
            write_text(os.path.join(MONITOR_RULES, name), data[name])
    return True, "规则已保存"




def capture_log_path(key):
    return os.path.join(PANEL_LOGS, f"{key}.log")


def launcher_pidfile(key):
    """QQ bot stack component."""
    return os.path.join(PANEL_LOGS, f"{key}.launcher.pid")






UI_SEEN_FILE = os.path.join(PANEL_LOGS, "ui_seen.txt")
_UI_LAST_WRITE = [0.0]


def is_browser_request():
    """QQ bot stack component."""



    h = request.headers
    return bool(h.get("Sec-Fetch-Site") or h.get("Sec-Fetch-Mode") or h.get("Referer"))


def note_ui_seen():
    """QQ bot stack component."""
    now = time.time()
    if now - _UI_LAST_WRITE[0] < 5:
        return
    _UI_LAST_WRITE[0] = now
    try:
        os.makedirs(PANEL_LOGS, exist_ok=True)
        with open(UI_SEEN_FILE, "w", encoding="utf-8") as f:
            f.write(str(now))
    except OSError:
        pass


def ui_idle_seconds():
    """QQ bot stack component."""
    try:
        with open(UI_SEEN_FILE, encoding="utf-8") as f:
            return max(0.0, time.time() - float(f.read().strip()))
    except (OSError, ValueError):
        return None


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")





_BLOB_RE = re.compile(r"[A-Za-z0-9+/=_\-]{180,}")


def _collapse_blobs(line: str) -> str:
    def sub(m):
        s = m.group(0)
        
        return f"⟪已折叠 {len(s)} 字符的编码数据（多半是登录二维码/图片 base64）⟫"
    return _BLOB_RE.sub(sub, line)





_BLOCK_CHARS = set("█▀▄░▒▓■□▐▌")
_QR_ART_MARK = "⟪已折叠 {n} 行二维码图案（NapCat 登录用；扫码请点上面的「打开 NapCat WebUI」，" \
               "或看日志里的「二维码解码URL」）⟫"


def _is_qr_art(line: str) -> bool:
    s = line.strip()
    if len(s) < 8:
        return False
    solid = s.replace(" ", "")
    blocks = sum(1 for c in s if c in _BLOCK_CHARS)
    return blocks >= 10 and blocks / max(1, len(solid)) >= 0.5


def read_capture(key, lines=200):
    """QQ bot stack component."""




    p = capture_log_path(key)
    if not os.path.isfile(p):
        return None
    out, art = [], 0
    for line in tail_file(p, lines):
        if not line.startswith("(无法读取") and _is_qr_art(line):
            art += 1
            continue
        if art:
            out.append(_QR_ART_MARK.format(n=art))
            art = 0
        if line.startswith("(无法读取"):
            out.append(line)
            continue
        out.append(_collapse_blobs(_ANSI_RE.sub("", line)))
    if art:
        out.append(_QR_ART_MARK.format(n=art))
    return out


def make_launcher(key):
    """QQ bot stack component."""





    svc = SERVICES[key]
    os.makedirs(PANEL_LOGS, exist_ok=True)
    log = capture_log_path(key)
    
    try:
        if os.path.getsize(log) > CAPTURE_MAX_BYTES:
            os.replace(log, log + ".1")
    except OSError:
        pass
    cmd = [str(c) for c in svc["cmd"]]
    
    if len(cmd) >= 3 and os.path.basename(cmd[0]).lower() in ("cmd", "cmd.exe") and cmd[1].lower() == "/c":
        cmd = cmd[2:]
    args = subprocess.list2cmdline(cmd)
    bat = os.path.join(PANEL_LOGS, f"launch_{key}.bat")
    label = svc["label"]
    
    
    
    
    body = "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        
        
        
        'set "PYTHONIOENCODING=utf-8"',
        
        
        
        *[f'set "{k}={v}"' for k, v in (svc.get("env") or {}).items()],
        f"title QQ-{label}",
        f'cd /d "{svc["cwd"]}"',
        f'>> "{log}" echo.',
        f'>> "{log}" echo ========== 启动 {label}  %date% %time% ==========',
        f'>> "{log}" echo 工作目录: {svc["cwd"]}',
        f'>> "{log}" echo 启动命令: {args}',
        
        
        
        
        f'call {args} >> "{log}" 2>&1 < nul',
        f'>> "{log}" echo ========== 已退出，退出码 %errorlevel%  %date% %time% ==========',
        "",
    ])
    write_text(bat, body)
    return bat


def tail_file(path, lines=200):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            block = min(size, max(4096, lines * 400))
            f.seek(size - block)
            data = f.read().decode("utf-8", errors="replace")
        
        
        data = data.replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")
        return data.split("\n")[-lines:]
    except Exception as e:
        return [f"(无法读取: {e})"]


def latest_in(dirpath, patterns):
    if not os.path.isdir(dirpath):
        return None
    best, best_m = None, -1
    for fn in os.listdir(dirpath):
        if any(re.search(p, fn) for p in patterns):
            p = os.path.join(dirpath, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > best_m:
                best, best_m = p, m
    return best


def service_log(key, lines=200):
    if not IS_WIN:
        
        
        if key == "napcat":
            return _run_lines(["docker", "logs", "--tail", str(lines), "napcat"], lines)
        if key in ("adapter", "panel"):
            out = _run_lines(["journalctl", "-u", LINUX_UNITS[key], "-n", str(lines),
                              "--no-pager", "-o", "short-iso"], lines)
            if out and not out[0].startswith("("):
                return out
        if key == "maibot":
            out = _run_lines(["journalctl", "-u", LINUX_UNITS[key], "-n", str(lines),
                              "--no-pager", "-o", "short-iso"], lines)
            if out and not out[0].startswith("(") and len(out) > 2:
                return out
    
    if key == "panel":
        f = os.path.join(PANEL_LOGS, "panel_boot.log")
        return tail_file(f, lines) if os.path.isfile(f) else ["(还没有控制台自身的日志)"]
    svc = SERVICES[key]
    d = svc.get("log")
    if key == "monitor":
        f = latest_in(d, [r"^monitor_.*\.log$"]) if d else None
        if f:
            return tail_file(f, lines)
        return read_capture(key, lines) or ["(暂无日志)"]
    if key == "maibot":
        f = latest_in(d, [r"^app_.*\.log\.jsonl$"]) if d else None
        if not f:
            return read_capture(key, lines) or ["(暂无日志)"]
        raw = tail_file(f, lines)
        out = []
        for ln in raw:
            try:
                j = json.loads(ln)
                ts = j.get("timestamp") or j.get("time") or ""
                lv = str(j.get("level", "")).upper()
                msg = j.get("event") or j.get("message") or ""
                extra = ""
                for kk in ("name", "group_id", "user_id"):
                    if j.get(kk):
                        extra += f" {kk}={j[kk]}"
                out.append(f"[{ts}] {lv:<8} {msg}{extra}")
            except Exception:
                out.append(ln)
        return out
    
    cap = read_capture(key, lines)
    if cap:
        return cap
    if d and os.path.isdir(d):
        f = latest_in(d, [r".*\.log$", r".*\.txt$"])
        if f:
            return tail_file(f, lines)
    return ["(还没有日志。点「启动」后，服务的控制台输出会实时抓到这里。)"]




app = Flask(__name__)




app.json.sort_keys = False


@app.route("/api/status")
def api_status():
    
    if is_browser_request():
        note_ui_seen()
    items = [service_status(k) for k in SERVICES]
    
    
    if snowluma_mode():
        items = [s for s in items if s["key"] not in ("napcat", "adapter")]
    by_key = {s["key"]: s for s in items}
    
    _health_tick({s["key"]: bool(s.get("running")) for s in items})
    
    stats = None
    if by_key.get("monitor", {}).get("running"):
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:8080/api/stats", timeout=4) as r:
                stats = json.loads(r.read().decode("utf-8"))
        except Exception:
            stats = None
    
    onebot_on = port_open(3001) or port_open(3000)
    
    cfg_bad = config_syntax_problems()
    if cfg_bad:
        first = cfg_bad[0]
        tip = (f"⚠ 配置文件语法错误（{first['label']}）：{first['error'][:120]}　"
               f"这个服务重启会起不来，请改回合法内容。")
    elif snowluma_mode():
        
        if not port_open(5099):
            tip = "SnowLuma 未启动。双击 start-snowluma.bat（QQ 接入、进程注入都在那边）。"
        elif not onebot_on:
            tip = ("QQ 还没登录：去 SnowLuma WebUI（http://127.0.0.1:5099/processes）"
                   "登录机器人号 QQ 并注入钩子。")
        elif not by_key["maibot"]["running"]:
            tip = "QQ 已登录，正在等麦麦核心启动完成。"
        elif isinstance(stats, dict) and stats.get("ws_connected") is False:
            
            
            
            tip = ("⚠ 监控（qq-monitor）没连上 QQ —— 聊天记录不会入库、也不会导出。"
                   "通常是 SnowLuma 刚重连过；重启「监控告警系统」即可让它重连。")
        else:
            tip = ""
    else:
        napcat_on = by_key.get("napcat", {}).get("running", False)
        if not napcat_on:
            tip = "NapCat 未启动。点「一键启动全部」。"
        elif not onebot_on:
            tip = ("NapCat 已启动但 QQ 还没登录（OneBot 端口 3000/3001 未开放）。"
                   "请点下面的「打开 NapCat WebUI」用手机 QQ 扫码登录机器人账号。")
        elif not by_key["maibot"]["running"]:
            tip = "QQ 已登录，正在等麦麦核心启动完成。"
        elif isinstance(stats, dict) and stats.get("ws_connected") is False:
            tip = ("⚠ 监控（qq-monitor）没连上 NapCat —— 聊天记录不会入库、也不会导出。"
                   "通常是 NapCat 刚崩过或掉登录；重启「监控告警系统」即可让它重连。")
        else:
            tip = ""
    return jsonify({
        "services": items,
        "monitor_stats": stats,
        "napcat_logged_in": bool(onebot_on),
        
        "snowluma": {
            "on": port_open(5099),
            "qq_on": bool(onebot_on),
            "webui": "http://127.0.0.1:5099/processes",
        },
        "tip": tip,
        "config_errors": cfg_bad,
        "netstat_error": _NETSTAT_ERR[0],
        "ui_idle_seconds": ui_idle_seconds(),
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


_FAVOR_TIERS_CACHE = {"mtime": None, "tiers": ()}


def _favor_relationship_tiers():
    """QQ bot stack component."""
    import ast
    path = os.path.join(MAIBOT_DIR, "src", "plugins", "built_in", "behavior_score", "logic.py")
    try:
        mtime = os.stat(path).st_mtime_ns
        if _FAVOR_TIERS_CACHE["mtime"] != mtime:
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read())
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "REL_TIERS" for t in node.targets):
                    tiers = ast.literal_eval(node.value)
                    _FAVOR_TIERS_CACHE.update(mtime=mtime, tiers=tuple(sorted(tiers)))
                    break
        return _FAVOR_TIERS_CACHE["tiers"]
    except (OSError, ValueError, SyntaxError, TypeError):
        return ()


def _favor_today(ts=None):
    return datetime.fromtimestamp(time.time() if ts is None else ts,
                                  timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _favor_relationship_view(record, score, tiers):
    """QQ bot stack component."""
    import math
    lower, label = (0, "不熟，也不想熟") if score < 30 else (30, "保持距离")
    following = None
    for threshold, title in tiers:
        if score >= threshold:
            lower, label = threshold, title
        else:
            following = (threshold, title)
            break
    relation = {"label": label, "threshold": lower, "next_score": None,
                "next_label": None, "remaining": None, "progress": 100.0}
    if following:
        threshold, title = following
        relation.update(next_score=threshold, next_label=title,
                        remaining=max(0, threshold - score),
                        progress=round(max(0, min(100, (score-lower)/(threshold-lower)*100)), 1))
    history = []
    for event in record.get("history", []) if isinstance(record.get("history"), list) else []:
        if not isinstance(event, dict):
            continue
        try:
            ts, delta, after = float(event["ts"]), float(event["delta"]), float(event["score"])
        except (KeyError, ValueError, TypeError):
            continue
        if not all(math.isfinite(v) for v in (ts, delta, after)) or ts <= 0 or delta == 0:
            continue
        history.append({"ts": ts, "delta": delta, "score": after,
                        "reason": str(event.get("reason") or "未注明原因"),
                        "source": "admin" if event.get("source") == "admin" else "interaction"})
    daily = record.get("daily")
    today = None
    if isinstance(daily, dict) and daily.get("date") == _favor_today():
        try:
            gain, loss = float(daily.get("gain", 0)), float(daily.get("loss", 0))
            if all(math.isfinite(v) and v >= 0 for v in (gain, loss)):
                today = {"gain": gain, "loss": loss, "net": gain-loss}
        except (TypeError, ValueError):
            pass
    days = record.get("interaction_days")
    days = len(set(str(v) for v in days)) if isinstance(days, list) else 0
    try:
        total_days = max(days, int(record.get("interaction_day_count", days)))
    except (ValueError, TypeError):
        total_days = days
    return {"relationship": relation, "recent_changes": sorted(history, key=lambda e: e["ts"], reverse=True)[:5],
            "today_change": today, "recorded_interaction_days": total_days}


def _favor_admin_history(rec, before, after, now):
    import math
    delta = after-before
    if not math.isfinite(delta) or not delta:
        return
    history = rec.get("history")
    history = history if isinstance(history, list) else []
    rec["history"] = (history + [{"ts": now, "delta": delta, "score": after,
                                 "reason": "管理员调整", "source": "admin"}])[-30:]
    daily = rec.get("daily")
    if not isinstance(daily, dict) or daily.get("date") != _favor_today(now):
        daily = {"date": _favor_today(now), "gain": 0, "loss": 0, "natural_gain": 0}
    for field in ("gain", "loss", "natural_gain"):
        try:
            value = float(daily.get(field, 0) or 0)
            daily[field] = value if math.isfinite(value) and value >= 0 else 0
        except (TypeError, ValueError):
            daily[field] = 0
    key = "gain" if delta > 0 else "loss"
    daily[key] += abs(delta)
    rec["daily"] = daily


@app.route("/api/favorability")
def api_favorability():
    """QQ bot stack component."""



    try:
        with open(FAVORABILITY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        users = d.get("users") or {}
        import math
        rows = []
        tiers = _favor_relationship_tiers()
        for uid, record in users.items():
            if not isinstance(record, dict):
                continue
            try:
                score = float(record.get("score", 100) or 0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(score):
                rows.append({**record, "user_id": str(uid), "score": score,
                             **_favor_relationship_view(record, score, tiers)})
        last_score, rank = None, 0
        for index, row in enumerate(sorted(rows, key=lambda r: (-r["score"], r["user_id"])), 1):
            if row["score"] != last_score:
                rank = index
            row["rank"], last_score = rank, row["score"]
        
        
        
        
        kw = (request.args.get("q") or "").strip().lower()
        if kw:
            def _fv_hit(u):
                blob = " ".join(str(u.get(k) or "") for k in
                                ("user_id", "name", "nickname", "identity", "last_reason")).lower()
                return kw in blob
            rows = [u for u in rows if _fv_hit(u)]
        keymap = {
            "score": lambda x: float(x.get("score", 100) or 0),
            "hits": lambda x: float(x.get("hits", 0) or 0),
            "last_ts": lambda x: float(x.get("last_ts", 0) or 0),
            "name": lambda x: str(x.get("name") or ""),
        }
        sort = (request.args.get("sort") or "score").strip()
        order = (request.args.get("order") or "asc").strip().lower()
        rows.sort(key=keymap.get(sort, keymap["score"]), reverse=(order == "desc"))
        try:
            limit = int(request.args.get("limit") or 0)
        except ValueError:
            limit = 0
        try:
            offset = max(0, int(request.args.get("offset") or 0))
        except ValueError:
            offset = 0
        page = rows[offset:] if limit <= 0 else rows[offset:offset + limit]
        return jsonify({"updated_at": d.get("updated_at", ""), "users": page,
                        "total": len(rows), "all_total": len(users),
                        "file": FAVORABILITY_FILE})
    except FileNotFoundError:
        return jsonify({"users": [], "total": 0, "file": FAVORABILITY_FILE,
                        "hint": "还没有好感度记录（插件刚装上，或者还没人跟它说过话）"})
    except Exception as e:
        return jsonify({"users": [], "total": 0, "file": FAVORABILITY_FILE,
                        "error": f"{type(e).__name__}: {e}"})


def _admin_write_json(path, mutate):
    """QQ bot stack component."""






    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            raise ValueError("内容不是对象")
    except FileNotFoundError:
        d = {"updated_at": "", "users": {}}
    except Exception as e:
        return False, f"读不到或内容坏了：{type(e).__name__}: {e}"
    try:
        mutate(d)
        d["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path),
                                             prefix=os.path.basename(path) + ".", suffix=".tmp", delete=False) as f:
                tmp = f.name
                json.dump(d, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
        return True, "已保存（麦麦下次读写时会自动重读，不用重启）"
    except Exception as e:
        return False, f"写入失败：{type(e).__name__}: {e}"


@app.route("/api/favorability/set", methods=["POST"])
def api_favorability_set():
    """QQ bot stack component."""
    d = request.get_json(silent=True) or {}
    uid = str(d.get("user_id", "") or "")
    name = str(d.get("name", "") or "")

    def mutate(data):
        users = data.setdefault("users", {})
        if d.get("reset_all"):
            now = time.time()
            for rec in users.values():
                if isinstance(rec, dict):
                    before = float(rec.get("score", 100))
                    rec["score"] = 100
                    _favor_admin_history(rec, before, 100, now)
                    rec["last_ts"], rec["last_reason"] = now, "管理员调整"
            return
        if not uid:
            raise ValueError("缺少 user_id")
        rec = users.setdefault(uid, {"name": "", "score": 100, "last_ts": 0.0, "hits": 0})
        if name:
            rec["name"] = name[:32]
        before = float(rec.get("score", 100))
        rec["last_ts"] = time.time()
        rec["last_reason"] = "管理员调整"
        if d.get("reset_one"):
            rec["score"] = 100
        elif d.get("value") is not None:
            rec["score"] = max(0, int(d["value"]))
        elif d.get("delta") is not None:
            rec["score"] = max(0, int(rec.get("score", 100)) + int(d["delta"]))
        else:
            raise ValueError("要给出 value / delta / reset_one 之一")
        _favor_admin_history(rec, before, rec["score"], rec["last_ts"])

    ok, msg = _admin_write_json(FAVORABILITY_FILE, mutate)
    return jsonify({"success": ok, "message": msg})







import sqlite3


def _mem_conn(readonly: bool = True):
    
    
    if not os.path.isfile(MAIBOT_DB):
        raise FileNotFoundError(MAIBOT_DB)
    if readonly:
        return sqlite3.connect(f"file:{MAIBOT_DB}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(MAIBOT_DB, timeout=10)


def _mem_group_names(con) -> dict:
    """QQ bot stack component."""





    for sql in (
        "SELECT stream_id, group_name FROM chat_streams",
        "SELECT DISTINCT session_id, group_name FROM mai_messages"
        " WHERE group_name IS NOT NULL AND group_name != ''",
    ):
        try:
            return {str(r[0]): str(r[1] or "") for r in con.execute(sql)}
        except Exception:
            continue
    return {}







AMEMORIX_DB = os.path.join(os.path.dirname(MAIBOT_DB), "a-memorix", "metadata", "metadata.db")


_AMEM_KINDS = {
    "paragraph": ("paragraphs", "content", "段落", "created_at"),
    "entity": ("entities", "name", "实体", "created_at"),
    "relation": ("relations",
                 "subject || ' ' || predicate || ' ' || object", "关系三元组", "created_at"),
    "profile": ("person_profile_snapshots", "profile_text", "人物画像快照", "updated_at"),
}


def _amem_conn():
    if not os.path.isfile(AMEMORIX_DB):
        raise FileNotFoundError(AMEMORIX_DB)
    return sqlite3.connect(f"file:{AMEMORIX_DB}?mode=ro", uri=True, timeout=10)


def _amem_row(kind, r, names) -> dict:
    """QQ bot stack component."""
    def _t(ts):
        try:
            ts = float(ts or 0)
        except (TypeError, ValueError):
            return ""
        return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""

    if kind == "paragraph":
        content = str(r["content"] or "")
        cid = ""
        try:
            cid = str((json.loads(r["metadata"] or "{}") or {}).get("chat_id") or "")
        except Exception:
            cid = ""
        return {"id": str(r["hash"]), "title": str(r["source"] or ""), "content": content,
                "chat_id": cid, "group_name": names.get(cid, ""), "time": _t(r["created_at"]),
                "chars": int(r["word_count"] or len(content)), "ro": True}
    if kind == "entity":
        return {"id": str(r["hash"]), "title": str(r["name"] or ""),
                "content": f"出现 {int(r['appearance_count'] or 0)} 次",
                "chat_id": "", "group_name": "", "time": _t(r["created_at"]),
                "chars": 0, "ro": True}
    if kind == "relation":
        return {"id": str(r["hash"]),
                "title": f"{r['subject']} —{r['predicate']}→ {r['object']}",
                "content": f"置信度 {r['confidence']}",
                "chat_id": "", "group_name": "", "time": _t(r["created_at"]),
                "chars": 0, "ro": True}
    try:
        aliases = json.loads(r["aliases_json"] or "[]") or []
    except Exception:
        aliases = []
    text = str(r["profile_text"] or "")
    who = str(r["person_id"] or "")
    if aliases:
        who += "（" + ", ".join(str(a) for a in aliases[:3]) + "）"
    return {"id": str(r["snapshot_id"]), "title": who, "content": text[:4000],
            "chat_id": "", "group_name": "", "time": _t(r["updated_at"]),
            "chars": len(text), "ro": True}


def _memories_amem():
    """QQ bot stack component."""
    def _int(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    kind = str(request.args.get("kind", "paragraph") or "paragraph").strip().lower()
    if kind not in _AMEM_KINDS:
        kind = "paragraph"
    table, scol, label, tcol = _AMEM_KINDS[kind]
    limit = _int("limit", 40, 1, 200)
    offset = _int("offset", 0, 0, 10 ** 7)
    kw = str(request.args.get("q", "") or "").strip()
    group = str(request.args.get("group", "") or "").strip()

    try:
        con = _amem_conn()
        con.row_factory = sqlite3.Row
        try:
            
            try:
                mcon = _mem_conn(True)
                try:
                    names = _mem_group_names(mcon)
                finally:
                    mcon.close()
            except Exception:
                names = {}

            where, args = [], []
            if kind in ("paragraph", "entity"):
                where.append("COALESCE(is_deleted, 0) = 0")
            if kind == "paragraph" and group:
                where.append("json_extract(metadata, '$.chat_id') = ?")
                args.append(group)
            if kw:
                where.append(f"({scol}) LIKE ?")
                args.append(f"%{kw}%")
            cond = (" WHERE " + " AND ".join(where)) if where else ""
            cur = con.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {table}{cond}", args)
            total = int(cur.fetchone()[0])
            cur.execute(f"SELECT * FROM {table}{cond} ORDER BY {tcol} DESC LIMIT ? OFFSET ?",
                        args + [limit, offset])
            rows = [_amem_row(kind, r, names) for r in cur.fetchall()]

            stats = {}
            for k, (t, _s, lbl, _tc) in _AMEM_KINDS.items():
                try:
                    stats[k] = {"label": lbl,
                                "count": int(con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])}
                except Exception:
                    stats[k] = {"label": lbl, "count": -1}
            groups = []
            if kind == "paragraph":
                try:
                    groups = [{"group_id": str(g or ""),
                               "group_name": names.get(str(g or ""), "") or str(g or "(无群)"),
                               "count": int(n)}
                              for g, n in con.execute(
                                  "SELECT json_extract(metadata, '$.chat_id') AS g, COUNT(*)"
                                  " FROM paragraphs WHERE COALESCE(is_deleted, 0) = 0"
                                  " GROUP BY g ORDER BY 2 DESC")]
                except Exception:
                    groups = []
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [], "stats": {},
                        "message": f"{type(e).__name__}: {e}"})
    return jsonify({"success": True, "source": "amem", "kind": kind, "label": label,
                    "rows": rows, "total": total, "groups": groups, "stats": stats,
                    "limit": limit, "offset": offset, "db": AMEMORIX_DB})


@app.route("/api/memories")
def api_memories():
    """QQ bot stack component."""
    src = str(request.args.get("source", "amem") or "amem").strip().lower()
    if src in ("legacy", "chest", "old", "memory_chest"):
        return _memories_legacy()
    return _memories_amem()


def _memories_legacy():
    """QQ bot stack component."""
    def _int(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 40, 1, 200)
    offset = _int("offset", 0, 0, 10 ** 7)
    group = str(request.args.get("group", "") or "").strip()
    kw = str(request.args.get("q", "") or "").strip()

    try:
        con = _mem_conn(True)
        con.row_factory = sqlite3.Row
        try:
            names = _mem_group_names(con)
            where, args = [], []
            if group:
                where.append("chat_id = ?")
                args.append(group)
            if kw:
                where.append("(content LIKE ? OR title LIKE ?)")
                args += [f"%{kw}%", f"%{kw}%"]
            cond = (" WHERE " + " AND ".join(where)) if where else ""
            cur = con.cursor()
            cur.execute(f"SELECT COUNT(*) FROM memory_chest{cond}", args)
            total = int(cur.fetchone()[0])
            cur.execute(
                f"SELECT id, title, content, chat_id, locked, create_time"
                f" FROM memory_chest{cond} ORDER BY create_time DESC LIMIT ? OFFSET ?",
                args + [limit, offset])
            rows = []
            for r in cur.fetchall():
                try:
                    ts = float(r["create_time"] or 0)
                except (TypeError, ValueError):
                    ts = 0.0
                rows.append({
                    "id": int(r["id"]),
                    "title": str(r["title"] or ""),
                    "content": str(r["content"] or ""),
                    "chat_id": str(r["chat_id"] or ""),
                    "group_name": names.get(str(r["chat_id"] or ""), ""),
                    "locked": bool(r["locked"]),
                    "time": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else "",
                    "chars": len(str(r["content"] or "")),
                })
            groups = [{"group_id": str(g), "group_name": names.get(str(g), "") or str(g), "count": int(n)}
                      for g, n in con.execute(
                          "SELECT chat_id, COUNT(*) FROM memory_chest GROUP BY chat_id ORDER BY 2 DESC")]
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [],
                        "message": f"{type(e).__name__}: {e}"})
    return jsonify({"success": True, "rows": rows, "total": total, "groups": groups,
                    "limit": limit, "offset": offset, "db": MAIBOT_DB})


@app.route("/api/memories/remove", methods=["POST"])
def api_memories_remove():
    """QQ bot stack component."""
    try:
        mid = int((request.get_json(silent=True) or {}).get("id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "缺少有效的 id"})
    try:
        con = _mem_conn(False)
        try:
            cur = con.cursor()
            cur.execute("SELECT title FROM memory_chest WHERE id = ?", (mid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "message": "这条记忆已经不在了"})
            cur.execute("DELETE FROM memory_chest WHERE id = ?", (mid,))
            con.commit()
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
    return jsonify({"success": True, "message": f"已删除记忆 #{mid}：{str(row[0])[:40]}"})


@app.route("/api/memories/lock", methods=["POST"])
def api_memories_lock():
    """QQ bot stack component."""
    d = request.get_json(silent=True) or {}
    try:
        mid = int(d.get("id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "缺少有效的 id"})
    locked = 1 if d.get("locked") else 0
    try:
        con = _mem_conn(False)
        try:
            cur = con.cursor()
            cur.execute("UPDATE memory_chest SET locked = ? WHERE id = ?", (locked, mid))
            if cur.rowcount == 0:
                return jsonify({"success": False, "message": "这条记忆已经不在了"})
            con.commit()
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
    return jsonify({"success": True, "message": "已锁定（不会再被自动清理）" if locked else "已解锁"})


@app.route("/api/memories/update", methods=["POST"])
def api_memories_update():
    """QQ bot stack component."""





    d = request.get_json(silent=True) or {}
    try:
        mid = int(d.get("id"))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "缺少有效的 id"})
    has_title = "title" in d
    has_content = "content" in d
    if not (has_title or has_content):
        return jsonify({"success": False, "message": "没有要改的内容"})
    title = str(d.get("title") or "").strip()[:200]
    content = str(d.get("content") or "").strip()
    if has_content and not content:
        return jsonify({"success": False, "message": "内容不能改成空 —— 想删掉就点「删除」"})
    try:
        con = _mem_conn(False)
        try:
            cur = con.cursor()
            cur.execute("SELECT title, content FROM memory_chest WHERE id = ?", (mid,))
            row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "message": "这条记忆已经不在了"})
            new_title = title if has_title else row[0]
            new_content = content if has_content else row[1]
            cur.execute("UPDATE memory_chest SET title = ?, content = ? WHERE id = ?",
                        (new_title, new_content, mid))
            con.commit()
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
    return jsonify({"success": True,
                    "message": f"已保存记忆 #{mid}（{len(new_content or '')} 字），它下次查询就用新版"})


@app.route("/api/memories/duplicates")
def api_memories_duplicates():
    """QQ bot stack component."""




    try:
        threshold = max(0.3, min(0.95, float(request.args.get("threshold", 0.55))))
    except (TypeError, ValueError):
        threshold = 0.55
    from difflib import SequenceMatcher
    try:
        con = _mem_conn(True)
        con.row_factory = sqlite3.Row
        try:
            names = _mem_group_names(con)
            rows = [dict(r) for r in con.execute(
                "SELECT id, title, content, chat_id, locked, create_time"
                " FROM memory_chest ORDER BY create_time DESC")]
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "clusters": [], "message": f"{type(e).__name__}: {e}"})

    by_chat = {}
    for r in rows:
        by_chat.setdefault(str(r.get("chat_id") or ""), []).append(r)

    clusters, used = [], set()
    for cid, group in by_chat.items():
        for i, a in enumerate(group):
            if a["id"] in used:
                continue
            sa = str(a.get("content") or "")[:240]
            if not sa:
                continue
            members = [a]
            for b in group[i + 1:]:
                if b["id"] in used:
                    continue
                sb = str(b.get("content") or "")[:240]
                if sb and SequenceMatcher(None, sa, sb).ratio() >= threshold:
                    members.append(b)
                    used.add(b["id"])
            if len(members) > 1:
                used.add(a["id"])
                clusters.append({
                    "group_name": names.get(cid, "") or cid,
                    "chat_id": cid,
                    "items": [{"id": int(m["id"]), "title": str(m.get("title") or ""),
                               "content": str(m.get("content") or ""),
                               "time": datetime.fromtimestamp(float(m.get("create_time") or 0)
                                                              ).strftime("%m-%d %H:%M")
                                       if m.get("create_time") else "",
                               "locked": bool(m.get("locked"))} for m in members],
                })
    clusters.sort(key=lambda c: -len(c["items"]))
    return jsonify({"success": True, "clusters": clusters, "groups": len(clusters),
                    "threshold": threshold, "scanned": len(rows)})







QUIRKY_FILE = os.path.join(MAIBOT_DIR, "data", "quirky_lines.json")


def _monitor_data_dir():
    """QQ bot stack component."""





    for name in (("config.win.json", "config.linux.json", "config.json") if IS_WIN
                 else ("config.linux.json", "config.json")):
        try:
            with open(os.path.join(MONITOR_DIR, "config", name), encoding="utf-8") as f:
                d = json.load(f)
            v = (d.get("storage") or {}).get("data_dir")
            if v and os.path.isabs(str(v)):
                
                
                if IS_WIN and str(v).startswith("/"):
                    continue
                return str(v)
        except Exception:
            continue
    return os.path.join(BOT_DATA_DIR, "data")


MARKED_USERS_FILE = os.path.join(_monitor_data_dir(), "marked_users.jsonl")


def _read_marked_jsonl(path, limit=500):
    """QQ bot stack component."""




    recs = []
    try:
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    obj = json.loads(ln)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    recs.append(obj)
    except FileNotFoundError:
        return []
    return recs[-limit:]


@app.route("/api/marked_users")
def api_marked_users():
    """QQ bot stack component."""




    try:
        recs = _read_marked_jsonl(MARKED_USERS_FILE)
        agg = {}
        for r in recs:                      
            qq = str(r.get("qq") or "")
            if not qq:
                continue
            a = agg.setdefault(qq, {"qq": qq, "nickname": "", "role": "", "count": 0,
                                    "first": "", "last": "", "_groups": set()})
            a["count"] += 1
            
            if r.get("nickname"):
                a["nickname"] = str(r["nickname"])
            if r.get("role"):
                a["role"] = str(r["role"])
            ts = str(r.get("ts") or "")
            if ts and not a["first"]:
                a["first"] = ts
            if ts:
                a["last"] = ts
            g = str(r.get("group_name") or r.get("group_id") or "")
            if g:
                a["_groups"].add(g)
        summary = []
        for a in agg.values():
            a["groups"] = "、".join(sorted(a.pop("_groups")))
            summary.append(a)
        summary.sort(key=lambda x: (x["count"], x["last"]), reverse=True)
        return jsonify({"success": True, "total": len(recs), "unique": len(summary),
                        "summary": summary, "events": list(reversed(recs)),
                        "file": MARKED_USERS_FILE})
    except Exception as e:
        return jsonify({"success": False, "total": 0, "unique": 0, "summary": [],
                        "events": [], "message": f"{type(e).__name__}: {e}"})


@app.route("/api/model/usage")
def api_model_usage():
    """QQ bot stack component."""








    period = str(request.args.get("period") or "24").strip()
    out = {"success": True, "period": period, "generated_at": 0, "periods": [],
           "summary": {}, "models": [], "price_missing": [], "total_cost": 0.0}
    try:
        with open(LOCAL_STORE, encoding="utf-8") as f:
            store = json.load(f)
    except FileNotFoundError:
        return jsonify({"success": False, "message": "还没有统计缓存（麦麦刚起来？过几分钟再看）"})
    except Exception as e:  
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
    cache = store.get("webui_dashboard_statistics_cache") or {}
    entries = cache.get("entries") or {}
    out["generated_at"] = cache.get("generated_at") or 0
    out["periods"] = sorted((str(k) for k in entries.keys()),
                            key=lambda x: int(x) if x.isdigit() else 0)
    ent = entries.get(period) or {}
    s = ent.get("summary") or {}
    out["summary"] = {
        "requests": s.get("total_requests") or 0,
        "tokens": s.get("total_tokens") or 0,
        "input_tokens": s.get("input_tokens") or 0,
        "output_tokens": s.get("output_tokens") or 0,
        "cache_hit_tokens": s.get("cache_hit_tokens") or 0,
    }
    prices = {}
    codex_family_prices = {}
    try:
        tk = _tomlkit()
        doc = tk.parse(read_text(MAIBOT_MODEL_CONFIG))
        for m in (doc.get("models") or []):
            try:
                prices[str(m.get("name") or "")] = (float(m.get("price_in") or 0),
                                                    float(m.get("price_out") or 0))
                family = re.fullmatch(r"gpt-6-(astra|sol|luna)(?:-.*)?", str(m.get("model_identifier") or ""))
                if family and str(m.get("name") or "").startswith("Codex"):
                    codex_family_prices[family[1].lower()] = prices[str(m.get("name") or "")]
            except (TypeError, ValueError):
                continue
    except Exception:  
        pass
    rows = []
    total_cost = 0.0
    for m in (ent.get("model_stats") or []):
        if not isinstance(m, dict):
            continue
        name = str(m.get("model_name") or "?")
        tin = float(m.get("input_tokens") or 0)
        tout = float(m.get("output_tokens") or 0)
        price = prices.get(name)
        if price is None and name.startswith("Codex"):
            family = re.search(r"\bGPT-6 (Astra|Sol|Luna)\b", name, re.IGNORECASE)
            if family:
                price = codex_family_prices.get(family[1].lower())
        pin, pout = price or (0.0, 0.0)
        cost = tin / 1e6 * pin + tout / 1e6 * pout
        total_cost += cost
        if pin <= 0 and pout <= 0 and (tin or tout):
            out["price_missing"].append(name)
        rows.append({"name": name, "requests": m.get("request_count") or 0,
                     "input_tokens": tin, "output_tokens": tout,
                     "total_tokens": float(m.get("total_tokens") or (tin + tout)),
                     "cache_hit_tokens": float(m.get("cache_hit_tokens") or 0),
                     "cache_hit_rate": m.get("cache_hit_rate"),
                     "avg_response_time": m.get("avg_response_time"),
                     "price_in": pin, "price_out": pout, "cost": round(cost, 4)})
    rows.sort(key=lambda x: x["total_tokens"], reverse=True)
    out["models"] = rows
    out["total_cost"] = round(total_cost, 4)
    return jsonify(out)


@app.route("/api/talk_strength", methods=["GET", "POST"])
def api_talk_strength():
    """QQ bot stack component."""
    if request.method == "GET":
        return jsonify({"success": True, **talk_strength_get()})
    d = request.get_json(silent=True) or {}
    ok, msg = talk_strength_set(d.get("groups") or {})
    return jsonify({"success": ok, "message": msg, "need_restart": ok})


@app.route("/api/sing/status", methods=["GET"])
def api_sing_status():
    """QQ bot stack component."""







    data = {"enabled_groups": {}, "disabled_groups": [], "default_on": True,
            "groups": [], "groups_error": "", "status": {}, "model": "",
            "tools_ok": False, "toggle_path": ""}
    try:
        import sys
        tools_dir = os.path.join(BASE_DIR, "panel", "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        
        SING_TOGGLE_PATH = os.path.join(BASE_DIR, "qq-monitor", "config", "sing_groups.json")
        data["toggle_path"] = SING_TOGGLE_PATH
        try:
            with open(SING_TOGGLE_PATH, encoding="utf-8") as f:
                raw = {str(k): bool(v) for k, v in (json.load(f) or {}).items()}
        except Exception:                                      
            raw = {}
        data["enabled_groups"] = {k: True for k, v in raw.items() if v}   
        data["disabled_groups"] = sorted(k for k, v in raw.items() if not v)
        import rvc_singer                                       
        data["tools_ok"] = True
        
        data["model"] = os.environ.get(
            "SING_VOICE", getattr(rvc_singer, "DEFAULT_VOICE", "")
            or getattr(rvc_singer, "DEFAULT_MODEL", ""))
        try:
            data["status"] = rvc_singer.status()
        except Exception as e:                                  
            data["status"] = {"error": f"{type(e).__name__}: {e}"}
    except Exception as e:                                      
        data["error"] = f"{type(e).__name__}: {e}"
    
    try:
        gs = napcat_groups()
        if gs is None:
            data["groups_error"] = "取不到 OneBot 群列表（QQ 端未登录？）"
            data["groups"] = []
        else:
            data["groups"] = gs
    except Exception as e:                                      
        data["groups_error"] = f"{type(e).__name__}: {e}"
    return jsonify({"success": True, "data": data})


@app.route("/api/sing/toggle", methods=["POST"])
def api_sing_toggle():
    """QQ bot stack component."""





    body = request.get_json(force=True, silent=True) or {}
    raw_ids = body.get("group_ids")
    ids = ([str(x) for x in raw_ids] if isinstance(raw_ids, (list, tuple))
           else [str(body.get("group_id") or "")])
    ids = [g.strip() for g in ids if str(g).strip()]
    bad = [g for g in ids if not g.isdigit()]
    if not ids or bad:
        return jsonify({"success": False,
                        "message": f"群号只能是数字（收到 {bad or ids!r}）"}), 400
    on = body.get("on", True) is not False
    path = os.path.join(BASE_DIR, "qq-monitor", "config", "sing_groups.json")
    try:
        with open(path, encoding="utf-8") as f:
            m = {str(k): bool(v) for k, v in (json.load(f) or {}).items()}
    except Exception:                                          
        m = {}
    for gid in ids:
        if on:
            m.pop(gid, None)      
        else:
            m[gid] = False
    clean = {str(k): False for k, v in m.items() if not v}
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:                                      
        return jsonify({"success": False, "message": f"写开关失败：{type(e).__name__}: {e}"}), 500
    if len(ids) == 1:
        msg = (f"群 {ids[0]} 唱歌已打开（本来就是默认开的，已从关闭清单里移除）" if on
               else f"群 {ids[0]} 唱歌已关闭（想恢复随时点「打开」）")
    else:
        msg = (f"{len(ids)} 个群唱歌已全部打开（恢复默认）" if on
               else f"{len(ids)} 个群唱歌已全部关闭")
    return jsonify({"success": True, "message": msg + "（监控热读，立即生效）"})


@app.route("/api/quirky", methods=["GET"])
def api_quirky():
    try:
        with open(QUIRKY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        items = list(d.get("items") or [])
        
        items.sort(key=lambda x: (-int(x.get("used", 0) or 0), str(x.get("text", ""))))
        return jsonify({"success": True, "items": items, "total": len(items),
                        "enabled": sum(1 for i in items if i.get("enabled", True)),
                        "used_total": sum(int(i.get("used", 0) or 0) for i in items),
                        "updated_at": d.get("updated_at", ""), "file": QUIRKY_FILE})
    except FileNotFoundError:
        return jsonify({"success": True, "items": [], "total": 0, "enabled": 0,
                        "file": QUIRKY_FILE, "hint": "还没有怪话 —— 在下面的框里塞几条进去"})
    except Exception as e:
        return jsonify({"success": False, "items": [], "total": 0,
                        "message": f"{type(e).__name__}: {e}"})


@app.route("/api/quirky/add", methods=["POST"])
@app.route("/api/quirky/stats")
def api_quirky_stats():
    """QQ bot stack component."""




    out = {"success": True, "total": 0, "enabled": 0, "usable": 0,
           "too_long": 0, "disabled": 0, "used": 0, "file": QUIRKY_FILE}
    try:
        with open(QUIRKY_FILE, encoding="utf-8") as f:
            d = json.load(f)
    except FileNotFoundError:
        return jsonify(out)
    except Exception as e:  
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"})
    items = d.get("items") or []
    mc = _quirky_max_chars()
    used_any = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        on = it.get("enabled", True) is not False
        if int(it.get("used") or 0) > 0:
            used_any += 1
        if on:
            out["enabled"] += 1
            if text and (mc <= 0 or len(text) <= mc):
                out["usable"] += 1
            else:
                out["too_long"] += 1
        else:
            out["disabled"] += 1
    out["total"] = len(items)
    out["used"] = used_any
    return jsonify(out)


def api_quirky_add():
    """QQ bot stack component."""




    d = request.get_json(silent=True) or {}
    raw = str(d.get("text") or "")
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return jsonify({"success": False, "message": "先写点东西再塞"})
    kind = str(d.get("kind") or "管理员加的")[:16]
    counter = {"added": 0, "skipped": 0}

    def mutate(data):
        items = data.setdefault("items", [])
        exist = {str(i.get("text", "")).strip() for i in items}
        for text in lines:
            t = text[:120]
            if not t or t in exist:
                counter["skipped"] += 1
                continue
            items.append({"id": os.urandom(4).hex(), "text": t, "kind": kind,
                          "enabled": True, "used": 0, "last_used": 0.0})
            exist.add(t)
            counter["added"] += 1

    ok, msg = _admin_write_json(QUIRKY_FILE, mutate)
    if not ok:
        return jsonify({"success": False, "message": msg})
    tail = f"，{counter['skipped']} 条已存在跳过" if counter["skipped"] else ""
    return jsonify({"success": True, "added": counter["added"],
                    "message": f"加进去 {counter['added']} 条{tail}，冷场时它就有可能说出来"})


@app.route("/api/quirky/remove", methods=["POST"])
def api_quirky_remove():
    rid = str((request.get_json(silent=True) or {}).get("id") or "")
    if not rid:
        return jsonify({"success": False, "message": "缺少 id"})

    def mutate(data):
        data["items"] = [i for i in (data.get("items") or []) if i.get("id") != rid]

    ok, msg = _admin_write_json(QUIRKY_FILE, mutate)
    return jsonify({"success": ok, "message": "已删除" if ok else msg})


@app.route("/api/quirky/toggle", methods=["POST"])
def api_quirky_toggle():
    d = request.get_json(silent=True) or {}
    rid = str(d.get("id") or "")
    enabled = bool(d.get("enabled", True))
    if not rid:
        return jsonify({"success": False, "message": "缺少 id"})

    def mutate(data):
        for i in (data.get("items") or []):
            if i.get("id") == rid:
                i["enabled"] = enabled

    ok, msg = _admin_write_json(QUIRKY_FILE, mutate)
    return jsonify({"success": ok,
                    "message": ("已启用" if enabled else "已停用（不会被挑出来）") if ok else msg})






QUIRKY_AUTO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "quirky_auto.json")


_QUIRKY_AUTO_STATE = {
    
    "enabled": False, "threshold_min": 30, "cooldown_min": 120,
    "max_idle_min": 1440,
    "last_run": 0.0, "sent": {}, "message": "未运行", "group_on": {}, "fails": {},
    
    "topic_enabled": False, "topic_prob": 0.8, "topic_cooldown_min": 180,
    
    "sched_quirky": False, "gap_min": 120, "gap_max": 240,
    
    "quiet_start": 0, "quiet_end": 8,
    
    "follow_enabled": False, "follow_watch_min": 20, "follow_delay_sec": 25, "follow_max": 2,
    
    "llm_model": "", "llm_api_base": "", "llm_api_key": "",
    
    "sched_next": {}, "pending": {}, "topics_used": [], "topic_last": {},
}
_QUIRKY_GROUPS = []



_QUIRKY_AUTO_LOCK = threading.Lock()


_QUIRKY_SAVE_KEYS = (
    "enabled", "threshold_min", "cooldown_min", "max_idle_min",
    "topic_enabled", "topic_prob", "topic_cooldown_min",
    "sched_quirky", "gap_min", "gap_max",
    "quiet_start", "quiet_end",
    "follow_enabled", "follow_watch_min", "follow_delay_sec", "follow_max",
    "llm_model", "llm_api_base", "llm_api_key",
)


def _quirky_groups():
    """QQ bot stack component."""
    try:
        p = os.path.join(MAIBOT_DIR, "plugins", "snowluma-adapter", "config.toml")
        with open(p, encoding="utf-8") as f:
            txt = f.read()
        m = re.search(r"group_list\s*=\s*\[([^\]]*)\]", txt)
        if m:
            gids = [int(x) for x in re.findall(r"\d+", m.group(1))]
            if gids:
                return gids
    except Exception:
        pass
    return list(_QUIRKY_GROUPS)


def _maibot_latest_ts(gid):
    """QQ bot stack component."""






    db = os.path.join(MAIBOT_DIR, "data", "MaiBot.db")
    if not os.path.isfile(db):
        return -1
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
        try:
            row = con.execute("SELECT MAX(timestamp) FROM mai_messages WHERE group_id=?",
                              (int(gid),)).fetchone()
        finally:
            con.close()
        t = str((row or [None])[0] or "").strip()
        if len(t) < 19:
            return -1
        return int(time.mktime(time.strptime(t[:19], "%Y-%m-%d %H:%M:%S")))
    except Exception:
        return -1




LATEST_TS_TTL = 45.0
_LATEST_TS_CACHE = {}
_LATEST_TS_LOCK = threading.Lock()


def _group_latest_ts(gid):
    """QQ bot stack component."""











    now = time.time()
    key = str(gid)
    with _LATEST_TS_LOCK:
        hit = _LATEST_TS_CACHE.get(key)
        if hit and now - hit[0] < LATEST_TS_TTL:
            return hit[1]
    ts = _group_latest_ts_uncached(gid)
    with _LATEST_TS_LOCK:
        _LATEST_TS_CACHE[key] = (now, ts)
    return ts


def _group_latest_ts_uncached(gid):
    """QQ bot stack component."""
    try:
        with urllib.request.urlopen(
                f"{MONITOR_BASE}/api/messages?group_id={gid}&page_size=1", timeout=6) as r:
            d = json.loads(r.read().decode("utf-8"))
        ms = d.get("messages") or []
        ts = int(ms[0].get("time") or 0) if ms else 0
        if ts > 0:
            return ts
    except Exception:
        pass
    return _maibot_latest_ts(gid)


def _quirky_max_chars():
    """QQ bot stack component."""




    try:
        with open(KEYWORD_FILE, encoding="utf-8") as f:
            return int(json.load(f).get("max_chars") or 0)
    except Exception:  
        return QUIRKY_MAX_CHARS_DEFAULT


def _quirky_pick():
    """QQ bot stack component."""






    mc = _quirky_max_chars()
    blocked = ("狗罕见", "沙皮", "贩剑", "nmsl", "傻逼", "傻*", "死全家", "滚出中国",
               "原批", "欧泡", "不转不是中国人", "转发到", "转发这", "发到99", "发到 99",
               "发到你各个群", "群里的中国人", "日本人就给", "美国人就给", "发到你所在")
    try:
        with open(QUIRKY_FILE, encoding="utf-8") as f:
            d = json.load(f)
        pool = [i for i in (d.get("items") or [])
                if i.get("enabled", True) and str(i.get("text", "")).strip()
                and (mc <= 0 or len(str(i.get("text", "")).strip()) <= mc)
                and not any(p in str(i.get("text", "")).lower() for p in blocked)]
    except Exception:
        return None
    if not pool:
        return None
    import random as _rnd
    pool.sort(key=lambda i: (int(i.get("used", 0) or 0), _rnd.random()))
    return pool[0]


def _quirky_napcat_cfg():
    """QQ bot stack component."""





    names = (("config.win.json", "config.linux.json", "config.json") if IS_WIN
             else ("config.linux.json", "config.json"))
    for name in names:
        try:
            with open(os.path.join(MONITOR_DIR, "config", name), encoding="utf-8") as f:
                d = json.load(f) or {}
            nav = d.get("napcat") or {}
            if nav.get("http_url") and nav.get("token"):
                return str(nav["http_url"]).rstrip("/"), str(nav["token"])
        except Exception:
            continue
    return "http://127.0.0.1:3000", ""


def _quirky_send(gid, text):
    """QQ bot stack component."""
    try:
        base, token = _quirky_napcat_cfg()
        req = urllib.request.Request(
            base + "/send_group_msg",
            data=json.dumps({"group_id": int(gid),
                             "message": [{"type": "text", "data": {"text": text}}]},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
        flat = body.replace(" ", "")
        return ('"status":"ok"' in flat or '"retcode":0' in flat), body[:120]
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def _quirky_mark_used(rid):
    """QQ bot stack component."""
    def mutate(data):
        for i in (data.get("items") or []):
            if i.get("id") == rid:
                i["used"] = int(i.get("used", 0) or 0) + 1
                i["last_used"] = time.time()
    _admin_write_json(QUIRKY_FILE, mutate)


def _llm_from_monitor():
    """QQ bot stack component."""











    names = (("config.win.json", "config.linux.json", "config.json") if IS_WIN
             else ("config.linux.json", "config.json"))
    for name in names:
        try:
            with open(os.path.join(MONITOR_DIR, "config", name), encoding="utf-8") as f:
                d = json.load(f) or {}
        except Exception:
            continue
        for sec in ("ai_review", "secondary_ai_review"):
            cfg = d.get(sec) or {}
            base = str(cfg.get("api_base") or "").rstrip("/")
            if base and cfg.get("api_key"):
                if _is_local_ollama(base):
                    
                    continue
                return (base, str(cfg["api_key"]), str(cfg.get("model") or "").strip())
    return "", "", ""




_OLLAMA_BASE_RE = re.compile(r"^https?://(127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]):11434(/|$)",
                             re.IGNORECASE)


def _is_local_ollama(base: str) -> bool:
    """QQ bot stack component."""







    return bool(_OLLAMA_BASE_RE.match(str(base or "").strip()))


def _llm_from_maibot():
    """QQ bot stack component."""





    try:
        with open(os.path.join(MAIBOT_DIR, "config", "model_config.toml"),
                  encoding="utf-8") as f:
            txt = f.read()
    except Exception:
        return "", ""
    
    blocks = re.split(r"^\s*\[\[", txt, flags=re.MULTILINE)
    for blk in blocks:
        mb = re.search(r'base_url\s*=\s*"([^"]+)"', blk)
        mk = re.search(r'api_key\s*=\s*"(sk-[^"]+)"', blk)
        if not (mb and mk):
            continue
        base = mb.group(1).rstrip("/")
        if _is_local_ollama(base):
            continue
        return base, mk.group(1)
    
    base = re.search(r'base_url\s*=\s*"([^"]+)"', txt)
    key = re.search(r'api_key\s*=\s*"(sk-[^"]+)"', txt)
    if base and key:
        return base.group(1).rstrip("/"), key.group(1)
    return "", ""


def _proactive_llm():
    """QQ bot stack component."""













    st = _QUIRKY_AUTO_STATE
    base = str(st.get("llm_api_base") or "").strip()
    key = str(st.get("llm_api_key") or "").strip()
    model = str(st.get("llm_model") or "").strip()
    
    if base and _is_local_ollama(base):
        base, key, model = "", "", ""
    mb, mk, mm = _llm_from_monitor()
    if not base or not key:
        base, key = (base or mb), (key or mk)
        if not model and mb and mm and base == mb:
            model = mm        
    if not base or not key:
        b2, k2 = _llm_from_maibot()
        base, key = (base or b2), (key or k2)
    if not model and proactive is not None:
        model = proactive.DEFAULT_MODEL
    return {"api_base": base, "api_key": key, "model": model}


def _proactive_ready():
    return proactive is not None and proactive.llm_ready(_proactive_llm())


def _proactive_llm_desc():
    """QQ bot stack component."""
    llm = _proactive_llm()
    if not proactive or not proactive.llm_ready(llm):
        return "未配置（联网找话题会退化成发怪话）"
    return f"{llm['model']} @ {llm['api_base']}"


def _proactive_set_next(key, now):
    """QQ bot stack component."""
    st = _QUIRKY_AUTO_STATE
    if proactive is not None:
        gap = proactive.roll_gap(st.get("gap_min", 120), st.get("gap_max", 240))
    else:
        gap = 180 * 60
    st.setdefault("sched_next", {})[key] = now + gap


def _topic_ready(key, now):
    """QQ bot stack component."""
    st = _QUIRKY_AUTO_STATE
    gap = float(st.get("topic_cooldown_min") or 180) * 60
    last = float((st.get("topic_last") or {}).get(key) or 0)
    return (not last) or (now - last >= gap)


def _proactive_note_fail(gid, key, now, info):
    """QQ bot stack component."""
    st = _QUIRKY_AUTO_STATE
    st["sent"][key] = now
    fm = st.setdefault("fails", {})
    fm[key] = int(fm.get(key, 0)) + 1
    st["message"] = f"发送失败（群 {gid}，连续第 {fm[key]} 次）: {info}"


def _proactive_record_sent(gid, key, text, now, kind, title=""):
    """QQ bot stack component."""
    st = _QUIRKY_AUTO_STATE
    st["sent"][key] = now
    (st.get("fails") or {}).pop(key, None)          
    if not st.get("follow_enabled", True):
        return
    st.setdefault("pending", {})[key] = {
        "ts": now, "text": str(text)[:200], "kind": kind, "title": str(title)[:120],
        "replied": 0, "wait_ts": now,
        "expire": now + float(st.get("follow_watch_min") or 20) * 60,
    }


def _send_quirky_to(gid, key, now, reason, idle):
    """QQ bot stack component."""
    st = _QUIRKY_AUTO_STATE
    item = _quirky_pick()
    if not item:
        st["message"] = "怪话库空了，先去怪话库加几条"
        return False
    text = str(item.get("text", "")).strip()
    ok, info = _quirky_send(gid, text)
    if not ok:
        _proactive_note_fail(gid, key, now, info)
        return False
    _quirky_mark_used(item.get("id", ""))
    _proactive_record_sent(gid, key, text, now, "quirky")
    st["message"] = (f"群 {gid} {reason}（最后有人说话是 {int(idle//60)} 分钟前），"
                     f"已发怪话：「{text[:40]}」")
    return True


def _send_topic_to(gid, key, now, idle):
    """QQ bot stack component."""







    st = _QUIRKY_AUTO_STATE
    if not _proactive_ready():
        st["message"] = "没有可用的模型配置，这轮退回怪话"
        return False
    items = proactive.hot_topics()
    if not items:
        st["message"] = "热点源一个都没抓到内容，这轮退回怪话"
        return False
    used = list(st.get("topics_used") or [])
    text, title = proactive.make_opening(_proactive_llm(), items,
                                         proactive.group_name_of(gid), used)
    if not text:
        why = str((proactive.LAST_ERROR or {}).get("msg") or "")[:80]
        st["message"] = f"模型没给出开场白，这轮退回怪话（{why}）" if why else "模型没给出开场白，这轮退回怪话"
        return False
    ok, info = _quirky_send(gid, text)
    if not ok:
        _proactive_note_fail(gid, key, now, info)
        return None
    st.setdefault("topic_last", {})[key] = now
    if title:
        used.append(title)
        st["topics_used"] = used[-40:]
    _proactive_record_sent(gid, key, text, now, "topic", title)
    st["message"] = (f"群 {gid} 冷场 {int(idle//60)} 分钟，已联网起话题："
                     f"「{text[:40]}」（取自 {title[:20]}）")
    return True


def _proactive_followup_tick(now):
    """QQ bot stack component."""





    st = _QUIRKY_AUTO_STATE
    if proactive is None or not st.get("follow_enabled", True):
        return
    pend = st.get("pending")
    if not isinstance(pend, dict) or not pend:
        return
    bot = proactive.bot_qq()
    delay = float(st.get("follow_delay_sec") or 25)
    max_reply = int(st.get("follow_max") or 2)
    for key in list(pend.keys()):
        p = pend.get(key)
        if not isinstance(p, dict):
            pend.pop(key, None)
            continue
        try:
            gid = int(key)
        except Exception:
            pend.pop(key, None)
            continue
        if now > float(p.get("expire") or 0):
            pend.pop(key, None)                      
            continue
        since = float(p.get("wait_ts") or p.get("ts") or 0)
        rows = proactive.messages_since(gid, since, exclude_user=bot, limit=20)
        if not rows:
            continue
        last_ts = float(rows[-1].get("ts") or 0)
        if now - last_ts < delay:
            continue                                 
        if proactive.bot_spoke_since(gid, last_ts, bot):
            pend.pop(key, None)                      
            continue
        if int(p.get("replied") or 0) >= max_reply:
            pend.pop(key, None)
            continue
        if not _proactive_ready():
            continue
        text = proactive.make_reply(_proactive_llm(), p.get("text", ""), p.get("title", ""),
                                    [r["text"] for r in rows],
                                    proactive.group_name_of(gid))
        if not text:
            p["wait_ts"] = last_ts                   
            continue
        ok, info = _quirky_send(gid, text)
        p["wait_ts"] = last_ts
        if not ok:
            st["message"] = f"接话回复失败（群 {gid}）: {info}"
            continue
        p["replied"] = int(p.get("replied") or 0) + 1
        p["expire"] = now + float(st.get("follow_watch_min") or 20) * 60
        st["message"] = f"群 {gid} 有人接了话，已回（第 {p['replied']} 次）：「{text[:40]}」"
        if p["replied"] >= max_reply:
            pend.pop(key, None)


def _quirky_auto_tick():
    """QQ bot stack component."""





    st = _QUIRKY_AUTO_STATE
    now = time.time()
    st["last_run"] = now

    
    try:
        _proactive_followup_tick(now)
    except Exception as e:  
        st["message"] = f"接话跟进异常: {type(e).__name__}: {e}"

    if proactive is not None and proactive.in_quiet_hours(
            now, st.get("quiet_start", 0), st.get("quiet_end", 8)):
        st["message"] = (f"凌晨静默（{st.get('quiet_start', 0)}~{st.get('quiet_end', 8)} 点）："
                         f"不主动发怪话/话题，别人接话照样回")
        return

    group_on = st.get("group_on") or {}
    for gid in _quirky_groups():
        key = str(gid)
        
        if group_on.get(key, True) is False:
            continue
        
        
        
        
        fails = int((st.get("fails") or {}).get(key, 0))
        cd_min = float(st["cooldown_min"] or 120)
        if fails >= 3:
            cd_min = max(cd_min, 360)      
        last_sent = st.get("sent", {}).get(key, 0)
        cooled = (not last_sent) or (now - last_sent >= cd_min * 60)

        ts = _group_latest_ts(gid)
        if ts <= 0:
            continue  
        idle = now - ts
        
        max_idle = float(st.get("max_idle_min") or 0) * 60
        if max_idle > 0 and idle > max_idle:
            continue  

        
        if st.get("sched_quirky", True):
            due = float((st.get("sched_next") or {}).get(key) or 0)
            if due <= 0:
                _proactive_set_next(key, now)
            elif now >= due:
                if cooled:
                    if _send_quirky_to(gid, key, now, "到点发怪话", idle):
                        _proactive_set_next(key, now)
                        continue
                else:
                    _proactive_set_next(key, now)   

        
        if idle < float(st["threshold_min"] or 30) * 60:
            continue  
        if not cooled:
            continue
        if (st.get("topic_enabled", True) and proactive is not None
                and _topic_ready(key, now)
                and proactive.should_use_topic(st.get("topic_prob", 0.8))):
            hit = _send_topic_to(gid, key, now, idle)
            if hit is True:
                continue
            if hit is None:
                continue    
        _send_quirky_to(gid, key, now, "冷场", idle)


def _quirky_auto_worker():
    """QQ bot stack component."""





    while True:
        try:
            if _QUIRKY_AUTO_STATE.get("enabled"):
                _quirky_auto_tick()
                _quirky_auto_save({})
        except Exception as e:
            _QUIRKY_AUTO_STATE["message"] = f"worker 异常: {type(e).__name__}: {e}"
        time.sleep(60)


def _quirky_auto_save(patch):
    """QQ bot stack component."""











    with _QUIRKY_AUTO_LOCK:
        for k in _QUIRKY_SAVE_KEYS:
            if k in patch:
                _QUIRKY_AUTO_STATE[k] = patch[k]
        for k in ("group_on", "sched_next", "topic_last", "sent", "fails"):
            if k in patch and isinstance(patch[k], dict):
                _QUIRKY_AUTO_STATE.setdefault(k, {}).update(
                    {str(a): b for a, b in patch[k].items()})
        try:
            os.makedirs(os.path.dirname(QUIRKY_AUTO_FILE), exist_ok=True)
            blob = json.dumps(_QUIRKY_AUTO_STATE, ensure_ascii=False, indent=2)
            tmp = QUIRKY_AUTO_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(blob)
            os.replace(tmp, QUIRKY_AUTO_FILE)
            _QUIRKY_AUTO_STATE["_save_error"] = ""
        except Exception as e:
            _QUIRKY_AUTO_STATE["_save_error"] = f"{type(e).__name__}: {e}"
            _QUIRKY_AUTO_STATE["message"] = (
                f"主动说话状态写盘失败（设置可能不生效）：{type(e).__name__}: {e}")
            return False
    return True


def _quirky_auto_load():
    try:
        with open(QUIRKY_AUTO_FILE, encoding="utf-8") as f:
            d = json.load(f)
        for k in _QUIRKY_SAVE_KEYS:
            if k in d:
                _QUIRKY_AUTO_STATE[k] = d[k]
        for k in ("group_on", "sched_next", "pending", "topic_last", "sent", "fails"):
            if isinstance(d.get(k), dict):
                _QUIRKY_AUTO_STATE[k] = {str(a): b for a, b in d[k].items()}
        if isinstance(d.get("topics_used"), list):
            _QUIRKY_AUTO_STATE["topics_used"] = [str(x) for x in d["topics_used"]][-40:]
    except FileNotFoundError:
        pass
    except Exception as e:
        
        _QUIRKY_AUTO_STATE["message"] = (
            f"主动说话设置读取失败（已按默认值运行）：{type(e).__name__}: {e}")
        _QUIRKY_AUTO_STATE["_load_error"] = f"{type(e).__name__}: {e}"


@app.route("/api/quirky/auto")
def api_quirky_auto():
    now = time.time()
    st = _QUIRKY_AUTO_STATE
    group_on = st.get("group_on") or {}
    max_idle = float(st.get("max_idle_min") or 0) * 60
    groups = []
    for gid in _quirky_groups():
        ts = _group_latest_ts(gid)
        key = str(gid)
        last_sent = st.get("sent", {}).get(key, 0)
        due = float((st.get("sched_next") or {}).get(key) or 0)
        groups.append({
            "group_id": gid,
            "on": bool(group_on.get(key, True)),
            "latest_ts": ts,
            "idle_min": int((now - ts) // 60) if ts > 0 else -1,
            "last_sent_min": int((now - last_sent) // 60) if last_sent else -1,
            
            "dead": bool(max_idle > 0 and ts > 0 and (now - ts) > max_idle),
            "next_sched_min": int((due - now) // 60) if due > 0 else -1,
            "topic_ready": bool(_topic_ready(key, now)),
            "awaiting": bool((st.get("pending") or {}).get(key)),
        })
    quiet = (proactive is not None
             and proactive.in_quiet_hours(now, st.get("quiet_start", 0), st.get("quiet_end", 8)))
    return jsonify({"success": True,
                    "enabled": bool(st.get("enabled")),
                    "threshold_min": st.get("threshold_min", 30),
                    "cooldown_min": st.get("cooldown_min", 120),
                    "max_idle_min": st.get("max_idle_min", 1440),
                    "last_run": st.get("last_run", 0),
                    "message": st.get("message", ""),
                    "quiet_now": bool(quiet),
                    
                    "topic_enabled": bool(st.get("topic_enabled", True)),
                    "topic_prob": st.get("topic_prob", 0.8),
                    "topic_cooldown_min": st.get("topic_cooldown_min", 180),
                    "llm": _proactive_llm_desc(),
                    "llm_ready": bool(_proactive_ready()),
                    "topics_used": len(st.get("topics_used") or []),
                    
                    "sched_quirky": bool(st.get("sched_quirky", True)),
                    "gap_min": st.get("gap_min", 120),
                    "gap_max": st.get("gap_max", 240),
                    
                    "quiet_start": st.get("quiet_start", 0),
                    "quiet_end": st.get("quiet_end", 8),
                    
                    "follow_enabled": bool(st.get("follow_enabled", True)),
                    "follow_watch_min": st.get("follow_watch_min", 20),
                    "follow_delay_sec": st.get("follow_delay_sec", 25),
                    "follow_max": st.get("follow_max", 2),
                    "groups": groups})


@app.route("/api/quirky/auto", methods=["POST"])
def api_quirky_auto_set():
    d = request.get_json(silent=True) or {}
    patch = {}

    def _num(v, default, cast):
        """QQ bot stack component."""






        try:
            return cast(v)
        except (TypeError, ValueError):
            return default

    def _int(key, lo, hi, default):
        patch[key] = max(lo, min(_num(d.get(key), default, int), hi))

    if "enabled" in d:
        patch["enabled"] = bool(d["enabled"])
    if "threshold_min" in d:
        _int("threshold_min", 5, 480, 30)
    if "cooldown_min" in d:
        _int("cooldown_min", 30, 1440, 120)
    if "max_idle_min" in d:
        _int("max_idle_min", 0, 10080, 0)        
    
    if "topic_enabled" in d:
        patch["topic_enabled"] = bool(d["topic_enabled"])
    if "topic_prob" in d:
        
        patch["topic_prob"] = max(0.0, min(_num(d.get("topic_prob"), 0, float) / 100.0, 1.0))
    if "topic_cooldown_min" in d:
        _int("topic_cooldown_min", 10, 1440, 180)
    
    if "sched_quirky" in d:
        patch["sched_quirky"] = bool(d["sched_quirky"])
    if "gap_min" in d:
        patch["gap_min"] = max(30, min(_num(d.get("gap_min"), 120, int), 1440))
    if "gap_max" in d:
        patch["gap_max"] = max(30, min(_num(d.get("gap_max"), 240, int), 1440))
    if patch.get("gap_max") is not None and patch.get("gap_min") is not None \
            and patch["gap_max"] < patch["gap_min"]:
        patch["gap_max"] = patch["gap_min"]
    
    for k in ("quiet_start", "quiet_end"):
        if k in d:
            patch[k] = max(0, min(_num(d.get(k), 0, int), 23))
    
    if "follow_enabled" in d:
        patch["follow_enabled"] = bool(d["follow_enabled"])
    if "follow_delay_sec" in d:
        _int("follow_delay_sec", 5, 600, 25)
    if "follow_watch_min" in d:
        _int("follow_watch_min", 3, 180, 20)
    if "follow_max" in d:
        _int("follow_max", 1, 6, 2)
    
    for k in ("llm_model", "llm_api_base"):
        if k in d:
            patch[k] = str(d[k] or "").strip()
    if "llm_api_key" in d and str(d["llm_api_key"] or "").strip():
        patch["llm_api_key"] = str(d["llm_api_key"]).strip()
    if "clear_llm_api_key" in d and d["clear_llm_api_key"]:
        patch["llm_api_key"] = ""
    if "group_id" in d and "group_on" in d:
        patch["group_on"] = {str(d["group_id"]): bool(d["group_on"])}
    
    if "gap_min" in patch or "gap_max" in patch:
        patch["sched_next"] = {}
    _quirky_auto_save(patch)
    changed = "、".join(k for k in patch if k != "sched_next") or "（无变化）"
    return jsonify({"success": True, "message": f"已保存：{changed}",
                    "state": {k: _QUIRKY_AUTO_STATE.get(k) for k in _QUIRKY_SAVE_KEYS
                              if k != "llm_api_key"}})


@app.route("/api/quirky/auto/topics")
def api_quirky_topics():
    """QQ bot stack component."""
    if proactive is None:
        return jsonify({"success": False, "message": "proactive 模块没加载起来"})
    force = request.args.get("force") in ("1", "true", "yes")
    items = proactive.hot_topics(force=force)
    return jsonify({"success": True, "count": len(items),
                    "sources": [s["name"] for s in proactive.SOURCES],
                    "llm": _proactive_llm_desc(),
                    "items": items[:40]})


@app.route("/api/quirky/auto/topic", methods=["POST"])
def api_quirky_auto_topic():
    """QQ bot stack component."""
    if proactive is None:
        return jsonify({"success": False, "message": "proactive 模块没加载起来"})
    d = request.get_json(silent=True) or {}
    gid = int(d.get("group_id") or 0)
    if not gid:
        gs = _quirky_groups()
        gid = gs[0] if gs else 0
    if not gid:
        return jsonify({"success": False, "message": "没有可用的群"})
    if not _proactive_ready():
        return jsonify({"success": False,
                        "message": f"模型不可用：{_proactive_llm_desc()}"})
    if d.get("dry_run"):
        
        items = proactive.hot_topics(force=bool(d.get("force")))
        text, title = proactive.make_opening(
            _proactive_llm(), items, proactive.group_name_of(gid),
            list(_QUIRKY_AUTO_STATE.get("topics_used") or []))
        if not text:
            return jsonify({"success": False, "message": "模型没给出开场白"})
        return jsonify({"success": True, "preview": True, "text": text, "title": title})
    ok = _send_topic_to(gid, str(gid), time.time(),
                        time.time() - _group_latest_ts(gid))
    if not ok:
        return jsonify({"success": False, "message": _QUIRKY_AUTO_STATE.get("message", "失败")})
    pend = (_QUIRKY_AUTO_STATE.get("pending") or {}).get(str(gid)) or {}
    return jsonify({"success": True, "message": _QUIRKY_AUTO_STATE.get("message", "已发"),
                    "text": pend.get("text", ""), "title": pend.get("title", "")})


@app.route("/api/quirky/auto/send", methods=["POST"])
def api_quirky_auto_send():
    """QQ bot stack component."""
    d = request.get_json(silent=True) or {}
    gid = int(d.get("group_id") or 0)
    if not gid:
        gs = _quirky_groups()
        gid = gs[0] if gs else 0
    if not gid:
        return jsonify({"success": False, "message": "没有可用的群"})
    item = _quirky_pick()
    if not item:
        return jsonify({"success": False, "message": "怪话库空了，先去加几条"})
    ok, info = _quirky_send(gid, str(item.get("text", "")))
    if ok:
        _quirky_mark_used(item.get("id", ""))
        _proactive_record_sent(gid, str(gid), item.get("text", ""), time.time(), "quirky")
        return jsonify({"success": True, "message": f"已发到群 {gid}：「{item.get('text','')[:40]}」",
                        "text": item.get("text", "")})
    return jsonify({"success": False, "message": f"发送失败: {info}"})




def _strip_reply_prefix(text: str) -> str:
    """QQ bot stack component."""





    t = str(text or "")
    idx = t.rfind("]")
    if idx >= 0 and "[回复" in t[: idx + 1] and len(t[idx + 1:].strip()) >= 2:
        return t[idx + 1:].strip()
    return t.strip()


def _split_reply_target(text: str):
    """QQ bot stack component."""




    raw = str(text or "")
    import re as _re
    m = _re.match(r"\s*\[回复<([^:<>]+):([^:<>]+)>", raw)
    body = _strip_reply_prefix(raw)
    if m:
        return m.group(1).strip(), m.group(2).strip(), body
    return "", "", body


def _maibot_bot_qq() -> str:
    """QQ bot stack component."""
    try:
        import tomllib
        with open(MAIBOT_CONFIG, "rb") as f:
            cfg = tomllib.load(f)
        return str((cfg.get("bot") or {}).get("qq_account", "") or "")
    except Exception:
        return ""


def _maibot_message_schema():
    """QQ bot stack component."""







    import sqlite3
    con = sqlite3.connect(f"file:{MAIBOT_DB}?mode=ro", uri=True, timeout=8)
    try:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
        for table in ("mai_messages", "messages"):
            if table not in tables:
                continue
            cols = {r[1] for r in con.execute(f'pragma table_info("{table}")')}
            return {
                "table": table,
                "time": "timestamp" if "timestamp" in cols else "time",
                "group_id": "group_id" if "group_id" in cols else "chat_info_group_id",
                "group_name": "group_name" if "group_name" in cols else "chat_info_group_name",
                "display": "display_message" if "display_message" in cols else None,
            }
        return None
    finally:
        con.close()


def _maibot_row_ts(value):
    """QQ bot stack component."""




    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


@app.route("/api/bot_speeches")
def api_bot_speeches():
    """QQ bot stack component."""
    def _int(name, default, lo, hi):
        try:
            return max(lo, min(hi, int(request.args.get(name, default))))
        except (TypeError, ValueError):
            return default

    limit = _int("limit", 50, 1, 200)
    offset = _int("offset", 0, 0, 10 ** 7)
    group = str(request.args.get("group", "") or "").strip()
    kw = str(request.args.get("q", "") or "").strip()

    if not os.path.isfile(MAIBOT_DB):
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [],
                        "message": f"找不到麦麦的消息库：{MAIBOT_DB}"})
    bot_qq = _maibot_bot_qq()
    if not bot_qq:
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [],
                        "message": f"读不到机器人 QQ（{MAIBOT_CONFIG} 的 [bot] qq_account）"})

    schema = _maibot_message_schema()
    if not schema:
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [],
                        "message": f"消息库里既没有 mai_messages 也没有 messages：{MAIBOT_DB}"})

    try:
        import sqlite3
        
        con = sqlite3.connect(f"file:{MAIBOT_DB}?mode=ro", uri=True, timeout=8)
        try:
            con.row_factory = sqlite3.Row
            cur = con.cursor()
            table = schema["table"]
            col_time = schema["time"]
            col_gid = schema["group_id"]
            col_gname = schema["group_name"]
            display_expr = schema["display"] or "processed_plain_text"
            where = ["CAST(user_id AS TEXT) = ?"]
            args: list = [bot_qq]
            if group:
                where.append(f"CAST({col_gid} AS TEXT) = ?")
                args.append(group)
            if kw:
                where.append("processed_plain_text LIKE ?")
                args.append(f"%{kw}%")
            cond = " AND ".join(where)

            cur.execute(f"SELECT COUNT(*) FROM {table} WHERE {cond}", args)
            total = int(cur.fetchone()[0])

            cur.execute(
                f"SELECT message_id, {col_time} AS mtime, {col_gid} AS gid, {col_gname} AS gname,"
                f" processed_plain_text, {display_expr} AS display_message"
                f" FROM {table} WHERE {cond} ORDER BY mtime DESC LIMIT ? OFFSET ?",
                args + [limit, offset],
            )
            rows = []
            for r in cur.fetchall():
                ts = _maibot_row_ts(r["mtime"])
                r_name, r_uid, body = _split_reply_target(
                    r["processed_plain_text"] or r["display_message"] or "")
                rows.append({
                    "message_id": str(r["message_id"] or ""),
                    "ts": ts,
                    "time": datetime.fromtimestamp(ts).strftime("%m-%d %H:%M:%S") if ts else "",
                    "group_id": str(r["gid"] or ""),
                    "group_name": str(r["gname"] or ""),
                    "text": body,
                    "reply_name": r_name,
                    "reply_uid": r_uid,
                })

            
            cur.execute(
                f"SELECT {col_gid} AS gid, {col_gname} AS gname, COUNT(*) AS n"
                f" FROM {table} WHERE CAST(user_id AS TEXT) = ?"
                f" GROUP BY gid ORDER BY n DESC",
                [bot_qq],
            )
            groups = [{"group_id": str(g["gid"] or ""), "group_name": str(g["gname"] or ""),
                       "count": int(g["n"] or 0)} for g in cur.fetchall()]
        finally:
            con.close()
    except Exception as e:
        return jsonify({"success": False, "rows": [], "total": 0, "groups": [],
                        "message": f"{type(e).__name__}: {e}"})

    return jsonify({"success": True, "rows": rows, "total": total, "limit": limit,
                    "offset": offset, "groups": groups, "bot_qq": bot_qq, "db": MAIBOT_DB})


@app.route("/api/service/<key>/<action>", methods=["POST"])
def api_service(key, action):
    if key not in SERVICES:
        return jsonify({"success": False, "message": "未知服务"}), 404
    if action == "start":
        ok, msg = start_service(key)
    elif action == "stop":
        ok, msg = stop_service(key)
    elif action == "restart":
        stop_service(key)
        time.sleep(1)
        ok, msg = start_service(key)
    elif action == "start-all":
        ok, msg = True, ""
    else:
        return jsonify({"success": False, "message": "未知操作"}), 400
    return jsonify({"success": ok, "message": f"{SERVICES[key]['label']}: {msg}"})


@app.route("/api/snowluma/<action>", methods=["POST"])
def api_snowluma(action):
    return jsonify({"success": False, "message": "请自行运行和维护 QQ 与 OneBot 适配器。"}), 501


@app.route("/api/service-all/<action>", methods=["POST"])
def api_service_all(action):
    if action not in ("start", "stop"):
        return jsonify({"success": False, "message": "未知操作"}), 400
    result = subprocess.run([sys.executable, os.path.join(BASE_DIR, "tools", "stack.py"), action], capture_output=True, timeout=90)
    return jsonify({"success": result.returncode == 0, "message": decode_output(result.stdout) + decode_output(result.stderr)})


def _snowluma_spawn(action):
    return False, "请自行管理 QQ 和 OneBot 适配器。"


def _service_all_impl(action):
    msgs = []
    all_ok = True
    
    
    
    skip = {"napcat", "adapter"} if snowluma_mode() else set()
    if action == "start":
        
        if snowluma_mode() and not port_open(5099):
            if _snowluma_spawn("start"):
                msgs.append("SnowLuma（QQ 接入）: 未运行 → 已在后台启动（最长 4 分钟，状态会随刷新更新）")
            else:
                msgs.append("SnowLuma（QQ 接入）: 已在启动/停止中，跳过")
        for k in START_ORDER:
            if k in skip:
                continue
            ok, msg = start_service(k)
            msgs.append(f"{SERVICES[k]['label']}: {msg}")
            
            
            already = "已在运行" in msg
            if not (ok or already):
                all_ok = False
                continue
            
            
            rp = SERVICES[k].get("ready_port") or SERVICES[k].get("port")
            waited = wait_for_port(rp, timeout=45)
            if not waited:
                all_ok = False
                msgs.append(f"    ⚠ 等待端口 {rp} 超时（45 秒），后续服务可能连不上")
                
                for ln in service_log(k, 6)[-3:]:
                    msgs.append(f"      日志: {ln.strip()[:160]}")
    elif action == "stop":
        for k in STOP_ORDER:
            if k in skip:
                continue
            ok, msg = stop_service(k)
            msgs.append(f"{SERVICES[k]['label']}: {msg}")
            
            all_ok = all_ok and (ok or "未在运行" in msg)
    else:
        return jsonify({"success": False, "message": "未知操作"}), 400
    return jsonify({"success": all_ok, "message": "\n".join(msgs)})


@app.route("/api/hmml/ensure", methods=["POST"])
def api_hmml_ensure():
    return jsonify({"success": False, "message": "请在所安装的 MaiBot 中单独运行 HMML。"}), 501







MON_PROXY_ALLOW = {
    "stats", "messages", "messages/file", "alerts", "alerts/users", "groups",
    "groups/info", "storage", "storage/attachments", "folders", "pending-files",
    
    "export/all", "export/word", "export/word/status",
    
    "history/backfill", "history/backfill/status", "history/topup",
}
_MON_GROUP_PATHS = re.compile(r"^groups/\d+/dates$")


def monitor_access_token():
    """QQ bot stack component."""
    try:
        with open(MONITOR_CONFIG, encoding="utf-8") as f:
            return ((json.load(f).get("web_panel") or {}).get("access_token") or "").strip()
    except Exception:
        return ""


def _ps_capture(script):
    """QQ bot stack component."""
    try:
        r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", script],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=25, creationflags=_CREATE_NO_WINDOW)
        return (r.stdout or "").strip()
    except Exception:
        return ""


@app.route("/api/autostart")
def api_autostart():
    return jsonify({"success": True, "items": [], "message": "公开版不管理系统自启项，请自行按需配置。"})


@app.route("/api/autostart", methods=["POST"])
def api_autostart_set():
    return jsonify({"success": False, "message": "公开版不管理系统自启项。"}), 501


@app.route("/api/health")
def api_health():
    """QQ bot stack component."""
    svcs = [{"key": k, "label": SERVICES[k]["label"]}
            for k in SERVICES
            if not (snowluma_mode() and k in ("napcat", "adapter"))]
    return jsonify({
        "success": True,
        "services": svcs,
        "samples": [{"t": ts, "s": st} for ts, st in _HEALTH_DEQUE],
        "interval": 60,
        "now": time.time(),
    })


@app.route("/api/trend")
def api_trend():
    """QQ bot stack component."""
    now = time.time()
    if _TREND_CACHE[0] and now - _TREND_CACHE[0] < 60:
        return jsonify(_TREND_CACHE[1])
    try:
        with urllib.request.urlopen(f"{MONITOR_BASE}/api/groups", timeout=5) as r:
            groups = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return jsonify({"success": False, "message": f"监控服务不可用：{e}"}), 502

    def _total(path):
        try:
            with urllib.request.urlopen(
                    f"{MONITOR_BASE}/api/messages?{path}&page_size=1", timeout=5) as r:
                return json.loads(r.read().decode("utf-8")).get("total", 0)
        except Exception:
            return 0

    available = set()
    for g in groups:
        available.update(g.get("available_dates", []))
    dates = sorted(available, reverse=True)[:14]
    
    days = [{"date": d, "total": _total(
                urllib.parse.quote(f"start_time={d} 00:00:00&end_time={d} 23:59:59", safe='=&'))}
            for d in dates]

    
    names = {}
    try:
        for g in group_switches_get().get("groups", []):
            if g.get("group_name"):
                names[g["group_id"]] = g["group_name"]
    except Exception:
        pass

    grp = []
    for g in groups:
        gid = g.get("group_id")
        if not gid:
            continue
        grp.append({"group_id": gid,
                    "group_name": names.get(gid, str(gid)),
                    "total": _total(f"group_id={gid}")})
    grp.sort(key=lambda x: x["total"], reverse=True)

    payload = {"success": True, "days": days, "groups": grp}
    _TREND_CACHE[0] = now
    _TREND_CACHE[1] = payload
    return jsonify(payload)


@app.route("/api/mon/<path:sub>", methods=["GET", "POST"])
def api_mon_proxy(sub):
    if sub not in MON_PROXY_ALLOW and not _MON_GROUP_PATHS.match(sub):
        return jsonify({"success": False, "message": f"不允许访问监控接口 {sub}"}), 403
    qs = request.query_string.decode("utf-8")
    url = f"{MONITOR_BASE}/api/{sub}" + (f"?{qs}" if qs else "")
    
    body = request.get_data() if request.method == "POST" else None
    req = urllib.request.Request(url, data=body, method=request.method)
    if body:
        req.add_header("Content-Type", "application/json")
    tok = monitor_access_token()
    if tok:
        req.add_header("X-Access-Token", tok)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return Response(r.read(), mimetype="application/json")
    except urllib.error.HTTPError as e:
        
        
        
        
        try:
            detail = e.read()
        except Exception:
            detail = b""
        if not detail:
            detail = json.dumps(
                {"success": False, "message": f"监控返回 HTTP {e.code}"},
                ensure_ascii=False).encode("utf-8")
        return Response(detail, status=e.code, mimetype="application/json")
    except Exception as e:
        return jsonify({"success": False, "message": f"监控服务不可用：{e}"}), 502


@app.route("/api/pick_dir", methods=["POST"])
def api_pick_dir():
    """QQ bot stack component."""





    try:
        if not IS_WIN:
            
            
            return jsonify({"success": False, "cancelled": False,
                            "message": "Linux 模式下没有图形目录选择框，请直接在输入框里填绝对路径"
                                       "（例如 /srv/botdata/聊天记录导出）"})
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:
            pass
        path = filedialog.askdirectory(title="选择聊天记录导出目录")
        root.destroy()
        if not path:
            return jsonify({"success": False, "cancelled": True, "message": "没有选择目录"})
        return jsonify({"success": True, "path": os.path.abspath(path)})
    except Exception as e:
        return jsonify({"success": False,
                        "message": f"打不开目录选择框：{type(e).__name__}: {e}"})


@app.route("/api/export/chat", methods=["POST"])
def api_export_chat():
    """QQ bot stack component."""




    d = request.get_json(silent=True) or {}
    target = str(d.get("dir") or "").strip()

    if target:
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            return jsonify({"success": False,
                            "message": f"这个目录建不出来：{type(e).__name__}: {e}"}), 400
        try:
            monitor_export_dir_set(target)
        except Exception as e:
            return jsonify({"success": False,
                            "message": f"写监控配置失败：{type(e).__name__}: {e}"}), 500

    body = json.dumps({"export_dir": target} if target else {}).encode("utf-8")
    req = urllib.request.Request(MONITOR_BASE + "/api/export/all", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    tok = monitor_access_token()
    if tok:
        req.add_header("X-Access-Token", tok)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            out = json.loads(r.read().decode("utf-8"))
        if out.get("success"):
            out["message"] = f"导出完成：{out.get('exported', '?')} 条记录 → {out.get('export_dir', '')}"
        return jsonify(out)
    except Exception as e:
        return jsonify({"success": False,
                        "message": f"导出失败（监控服务要用「服务控制」启动）：{e}"}), 502


@app.route("/api/export/word", methods=["POST"])
def api_export_word():
    """QQ bot stack component."""





    d = request.get_json(silent=True) or {}
    target = str(d.get("dir") or "").strip()

    if target:
        try:
            os.makedirs(target, exist_ok=True)
        except Exception as e:
            return jsonify({"success": False,
                            "message": f"这个目录建不出来：{type(e).__name__}: {e}"}), 400
        try:
            monitor_export_dir_set(target)
        except Exception as e:
            return jsonify({"success": False,
                            "message": f"写监控配置失败：{type(e).__name__}: {e}"}), 500

    body = json.dumps({"dir": target} if target else {}).encode("utf-8")
    req = urllib.request.Request(MONITOR_BASE + "/api/export/word", data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    tok = monitor_access_token()
    if tok:
        req.add_header("X-Access-Token", tok)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return jsonify(json.loads(r.read().decode("utf-8")))
    except Exception as e:
        return jsonify({"success": False,
                        "message": f"启动 Word 导出失败（监控服务要用「服务控制」启动）：{e}"}), 502


@app.route("/api/mon/health")
def api_mon_health():
    """QQ bot stack component."""
    return jsonify({"running": port_open(8080, force=True),
                    "base": MONITOR_BASE,
                    "token": monitor_access_token()})


@app.route("/api/logs/<key>")
def api_logs(key):
    if key == "panel":
        n = request.args.get("lines", 200, type=int)
        return jsonify({"key": "panel", "label": "统一控制台自身",
                        "lines": service_log("panel", max(20, min(n, 1000)))})
    if key not in SERVICES:
        return jsonify({"error": "未知服务"}), 404
    n = request.args.get("lines", 200, type=int)
    return jsonify({"key": key, "label": SERVICES[key]["label"],
                    "lines": service_log(key, max(20, min(n, 1000)))})


def toml_syntax_problem(text):
    """QQ bot stack component."""





    try:
        import tomllib
        tomllib.loads(text)
        return ""
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def write_toml_checked(path, original, new_text):
    """QQ bot stack component."""




    if new_text == original:
        return False, ""
    err = toml_syntax_problem(new_text)
    if err:
        return False, f"改完不是合法 TOML，已拒绝写入：{err}"
    save_text_if_changed(path, original, new_text)
    return True, ""


def config_syntax_problems():
    """QQ bot stack component."""




    out = []
    for path, label in ((MAIBOT_CONFIG, "麦麦配置 bot_config.toml"),
                        (MAIBOT_MODEL_CONFIG, "麦麦模型 model_config.toml"),
                        (ADAPTER_CONFIG, "适配器配置 config.toml")):
        if not os.path.isfile(path):
            continue
        err = toml_syntax_problem(read_text(path))
        if err:
            out.append({"file": path, "label": label, "error": err})
    try:
        with open(MONITOR_CONFIG, encoding="utf-8") as f:
            json.load(f)
    except Exception as e:
        out.append({"file": MONITOR_CONFIG, "label": "监控配置 config.json",
                    "error": f"{type(e).__name__}: {e}"})
    return out


@app.route("/api/config/maibot", methods=["GET", "POST"])
def api_cfg_maibot():
    if request.method == "GET":
        return jsonify({"fields": maibot_config_get(), "path": MAIBOT_CONFIG})
    data = request.get_json(force=True) or {}
    changed, failed, err = maibot_config_set(data.get("fields", []))
    if err:
        return jsonify({"success": False, "changed": [], "failed": failed, "message": err})
    return jsonify({"success": True, "changed": changed, "failed": failed,
                    "message": f"已更新 {len(changed)} 项" + (f"，失败 {failed}" if failed else "")})


@app.route("/api/config/adapter", methods=["GET", "POST"])
def api_cfg_adapter():
    if request.method == "GET":
        out = {"fields": adapter_config_get(), "path": ADAPTER_CONFIG}
        if not os.path.isfile(ADAPTER_CONFIG):      
            out["retired"] = True
            out["message"] = ADAPTER_RETIRED_MSG
        return jsonify(out)
    data = request.get_json(force=True) or {}
    changed, failed, err = adapter_config_set(data.get("fields", []))
    if err:
        return jsonify({"success": False, "changed": [], "failed": failed, "message": err})
    return jsonify({"success": True, "changed": changed, "failed": failed,
                    "message": f"已更新 {len(changed)} 项" + (f"，失败 {failed}" if failed else "")})




@app.route("/api/model/config", methods=["GET"])
def api_model_config():
    try:
        return jsonify({"success": True, **model_config_get()})
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 500


def _model_op(fn, *args):
    try:
        ok, note = fn(*args)
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"success": ok, "message": note})


@app.route("/api/model/provider", methods=["POST"])
def api_model_provider():
    return _model_op(model_provider_save, request.get_json(force=True) or {})


@app.route("/api/model/provider/<name>", methods=["DELETE"])
def api_model_provider_del(name):
    return _model_op(model_provider_delete, name)


@app.route("/api/model/model", methods=["POST"])
def api_model_model():
    return _model_op(model_save, request.get_json(force=True) or {})


@app.route("/api/model/model/<name>", methods=["DELETE"])
def api_model_model_del(name):
    return _model_op(model_delete, name)


@app.route("/api/model/task", methods=["POST"])
def api_model_task():
    return _model_op(model_task_save, request.get_json(force=True) or {})




@app.route("/api/groups/switches", methods=["GET", "POST"])
def api_group_switches():
    if request.method == "GET":
        try:
            return jsonify({"success": True, **group_switches_get()})
        except Exception as e:
            return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 500
    data = request.get_json(force=True) or {}
    try:
        ok, msg = group_switches_set(data.get("groups", []))
    except Exception as e:
        return jsonify({"success": False, "message": f"{type(e).__name__}: {e}"}), 500
    return jsonify({"success": ok, "message": msg})


@app.route("/api/config/monitor", methods=["GET", "POST"])
def api_cfg_monitor():
    if request.method == "GET":
        return jsonify(monitor_config_get())
    ok, msg = monitor_config_set(request.get_json(force=True) or {})
    return jsonify({"success": ok, "message": msg})


@app.route("/api/cg_prompts", methods=["GET", "POST"])
def api_cg_prompts():
    """QQ bot stack component."""
    if request.method == "GET":
        try:
            return jsonify({"ok": True, "data": cg_prompts_get(), "path": CG_PROMPTS_FILE})
        except FileNotFoundError:
            return jsonify({"ok": False, "data": {}, "path": CG_PROMPTS_FILE,
                            "message": f"没找到 {CG_PROMPTS_FILE}（麦麦插件还没生成它？）"})
        except Exception as e:
            return jsonify({"ok": False, "data": {}, "path": CG_PROMPTS_FILE,
                            "message": f"{type(e).__name__}: {e}"}), 500
    body = request.get_json(force=True, silent=True) or {}
    ok, msg = cg_prompts_set(body.get("data"))
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/keyword_reply", methods=["GET", "POST"])
def api_keyword_reply():
    """QQ bot stack component."""




    if request.method == "GET":
        try:
            return jsonify({"success": True, "data": keyword_reply_get(), "path": KEYWORD_FILE})
        except Exception as e:
            return jsonify({"success": False, "data": {},
                            "message": f"读不到 {KEYWORD_FILE}：{type(e).__name__}: {e}"}), 500
    body = request.get_json(force=True, silent=True) or {}
    ok, msg = keyword_reply_set(body.get("data"))
    return jsonify({"success": ok, "message": msg})


@app.route("/api/config/rules", methods=["GET", "POST"])
def api_cfg_rules():
    if request.method == "GET":
        return jsonify(rules_get())
    ok, msg = rules_set(request.get_json(force=True) or {})
    return jsonify({"success": ok, "message": msg})





LONGTERM_DB = os.path.join(MONITOR_DIR, "data", "memory_keeper.db")


def _lt_conn(read_only=True):
    """QQ bot stack component."""
    if not os.path.exists(LONGTERM_DB):
        return None
    target = f"file:{LONGTERM_DB}?mode=ro" if read_only else LONGTERM_DB
    con = sqlite3.connect(target, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


_LT_PAGE = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>长期记忆管家 · 示例角色</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
button[onclick*="snowAct"],button[onclick*="ensureHmml"],button[onclick*="ensureHMML"]{display:none !important;}

body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:20px}
h1{font-size:20px;margin:0 0 12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
select,input,button{background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:6px 10px;font-size:13px}
button{cursor:pointer}button:hover{background:#334155}
.stats{font-size:12px;color:#94a3b8;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid #1e293b;text-align:left;vertical-align:top}
th{color:#94a3b8;font-weight:500}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px}
.agreement{background:#7c2d12}.trivia{background:#1e3a5f}.nickname{background:#3b0764}.affection{background:#701a37}
.done{color:#64748b}.active{color:#34d399}small{color:#64748b}
</style></head><body>
<h1>🧠 长期记忆管家 <small>按人和时间查助手记住的每件事</small></h1>
<div class="stats" id="stats">加载中…</div>
<div class="bar">
 <select id="person"><option value="">所有人</option></select>
 <select id="cat"><option value="">全部类型</option><option value="agreement">约定</option><option value="trivia">琐事</option><option value="nickname">称呼</option><option value="affection">好感事件</option></select>
 <select id="status"><option value="">全部状态</option><option value="active">待处理</option><option value="done">已完成</option></select>
 <input id="from" type="date"><input id="to" type="date">
 <button onclick="load()">查询</button>
</div>
<table><thead><tr><th>人</th><th>类型</th><th>内容</th><th>到期</th><th>状态</th><th>记录时间</th><th>群</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
const CAT={agreement:'约定',trivia:'琐事',nickname:'称呼',affection:'好感'};
async function load(){
 const q=new URLSearchParams();
 const p=document.getElementById('person').value,c=document.getElementById('cat').value,
 s=document.getElementById('status').value,f=document.getElementById('from').value,t=document.getElementById('to').value;
 if(p)q.set('person_id',p);if(c)q.set('category',c);if(s)q.set('status',s);if(f)q.set('date_from',f);if(t)q.set('date_to',t);
 const r=await fetch('/api/longterm/memories?'+q);const d=await r.json();
 document.getElementById('rows').innerHTML=(d.items||[]).map(m=>
  `<tr><td>${m.person_name||''}<br><small>${m.person_id}</small></td>
   <td><span class="tag ${m.category}">${CAT[m.category]||m.category}</span></td><td>${m.content}</td>
   <td>${m.due_at||'-'}</td><td class="${m.status}">${m.status==='done'?'已完成':'待处理'}</td>
   <td>${m.created_at}</td><td>${m.group_id||''}</td></tr>`).join('')||'<tr><td colspan="7">没有记录</td></tr>';
}
async function boot(){
 try{
  const s=await fetch('/api/longterm/stats');const st=await s.json();
  document.getElementById('stats').textContent=`共 ${st.total} 条 / 待处理 ${st.active} / 人数 ${st.persons} / 待到期追问 ${st.pending_due} ｜ 模型 ${st.model}`;
  const r=await fetch('/api/longterm/persons');const d=await r.json();
  document.getElementById('person').innerHTML='<option value="">所有人</option>'+(d.persons||[]).map(p=>
   `<option value="${p.person_id}">${p.display_name||p.person_id}（好感${p.affection}/记事${p.c}）</option>`).join('');
 }catch(e){document.getElementById('stats').textContent='监控数据加载失败：'+e;}
 load();
}
boot();
</script></body></html>"""


@app.route("/memory")
def longterm_memory_page():
    return render_template_string(_LT_PAGE)


@app.route("/api/longterm/stats")
def api_longterm_stats():
    con = _lt_conn()
    if con is None:
        return jsonify({"ok": True, "total": 0, "active": 0, "persons": 0,
                        "pending_due": 0, "model": "(见监控配置)",
                        "hint": "长期记忆库还没生成（监控还没跑过或没启用这一块）"})
    try:
        def _c(sql, p=()):
            return con.execute(sql, p).fetchone()[0]
        now_cn = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        return jsonify({
            "ok": True,
            "total": _c("SELECT COUNT(*) FROM memories"),
            "active": _c("SELECT COUNT(*) FROM memories WHERE status='active'"),
            "persons": _c("SELECT COUNT(*) FROM persons"),
            "pending_due": _c("SELECT COUNT(*) FROM memories WHERE status='active'"
                              " AND category='agreement' AND due_at IS NOT NULL AND due_at<=?", (now_cn,)),
            "model": "(见监控配置)",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e),
                        "total": 0, "active": 0, "persons": 0, "pending_due": 0,
                        "model": "(见监控配置)"})
    finally:
        con.close()


@app.route("/api/longterm/persons")
def api_longterm_persons():
    con = _lt_conn()
    if con is None:
        return jsonify({"ok": True, "persons": []})
    try:
        rows = con.execute(
            "SELECT p.person_id, p.display_name, p.affection, COUNT(m.id) AS c "
            "FROM persons p LEFT JOIN memories m ON m.person_id=p.person_id "
            "GROUP BY p.person_id ORDER BY p.affection DESC, c DESC").fetchall()
        return jsonify({"ok": True, "persons": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "persons": []})
    finally:
        con.close()


@app.route("/api/longterm/memories")
def api_longterm_memories():
    con = _lt_conn()
    if con is None:
        return jsonify({"ok": True, "items": []})
    try:
        where, params = [], []
        a = request.args
        if a.get("person_id"):
            where.append("m.person_id=?"); params.append(a.get("person_id"))
        if a.get("group_id"):
            where.append("m.group_id=?"); params.append(a.get("group_id"))
        if a.get("category"):
            where.append("m.category=?"); params.append(a.get("category"))
        if a.get("status"):
            where.append("m.status=?"); params.append(a.get("status"))
        if a.get("date_from"):
            where.append("m.created_at>=?"); params.append(a.get("date_from"))
        if a.get("date_to"):
            where.append("m.created_at<=?"); params.append(a.get("date_to") + " 23:59:59")
        sql = "SELECT m.* FROM memories m"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY m.created_at DESC, m.id DESC LIMIT ? OFFSET ?"
        params.extend([min(int(a.get("limit", 100)), 500), int(a.get("offset", 0))])
        rows = con.execute(sql, params).fetchall()
        return jsonify({"ok": True, "items": [dict(r) for r in rows]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "items": []})
    finally:
        con.close()






def _diary_proxy(path, payload=None):
    """QQ bot stack component."""
    headers = {"Content-Type": "application/json"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request("http://127.0.0.1:8080/api/diary/" + path,
                                 data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=8) as response:
            result = json.loads(response.read(4 * 1024 * 1024))
        if not isinstance(result, dict):
            raise ValueError("invalid diary response")
        return jsonify(result)
    except urllib.error.HTTPError as exc:
        message = "日记服务暂时无法完成请求"
        try:
            detail = json.loads(exc.read(16384))
            if isinstance(detail, dict) and isinstance(detail.get("error"), str):
                message = detail["error"][:300]
        except (ValueError, OSError):
            pass
        code = exc.code if exc.code in (400, 404, 409, 422, 429) else 502
        return jsonify({"error": message}), code
    except Exception:
        return jsonify({"error": "暂时联系不上日记本，请稍后刷新"}), 502


def _diary_filters(args):
    allowed = {"date", "group_id", "user_id", "q", "limit"}
    if set(args) - allowed:
        raise ValueError("不支持的查询条件")
    result = {k: args.get(k, "").strip() for k in allowed if args.get(k, "")}
    if result.get("date"):
        value = result["date"]
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("日期格式应为年-月-日")
        datetime.strptime(value, "%Y-%m-%d")
    for key in ("group_id", "user_id"):
        if key in result and not re.fullmatch(r"[0-9]{1,20}", result[key]):
            raise ValueError("群号或用户号格式有误")
    if len(result.get("q", "")) > 200:
        raise ValueError("关键词请控制在200字以内")
    if "limit" in result:
        if not result["limit"].isdigit() or not 1 <= int(result["limit"]) <= 100:
            raise ValueError("每次最多查询100条")
    return result


@app.route("/api/diary/status")
def api_diary_status():
    return _diary_proxy("status")


@app.route("/api/diary/<kind>")
def api_diary_query(kind):
    if kind not in ("list", "search"):
        return jsonify({"error": "未找到此日记功能"}), 404
    try:
        args = _diary_filters(request.args)
    except (ValueError, TypeError):
        return jsonify({"error": "查询条件有误，请检查日期、群号和关键词"}), 400
    return _diary_proxy(kind + "?" + urllib.parse.urlencode(args))


@app.route("/api/diary/detail/<entry_id>")
def api_diary_detail(entry_id):
    if not re.fullmatch(r"[0-9]{1,18}", entry_id):
        return jsonify({"error": "日记编号有误"}), 400
    return _diary_proxy("detail/" + entry_id)


@app.route("/api/notebook")
def api_notebook_list():
    q = request.args.get("q", "").strip()
    if len(q) > 200:
        return jsonify({"error": "关键词请控制在200字以内"}), 400
    return _diary_proxy("notebook?" + urllib.parse.urlencode({"q": q, "limit": "50"}))


@app.route("/api/notebook/<entry_id>")
def api_notebook_detail(entry_id):
    if not re.fullmatch(r"[0-9]{1,18}", entry_id):
        return jsonify({"error": "本子页码有误"}), 400
    return _diary_proxy("notebook/" + entry_id)


@app.route("/api/diary/generate", methods=["POST"])
def api_diary_generate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {"date", "group_id"}:
        return jsonify({"error": "请选择日记日期"}), 400
    try:
        if not all(isinstance(data.get(k), str) and data[k] for k in ("date", "group_id")):
            raise ValueError()
        args = _diary_filters(data)
        today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        if args["date"] > today:
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({"error": "请选择今天或过去的日期"}), 400
    return _diary_proxy("generate", args)


@app.route("/diary")
def diary_page():
    return render_template_string(PAGE)


@app.route("/notebook")
def notebook_page():
    return render_template_string(PAGE)


@app.route("/")
def index():
    return render_template_string(PAGE)




PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQ 机器人统一控制台</title>
<style>
button[onclick*="snowAct"],button[onclick*="ensureHmml"],button[onclick*="ensureHMML"]{display:none !important;}

/* ===================== 设计令牌 =====================
   所有颜色/圆角/间距都从这里取，避免"这里 #667eea、那里 #5b5bd6"，
   也方便以后整体换色只改一行。 */
:root{
  --brand:#4f5bd5; --brand2:#7a5cf0; --brand-weak:#eef0ff; --brand-line:#c7cbf7;
  --bg:#f4f6fa; --card:#fff;
  --line:#e6e8ee; --line2:#f0f2f6;
  --t1:#1d2129; --t2:#4e5969; --t3:#8a92a6;
  --ok:#00a854; --ok-bg:#eafaf0; --ok-line:#b7ebc9;
  --warn:#c26a00; --warn-bg:#fff8e6; --warn-line:#ffe0a3;
  --err:#e5484d; --err-bg:#fdecec; --err-line:#f9c9cb;
  --r:14px; --r-sm:9px;
  --sh:0 1px 2px rgba(29,33,41,.04), 0 8px 24px -12px rgba(29,33,41,.16);
  --sh-hi:0 2px 6px rgba(29,33,41,.06), 0 14px 32px -14px rgba(29,33,41,.22);
  --mono:ui-monospace,SFMono-Regular,Consolas,"Cascadia Mono",monospace;
}
/* ============ 暗色主题（html[data-theme="dark"]） ============ */
html[data-theme="dark"]{
  --brand:#7b8cff; --brand2:#9a7bff; --brand-weak:#252a45; --brand-line:#3a3f66;
  --bg:#0e1016; --card:#161922;
  --line:#262b38; --line2:#1f232e;
  --t1:#e8eaf0; --t2:#a9b0c0; --t3:#68708a;
  --ok:#3ddc84; --ok-bg:#12281c; --ok-line:#1e5a38;
  --warn:#f0a24a; --warn-bg:#291f12; --warn-line:#5a421e;
  --err:#f26d6d; --err-bg:#2a1517; --err-line:#5a2b2e;
  --sh:0 1px 2px rgba(0,0,0,.4), 0 8px 24px -12px rgba(0,0,0,.6);
  --sh-hi:0 2px 6px rgba(0,0,0,.5), 0 14px 32px -14px rgba(0,0,0,.7);
}
html[data-theme="dark"] body{background:var(--bg)}
html[data-theme="dark"] .svc{background:#1a1e2a}
html[data-theme="dark"] .svc.on{background:linear-gradient(180deg,#122018,#0e1a14)}
html[data-theme="dark"] .tabs{background:var(--card)}
html[data-theme="dark"] .header{background:linear-gradient(120deg,#232a4d 0%,#2a2652 55%,#33206a 100%)}
html[data-theme="dark"] .log{background:#0b0d12;color:#c8cfdd;border-color:var(--line)}
/* 服务稳定性色块 */
.hb{width:9px;height:16px;border-radius:2px;background:#e4e7ee;flex:none}
.hb-ok{background:var(--ok)}
.hb-bad{background:var(--err)}
.hb-gray{background:#d5d9e4}
html[data-theme="dark"] .hb{background:#2a2f3d}
html[data-theme="dark"] .hb-gray{background:#262b38}
*{margin:0;padding:0;box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:"Microsoft YaHei",-apple-system,"Segoe UI",sans-serif;background:var(--bg);
  color:var(--t1);font-size:14px;line-height:1.6;-webkit-font-smoothing:antialiased}
/* 细一点、跟主题同色的滚动条，默认那种灰色很抢眼 */
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#cfd4e0;border-radius:6px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:#b3bacb;background-clip:content-box}
::-webkit-scrollbar-track{background:transparent}
:focus-visible{outline:2px solid var(--brand);outline-offset:2px;border-radius:4px}

/* ===================== 顶部 ===================== */
.header{background:linear-gradient(120deg,#4f5bd5 0%,#6a54d8 55%,#8a5cf0 100%);color:#fff;
  padding:20px 28px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.header h1{font-size:19px;font-weight:600;letter-spacing:.3px;display:flex;align-items:center;gap:10px}
.header .t{font-size:12.5px;opacity:.92;font-variant-numeric:tabular-nums;
  background:rgba(255,255,255,.15);padding:5px 12px;border-radius:999px;backdrop-filter:blur(4px)}
.container{max-width:1360px;margin:18px auto;padding:0 18px}

/* ===================== 页签（吸顶 + 按用途分组） =====================
   11 个页签平铺一排会很挤（视觉模型评审两次都点了这一条），
   所以按 运行 / 配置 / 群聊 分成三组，每组前面带一个小标签、组间一条浅线。 */
.tabs{display:flex;gap:8px 12px;margin-bottom:16px;background:var(--card);padding:8px 12px;
  border-radius:var(--r);box-shadow:var(--sh);flex-wrap:wrap;align-items:center;
  position:sticky;top:0;z-index:20;border:1px solid var(--line)}
.tgroup{display:flex;align-items:center;gap:2px;padding-left:12px;
  border-left:1px solid var(--line2);flex-wrap:wrap}
.glabel{font-size:11px;font-weight:600;color:var(--t3);letter-spacing:.6px;
  margin-right:5px;white-space:nowrap}
.tab{padding:8px 14px;border-radius:var(--r-sm);cursor:pointer;font-size:13.5px;font-weight:500;
  color:var(--t2);border:none;background:none;transition:background .15s,color .15s;white-space:nowrap}
.tab:hover{background:var(--line2);color:var(--t1)}
.tab.active{background:var(--brand-weak);color:var(--brand);font-weight:600;
  box-shadow:inset 0 0 0 1px var(--brand-line)}

/* ===================== 卡片 ===================== */
.panel{display:none}.panel.active{display:block}
.card{background:var(--card);border-radius:var(--r);border:1px solid var(--line);
  box-shadow:var(--sh);padding:20px 22px;margin-bottom:16px}
.card h3{font-size:15px;font-weight:600;margin-bottom:14px;padding-left:11px;position:relative;color:var(--t1)}
.card h3::before{content:"";position:absolute;left:0;top:2px;bottom:2px;width:3px;border-radius:2px;
  background:linear-gradient(180deg,var(--brand),var(--brand2))}

/* ===================== 服务行 ===================== */
.svc{display:flex;align-items:center;gap:14px;padding:14px 16px;border:1px solid var(--line);
  border-radius:var(--r-sm);margin-bottom:10px;transition:box-shadow .15s,border-color .15s,transform .15s;
  background:#fcfdff}
.svc:hover{box-shadow:var(--sh-hi);border-color:#d8dce8;transform:translateY(-1px)}
.svc.on{border-color:var(--ok-line);background:linear-gradient(180deg,#fbfffd,#f4fdf8)}
.dot{width:9px;height:9px;border-radius:50%;background:#c9ced9;flex:none;transition:background .2s}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px rgba(0,168,84,.16)}
.svc .info{flex:1;min-width:0}
.svc .name{font-weight:600;font-size:14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.svc .sub{font-size:12px;color:var(--t3);margin-top:3px;line-height:1.5;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* 状态小胶囊（原来是一段内联彩色文字） */
.badge{font-size:11.5px;font-weight:600;padding:1px 8px;border-radius:999px;line-height:1.7}
.badge.ok{color:var(--ok);background:var(--ok-bg);border:1px solid var(--ok-line)}
.badge.off{color:var(--t3);background:var(--line2);border:1px solid var(--line)}

/* ===================== 按钮 ===================== */
button{padding:7px 15px;border-radius:var(--r-sm);border:1px solid var(--line);background:#fff;
  cursor:pointer;font-size:13px;color:var(--t2);font-family:inherit;
  transition:background .15s,border-color .15s,color .15s,box-shadow .15s}
button:hover{border-color:var(--brand-line);color:var(--brand);background:var(--brand-weak)}
button:active{transform:translateY(1px)}
button.p{background:linear-gradient(120deg,var(--brand),var(--brand2));color:#fff;border:none;
  font-weight:600;box-shadow:0 4px 12px -4px rgba(79,91,213,.5)}
button.p:hover{filter:brightness(1.06);color:#fff;box-shadow:0 6px 16px -4px rgba(79,91,213,.6)}
button.d{background:#fff;border-color:var(--err-line);color:var(--err)}
button.d:hover{background:var(--err);border-color:var(--err);color:#fff}
/* 「全部停止」是一次性影响全部服务的破坏性操作：用实心红，比描边红更明确，
   也不会和每行服务里的描边「停止」混成一样的分量 */
button.d-solid{background:var(--err);border-color:var(--err);color:#fff;font-weight:600}
button.d-solid:hover{background:#cf3b40;border-color:#cf3b40;color:#fff}
button:disabled{opacity:.45;cursor:not-allowed;transform:none;box-shadow:none}
button:disabled:hover{border-color:var(--line);color:var(--t2);background:#fff}
button.p:disabled:hover{filter:none}

/* ===================== 表单 ===================== */
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
label.f{display:block;margin-bottom:13px}
label.f .k{display:block;font-size:12.5px;color:var(--t2);margin-bottom:5px;font-weight:500}
input[type=text],input[type=number],input[type=date],textarea,select{width:100%;padding:8px 11px;
  border:1px solid var(--line);border-radius:var(--r-sm);font-size:13px;font-family:inherit;
  color:var(--t1);background:#fff;transition:border-color .15s,box-shadow .15s}
input:hover,textarea:hover,select:hover{border-color:#cfd4e0}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--brand);
  box-shadow:0 0 0 3px rgba(79,91,213,.12)}
input[type=checkbox]{width:auto;accent-color:var(--brand);transform:scale(1.15);cursor:pointer}
textarea{min-height:74px;resize:vertical;line-height:1.6}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:6px 18px}
@media(max-width:860px){.grid2{grid-template-columns:1fr}}

/* ===================== 提示条 ===================== */
.msg{padding:10px 14px;border-radius:var(--r-sm);font-size:13px;margin-bottom:12px;display:none;
  border-left:3px solid transparent}
.msg.ok{display:block;background:var(--ok-bg);border:1px solid var(--ok-line);border-left:3px solid var(--ok);color:#0a7a3d}
.msg.err{display:block;background:var(--err-bg);border:1px solid var(--err-line);border-left:3px solid var(--err);color:#b3282d}
.hint{font-size:12px;color:var(--t3);margin-top:4px;line-height:1.7}
h3+.hint{margin-top:-8px;margin-bottom:12px}
code{background:var(--brand-weak);color:var(--brand);padding:1px 5px;border-radius:4px;
  font-family:var(--mono);font-size:12px}

/* ===================== 工具栏（一页上面的那排控件） ===================== */
.toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:10px 12px;
  background:#fafbfe;border:1px solid var(--line);border-radius:var(--r-sm);margin-bottom:12px}
.toolbar .tl{font-size:12.5px;color:var(--t2);font-weight:500;white-space:nowrap}
.tchk{display:flex;align-items:center;gap:6px;font-size:13px;color:var(--t2);cursor:pointer;white-space:nowrap}

/* ===================== 可折叠说明（长提示别铺满屏幕） ===================== */
.note{background:#fafbfe;border:1px solid var(--line);border-radius:var(--r-sm);
  padding:9px 13px;margin:2px 0 10px}
.note>summary{cursor:pointer;font-size:12.5px;color:var(--t2);list-style:none;user-select:none}
.note>summary::-webkit-details-marker{display:none}
.note>summary::before{content:"▸ ";color:var(--brand);font-weight:700}
.note[open]>summary::before{content:"▾ "}
.note>div{font-size:12.5px;color:var(--t3);line-height:1.85;margin-top:8px;padding-left:15px}
.note b{color:var(--t2)}

/* ===================== 日志 ===================== */
pre.log{background:#11131a;color:#d5dae5;padding:16px 18px;border-radius:var(--r);font-size:12.5px;
  line-height:1.72;max-height:560px;overflow:auto;white-space:pre-wrap;word-break:break-all;
  font-family:var(--mono);border:1px solid #23262f}
pre.log::-webkit-scrollbar-thumb{background:#3a3f4d;background-clip:content-box}
/* 日志分级着色：一屏几百行纯文本很难扫，颜色能让人一眼跳到 ERROR/WARN */
pre.log .e{color:#ff8080}
pre.log .w{color:#ffc069}
pre.log .d{color:#767f92}
pre.log .i{color:#8fc7ff}

/* ===================== 统计卡 ===================== */
.stat{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px}
.stat .i{background:linear-gradient(180deg,#fff,#f7f9fd);border:1px solid var(--line);
  border-radius:var(--r-sm);padding:16px 12px;text-align:center;transition:box-shadow .15s,transform .15s}
.stat .i:hover{box-shadow:var(--sh-hi);transform:translateY(-1px)}
.stat .v{font-size:26px;font-weight:700;letter-spacing:-.5px;color:var(--brand);
  font-variant-numeric:tabular-nums;line-height:1.25}
.stat .l{font-size:12px;color:var(--t3);margin-top:3px}
/* ==================== 2026-10-02 视觉增强（追加，不改上面原有规则） ==================== */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(172px,1fr));gap:12px}
.kpi{position:relative;overflow:hidden;border:1px solid var(--line);border-radius:14px;padding:14px 16px;
  background:linear-gradient(160deg,#fff 0%,#f7f8ff 100%);transition:transform .18s ease,box-shadow .18s ease}
.kpi:hover{transform:translateY(-2px);box-shadow:0 10px 26px -14px rgba(79,91,213,.5)}
.kpi::after{content:"";position:absolute;right:-26px;top:-26px;width:84px;height:84px;border-radius:50%;
  background:radial-gradient(circle,rgba(79,91,213,.16),rgba(79,91,213,0) 70%);pointer-events:none}
.kpi .k-top{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--t3)}
.kpi .k-ico{font-size:15px;line-height:1}
.kpi .k-val{font-size:27px;font-weight:700;letter-spacing:-.5px;margin-top:6px;line-height:1.15;
  font-variant-numeric:tabular-nums;color:var(--t1)}
.kpi .k-sub{font-size:11.5px;color:var(--t3);margin-top:3px}
.kpi.ok .k-val{color:var(--ok)} .kpi.bad .k-val{color:var(--err)} .kpi.warn .k-val{color:#c07a00}
.donut-wrap{display:flex;align-items:center;gap:22px;flex-wrap:wrap}
.donut{width:140px;height:140px;flex:none;transform:rotate(-90deg)}
.donut circle{fill:none;stroke-width:4.2;stroke-linecap:round}
.donut .bgc{stroke:#eceef6}
.donut .fgc{transition:stroke-dashoffset .8s cubic-bezier(.2,.8,.2,1),stroke-dasharray .8s cubic-bezier(.2,.8,.2,1)}
.legend{display:flex;flex-direction:column;gap:8px;font-size:12.5px;min-width:190px}
.legend .li{display:flex;align-items:center;gap:8px}
.legend .sw{width:11px;height:11px;border-radius:3px;flex:none}
.legend .lv{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums}
.bars{display:flex;flex-direction:column;gap:9px}
.bar-row{display:flex;align-items:center;gap:10px;font-size:12.5px}
.bar-row .lbl{flex:none;width:148px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t2)}
.bar-row .track{flex:1;height:9px;border-radius:999px;background:#eef0f7;overflow:hidden}
.bar-row .fill{display:block;height:100%;border-radius:999px;
  background:linear-gradient(90deg,#4f5bd5,#8a5cf0);transition:width .6s cubic-bezier(.2,.8,.2,1)}
.bar-row .fill.warm{background:linear-gradient(90deg,#f0a020,#f06a3c)}
.bar-row .fill.dead{background:linear-gradient(90deg,#c3c8d6,#9aa2b6)}
.bar-row .num{flex:none;width:104px;text-align:right;color:var(--t3);font-variant-numeric:tabular-nums}
.tab .ti{margin-right:5px;font-size:14px;line-height:1}
@keyframes dsFadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.panel.active{animation:dsFadeUp .25s ease}
@keyframes dsPulse{0%,100%{opacity:1}50%{opacity:.45}}
.dot.on{animation:dsPulse 2.4s ease-in-out infinite}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-thumb{background:#ccd1e0;border-radius:6px;border:2px solid transparent;background-clip:content-box}
::-webkit-scrollbar-thumb:hover{background:#b3bad0;background-clip:content-box}
::-webkit-scrollbar-track{background:transparent}
</style></head><body>
<div class="header">
  <h1>🤖 QQ 机器人统一控制台</h1>
  <div style="display:flex;align-items:center;gap:10px">
    <button class="t" id="themeBtn" onclick="toggleTheme()" style="cursor:pointer;border:none;color:#fff;background:rgba(255,255,255,.15);padding:5px 12px;border-radius:999px;font-size:12.5px">🌙 暗色</button>
    <div class="t" id="clock">-</div>
  </div>
</div>
<div class="container">
  <div class="tabs">
    <button class="tab active" data-k="home" onclick="tab('home')">总览</button>
    <div class="tgroup"><span class="glabel">运行</span>
      <button class="tab" data-k="svc" onclick="tab('svc')"><span class="ti">🎛</span>服务控制</button>
      <button class="tab" data-k="logs" onclick="tab('logs')"><span class="ti">📜</span>日志</button>
    </div>
    <div class="tgroup"><span class="glabel">配置</span>
      <button class="tab" data-k="maibot" onclick="tab('maibot')"><span class="ti">🤖</span>麦麦配置</button>
      <button class="tab" data-k="api" onclick="tab('api')"><span class="ti">🔌</span>API 管理</button>
      <button class="tab" data-k="usage" onclick="tab('usage');loadModelUsage()"><span class="ti">📊</span>模型用量</button>
      <button class="tab" data-k="monitor" onclick="tab('monitor')"><span class="ti">📡</span>监控配置</button>
      <button class="tab" data-k="autostart" onclick="tab('autostart')"><span class="ti">🚀</span>自启管理</button>
      <button class="tab" data-k="cg" onclick="tab('cg')"><span class="ti">🎨</span>CG 与身份</button>
    </div>
    <div class="tgroup"><span class="glabel">群聊</span>
      <button class="tab" data-k="mon" onclick="tab('mon')"><span class="ti">💬</span>群聊消息</button>
      <button class="tab" data-k="groups" onclick="tab('groups')"><span class="ti">👥</span>群聊开关</button>
      <button class="tab" data-k="rules" onclick="tab('rules')"><span class="ti">📋</span>关键词规则</button>
      <button class="tab" data-k="kwr" onclick="tab('kwr')"><span class="ti">🔑</span>关键词回复</button>
      <button class="tab" data-k="speech" onclick="tab('speech')"><span class="ti">🗣</span>AI 发言</button>
      <button class="tab" data-k="favor" onclick="tab('favor')"><span class="ti">💗</span>好感度</button>
      <button class="tab" data-k="diary" onclick="tab('diary')"><span class="ti">📔</span>日记本</button>
      <button class="tab" data-k="notebook" onclick="tab('notebook')"><span class="ti">📓</span>助手的本子</button>
      <button class="tab" data-k="memory" onclick="tab('memory')"><span class="ti">🧠</span>记忆库</button>
      <button class="tab" data-k="quirky" onclick="tab('quirky')"><span class="ti">🎭</span>怪话库</button>
      <button class="tab" data-k="mark" onclick="tab('mark')"><span class="ti">🏷</span>标记用户</button>
      <button class="tab" data-k="search" onclick="tab('search')"><span class="ti">🔍</span>消息搜索</button>
    </div>
  </div>

  <div class="panel" id="p-diary">
    <div class="card">
      <h3>📔 助手的总日记</h3>
      <p class="hint">我把一天在各个群里的经历写进同一本日记。具体说过什么，可以再翻当时的聊天原文。</p>
      <p id="diaryStatus" class="hint" role="status">正在翻开日记本…</p>
      <div class="row" style="margin-top:12px;flex-wrap:wrap">
        <label>日期 <input id="diaryDate" type="date"></label>
        <label>来源群 <select id="diaryGroup"><option value="">全部群</option></select></label>
        <label>关键词 <input id="diaryQuery" maxlength="200" placeholder="想找的事或人"></label>
        <button onclick="loadDiaryList()">查日记</button>
        <button onclick="searchDiarySources()">查聊天原文</button>
        <button id="diaryWrite" onclick="writeDiary()">写今天的日记</button>
      </div>
      <p id="diaryMessage" class="hint" role="status" style="margin-top:8px"></p>
    </div>
    <div class="card"><div id="diaryList">还没有打开日记。</div></div>
    <div class="card" id="diaryDetail" hidden></div>
  </div>

  <div class="panel" id="p-notebook">
    <div class="card">
      <h3>📓 助手的本子</h3>
      <p class="hint">日记写一天的经历；这里留我想继续记着的一件事、一个人或一句话。每篇完整日记写好后，我会自己留下一页。</p>
      <div class="row" style="margin-top:12px;flex-wrap:wrap">
        <label>找一页 <input id="notebookQuery" maxlength="200" placeholder="名字、念头或一句话"></label>
        <button onclick="loadNotebook()">翻本子</button>
      </div>
      <p id="notebookMessage" class="hint" role="status" style="margin-top:8px"></p>
    </div>
    <div class="card"><div id="notebookList">还没有翻开本子。</div></div>
    <div class="card" id="notebookDetail" hidden></div>
  </div>

  <div class="panel active" id="p-home">
    <div class="card">
      <h3>📊 一眼看板</h3>
      <div class="kpi-grid" id="homeKpi"><span class="hint">加载中…</span></div>
    </div>
    <div class="card">
      <h3>📈 怪话库构成 · 各群冷场状况</h3>
      <div class="donut-wrap">
        <svg class="donut" viewBox="0 0 42 42" aria-hidden="true">
          <circle class="bgc" cx="21" cy="21" r="15.9"></circle>
          <circle class="fgc" id="qArc" cx="21" cy="21" r="15.9" stroke="#4f5bd5"
                  stroke-dasharray="0 100" stroke-dashoffset="0"></circle>
        </svg>
        <div class="legend" id="qLegend"><span class="hint">加载中…</span></div>
      </div>
      <div class="bars" id="coldBars" style="margin-top:16px"><span class="hint">加载中…</span></div>
    </div>

    <div class="card" id="tipCard" style="display:none">
      <h3>⚠️ 需要处理</h3>
      <div id="tipText" style="font-size:14px;line-height:1.7"></div>
    </div>
    <div class="card">
      <h3>SnowLuma（QQ 接入）</h3>
      <div id="snowSvc"><span class="hint">加载中…</span></div>
      <div class="msg" id="snowMsg"></div>
    </div>
    <div class="card">
      <h3>服务状态</h3>
      <div id="homeSvc"></div>
      <div class="row" style="margin-top:6px">
        <button class="p" onclick="allStart()">▶ 一键启动全部</button>
        <button class="d d-solid" onclick="allStop()">■ 全部停止</button>
        <span class="hint">先自行运行 QQ 与 OneBot 适配器；一键启停仅管理本仓库监控和控制台，麦麦可单独启停；
          NapCat 与麦麦适配器已退役，不再显示在这里</span>
      </div>
      <div class="msg" id="homeMsg"></div>
    </div>
    <div class="card">
      <h3>监控统计</h3>
      <div id="homeStats"><span class="hint">监控服务未运行</span></div>
      <div class="row"><button class="p" onclick="tab('mon')">查看群聊消息 / 违规告警 →</button></div>
    </div>
    <div class="card">
      <h3>消息趋势（最近 14 天）</h3>
      <div id="homeTrend"><span class="hint">加载中…</span></div>
      <div class="row">
        <button onclick="loadTrend(true)">刷新</button>
        <span class="hint">柱高 = 当天消息总量；下方是各群累计量排行（缓存 1 分钟）</span>
      </div>
    </div>
    <div class="card">
      <h3>服务稳定性（最近 24 小时）</h3>
      <div id="homeHealth"><span class="hint">加载中…</span></div>
      <div class="row"><button onclick="loadHealth(true)">刷新</button>
        <span class="hint">每 60 秒采样一次，重启面板后重新累积</span></div>
    </div>
    <div class="card">
      <h3>主动说话（冷场找话题 / 定时怪话 / 接话跟进）</h3>
      <div id="homeQuirky"><span class="hint">加载中…</span></div>
      <div class="msg" id="qkHomeMsg"></div>
      <div class="row">
        <button onclick="loadQuirkyAuto(true)">刷新</button>
        <button class="p" onclick="quirkySendNow()">现在试一句怪话</button>
        <button class="p" onclick="quirkyTopicNow(0,true)">预览起话题</button>
        <button class="p" onclick="quirkyTopicNow(0,false)">真发一条话题</button>
        <button onclick="quirkyShowTopics()">看热点源</button>
        <span class="hint">冷场阈值到了：80% 上网找话题、20% 念怪话；白天每 2~4 小时还会定时发一条怪话</span>
      </div>
      <div id="qkTopics" class="hint" style="margin-top:6px;white-space:pre-wrap;max-height:180px;overflow:auto"></div>
    </div>
    <div class="card">
      <h3>好感度（对每个人）</h3>
      <div id="homeFav"><span class="hint">加载中…</span></div>
      <div class="row">
        <button onclick="loadFav()">刷新</button>
        <button class="d" onclick="favResetAll()">全部重置为 100</button>
        <span class="hint">初始 100、**无上限**。正常交流 +3、聊得开心 +5；被否定 -4、被叫停 -8、被欺负 -12。掉到 30 以下就不再理那个人（@它只会被回一句"你是坏人"）。</span>
      </div>
      <div class="hint">改数字直接生效，不用重启麦麦（插件检测到文件变了会重读）。群里也可以用命令：<code>好感度 @某人 50</code> / <code>好感度 @某人 +20</code> / <code>好感度 重置</code>（仅管理员）。</div>
      <div class="msg" id="favMsg"></div>
    </div>
  </div>

  <div class="panel" id="p-svc"><div class="card"><h3>服务控制</h3><div id="svcList"></div><div class="msg" id="svcMsg"></div></div></div>

  <div class="panel" id="p-maibot"><div class="card"><h3>麦麦（陪聊机器人）配置</h3>
    <div class="msg" id="mbMsg"></div><div id="mbForm"></div>
    <div class="row"><button class="p" onclick="saveMb()">保存配置</button><button onclick="loadMb()">重新读取</button>
    <span class="hint" id="mbPath"></span></div>
    <div class="hint">改完需重启「麦麦核心」生效。这里只覆盖常用项，完整配置用下面的 HMML 面板。</div>
  </div>
  <div class="card">
    <h3>完整配置面板（HMML，麦麦官方）</h3>
    <div class="row">
      <button class="p" onclick="ensureHmml(true)">启动并加载</button>
      <button onclick="openHmml()">在新窗口打开</button>
      <span class="hint" id="hmmlHint">公开版请在 MaiBot 安装目录中单独运行 HMML。</span>
    </div>
    <div class="msg" id="hmmlMsg"></div>
    <iframe id="hmmlFrame" style="width:100%;height:820px;border:1px solid #e8e8e8;border-radius:8px;background:#fff"></iframe>
    <div class="hint">
      HMML 是麦麦自带的完整配置界面，覆盖本面板没有的东西：
      <strong>API 管理</strong>（上面的页签是本面板自己的）、插件市场、表情包、表达方式、
      人物信息、聊天流等。两个进程按需启动，不用时可在「服务控制」里停掉。
    </div>
  </div></div>

  <div class="panel" id="p-cg">
    <div class="card">
      <h3>CG 与身份 · 提示词</h3>
      <div class="hint">这里改的是麦麦的 <code>cg_prompts.json</code>，一共三套：
        <b>身份选择</b>（好感度够 <code>min_favor</code> 时让用户从几个身份里挑一个，
        用户问「菜单 / 帮助」时回 <code>help</code> 那份模板）、
        <b>自定义称呼</b>（用户说「以后叫我 XX」之后怎么叫他）、
        <b>里程碑 CG</b>（好感度每涨一档生成一张纪念图，提示词由
        <code>base_prompt</code> + 那一档的 <code>prompt</code> 拼出来）。
        三套都是<b>直接进提示词</b>的，改完不用重启麦麦（插件按文件时间自动重读）。</div>
      <div class="msg" id="cgMsg"></div>
      <div id="cgForm"></div>
      <div class="row"><button class="p" onclick="saveCg()">保存提示词</button>
        <button onclick="loadCg()">重新读取</button>
        <span class="hint" id="cgPath"></span></div>
      <div class="hint">提示词里的 <code>{who}</code> / <code>{cur}</code> / <code>{min_favor}</code>
        这类花括号占位符是麦麦运行时替换的，别改写法。<b>生图</b>那部分改完是先在新一档生效，
        已经发过的纪念图不会重发。</div>
    </div>
  </div>

  <div class="panel" id="p-usage">
    <div class="card">
      <h3>📊 模型用量与花费</h3>
      <div class="hint">
        数据来自麦麦自己写的统计缓存 <code>data/local_store.json</code>（它每几分钟刷一次）。<br>
        <b>花费＝输入 token × 单价 + 输出 token × 单价</b>，单价读的是
        <code>model_config.toml</code> —— 单价没填的模型算出来必然是 0，下面会点名；<br>
        要补单价就去「🔌 API 管理」里改对应模型（改完这里跟着准）。<br>
        Codex 为官方 Standard API 参考估价，固定按 1 美元＝7 元折算；未扣除缓存折扣，不代表账号实际扣费。
      </div>
      <div class="row">
        <span id="muPeriods"></span>
        <button onclick="loadModelUsage()">刷新</button>
        <span class="hint" id="muStat"></span>
      </div>
      <div class="kpi-grid" id="muKpi"><span class="hint">加载中…</span></div>
      <div class="msg" id="muWarn"></div>
      <div class="bars" id="muBars" style="margin-top:16px"><span class="hint">加载中…</span></div>
      <div id="muTable" style="margin-top:14px"></div>
    </div>
  </div>

  <div class="panel" id="p-api">
    <div class="card">
      <h3>配置体检</h3>
      <div id="apiWarn"></div>
    </div>
    <div class="card">
      <h3>API 提供商</h3>
      <div class="hint">这里对应麦麦的 <code>model_config.toml</code>。密钥是明文存在该文件里的，别把这个页面或文件外发。</div>
      <div class="msg" id="pvMsg"></div>
      <div id="pvList"></div>
      <div class="row"><button class="p" onclick="pvNew()">+ 新增提供商</button>
        <button onclick="loadApi(true)">重新读取</button>
        <span class="hint" id="apiPath"></span></div>
    </div>
    <div class="card">
      <h3>模型</h3>
      <div class="hint">「模型标识符」是服务商那边的真实模型名；「模型名称」是麦麦内部用的代号，下面的角色分配按名称引用。</div>
      <div class="msg" id="mdMsg"></div>
      <div id="mdList"></div>
      <div class="row"><button class="p" onclick="mdNew()">+ 新增模型</button></div>
    </div>
    <div class="card">
      <h3>角色 → 模型分配</h3>
      <div class="hint">麦麦的不同部件各用一个模型。多个模型用逗号分隔，会按顺序尝试。改完需重启「麦麦核心」。</div>
      <div class="msg" id="tkMsg"></div>
      <div id="tkList"></div>
      <datalist id="mdNames"></datalist>
    </div>
  </div>

  <div class="panel" id="p-monitor"><div class="card"><h3>监控告警系统配置</h3>
    <div class="msg" id="moMsg"></div><div id="moForm"></div>
    <div class="row"><button class="p" onclick="saveMo()">保存配置</button><button onclick="loadMo()">重新读取</button></div>
    <div class="hint">改完需重启「监控告警系统」生效。聊天记录查询、告警列表等请用监控自带面板（:8080）。</div>
  </div></div>

  <div class="panel" id="p-rules"><div class="card"><h3>关键词 / 禁言词规则</h3>
    <div class="msg" id="ruMsg"></div>
    <div class="grid2">
      <div><label class="f"><span class="k">keywords.txt（命中记 medium）</span><textarea id="kw" style="min-height:320px;font-family:Consolas,monospace"></textarea></label></div>
      <div><label class="f"><span class="k">banned_words.txt（命中记 high）</span><textarea id="bw" style="min-height:320px;font-family:Consolas,monospace"></textarea></label></div>
    </div>
    <div class="row"><button class="p" onclick="saveRu()">保存规则</button><button onclick="loadRu()">重新读取</button></div>
    <div class="hint">每行一条；# 开头是注释；正则用 /pattern/ 包裹。保存后在监控面板点「重新加载规则」或重启生效。</div>
  </div></div>

  <div class="panel" id="p-kwr">
    <div class="card">
      <h3>关键词自动回复 <span class="hint" id="kwrHint"></span></h3>
      <div class="hint">
        群里有人提到「触发词」，机器人就把「回复内容」<b>一字不差</b>发出去 —— 不过 AI、不改写、不额外说话。<br>
        发消息的是<b>监控</b>（不走麦麦）：麦麦关着、或者适配器全群禁言，这套照样生效。
        改完<b>立即生效</b>，不用重启任何服务。<br>
        规则有两种：<b>普通回复</b>（发固定的那段话）和<b>随机怪话</b>（@机器人 说「随机文案 / 来句怪话」
        之类 → 从下面的怪话库随机挑一条发出去，不走麦麦、因此不会瞎编、也不会再跟一句）。<br>
        （注意别和「关键词规则」混了：那个是给<b>审查告警</b>用的词表，这里才是自动回复。）
      </div>
      <div class="msg" id="kwrMsg"></div>
      <div class="row">
        <label style="font-size:13px"><input type="checkbox" id="kwrEnabled"> 启用</label>
        <label style="font-size:13px"><input type="checkbox" id="kwrMention"> 回复时 @ 提问的人</label>
        <label style="font-size:13px">冷却 <input id="kwrCd" type="number" min="0" style="width:70px"> 秒 / 群</label>
      </div>
      <div class="row">
        <label style="font-size:13px;flex:1">
          只在哪些群生效（群号，逗号分隔；<b>留空 = 机器人所在的每个群都生效</b>）
          <input id="kwrGroups" style="width:100%;max-width:420px" placeholder="例：100000001, 100000001">
        </label>
      </div>
      <div class="row">
        <label style="font-size:13px;flex:1">怪话库文件（留空 = 麦麦的 <code>data\quirky_lines.json</code>，一般不用改）
          <input id="kwrQf" style="width:100%;max-width:560px" placeholder="留空即可"></label>
        <label style="font-size:13px;flex:none">怪话最长
          <input id="kwrMc" type="number" min="0" style="width:80px" onchange="kwrPoolLine()"> 字</label>
      </div>
      <div class="hint" id="kwrPoolHint"></div>
      <div id="kwrList" style="margin-top:10px"></div>
      <div class="row">
        <button onclick="kwrAdd()">加一条规则</button>
        <button class="p" onclick="kwrSave()">保存</button>
        <button onclick="loadKwr(true)">重新读取</button>
        <span class="hint" id="kwrPath"></span>
      </div>
      <div class="hint" style="margin-top:10px">
        试一句（只在本机算，不会发消息）：
        <input id="kwrTest" style="width:320px" placeholder="例：你们有哪些部门呀" oninput="kwrTestRun()">
        <span id="kwrTestOut"></span>
      </div>
    </div>

    <div class="card">
      <h3>唱歌（RVC）<span class="hint" id="singHint"></span></h3>
      <div class="hint">
        <b>默认所有群都能唱</b> —— 机器人所在的任何群，<b>@机器人 说「唱《歌名》」</b> 就会跑
        「UVR5 分离人声 → RVC 转音色 → 混音」再发语音（一首约 1~3 分钟，队列最多排 3 首）。<br>
        下面列出<strong>机器人所在的群</strong>：点 <b>关掉</b> 这个群就不唱了，点 <b>打开</b> 恢复，
        也可以直接填群号操作 —— 改完<b>立刻生效，不用重启</b>（在群里说「关闭唱歌 / 打开唱歌」是同一件事）。<br>
        唱歌走的是监控的关键词规则，<b>不需要把这个群加进「监控群名单」</b>（那只会让你收到这个群的审核信息）。
      </div>
      <div class="msg" id="singMsg"></div>
      <div class="row">
        <button class="p" onclick="loadSing(true)">刷新状态</button>
        <button onclick="singToggleAll(true)">全部打开</button>
        <button onclick="singToggleAll(false)">全部关闭</button>
        <span class="hint" id="singModel"></span>
      </div>
      <div id="singState" class="hint"></div>
      <div class="row" style="margin-top:8px">
        <label style="font-size:13px;flex:none">群号
          <input id="singGid" style="width:160px" placeholder="例：100000001"></label>
        <button onclick="singToggleUI(true)">打开这个群</button>
        <button onclick="singToggleUI(false)">关掉这个群</button>
      </div>
      <div id="singList" style="margin-top:8px"></div>
    </div>
  </div>

  <div class="panel" id="p-mon">
    <div class="card">
      <h3>导出聊天记录（TXT）</h3>
      <div class="row">
        <input type="text" id="expDir" placeholder="导出目录，例如 ./local-data/exports" style="width:430px">
        <button onclick="pickDir()">选择目录…</button>
        <button class="p" onclick="exportAll()">导出全部聊天记录（TXT）</button>
        <button class="p" onclick="exportWord()">导出 Word（图片内嵌）</button>
        <button onclick="backfillHistory()">补齐历史（含 AI 发言）</button>
      </div>
      <div class="hint">把所有群、所有日期的记录导成人类可读的文件。TXT 里图片只留路径；<b>Word</b> 会把图片压小后直接嵌进文档，一天一个 .docx，输出到 &lt;目录&gt;\Word\群&lt;群号&gt;\&lt;日期&gt;.docx。<b>机器人自己说的话也会在里面，标成「昵称[AI]」</b>；要是发现 AI 的发言不全，点「补齐历史」从 QQ 往回翻（OneBot 的实时事件默认不推自发言，监控另外每 3 分钟会自动补一次最近的）。目录留空 = 用监控配置里那个；点「选择目录…」会弹出系统目录框（在服务器这台机器上弹，看一眼任务栏）。TXT 要几十秒；Word 因为要逐张处理图片，通常 1~3 分钟，进度实时显示，别关页面。</div>
      <div class="msg" id="expMsg"></div>
    </div>
    <div class="card">
      <h3>监控概览</h3>
      <div id="monStats"><span class="hint">加载中…</span></div>
      <div class="row">
        <button onclick="loadMon(true)">刷新全部</button>
        <span class="hint" id="monHint"></span>
      </div>
      <div class="msg" id="monMsg"></div>
    </div>

    <div class="card">
      <h3>群聊消息</h3>
      <div class="row">
        <select id="mGroup" style="width:210px"></select>
        <input id="mKeyword" placeholder="搜索内容关键词" style="width:190px">
        <label style="font-size:13px;color:#666">从 <input type="date" id="mFrom" style="width:140px"></label>
        <label style="font-size:13px;color:#666">到 <input type="date" id="mTo" style="width:140px"></label>
        <label style="font-size:13px;color:#666"><input type="checkbox" id="mViol"> 只看有违规的</label>
        <button class="p" onclick="monSearch(1)">查询</button>
        <button onclick="monReset()">重置</button>
      </div>
      <div id="monPagerTop" class="hint" style="margin-top:6px"></div>
      <details class="note">
        <summary>图片显示成灰色 <b>[图片未落盘 ↗]</b> 是什么意思？</summary>
        <div>表示这张图当时没下载到本地 —— 监控只在收到消息那一刻下一次，网络抖动就会失败。
        带 ↗ 的可以点开看原始链接（QQ 直链有时效）；要批量补下来跑
        <code>python qq-monitor\tools\repair_missing_images.py --apply</code>。
        鼠标悬停在灰色字上能看到当时失败的原因。</div>
      </details>
      <div id="monList"></div>
      <div id="monPagerBot" style="margin-top:8px"></div>
    </div>

    <div class="card">
      <h3>违规告警</h3>
      <div class="row">
        <select id="aGroup" style="width:210px"></select>
        <select id="aSeverity" style="width:130px">
          <option value="">全部级别</option>
          <option value="high">高</option><option value="medium">中</option><option value="low">低</option>
        </select>
        <select id="aSecondary" style="width:190px">
          <option value="">全部复核状态</option>
          <option value="likely_false_positive">二次复核可能误报</option>
          <option value="confirmed">二次复核确认</option>
        </select>
        <select id="aLimit" style="width:120px">
          <option value="50">最近 50 条</option><option value="100">100 条</option>
          <option value="200">200 条</option><option value="500">500 条</option>
        </select>
        <button class="p" onclick="loadAlerts()">刷新</button>
        <span class="hint">点标题可展开完整判定理由与二次复核结论</span>
      </div>
      <div id="alertSummary" style="margin-top:6px"></div>
      <div id="alertList"></div>
    </div>

    <div class="card">
      <h3>违规用户排行</h3>
      <div class="hint">按历史告警条数排（来自监控面板的统计）</div>
      <div id="alertUsers"><span class="hint">加载中…</span></div>
    </div>

    <div class="card">
      <h3>群组概览</h3>
      <div id="groupList"></div>
    </div>
  </div>

  <div class="panel" id="p-groups">
    <div class="card">
      <h3>群聊开关（监控 / 发言）</h3>
      <div class="hint">
        <b>监控</b>：记录并审查这个群的消息。改完<b>立即生效</b>，不用重启。<br>
        <b>发言</b>：麦麦在这个群里说话。改完需<b>重启「麦麦适配器」</b>才生效。<br>
        群列表取自 QQ（OneBot 接口，机器人实际所在的群），不是只看配置。
      </div>
      <div class="msg" id="gsMsg"></div>
      <div class="row">
        <button onclick="loadSwitchGroups(true)">重新读取</button>
        <button class="p" onclick="saveSwitchGroups()">保存开关</button>
        <button class="p" onclick="saveTalkStrength()">保存发言强度</button>
        <button class="p" onclick="saveTalkStrength(true)">保存并重启麦麦</button>
        <button onclick="gsAllSpeak(true)">全部允许发言</button>
        <button onclick="gsAllSpeak(false)">全部禁止发言</button>
        <span class="hint" id="gsHint"></span>
      </div>
      <div id="gsList"></div>
    </div>
  </div>

  <div class="panel" id="p-speech">
    <div class="card">
      <h3>麦麦的历史发言 <span class="hint" id="spHint"></span></h3>
      <div class="hint">
        翻它说过的每句话，需要时可以对某个人调一下<b>好感度</b>。
        数据取自麦麦自己的消息库（比导出的全），改完<b>立即生效、不用重启</b>。<br>
        （表现分打分已于 2026-10-21 下线 —— 原来的 <code>/api/bot_speeches/rate</code> 和
        首页那张表现分卡片一并删除，麦麦自己的评分不受影响。）
      </div>
      <div class="row">
        <input id="spKw" placeholder="搜发言内容…" style="width:200px"
               onkeydown="if(event.key==='Enter')loadSpeeches(true)">
        <select id="spGroup" onchange="loadSpeeches(true)"><option value="">全部群</option></select>
        <button onclick="loadSpeeches(true)">查询</button>
        <span class="hint" id="spMsg2"></span>
      </div>
      <div class="msg" id="spMsg"></div>
      <div id="spList"></div>
      <div class="row" style="margin-top:8px">
        <button id="spMore" style="display:none" onclick="loadSpeeches(false)">加载更多</button>
      </div>
    </div>

    <div class="card">
      <h3>好感度</h3>
      <div class="hint">
        每条发言右边可以直接调<b>被它回复的那个人</b>的好感度（引用过谁就自动选中谁）。<br>
        要看<b>按人总览</b>、批量调整或搜人，请用顶部的「<b>好感度</b>」页签。
      </div>
    </div>
  </div>

  <div class="panel" id="p-favor">
    <div class="card">
      <h3>好感度排行榜 <span class="hint">（全局名次）</span> <span class="hint" id="fvHint"></span></h3>
      <div class="hint">
        助手<b>对每个人</b>的好感度：初始 100、<b>无上限</b>。关系阶段随分数变化，熟悉后也可以互损、敷衍和有自己的意见。<br>
        新增互动天数、今日涨跌和真实变动记录；旧分数与原有称呼、身份保留，旧历史没有记录就不补编。<br>
        改动<b>立即生效</b>（写进 <code>favorability.json</code>，插件侧有 mtime 检测会自动重读，不用重启麦麦）。<br>
        默认好感度从高到低，同分并列；阶段说明不代表自动选择恋爱关系。今日涨跌包含管理员调整，记录中会标明。
      </div>
      <div class="row">
        <input id="fvKw" placeholder="搜昵称 / QQ / 称呼 / 身份…" style="width:200px"
               oninput="fvRender(_fvData)" onkeydown="if(event.key==='Enter')loadFavorPage()">
        <select id="fvSort" onchange="fvRender(_fvData)" style="width:158px">
          <option value="score_asc">好感度 低 → 高</option>
          <option value="score_desc" selected>好感度 高 → 低（排行榜）</option>
          <option value="hits_desc">互动最多的</option>
          <option value="last_ts_desc">最近互动过的</option>
          <option value="name_asc">昵称 A → Z</option>
        </select>
        <button onclick="loadFavorPage()">刷新</button>
        <button onclick="fvExport()">导出 CSV</button>
        <button onclick="fvResetAll()">全部重置为 100</button>
        <span class="hint" id="fvStat"></span>
      </div>
      <div class="msg" id="fvMsg"></div>
      <div id="fvList"></div>
    </div>
  </div>

  <div class="panel" id="p-memory">
    <div class="card">
      <h3>记忆库 <span class="hint" id="mmHint"></span></h3>
      <div class="hint">
        <b>现役</b>：麦麦 1.2.5 的长期记忆系统 <b>A_memorix</b>（段落 / 实体 / 关系 / 人物画像快照），
        存在 <code>data/a-memorix/</code>。<b>本页只读，面板不写它</b> —— 要改记忆请用麦麦自己的记忆工具。<br>
        <b>历史遗留</b>：<code>memory_chest</code> 老表。麦麦 1.2.5（09-24）把 <code>MemoryChest</code>
        整套移除了，<b>最后一条停在 09-24</b>；切过去仍可看/搜/编辑/删除（那是面板唯一写麦麦库的地方）。
      </div>
      <div class="row">
        <select id="mmSource" onchange="mmSourceChanged()">
          <option value="amem">现役记忆（A_memorix）</option>
          <option value="legacy">历史遗留（memory_chest · 09-24 前）</option>
        </select>
        <select id="mmKind" onchange="loadMemories(true)">
          <option value="paragraph">段落</option>
          <option value="entity">实体</option>
          <option value="relation">关系三元组</option>
          <option value="profile">人物画像快照</option>
        </select>
        <input id="mmKw" placeholder="搜内容…" style="width:180px"
               onkeydown="if(event.key==='Enter')loadMemories(true)">
        <select id="mmGroup" onchange="loadMemories(true)"><option value="">全部群</option></select>
        <button onclick="loadMemories(true)">查询</button>
        <button id="mmDupBtn" onclick="mmDup()">找重复</button>
        <span class="hint" id="mmStat"></span>
      </div>
      <div class="hint" id="mmStatsRow"></div>
      <div class="msg" id="mmMsg"></div>
      <div id="mmList"></div>
      <div class="row" style="margin-top:8px">
        <button id="mmMore" style="display:none" onclick="loadMemories(false)">加载更多</button>
      </div>
    </div>

    <div class="card" id="mmDupCard" style="display:none">
      <h3>疑似重复 <span class="hint" id="mmDupHint"></span></h3>
      <div class="hint">
        同一个群里内容高度相似的记忆（跨群不比，不同群的话题本来就不该合并）。
        每一组<b>留一条就够</b>，把其余的删掉 —— 重复的记忆会重复占用它每次回答时的注意力。
      </div>
      <div class="msg" id="mmDupMsg"></div>
      <div id="mmDupList"></div>
    </div>
  </div>

  <div class="panel" id="p-quirky">
    <div class="card">
      <h3>怪话库 <span class="hint" id="qkHint"></span></h3>
      <div class="hint">
        群里<b>冷场太久</b>的时候，如果它没有别的话题，就会从这里<b>随机挑一条</b>发出去。<br>
        挑选标准：<b>没头没尾、不针对任何人、谁都能接一句</b> —— 因为它的用途就是打破沉默，不能需要上下文。<br>
        改动<b>立即生效</b>（写进 <code>quirky_lines.json</code>，麦麦侧有 mtime 检测会自动重读，不用重启）。
      </div>
      <div class="row" style="align-items:flex-start">
        <textarea id="qkNew" rows="4" placeholder="塞怪话进来，一行一条（可以一次贴一整批）&#10;例如：&#10;你们说，鱼会口渴吗&#10;为什么周一总是比周日短"
                  style="flex:1;min-width:300px;font-size:13px;font-family:inherit;line-height:1.6"></textarea>
        <span style="flex:none;display:flex;flex-direction:column;gap:6px">
          <button class="p" onclick="qkAdd()">塞进去</button>
          <button onclick="loadQuirky()">刷新</button>
        </span>
      </div>
      <div class="msg" id="qkMsg"></div>
      <div class="row" style="margin-top:4px">
        <span class="hint" id="qkStat"></span>
        <select id="qkLen" style="margin-left:8px" onchange="qkRender()">
          <option value="all">全部字数</option>
          <option value="s">短 (&lt;100字)</option>
          <option value="m">中 (100-200字)</option>
          <option value="l">长 (200-400字)</option>
          <option value="xl">超长 (400+字)</option>
        </select>
        <input id="qkKw" placeholder="搜…" style="width:150px;margin-left:8px"
               onkeydown="if(event.key==='Enter')qkRender()">
      </div>
      <div id="qkList"></div>
    </div>
  </div>

  <div class="panel" id="p-mark">
    <div class="card">
      <h3>标记用户 <span class="hint" id="mkHint"></span></h3>
      <div class="hint">
        群里有人 <b>@某人</b>、而且消息里出现 <code>**</code> 时，就<b>把这个被 @ 的人记下来</b>
        （<b>流水</b>：每次触发都记一条）。<code>**</code> 在 @ 前面/后面都算；
        <b>不看身份</b> —— 群主、管理员一样记（身份只作为信息显示）。<br>
        一次 @ 多个人就记多条；<code>@全体</code> 不算；@机器人自己不记。<br>
        <b>只记录，不影响机器人任何行为。</b>数据落在 qq-monitor 的
        <code>&lt;data_dir&gt;/marked_users.jsonl</code>（纯追加，本页不提供删除）。<br>
        想关掉：在 qq-monitor 的 <code>config.linux.json</code> 里加
        <code>"marked_users": {"enabled": false}</code>，然后重启监控。
      </div>
      <div class="row" style="margin-top:4px">
        <span class="hint" id="mkStat"></span>
        <input id="mkKw" placeholder="搜 QQ / 昵称 / 群 / 原文…" style="width:200px;margin-left:8px"
               onkeydown="if(event.key==='Enter')mkRender()">
        <button onclick="loadMarked()">刷新</button>
        <button onclick="mkRender()">筛选</button>
      </div>
      <div class="msg" id="mkMsg"></div>
      <div id="mkList"></div>
    </div>
  </div>

  <div class="panel" id="p-logs"><div class="card">
    <h3>日志</h3>
    <div class="toolbar">
      <span class="tl">服务</span>
      <select id="logKey" onchange="loadLog()" style="width:220px">
        <option value="monitor">监控告警系统</option>
        <option value="maibot">麦麦核心</option>
        <option value="hmml_backend">HMML 配置后端</option><option value="hmml_frontend">HMML 配置前端</option>
        <option value="panel">统一控制台自身</option>
      </select>
      <button onclick="loadLog()">刷新</button>
      <label class="tchk"><input type="checkbox" id="logAuto" checked> 自动刷新（5 秒）</label>
      <span class="hint" style="margin:0">显示最近 300 行</span>
    </div>
    <pre class="log" id="logBox">-</pre>
  </div></div>

  <div class="panel" id="p-search">
    <div class="card">
      <h3>历史消息搜索</h3>
      <div class="row">
        <input id="skKw" placeholder="关键词…" style="width:170px" onkeydown="if(event.key==='Enter')doSearch()">
        <select id="skGroup" style="width:200px"><option value="">全部群</option></select>
        <input id="skDate" type="date" style="width:150px" title="选日期则只搜当天">
        <button class="p" onclick="doSearch()">搜索</button>
        <span class="hint">查的是监控数据库（qq-monitor），最多 200 条/页</span>
      </div>
      <div class="msg" id="skMsg"></div>
      <div id="skResult"><span class="hint">输入关键词（或选群/日期）点搜索。关键词支持跨群、跨日期全文匹配。</span></div>
    </div>
  </div>

  <div class="panel" id="p-autostart">
    <div class="card">
      <h3>开机自启管理</h3>
      <div id="asList"><span class="hint">加载中…</span></div>
      <div class="msg" id="asMsg"></div>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
// 配置值会直接进 HTML，必须转义；否则值里出现 " < > 会截断属性、
// 表单显示错乱，而且再保存时会把残缺值写回配置文件。
const esc = s => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;')
                                .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
                                .replace(/'/g,'&#39;');
// ============ 暗色/亮色主题 ============
// 用 html[data-theme] + CSS 变量实现；选择记 localStorage（ui_smoke 的 Node 桩里
// 没有 localStorage，包一层 try 免得冒烟测试崩）。
function toggleTheme(){
  const cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', cur);
  const b = $('themeBtn');
  if(b) b.textContent = cur === 'dark' ? '☀ 亮色' : '🌙 暗色';
  try { localStorage.setItem('panel_theme', cur); } catch(e){}
}
(function(){
  try {
    if(typeof localStorage === 'undefined') return;
    const t = localStorage.getItem('panel_theme');
    if(t === 'dark'){
      document.documentElement.setAttribute('data-theme', 'dark');
      const b = $('themeBtn');
      if(b) b.textContent = '☀ 亮色';
    }
  } catch(e){}
})();
function tab(n){
  // 页签和面板都直接从 DOM 取，不维护硬编码清单。
  // 之前那份常量表漏了新增的页签，导致 tab('mon') 循环一圈谁也没激活、
  // 所有面板保持隐藏 —— 点过去就是整页空白（2026-09-15 踩过）。
  document.querySelectorAll('.tab[data-k]').forEach(b=>b.classList.toggle('active', b.dataset.k===n));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active', p.id==='p-'+n));
  if(n==='logs') loadLog();
  if(n==='maibot') ensureHmml();
  if(n==='api') loadApi();
  if(n==='mon') loadMon();
  if(n==='groups') loadSwitchGroups();
  if(n==='speech') loadSpeeches(true);
  if(n==='favor') loadFavorPage();
  if(n==='diary') loadDiaryPage();
  if(n==='notebook') loadNotebook();
  if(n==='memory') loadMemories(true);
  if(n==='quirky') loadQuirky();
  if(n==='mark') loadMarked();
  if(n==='search') loadSearchGroups();
  if(n==='autostart') loadAutostart();
  if(n==='cg') loadCg();
  if(n==='kwr'){ loadKwr(); loadSing(); }
}

// ==================== 日记本 ====================
let diaryBusy=false, diaryPoll=0, diaryPageLoaded=false;
const diaryText=(id,text)=>{ $(id).textContent=text; };
async function diaryFetch(path,options){
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),12000);
  try{
    const r=await fetch('/api/diary/'+path,Object.assign({},options||{},{signal:controller.signal}));
    const d=await r.json();
    if(!r.ok||d.error) throw new Error(d.error||'日记暂时没有打开，请稍后重试');
    return d;
  }finally{clearTimeout(timer);}
}
function diaryParams(){
  const p=new URLSearchParams();
  for(const [key,id] of [['date','diaryDate'],['group_id','diaryGroup'],['q','diaryQuery']]){
    if($(id).value.trim()) p.set(key,$(id).value.trim());
  }
  p.set('limit','50');return p;
}
function diaryProgressText(s){
  const p=(s.progress&&typeof s.progress==='object')?s.progress:(s.running||{});
  const total=Number(p.chunks_total??s.chunks_total??0),done=Number(p.chunks_done??s.chunks_done??0);
  const read=Number(p.prompt_source_count??s.prompt_source_count??0);
  if(p.stage==='merging'||p.stage==='writing') return '正在整理我的日记 · 已读 '+read+' 条原话';
  if(total&&done<total) return '正在读当天的聊天 '+done+'/'+total+' 段'+(read?' · 已读 '+read+' 条原话':'');
  if(total) return '正在整理日记 · 已读 '+(read||p.source_count||s.source_count||0)+' 条原话';
  if(s.running) return '正在阅读各群聊天，整理我的一天…';
  return '已排队，等待阅读和写作…';
}
// 2026-10-23：失败的真实原因以前一律被压成「上次未写成，请稍后重试」——
// 于是账户欠费（402）和模型超时看起来一模一样，用户只看到「鱼不会写日记」。
// 这里把后端 last_error 翻成人能照着做的事。
function diaryReason(text){
  // 后端已脱敏，这里再兜一道：库里可能还留着脱敏之前写进去的 last_error，
  // 不能让它出现在页面上。
  const s=String(text||'').trim()
    .replace(/sk-[A-Za-z0-9_-]{6,}/g,'sk-***')
    .replace(/Bearer\s+[A-Za-z0-9_.-]{6,}/g,'Bearer ***');
  if(!s) return '这次没写成，我会自己重试。';
  if(/402|Payment\s*Required/i.test(s)) return '账户余额不足（402），充值后会自动补写这一天的。';
  if(/401|403|Unauthorized|invalid\s*api.?key/i.test(s)) return '接口密钥被拒（401/403），请检查日记里配置的密钥。';
  if(/429|rate.?limit|queue|concurrency/i.test(s)) return '模型那边在排队/限流，稍后自动重试。';
  if(/timed?\s*out|ReadTimeout|超时/i.test(s)) return '模型响应超时（已放宽到 300 秒），稍后自动重试。';
  if(/5\d\d|Server\s*Error|Bad\s*Gateway|Connection/i.test(s)) return '模型服务端出错或连接中断，稍后自动重试。';
  if(/主人/.test(s)) return '草稿里冒出了旧称呼，我会重写一遍。';
  if(/JSON|解析|截断/.test(s)) return '模型返回的内容不完整，已自动补全并重写。';
  return s.replace(/^日记生成失败[（(]?[^）)]*[）)]?[：:]?\s*/,'').slice(0,90);
}
async function loadDiaryStatus(){
  const s=await diaryFetch('status');
  const sel=$('diaryGroup'), selected=sel.value;
  sel.replaceChildren();
  const all=document.createElement('option');all.value='';all.textContent='全部群';sel.appendChild(all);
  for(const g of s.groups||[]){
    const option=document.createElement('option');option.value=String(g.group_id);
    option.textContent=g.name||g.group_name||String(g.group_id);sel.appendChild(option);
  }
  sel.value=selected;
  diaryText('diaryStatus',(s.enabled?'每天 '+(s.daily_time||'00:10')+' 完整阅读前一天各群聊天，写一本总日记':'自动写日记已暂停')+
    ' ｜ 上次写作：'+(s.last_success||'还没有')+' ｜ 下次：'+(s.next_run||'等待安排')+
    (s.last_error?' ｜ '+diaryReason(s.last_error):'')+
    ((s.running||s.queued)?' ｜ '+diaryProgressText(s):''));
  return s;
}
async function loadDiaryPage(){
  try{await loadDiaryStatus();if(!diaryPageLoaded){diaryPageLoaded=true;await loadDiaryList();}}
  catch(e){diaryText('diaryStatus',e.message);}
}
async function loadDiaryList(){
  try{
    const d=await diaryFetch('list?'+diaryParams());const box=$('diaryList');box.replaceChildren();
    $('diaryDetail').hidden=true;
    if(!(d.items||[]).length){box.textContent='这段时间还没有总日记。每天会在第二天写下，安静的日子也会如实记录。';return;}
    for(const item of d.items){
      const row=document.createElement('div');row.style.cssText='padding:12px 0;border-bottom:1px solid var(--line)';
      const open=document.createElement('button');open.textContent=item.date+' · '+(item.title||'我的一天');
      open.onclick=()=>openDiary(item.id);row.appendChild(open);
      const hint=document.createElement('p');hint.className='hint';
      hint.textContent='已读 '+(item.prompt_source_count??item.source_count??0)+' 条原话 · '+(item.total_groups||0)+' 个群'+(item.partial?' · 今天的暂记（次日会补齐）':'');row.appendChild(hint);box.appendChild(row);
    }
    diaryText('diaryMessage','找到 '+(d.total||d.items.length)+' 篇日记（本页最多50篇）');
  }catch(e){diaryText('diaryMessage',e.message);}
}
function appendDiarySources(box,sources){
  if(!sources.length){const none=document.createElement('p');none.textContent='没有匹配的原文。';box.appendChild(none);return;}
  for(const source of sources){
    const row=document.createElement('div');row.style.cssText='margin:12px 0;padding:12px;background:var(--bg);border-radius:9px';
    const label=document.createElement('small');label.textContent=(source.source_group_name||source.source_group_id||'来源群')+' · '+String(source.time||'')+' · '+(source.name||'')+'（'+(source.user_id||'')+'） · 消息 '+(source.message_id||'');
    const text=document.createElement('p');text.style.whiteSpace='pre-wrap';text.textContent=source.text||'';
    row.append(label,text);box.appendChild(row);
  }
}
async function openDiary(id){
  try{
    const d=await diaryFetch('detail/'+encodeURIComponent(id)),box=$('diaryDetail');box.replaceChildren();box.hidden=false;
    const title=document.createElement('h3');title.textContent=d.date+' · '+(d.title||'我的一天')+(d.partial?' · 暂记':'');
    const body=document.createElement('div');body.style.cssText='white-space:pre-wrap;line-height:1.95;margin:16px 0';body.textContent=d.body||'';
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='翻看聊天原文（事实来源） · 共 '+(d.source_count||0)+' 条'+((d.sources||[]).length<(d.source_count||0)?'，此处显示 '+(d.sources||[]).length+' 条，可用「查聊天原文」继续查找':'');
    details.appendChild(summary);appendDiarySources(details,d.sources||[]);box.append(title,body,details);
  }catch(e){diaryText('diaryMessage',e.message);}
}
async function searchDiarySources(){
  try{
    const d=await diaryFetch('search?'+diaryParams()),box=$('diaryDetail');box.replaceChildren();box.hidden=false;
    const title=document.createElement('h3');title.textContent='聊天原文';box.appendChild(title);appendDiarySources(box,d.items||[]);
    diaryText('diaryMessage','本次最多显示50条原文。');
  }catch(e){diaryText('diaryMessage',e.message);}
}
async function writeDiary(){
  if(diaryBusy)return;
  diaryBusy=true;$('diaryWrite').disabled=true;
  const date=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date());
  try{
    const d=await diaryFetch('generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({date,group_id:'0'})});
    if(d.accepted===false){diaryText('diaryMessage','今天的日记已经写好，或正在写作。');await loadDiaryList();return;}
    diaryText('diaryMessage','已经开始完整阅读今天各群的聊天，再整理成我的一篇日记。可以继续使用控制台。');
    const group='0';diaryPoll++;
    const token=diaryPoll;
    for(let i=0;i<120&&token===diaryPoll;i++){
      await new Promise(resolve=>setTimeout(resolve,5000));
      const s=await loadDiaryStatus();
      const own=(s.jobs||[]).find(job=>job.date===date&&String(job.group_id)===group);
      // 2026-10-23：失败态在后端叫 retry，不叫 failed —— 原来认不出来，
      // 会一直空转到 10 分钟上限，最后报「仍在后台写作」，其实一次都没写成（今晚 402 就是这么被盖住的）。
      const diaryFailed=!!(own&&['failed','skipped','retry'].includes(own.state));
      if(diaryFailed||(own&&['done','success'].includes(own.state))||(!s.running&&!s.queued)){
        $('diaryDate').value=date;$('diaryGroup').value='';$('diaryQuery').value='';await loadDiaryList();
        diaryText('diaryMessage',diaryFailed?('这次没写成：'+diaryReason(own&&own.last_error)+' 不用重复点，我会自己重试。')
          :'写作已结束，日记列表已刷新；今天的暂记会在次日自动补齐。');return;
      }
    }
    diaryText('diaryMessage','今天的聊天较多，我仍在后台阅读和写作。稍后点「查日记」查看，不必重复提交。');
  }catch(e){diaryText('diaryMessage',e.message);}
  finally{diaryBusy=false;$('diaryWrite').disabled=false;}
}

// ==================== 助手的本子 ====================
async function notebookFetch(path){
  const r=await fetch('/api/notebook'+path);
  const d=await r.json();
  if(!r.ok||d.error) throw new Error(d.error||'暂时翻不开本子');
  return d;
}
async function loadNotebook(){
  try{
    const query=$('notebookQuery').value.trim();
    const d=await notebookFetch('?'+new URLSearchParams({q:query}));
    const box=$('notebookList');box.replaceChildren();
    $('notebookDetail').hidden=true;
    if(!(d.items||[]).length){box.textContent='本子里暂时还没有这一页。';$('notebookMessage').textContent='';return;}
    for(const item of d.items){
      const row=document.createElement('div');row.className='row';
      row.style.cssText='padding:10px 0;border-bottom:1px solid var(--line);flex-wrap:wrap';
      const open=document.createElement('button');open.textContent=(item.date||'')+' · '+(item.title||'没有标题');
      open.onclick=()=>openNotebook(item.id);
      const hint=document.createElement('span');hint.className='hint';
      hint.textContent=(item.kind==='letter'?'妈妈的信':'我留下的')+' · '+String(item.body||'').slice(0,80);
      row.append(open,hint);box.appendChild(row);
    }
    $('notebookMessage').textContent='共 '+(d.total||d.items.length)+' 页';
  }catch(e){$('notebookMessage').textContent=e.message;}
}
async function openNotebook(id){
  try{
    const d=await notebookFetch('/'+encodeURIComponent(id));
    const box=$('notebookDetail');box.replaceChildren();box.hidden=false;
    const title=document.createElement('h3');title.textContent=(d.date||'')+' · '+(d.title||'我的一页');
    const body=document.createElement('div');body.style.cssText='white-space:pre-wrap;line-height:1.95;margin:16px 0';
    body.textContent=d.body||'';
    box.append(title,body);
    box.scrollIntoView({behavior:'smooth',block:'start'});
  }catch(e){$('notebookMessage').textContent=e.message;}
}

// ==================== 历史消息搜索 ====================
// 直接走面板的 /api/mon/messages 代理（= qq-monitor 的搜索接口），纯前端实现。
let _skLoaded = false;
async function loadSearchGroups(){
  if(_skLoaded) return;
  try{
    const d = await api('/api/groups/switches');
    if(d.success){
      const sel = $('skGroup');
      sel.innerHTML = '<option value="">全部群</option>' + (d.groups||[]).map(g=>
        `<option value="${g.group_id}">${esc(g.group_name || g.group_id)}</option>`).join('');
      _skLoaded = true;
    }
  }catch(e){}
}
async function doSearch(){
  const kw = (($('skKw')||{}).value || '').trim();
  const gid = ($('skGroup')||{}).value || '';
  const date = ($('skDate')||{}).value || '';
  const box = $('skResult');
  if(!kw && !gid && !date){ box.innerHTML = '<span class="hint">至少填一个条件：关键词 / 群 / 日期</span>'; return; }
  const p = new URLSearchParams();
  p.set('page_size','200');
  if(kw) p.set('keyword', kw);
  if(gid) p.set('group_id', gid);
  if(date){ p.set('start_time', date + ' 00:00:00'); p.set('end_time', date + ' 23:59:59'); }
  box.innerHTML = '<span class="hint">搜索中…</span>';
  let d;
  try { d = await api('/api/mon/messages?' + p.toString()); }
  catch(e){ box.innerHTML = '<span class="hint" style="color:var(--err)">读不到监控数据：' + esc(e) + '</span>'; return; }
  if(d.error){ box.innerHTML = '<span class="hint" style="color:var(--err)">' + esc(d.error) + '</span>'; return; }
  const ms = d.messages || [];
  if(!ms.length){ box.innerHTML = '<span class="hint">没有匹配的消息</span>'; return; }
  box.innerHTML = `<div class="hint" style="margin-bottom:8px">共 ${d.total} 条（显示前 ${ms.length} 条）</div>`
    + ms.map(m=>{
      const txt = searchMsgText(m);
      return `<div class="row" style="border-bottom:1px solid var(--line2);padding:7px 0;align-items:flex-start;gap:10px">
        <span style="flex:none;font-size:11.5px;color:var(--t3);width:130px">${esc(m.datetime || '')}</span>
        <span style="flex:none;font-size:12px;color:var(--t2);width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(m.nickname || m.user_id || '')}</span>
        <span style="flex:1;font-size:13px">${esc(txt)}</span></div>`;
    }).join('');
}
function searchMsgText(m){
  const c = m.content;
  if(typeof c === 'string') return c;
  if(c && c.text) return c.text;
  if(c && c.raw_message) return c.raw_message;
  return m.raw_message || '[图片/卡片]';
}

// ==================== 开机自启管理 ====================
async function loadAutostart(){
  const box = $('asList');
  if(!box) return;
  let d;
  try { d = await api('/api/autostart'); }
  catch(e){ box.innerHTML = '<span class="hint">读取失败：' + esc(e) + '</span>'; return; }
  if(!d.success){ box.innerHTML = '<span class="hint">' + esc(d.message || '读取失败') + '</span>'; return; }
  box.innerHTML = (d.items || []).map(it=>{
    const on = it.state === 'enabled';
    const badge = on ? '<span class="badge ok">已启用</span>'
                     : (it.state === 'disabled' ? '<span class="badge off">已禁用</span>'
                                                : '<span class="badge off">不存在</span>');
    return `<div class="svc ${on?'on':''}">
      <span class="dot ${on?'on':''}"></span>
      <div class="info"><div class="name">${esc(it.label)} ${badge}</div>
      <div class="sub">${esc(it.desc || '')}</div></div>
      ${it.state !== 'enabled'
        ? `<button class="p" onclick="autoAct('${it.key}','enable')">启用</button>`
        : `<button class="d" onclick="autoAct('${it.key}','disable')">禁用</button>`}
    </div>`;
  }).join('');
}
async function autoAct(k,a){
  const r = await api('/api/autostart',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({key:k, action:a})});
  say('asMsg', r.message, r.success);
  loadAutostart();
}

// ==================== 标记用户 ====================
// 有人在群里 @机器人、且 **@ 之后**的文本里带 `**`，qq-monitor 就记一条流水
// （见 qq-monitor/src/marked_users.py）。本页只读：上面按 QQ 聚合，下面列流水。
// 次数/首次/最近都是从流水算出来的，不另存一份 —— 两份数据必然会对不上。
let _mkData = { summary: [], events: [] };

async function loadMarked(){
  let d;
  try { d = await api('/api/marked_users'); }
  catch(e){ say('mkMsg', '读取失败：' + e, false); return; }
  if(!d.success){ say('mkMsg', d.message || '读取失败', false); return; }
  _mkData = { summary: d.summary || [], events: d.events || [] };
  say('mkMsg', '', true);
  $('mkStat').textContent = `共 ${d.total} 条流水，去重后 ${d.unique} 人`;
  $('mkHint').textContent = d.total ? `数据：${d.file}` : '还没人触发过';
  mkRender();
}

function mkRender(){
  const kw = (($('mkKw') || {}).value || '').trim().toLowerCase();
  const hit = v => !kw || String(v == null ? '' : v).toLowerCase().includes(kw);
  const sum = (_mkData.summary || []).filter(r => hit(r.qq) || hit(r.nickname) || hit(r.groups));
  const evs = (_mkData.events || []).filter(r => hit(r.qq) || hit(r.nickname)
                                                || hit(r.group_id) || hit(r.group_name)
                                                || hit(r.by_nickname) || hit(r.by_qq) || hit(r.text));
  if(!sum.length && !evs.length){
    $('mkList').innerHTML = `<div class="hint">${kw
      ? '没有匹配的记录'
      : '还没有人被标记 —— 群里有人 @机器人 并在 @ 之后发 ** 时，这里就会出现记录。'}</div>`;
    return;
  }
  let html = '';
  if(sum.length){
    html += `<div class="hint" style="margin:10px 0 2px">按 QQ 聚合（${sum.length} 人，指的是被 @ 的人）</div>`;
    html += sum.map(r => `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0;align-items:center">
      <span style="flex:none;width:130px">${esc(r.qq)}</span>
      <span style="flex:1;min-width:110px">${esc(r.nickname || '')}${r.role ? `<span class="hint"> · ${esc(r.role)}</span>` : ''}</span>
      <span class="hint" style="flex:none;width:70px;text-align:right">${esc(String(r.count))} 次</span>
      <span class="hint" style="flex:none;width:200px;padding-left:10px">${esc(r.first || '')} → ${esc(r.last || '')}</span>
      <span class="hint" style="flex:none;max-width:220px">${esc(r.groups || '')}</span>
    </div>`).join('');
  }
  if(evs.length){
    html += `<div class="hint" style="margin:14px 0 2px">流水（最近 ${evs.length} 条，新→旧）</div>`;
    html += evs.map(r => `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0;align-items:flex-start">
      <span class="hint" style="flex:none;width:140px">${esc(r.ts || '')}</span>
      <span style="flex:none;width:190px">${esc(r.qq)} <span class="hint">${esc(r.nickname || '')}${r.role ? ` · ${esc(r.role)}` : ''}</span></span>
      <span class="hint" style="flex:none;width:130px">${esc(r.group_name || ('群' + (r.group_id || '')))}</span>
      <span class="hint" style="flex:none;width:120px">由 ${esc(r.by_nickname || r.by_qq || '?')}</span>
      <span style="flex:1;min-width:150px;font-size:13px">${esc(r.text || '')}</span>
    </div>`).join('');
  }
  $('mkList').innerHTML = html;
}

// ==================== 群聊开关 ====================
// 每个群两个独立开关：监控（要不要审查这个群）、发言（麦麦要不要在这里说话）
// 注意函数名带 Switch 前缀：面板里已有同名的 loadGroups（监控页的群组概览），
// 重名会让后声明的覆盖先声明的，点新页签其实调的是旧函数（2026-09-15 踩过）。
let _gs = null, _talk = null;
async function loadSwitchGroups(force){
  const d = await api('/api/groups/switches');
  if(!d.success){ say('gsMsg', d.message||'读取失败', false); return; }
  _gs = d;
  // 顺手把「按群的发言强度」读回来（麦麦 chat.reply_timing.talk_value_rules）
  try { const t = await api('/api/talk_strength'); _talk = (t && t.success) ? t : null; }
  catch(e){ _talk = null; }
  const hint = d.napcat_ok
    ? `共 ${d.groups.length} 个群（群列表来自 OneBot 接口）`
    : `⚠ 取不到 OneBot 的群列表（QQ 端未登录？），只列出了配置里出现过的群`;
  $('gsHint').textContent = hint + `　群名单模式：${d.mode === 'whitelist' ? '白名单（名单内才发言）' : '黑名单（名单内不发言）'}`
    + (d.chat_owner ? `　｜ 这份名单存在「${d.chat_owner}」的配置里` : '');
  $('gsList').innerHTML = d.groups.map((g,i)=>`
    <div class="row" style="border-bottom:1px solid #f0f0f0;padding:7px 0;align-items:center">
      <span style="flex:1;min-width:220px;font-size:13px">
        ${esc(g.group_name || '(未知群名)')}
        <span style="color:#999;font-size:12px"> · ${esc(String(g.group_id))}</span>
        ${g.member_count?`<span style="color:#bbb;font-size:11px"> · ${g.member_count} 人</span>`:''}
      </span>
      <label style="width:130px;font-size:13px;flex:none">
        <input type="checkbox" id="gs_m_${i}" ${g.monitored?'checked':''}> 监控
      </label>
      <label style="width:130px;font-size:13px;flex:none">
        <input type="checkbox" id="gs_s_${i}" ${g.speak?'checked':''}> 发言
      </label>
      <label style="width:170px;font-size:13px;flex:none" title="0~1，越大麦麦在这个群越爱说话；留空=用全局默认">
        强度 <input type="number" id="gs_t_${i}" min="0" max="1" step="0.05" style="width:66px"
          value="${(_talk && _talk.by_group[String(g.group_id)] !== undefined) ? _talk.by_group[String(g.group_id)] : ''}"
          placeholder="${_talk ? _talk.default : 0.2}">
      </label>
      <span style="width:150px;flex:none;font-size:11px;color:#999" id="gs_st_${i}">
        ${g.monitored?'<span style="color:#2a2">审查中</span>':'<span style="color:#bbb">不审查</span>'}
        ${g.speak?'<span style="color:#2a2">可发言</span>':'<span style="color:#c33">禁言</span>'}
      </span>
    </div>`).join('') || '<div class="hint">没有群。</div>';
}
function gsAllSpeak(v){
  if(!_gs) return;
  _gs.groups.forEach((g,i)=>{ const el=$(`gs_s_${i}`); if(el) el.checked=v; });
  say('gsMsg', v?'已把全部群勾成「允许发言」，点「保存开关」生效':'已把全部群勾成「禁止发言」，点「保存开关」生效', true);
}
// 保存每个群的发言强度（0~1）→ 麦麦 chat.reply_timing.talk_value_rules
async function saveTalkStrength(andRestart){
  if(!_gs){ return; }
  const map = {};
  for(let i=0;i<_gs.groups.length;i++){
    const el = $('gs_t_'+i);
    if(!el) continue;
    const v = String(el.value||'').trim();
    if(v === '') continue;                 // 留空 = 这个群不单独设，用全局默认
    const f = Number(v);
    if(!(f >= 0 && f <= 1)){
      say('gsMsg', `群 ${_gs.groups[i].group_id} 的强度要填 0~1 之间的数（留空=用全局默认）`, false);
      return;
    }
    map[String(_gs.groups[i].group_id)] = f;
  }
  const r = await api('/api/talk_strength', {method:'POST', headers:{'Content-Type':'application/json'},
                      body: JSON.stringify({groups: map})});
  say('gsMsg', r.message, r.success);
  if(r.success) loadSwitchGroups(true);     // 重新读回来，确认写进去了
  if(r.success && andRestart){
    // 麦麦只在**启动时**读配置，所以"保存并重启"才是一次到位的操作
    say('gsMsg', '已保存，正在重启麦麦（约 10 秒）…', true);
    const rr = await api('/api/service/maibot/restart', {method:'POST'});
    say('gsMsg', (rr.message || '重启完成') + '　—— 各群的新发言强度现在生效了', rr.success);
    setTimeout(refresh, 1500);
  }
}

async function saveSwitchGroups(){
  if(!_gs) return;
  const items = _gs.groups.map((g,i)=>({
    group_id: g.group_id,
    monitored: $(`gs_m_${i}`).checked,
    speak: $(`gs_s_${i}`).checked,
  }));
  if(!items.some(x=>x.monitored)){
    say('gsMsg','至少要监控一个群（监控系统的配置要求监控群非空）', false); return;
  }
  const r = await api('/api/groups/switches',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({groups:items})});
  say('gsMsg', r.message, r.success);
  if(r.success){ loadSwitchGroups(true); refresh(); }
}

// ==================== 关键词回复（监控直发，不依赖麦麦） ====================
// 2026-09-23 用户要做招新问答：提到「部门 / 加入 / 摆摊」就把固定答复原样发出去。
// 规则文件 qq-monitor\config\keyword_reply.json，**发消息的是监控**（麦麦关着也能用）；
// 监控按文件 mtime 热重载，所以这里保存完立即生效，不用重启。
let _kwr = null, _kwrPool = null;
// 非「普通回复」的规则类型（reply 由监控动态生成，不用填回复内容）。
// 与后端 keyword_reply_set 的白名单、以及 qq-monitor 的 rule_type() 保持一致。
// 🔴 2026-10-21：补上 reflect（禁闭反思）。它当初只加进了监控的 KNOWN_RULE_TYPES，
// 这里和下面的 _RTYPES 都没加 → 在面板上编辑禁闭规则会被**降级保存成 text**，
// 规则整条改坏（reply 变必填）。新增类型请把这三处一起补。
const KWR_SPECIAL = ['quirky','food','favor','learn','mylearn','sing','groupon','study','reflect'];
// 类型下拉选项（顺序即展示顺序）
const KWR_TYPES = [
  ['text',     '普通回复'],
  ['quirky',   '随机怪话'],
  ['food',     '抽食物（「吃什么」→ 从食物库抽一条）'],
  ['favor',    '好感度查询（仅管理员）'],
  ['learn',    '学习（「学怪话 正文」/ 发图+「学表情包」）'],
  ['mylearn',  '查我教的（「我教的」）'],
  ['sing',     '唱歌 / 点歌（走 RVC，默认全开，可单独关某个群）'],
  ['groupon',  '群内唱歌开关（「打开唱歌」「关闭唱歌」）'],
  ['study',    '闭关学习（「闭关 30 分钟」/「出关」，管理员）'],
  ['reflect',  '禁闭反思（「禁闭」→ 闭嘴反省，到期发悔过书，管理员）'],
];
let _sing = null, _singGroups = [], _singDisabled = [];
// 唱歌状态：**默认全开**，表里只记「被关掉的群」+ 队列（GET /api/sing/status）。
// 改完监控热读，立即生效 —— 不用重启、不用把群加进监控名单。
async function loadSing(force){
  try{
    const d = await api('/api/sing/status');
    if(!d.success){ say('singMsg', d.message||'读取失败', false); return; }
    _sing = d.data || {};
  }catch(e){ say('singMsg', '读取失败：'+e, false); return; }
  const s = _sing.status || {};
  $('singModel').textContent = _sing.model ? ('当前音色：'+_sing.model) : '';
  $('singHint').textContent = _sing.tools_ok ? '' : '（唱歌服务没就绪）';
  const running = s.running ? '正在唱' : '待机';
  const cur = s.current ? ('，正在唱《'+esc(s.current)+'》') : '';
  const que = s.queue ? ('，队列 '+s.queue+' 首') : '';
  const last = s.last_result ? ('　上次：'+esc(String(s.last_result)).slice(0,120)) : '';
  $('singState').textContent = `服务 ${running}${cur}${que}${last}`;
  if(_sing.error) $('singState').textContent += '　错误：'+_sing.error;
  singRender();
}
// 已生成过的歌：再点同款直接重发成品、不重新生成；管理员可说「重唱《歌名》」强制重录
function singCacheHint(){
  const cache = ((_sing && _sing.status) || {}).cache || [];
  if(!cache.length) return '';
  const names = cache.map(c=>esc(String(c.query||'')));
  return '<div class="hint">🎵 已生成过的歌（再点同款直接重发，不重新生成）：'+names.join('、')
    +'。管理员在群里说「重唱《歌名》」可强制重录一版。</div>';
}
function singRender(){
  const dis = ((_sing && _sing.disabled_groups) || []).map(String);
  _singDisabled = dis;
  const gs = (_sing && _sing.groups) || [];
  _singGroups = gs.map(g=>String(g.group_id));
  if(gs.length){
    $('singList').innerHTML =
      `<div class="hint">机器人所在的群（${gs.length}）—— 默认全开：</div>` +
      gs.map((g,ix)=>{
        const gid = String(g.group_id);
        const off = dis.indexOf(gid) >= 0;
        const nm = g.group_name || '(未命名)';
        return `<div class="row" style="align-items:center;margin:3px 0">
          <code style="flex:none">${esc(gid)}</code>
          <span class="hint" style="flex:1;margin:0">${esc(nm)}</span>
          <span style="flex:none">${off ? '已关掉' : '可以唱'}</span>
          <button style="flex:none" onclick="singGroupToggle(${ix})">${off ? '打开' : '关掉'}</button>
        </div>`;
      }).join('') + singCacheHint();
    return;
  }
  const err = (_sing && _sing.groups_error) || '';
  $('singList').innerHTML = (dis.length
    ? ('<div class="hint">被关掉唱歌的群（'+dis.length+'）：</div>' + dis.map((gid,ix)=>
        `<span class="row" style="align-items:center;margin:3px 0">
           <code style="flex:none">${esc(gid)}</code>
           <button style="flex:none" onclick="singToggleByIndex(${ix}, true)">打开</button>
         </span>`).join(''))
    : ('<div class="hint">还没关过任何群 —— 默认全开。'+(err ? ('（'+esc(err)+'）') : '')+'</div>'))
    + singCacheHint();
}
// 按钮只传下标（群号可能是脏数据，不往 onclick 里拼字符串 —— 项目规矩）
function singToggleByIndex(ix, on){
  const gid = (_singDisabled || [])[ix];
  if(!gid){ say('singMsg','群号找不到了，刷新一下再试', false); return; }
  singToggle(gid, on);
}
// 群列表里的按钮：下标 → 群号 → 取反（开着就关，关着就开）
function singGroupToggle(ix){
  const gid = (_singGroups || [])[ix];
  if(!gid){ say('singMsg','群号找不到了，刷新一下再试', false); return; }
  const off = (_singDisabled || []).indexOf(String(gid)) >= 0;
  singToggle(gid, off);
}
// 「全部打开 / 全部关闭」：一次请求批量改（群列表拉不到就让用户自己填群号）
async function singToggleAll(on){
  const gs = (_sing && _sing.groups) || [];
  const ids = gs.map(g=>String(g.group_id));
  if(!ids.length){ say('singMsg','取不到群列表，用下面的群号单独改吧', false); return; }
  singToggle(ids, on);
}
async function singToggle(gidOrIds, on){
  if(on === undefined || on === null){ say('singMsg', '内部错误：缺少开关状态', false); return; }
  const list = (Array.isArray(gidOrIds) ? gidOrIds : [gidOrIds])
    .map(x=>String(x == null ? '' : x).trim()).filter(x=>x);
  if(!list.length){ say('singMsg','请先填群号', false); return; }
  try{
    const body = list.length === 1 ? {group_id:list[0], on:!!on}
                                   : {group_ids:list, on:!!on};
    const r = await api('/api/sing/toggle',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    say('singMsg', r.message, r.success);
    if(r.success) loadSing(true);
  }catch(e){ say('singMsg','请求失败：'+e, false); }
}
function singToggleUI(on){
  const gid = ($('singGid') ? $('singGid').value : '').trim();
  singToggle(gid, on);
}

async function loadKwr(){
  const d = await api('/api/keyword_reply');
  if(!d.success){ say('kwrMsg', d.message||'读取失败', false); return; }
  _kwr = d.data || {};
  $('kwrPath').textContent = d.path ? ('规则文件：' + d.path) : '';
  $('kwrEnabled').checked = _kwr.enabled !== false;
  $('kwrMention').checked = _kwr.mention === true;
  $('kwrCd').value = (_kwr.cooldown_seconds === undefined ? 60 : _kwr.cooldown_seconds);
  $('kwrGroups').value = (_kwr.groups || []).join(', ');
  $('kwrQf').value = _kwr.quirky_file || '';
  $('kwrMc').value = (_kwr.max_chars === undefined ? 0 : _kwr.max_chars);
  kwrRender();
  kwrPoolInfo();
}
// 怪话库现状（条数 + 按当前字数上限还剩多少能发）—— 页面上看得见，免得「@了没反应」时瞎猜
async function kwrPoolInfo(){
  try{ const d = await api('/api/quirky'); _kwrPool = d.items || null; }
  catch(e){ _kwrPool = null; }
  kwrPoolLine();
}
function kwrUsable(){
  const mc = parseInt(($('kwrMc') ? $('kwrMc').value : '') || '0', 10) || 0;
  return (_kwrPool||[]).filter(x=>x.enabled!==false && String(x.text||'').trim()
                               && (!mc || String(x.text).length<=mc)).length;
}
function kwrPoolLine(){
  const mc = parseInt(($('kwrMc') ? $('kwrMc').value : '') || '0', 10) || 0;
  $('kwrPoolHint').textContent = _kwrPool
    ? `怪话库共 ${_kwrPool.length} 条；按当前上限（${mc||'不限'} 字）可发 ${kwrUsable()} 条`
    : '怪话库读取失败（监控/麦麦的 data/quirky_lines.json 读不到）';
}
// 特殊类型（不用填 reply）的说明文案。写成函数而不是嵌套三元 —— 三元套三元一旦
// 少一个括号，整页 JS 直接语法错，check_js 会红（2026-10-13 加 study 时踩过）。
function kwrSpecialHint(t){
  if(t === 'study')
    return '回复内容不用填 —— 命中后让麦麦<b>闭关学习</b>：一段时间内一条消息都不回，'
         + '把攒下的群消息分批喂给学习器（喊「出关」提前结束）。只有管理员能下令；'
         + '时长写在话里（「闭关 30 分钟」「学习半小时」），不写就按 30 分钟。半夜的自动学习照常。';
  if(t === 'sing')
    return '回复内容不用填 —— 命中后走「UVR5 分离 + RVC 转音色 + 混音」发语音。'
         + '<b>默认所有群都能唱</b>，只有被关掉的群才回一句提示、不唱（页面上或在群里说「关闭唱歌」）。';
  if(t === 'groupon')
    return '回复内容不用填 —— 命中后开/关「本群能不能唱歌」（写 qq-monitor/config/sing_groups.json）。';
  return `回复内容不用填 —— 命中后从怪话库随机挑一条（当前可发 ${kwrUsable()} 条）。`;
}
function kwrRender(){
  const rules = (_kwr && _kwr.rules) || [];
  $('kwrList').innerHTML = rules.map((r,i)=>{
    const t = KWR_SPECIAL.includes(r.type) ? r.type : 'text';
    const head = `
      <div class="row" style="align-items:center">
        <label style="font-size:13px;flex:none"><input type="checkbox" id="kwrE_${i}" ${r.enabled!==false?'checked':''}> 启用</label>
        <span class="hint" style="flex:none">第 ${i+1} 条</span>
        <label style="font-size:13px;flex:none">类型 <select id="kwrT_${i}" onchange="kwrSwitch(${i}, this.value)">
          ${KWR_TYPES.map(([v,label])=>`<option value="${v}" ${t===v?'selected':''}>${label}</option>`).join('')}
        </select></label>
        <button style="flex:none" onclick="kwrDel(${i})">删除</button>
      </div>`;
    const kws = `<label class="f"><span class="k">触发词（逗号分隔，命中任意一个就回）</span>
        <input id="kwrK_${i}" value="${esc((r.keywords||[]).join(', '))}"></label>`;
    if(KWR_SPECIAL.includes(t)){
      const hint = kwrSpecialHint(t);
      return `<div class="card" style="margin:6px 0;padding:10px;background:#fafafa">${head}${kws}
        <label class="f"><span class="k">前缀（可留空）</span>
          <input id="kwrP_${i}" value="${esc(r.prefix||'')}" placeholder="留空 = 直接发"></label>
        <label style="font-size:13px"><input type="checkbox" id="kwrA_${i}" ${r.require_at_bot===false?'':'checked'}>
          必须 @ 到机器人才发（推荐：群里闲聊提到触发词不会乱发）</label>
        <label style="font-size:13px"><input type="checkbox" id="kwrM_${i}" ${r.mention===true?'checked':''}>
          发出去时 @ 提问的人（默认不勾 = 只发正文，不 @ 人）</label>
        <div class="hint">${hint}</div>
      </div>`;
    }
    return `<div class="card" style="margin:6px 0;padding:10px;background:#fafafa">${head}${kws}
      <label class="f"><span class="k">回复内容（原样发出，一个字都不会改）</span>
        <textarea id="kwrR_${i}" style="min-height:70px">${esc(r.reply||'')}</textarea></label>
    </div>`;
  }).join('') || '<div class="hint">还没有规则，点「加一条规则」。</div>';
  kwrTestRun();
}
// 切换规则类型：先把正在编辑的内容收回 _kwr，再重画（不然输入会丢）
function kwrSwitch(i, v){
  const cur = kwrCollect();
  const r = cur.rules[i];
  r.type = KWR_SPECIAL.includes(v) ? v : 'text';
  if(KWR_SPECIAL.includes(r.type)){
    r.prefix = r.prefix || '';
    r.require_at_bot = true;
    r.reply = '';
  }
  _kwr = cur;
  kwrRender();
  say('kwrMsg','类型改了，点「保存」才写进文件', true);
}
function kwrCollect(){
  const rules = ((_kwr && _kwr.rules) || []).map((r,i)=>{
    const t = ($('kwrT_'+i) ? $('kwrT_'+i).value : (r.type||'text'));
    const o = {
      enabled: $('kwrE_'+i) ? $('kwrE_'+i).checked : true,
      type: KWR_SPECIAL.includes(t) ? t : 'text',
      keywords: ($('kwrK_'+i) ? $('kwrK_'+i).value : '').split(/[,，\n]/).map(x=>x.trim()).filter(Boolean),
      reply: '',
    };
    // 原样带着 id 走（learn 等规则靠 id 认领，丢了会出问题）
    if(r && r.id) o.id = r.id;
    if(KWR_SPECIAL.includes(o.type)){
      o.prefix = $('kwrP_'+i) ? $('kwrP_'+i).value.trim() : (r.prefix||'');
      o.require_at_bot = $('kwrA_'+i) ? $('kwrA_'+i).checked : (r.require_at_bot !== false);
      o.mention = $('kwrM_'+i) ? $('kwrM_'+i).checked : (r.mention === true);
    } else {
      o.reply = $('kwrR_'+i) ? $('kwrR_'+i).value.trim() : '';
    }
    return o;
  });
  return {
    enabled: $('kwrEnabled').checked,
    mention: $('kwrMention').checked,
    cooldown_seconds: parseInt($('kwrCd').value||'0',10) || 0,
    groups: ($('kwrGroups').value||'').split(/[,，\s]+/).map(x=>x.trim()).filter(Boolean),
    quirky_file: $('kwrQf') ? $('kwrQf').value.trim() : '',
    max_chars: parseInt(($('kwrMc') ? $('kwrMc').value : '') || '0', 10) || 0,
    rules: rules,
  };
}
function kwrAdd(){
  const cur = kwrCollect();          // 先收一遍，免得正在编辑的内容丢了
  cur.rules.push({enabled:true, type:'text', keywords:[], reply:''});
  _kwr = cur;
  kwrRender();
  say('kwrMsg','加了一条，填好触发词和回复内容再点「保存」', true);
}
function kwrDel(i){
  const cur = kwrCollect();
  if(!confirm('删掉第 ' + (i+1) + ' 条规则？')) return;
  cur.rules.splice(i,1);
  _kwr = cur;
  kwrRender();
  say('kwrMsg','删掉了，点「保存」才写进文件', true);
}
async function kwrSave(){
  const data = kwrCollect();
  const r = await api('/api/keyword_reply',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({data:data})});
  say('kwrMsg', r.message, r.success);
  if(r.success) loadKwr();
}
function kwrTestRun(){
  const t = ($('kwrTest') ? $('kwrTest').value : '') || '';
  const rules = ((_kwr && _kwr.rules) || []);
  if(!t.trim()){ $('kwrTestOut').textContent = ''; return; }
  for(let i=0;i<rules.length;i++){
    const r = rules[i];
    if(r.enabled === false) continue;
    const hit = (r.keywords||[]).find(k=>k && t.includes(k));
    if(hit){
      if(KWR_SPECIAL.includes(r.type)){
        // 这里只算触发词；真发还要看有没有 @ 到机器人（页面上给个醒目提示）
        const at = (r.require_at_bot === false) ? '不用 @ 机器人' : '必须 @ 到机器人才发';
        if(r.type === 'sing'){
          $('kwrTestOut').textContent =
            `命中第 ${i+1} 条（「${hit}」）→ 点歌唱歌（${at}；歌名取自书名号/引号里的内容，`
            + `没写歌名就回「想听什么呀」；非开启开关的群只回提示）`;
        } else if(r.type === 'groupon'){
          $('kwrTestOut').textContent =
            `命中第 ${i+1} 条（「${hit}」）→ 开/关本群唱歌开关（${at}）`;
        } else if(r.type === 'study'){
          $('kwrTestOut').textContent =
            `命中第 ${i+1} 条（「${hit}」）→ 闭关学习：一段时间内不回消息、专心学`
            + `（${at}；时长从话里抠「闭关 30 分钟 / 学习半小时」，不写按 30 分钟；`
            + `喊「出关」提前结束；只有管理员能下令）`;
        } else {
          $('kwrTestOut').textContent =
            `命中第 ${i+1} 条（「${hit}」）→ 从怪话库随机挑一条发（${at}；可发 ${kwrUsable()} 条；前缀「${r.prefix||'无'}」）`;
        }
      } else {
        $('kwrTestOut').textContent = `命中第 ${i+1} 条（「${hit}」）→ ${r.reply||'(回复是空的)'}`;
      }
      return;
    }
  }
  $('kwrTestOut').textContent = '没有命中任何规则 → 不会回复';
}

// ==================== 群聊消息 ====================
// 数据全部经 /api/mon/* 从监控面板(:8080)取，不在前端直连（会被 CORS 挡，且监控可能设了令牌）。
// 注意：聊天内容是**不可信输入**，一律经 esc() 再进 HTML。
let _mon = {base:'http://127.0.0.1:8080', token:'', ready:false, page:1, alertsPage:1};
const MON_GROUPS = [];

async function loadMon(force){
  const h = await api('/api/mon/health');
  _mon.base = h.base || _mon.base;
  _mon.token = h.token || '';
  if(!h.running){
    $('monHint').textContent = '监控服务没在运行。先到「服务控制」启动「监控告警系统」。';
    $('monStats').innerHTML = '<span class="hint">监控服务未运行</span>';
    $('monList').innerHTML = ''; $('alertList').innerHTML = ''; $('groupList').innerHTML = '';
    $('monPagerTop').textContent = ''; $('monPagerBot').textContent = ''; $('alertPager').textContent = '';
    return;
  }
  $('monHint').textContent = '数据来自监控面板 ' + _mon.base;
  try{
    const st = await api('/api/mon/stats');
    renderMonStats(st);
  }catch(e){ say('monMsg','统计读取失败：'+e, false); }
  await loadGroups();
  await monSearch(1);
  await loadAlerts();
  await loadAlertUsers();
}

function renderMonStats(st){
  const conn = st.ws_connected;
  const tp = st.history_topup || {};
  const bf = st.backfill || {};
  // 「AI 发言」这几个数是回答"导出的记录里有没有机器人自己说的话"最直接的证据
  const aiTxt = bf.running
    ? `补齐中：第 ${bf.pages||0} 页，新增 ${bf.added||0} 条（AI ${bf.self_added||0}）`
    : `最近补齐：${tp.last_run||'还没跑过'} 新增 ${tp.last_added||0} 条（AI ${tp.last_self_added||0}）`
      + `　间隔 ${tp.interval||0}s`;
  $('monStats').innerHTML = `<div class="stat">
    <div class="i"><div class="v">${st.total_messages??'-'}</div><div class="l">已存消息</div></div>
    <div class="i"><div class="v">${st.total_alerts??'-'}</div><div class="l">违规告警</div></div>
    <div class="i"><div class="v">${st.total_groups??'-'}</div><div class="l">监控群数</div></div>
    <div class="i"><div class="v">${st.pending_review??0}</div><div class="l">待审查</div></div>
    <div class="i"><div class="v">${st.storage_used_mb == null ? '计算中' : Number(st.storage_used_mb).toFixed(0)}</div><div class="l">占用 MB</div></div>
    <div class="i"><div class="v" style="color:${conn?'#2a2':'#c33'}">${conn?'在线':'离线'}</div><div class="l">QQ 连接</div></div>
    <div class="i"><div class="v">${st.session_messages??0}</div><div class="l">本次会话收到</div></div>
    <div class="i"><div class="v">${st.self_messages??0}</div><div class="l">本次自发言</div></div>
  </div><div class="hint">最后一条消息：${esc(st.last_message_time||'—')}</div>
  <div class="hint">${esc(aiTxt)}</div>`;
}

async function loadGroups(){
  try{
    const d = await api('/api/mon/groups/info');
    const gs = (d.groups||[]);
    MON_GROUPS.length = 0; MON_GROUPS.push(...gs);
    $('groupList').innerHTML = gs.map(g=>`
      <div class="row" style="border-bottom:1px solid #f0f0f0;padding:7px 0">
        <span style="width:170px;font-size:13px">${esc(g.group_name||('群'+g.group_id))}</span>
        <span style="width:120px;font-size:12px;color:#888">${esc(String(g.group_id))}</span>
        <span style="width:130px;font-size:12px;color:#888">${g.message_count??0} 条消息</span>
        <span style="width:110px;font-size:12px;color:#888">${g.date_files??0} 个日档</span>
        <span style="font-size:12px;color:${g.is_monitored?'#2a2':'#c33'}">${g.is_monitored?'监控中':'未监控'}</span>
      </div>`).join('') || '<div class="hint">没有群数据。</div>';
    const opts = '<option value="">全部群</option>' + gs.map(g=>
      `<option value="${g.group_id}">${esc(g.group_name||('群'+g.group_id))} (${g.message_count??0})</option>`).join('');
    const keepG = $('mGroup').value, keepA = $('aGroup').value;
    $('mGroup').innerHTML = opts; $('aGroup').innerHTML = opts;
    $('mGroup').value = keepG; $('aGroup').value = keepA;
  }catch(e){ $('groupList').innerHTML = `<div class="hint">读取失败：${esc(String(e))}</div>`; }
}

function imgUrl(p){
  // 只放行监控面板自己的 /api/ 路径：local_path 来自数据文件，
  // 不限制的话 javascript: 之类的伪协议会被塞进 href/src
  if(!p || typeof p !== 'string' || !p.startsWith('/api/')) return '';
  const u = _mon.base + p;
  return _mon.token ? u + (p.includes('?')?'&':'?') + 'token=' + encodeURIComponent(_mon.token) : u;
}

// 段类型 → 渲染。注意 text 段的 summary 是字面量 "text"，真正正文在 text 字段，
// 不能按 summary 优先取值（那样每条消息都会显示成 "text"）。
const SEG_LABEL = {face:'[表情]', reply:'[回复]', forward:'[合并转发消息]', markdown:'[markdown 卡片]',
  json:'[json 卡片]', xml:'[xml 卡片]', file:'[文件]', video:'[视频]', record:'[语音]', music:'[音乐]',
  poke:'[戳一戳]', shake:'[窗口抖动]', rps:'[猜拳]', dice:'[骰子]'};

// 一个段有两种形态，必须都认（实测同一次查询里两种都会出现）：
//   扁平： {"type":"text","text":"晚上好","summary":"text"}
//   嵌套： {"type":"text","data":{"text":"晚上好"}}
// 只认扁平那种的话，嵌套的 text 段会被当成空、at 段只剩一个「@」，
// 整条消息的正文就丢了（2026-09-15 用户发现）。
function segFlat(seg){
  const d = (seg && typeof seg.data === 'object' && seg.data) ? seg.data : null;
  return d ? Object.assign({}, seg, d) : seg;
}

function segHtml(rawSeg){
  const seg = segFlat(rawSeg);
  const t = seg.type || '';
  if(t === 'image'){
    const u = imgUrl(seg.local_path);
    if(u) return `<a href="${esc(u)}" target="_blank" rel="noopener">
      <img src="${esc(u)}" loading="lazy"
        style="max-width:170px;max-height:170px;border-radius:6px;border:1px solid #eee;vertical-align:top;margin:3px 4px 3px 0"></a>`;
    // 没落盘时别只丢一个灰色字：有原始直链就给个能点开的（QQ 的 rkey 没过期时还看得到），
    // 并把「为什么没落盘」放进悬停提示（img_error 是存储侧记下来的失败原因）。
    // 注意：这里不能用正则字面量写 http(s) 双斜杠 —— PAGE 是 Python 的 raw 三引号原文，
    // 反斜杠会原样进 JS，那样写出来的转义斜杠会被 JS 当成正则的结束符。
    // 另外：本段注释里也绝不能出现那个三引号开头的写法，它会把 PAGE 提前闭合（踩过一次）。
    const raw = (typeof seg.url === 'string'
      && (seg.url.indexOf('http://') === 0 || seg.url.indexOf('https://') === 0)) ? seg.url : '';
    const why = seg.img_error ? ` title="${esc('没落盘：' + seg.img_error)}"` : '';
    if(raw) return `<a href="${esc(raw)}" target="_blank" rel="noopener"${why}
      style="color:#c80;font-size:12px">[图片未落盘 ↗]</a> `;
    return `<span style="color:#c80;font-size:12px"${why}>[图片未落盘]</span> `;
  }
  if(t === 'text') return seg.text ? esc(seg.text) : '';
  if(t === 'at'){
    const n = seg.name || seg.qq || '';
    return `<span style="color:#06c">@${esc(n === 'all' ? '全体成员' : n)}</span> `;
  }
  const lab = SEG_LABEL[t];
  if(lab) return `<span style="color:#888;font-size:12px">${lab}</span> `;
  // 兜底：summary 有意义就用，否则用原始类型名，别把内容丢了
  const s = (seg.summary && seg.summary !== t) ? seg.summary : '';
  return s ? `<span style="color:#888;font-size:12px">${esc(s)}</span> `
           : (t ? `<span style="color:#888;font-size:12px">[${esc(t)}]</span> ` : '');
}

function rawPreview(m){
  // 兜底显示：把 [CQ:...] 码去掉，避免满屏机器码
  let s = String(m.raw_message || '').replace(/\[CQ:[^\]]*\]/g, '');
  s = s.replace(/&#91;/g,'[').replace(/&#93;/g,']').replace(/&amp;/g,'&').replace(/&#44;/g,',');
  return s.trim().slice(0, 300);
}

function msgHtml(m, flagged){
  const c = m.content || {};
  const parts = (c.segments || []).map(segHtml);
  const body = parts.some(p => p && p.trim()) ? parts.join('') : esc(rawPreview(m));
  return `<div style="display:flex;gap:10px;padding:6px 0;border-bottom:1px solid #f5f5f5">
    <div style="width:132px;flex:none;font-size:11px;color:#999;line-height:1.5">
      ${esc(m.datetime||'')}<br>群 ${esc(String(m.group_id||''))}</div>
    <div style="width:150px;flex:none;font-size:12px;line-height:1.5">
      <b>${esc(m.nickname||'(无名)')}</b><br>
      <span style="color:#999">${esc(String(m.user_id||''))}</span>
      ${m.role==='owner'||m.role==='admin'?`<span style="color:#c60"> · ${esc(m.role)}</span>`:''}</div>
    <div style="flex:1;font-size:13px;line-height:1.6;word-break:break-word">
      ${flagged?'<span style="background:#ffe1e1;color:#c00;font-size:11px;padding:1px 5px;border-radius:3px;margin-right:6px">违规</span>':''}
      ${body}</div>
  </div>`;
}

function pagerHtml(page, totalPages, total, fn){
  if(!totalPages || totalPages <= 1) return `<span class="hint">共 ${total??0} 条</span>`;
  const btn = (p,label,dis)=>`<button ${dis?'disabled':''} onclick="${fn}(${p})">${label}</button>`;
  return `<div class="row">${btn(1,'« 首页',page<=1)}${btn(page-1,'‹ 上一页',page<=1)}
    <span class="hint">第 ${page} / ${totalPages} 页 · 共 ${total??0} 条</span>
    ${btn(page+1,'下一页 ›',page>=totalPages)}${btn(totalPages,'末页 »',page>=totalPages)}</div>`;
}

async function monSearch(page){
  page = page || 1; _mon.page = page;
  const q = new URLSearchParams();
  if($('mGroup').value) q.set('group_id', $('mGroup').value);
  if($('mKeyword').value.trim()) q.set('keyword', $('mKeyword').value.trim());
  if($('mFrom').value) q.set('start_time', $('mFrom').value + ' 00:00:00');
  if($('mTo').value) q.set('end_time', $('mTo').value + ' 23:59:59');
  if($('mViol').checked) q.set('only_violations','1');
  q.set('include_alerts','1'); q.set('page', page); q.set('page_size','50');
  $('monList').innerHTML = '<div class="hint">查询中…</div>';
  try{
    const d = await api('/api/mon/messages?'+q.toString());
    const flagged = new Set((d.alerts||[]).map(a=>String(a.message_id)));
    $('monPagerTop').innerHTML = pagerHtml(d.page, d.total_pages, d.total, 'monSearch');
    $('monPagerBot').innerHTML = pagerHtml(d.page, d.total_pages, d.total, 'monSearch');
    $('monList').innerHTML = (d.messages||[]).map(m=>msgHtml(m, flagged.has(String(m.message_id)))).join('')
      || '<div class="hint">没有匹配的消息。</div>';
  }catch(e){
    $('monList').innerHTML = `<div class="hint">查询失败：${esc(String(e))}</div>`;
    $('monPagerTop').textContent=''; $('monPagerBot').textContent='';
  }
}

function monReset(){
  $('mGroup').value=''; $('mKeyword').value=''; $('mFrom').value=''; $('mTo').value='';
  $('mViol').checked=false; monSearch(1);
}

const SEV = {high:['高','#c00','#ffe1e1'], medium:['中','#c80','#fff3e0'], low:['低','#888','#f0f0f0']};

async function loadAlertUsers(){
  try{
    const list = await api('/api/mon/alerts/users');
    const arr = Array.isArray(list) ? list : [];
    $('alertUsers').innerHTML = arr.length ? arr.slice(0,20).map(u=>`
      <div class="row" style="border-bottom:1px solid #f5f5f5;padding:5px 0">
        <span style="width:180px;font-size:13px"><b>${esc(u.nickname||'(无名)')}</b></span>
        <span style="width:130px;font-size:12px;color:#888">${esc(String(u.user_id||''))}</span>
        <span style="width:110px;font-size:12px;color:#c00">${u.count??0} 次</span>
        <span style="font-size:11px;color:#999">最近 ${esc(String(u.latest_time||'').replace('T',' ').slice(0,19))}</span>
      </div>`).join('') : '<div class="hint">暂无数据。</div>';
  }catch(e){ $('alertUsers').innerHTML = `<div class="hint">读取失败：${esc(String(e))}</div>`; }
}

// 注意：监控的 /api/alerts 不支持分页，只支持 limit(<=1000) + 服务端筛选，
// 所以这里不做页码，而是让用户选条数。
async function loadAlerts(){
  const q = new URLSearchParams();
  if($('aGroup').value) q.set('group_id', $('aGroup').value);
  if($('aSeverity').value) q.set('severity', $('aSeverity').value);
  if($('aSecondary').value) q.set('secondary_status', $('aSecondary').value);
  q.set('limit', $('aLimit').value || '50');
  $('alertList').innerHTML = '<div class="hint">加载中…</div>';
  try{
    const list = await api('/api/mon/alerts?'+q.toString());
    const items = Array.isArray(list) ? list : (list.alerts||[]);
    const byUser = {};
    items.forEach(a=>{ const k=(a.nickname||'(无名)')+'|'+(a.user_id||''); byUser[k]=(byUser[k]||0)+1; });
    const top = Object.entries(byUser).sort((a,b)=>b[1]-a[1]).slice(0,8);
    $('alertSummary').innerHTML = items.length ? `<div class="hint">共 ${items.length} 条；出现最多：
      ${top.map(([k,v])=>{const p=k.split('|');return esc(p[0])+'('+esc(p[1])+')×'+v;}).join('、')}</div>` : '';
    $('alertList').innerHTML = items.map(a=>{
      const s = SEV[a.severity] || ['?','#888','#f0f0f0'];
      const falsePos = (a.secondary_status==='likely_false_positive');
      return `<div style="border-bottom:1px solid #f0f0f0;padding:8px 0">
        <div class="row" style="align-items:flex-start">
          <span style="background:${s[2]};color:${s[1]};font-size:11px;padding:2px 7px;border-radius:3px;flex:none">${s[0]}</span>
          <span style="flex:1;font-size:13px;cursor:pointer" onclick="var d=this.parentElement.nextElementSibling;d.style.display=d.style.display==='block'?'none':'block'">
            <b>${esc(a.category_label||a.violation_type||'违规')}</b>
            <span style="color:#666"> · ${esc(String(a.content_preview||'').slice(0,80))}</span>
            ${falsePos?'<span style="color:#c80;font-size:11px"> · 二次复核可能误报</span>':''}
            ${a.should_notify===false?'<span style="color:#999;font-size:11px"> · 不通知</span>':''}
          </span>
          <span style="width:210px;flex:none;font-size:11px;color:#999;text-align:right">
            ${esc(a.nickname||'')}(${esc(String(a.user_id||''))})<br>${esc(a.datetime||'')} · 群 ${esc(String(a.group_id||''))}</span>
        </div>
        <div style="display:none;font-size:12px;line-height:1.7;color:#555;background:#fafafa;padding:8px;border-radius:6px;margin-top:6px">
          <div><b>匹配词：</b>${esc(a.matched_word||'（无，AI 判定）')}</div>
          <div><b>判定理由：</b>${esc(a.reason||'—')}</div>
          ${a.secondary_status?`<div><b>二次复核：</b>${esc(a.secondary_status_label||'')}<br>${esc(a.secondary_reason||'')}</div>`:''}
          <div style="color:#999">告警ID ${esc(a.alert_id||'')} · 依据 ${esc(a.report_basis_label||a.report_basis||'')} · 复核时间 ${esc(a.review_time||'')}</div>
        </div>
      </div>`;
    }).join('') || '<div class="hint">没有符合条件的告警。</div>';
  }catch(e){
    $('alertList').innerHTML = `<div class="hint">告警读取失败：${esc(String(e))}</div>`;
  }
}

// ---------------- HMML（麦麦官方完整配置面板）----------------
let _hmmlReady=false, _hmmlBusy=false;
async function ensureHmml(force){
  if(_hmmlBusy) return;
  if(_hmmlReady && !force) return;
  _hmmlBusy=true;
  try{
    say('hmmlMsg','正在启动 HMML 配置面板…',true);
    const r = await api('/api/hmml/ensure',{method:'POST'});
    if(!r.success){ say('hmmlMsg', r.message||'启动失败', false); $('hmmlHint').textContent = r.message||''; return; }
    _hmmlReady=true;
    const f=$('hmmlFrame');
    if(force || !f.getAttribute('src')) f.src = r.url;
    $('hmmlHint').textContent='已启动并内嵌。前端 :7998 / 后端 :7999。';
    say('hmmlMsg','HMML 已就绪',true);
  }catch(e){ say('hmmlMsg','启动失败：'+e, false); }
  finally{ _hmmlBusy=false; }
}
function openHmml(){ window.open('http://127.0.0.1:7998'); }

// ---------------- API 管理 ----------------
let _api = null;
async function loadApi(force){
  const d = await api('/api/model/config');
  if(!d.success){ say('pvMsg', d.message||'读取失败', false); return; }
  _api = d;
  $('apiPath').textContent = d.path;
  $('mdNames').innerHTML = (d.model_names||[]).map(n=>`<option value="${esc(n)}">`).join('');
  renderApiWarn(d.warnings||[]);
  renderPv(d.providers); renderMd(d.models); renderTk(d.tasks, d.model_names||[]);
}
// 配置体检：这些都是「能启动但结果不对」的问题，不主动提示根本查不到
function renderApiWarn(list){
  const box = $('apiWarn');
  if(!list.length){
    box.innerHTML = '<div class="hint" style="color:#137333">✓ 没发现明显问题：'
      + '提供商地址不重复、被引用的都有 key、角色引用的模型都存在。</div>';
    return;
  }
  const color = {error:'#c5221f', warn:'#b06000', info:'#5f6368'};
  const icon = {error:'✕', warn:'!', info:'i'};
  box.innerHTML = list.map(w=>{
    const c = color[w.level]||'#5f6368';
    return `<div style="color:${c};margin:4px 0;line-height:1.6">`
      + `<b>${icon[w.level]||'·'}</b> ${esc(w.text)}</div>`;
  }).join('');
}
function renderPv(list){
  $('pvList').innerHTML = list.map((p,i)=>`
    <div class="card" style="background:#fafafa;margin:8px 0;padding:10px">
      <div class="row">
        <label class="f" style="width:190px"><span class="k">名称</span><input id="pv_n_${i}" value="${esc(p.name)}"></label>
        <label class="f" style="flex:1;min-width:260px"><span class="k">Base URL</span><input id="pv_u_${i}" value="${esc(p.base_url)}"></label>
        <label class="f" style="width:150px"><span class="k">请求客户端</span>
          <select id="pv_c_${i}">
            <option value="openai"${p.client_type==='openai'?' selected':''}>openai</option>
            <option value="gemini"${p.client_type==='gemini'?' selected':''}>gemini</option>
          </select></label>
      </div>
      <label class="f"><span class="k">API Key</span><input id="pv_k_${i}" value="${esc(p.api_key)}"></label>
      <div class="row">
        <label class="f" style="width:120px"><span class="k">重试次数</span><input type="number" id="pv_r_${i}" value="${esc(p.max_retry)}"></label>
        <label class="f" style="width:120px"><span class="k">超时(秒)</span><input type="number" id="pv_t_${i}" value="${esc(p.timeout)}"></label>
        <label class="f" style="width:140px"><span class="k">重试间隔(秒)</span><input type="number" id="pv_i_${i}" value="${esc(p.retry_interval)}"></label>
        <button class="p" onclick="pvSave(${i})">保存</button>
        <button class="d" onclick="pvDel(${i})">删除</button>
      </div>
    </div>`).join('') || '<div class="hint">还没有提供商，点下面新增。</div>';
}
function pvNew(){
  $('pvList').insertAdjacentHTML('afterbegin',`
    <div class="card" style="background:#f0f7ff;margin:8px 0;padding:10px" id="pvNewRow">
      <div class="row">
        <label class="f" style="width:190px"><span class="k">名称</span><input id="pvn_n" placeholder="例如 SiliconFlow"></label>
        <label class="f" style="flex:1;min-width:260px"><span class="k">Base URL</span><input id="pvn_u" placeholder="https://api.siliconflow.cn/v1"></label>
        <label class="f" style="width:150px"><span class="k">请求客户端</span>
          <select id="pvn_c"><option value="openai">openai</option><option value="gemini">gemini</option></select></label>
      </div>
      <label class="f"><span class="k">API Key</span><input id="pvn_k"></label>
      <div class="row">
        <label class="f" style="width:120px"><span class="k">重试次数</span><input type="number" id="pvn_r" value="2"></label>
        <label class="f" style="width:120px"><span class="k">超时(秒)</span><input type="number" id="pvn_t" value="30"></label>
        <label class="f" style="width:140px"><span class="k">重试间隔(秒)</span><input type="number" id="pvn_i" value="10"></label>
        <button class="p" onclick="pvSaveNew()">新增</button>
        <button onclick="document.getElementById('pvNewRow').remove()">取消</button>
      </div>
    </div>`);
}
async function pvSaveNew(){
  const body={name:$('pvn_n').value.trim(), base_url:$('pvn_u').value.trim(),
    api_key:$('pvn_k').value, client_type:$('pvn_c').value,
    max_retry:$('pvn_r').value, timeout:$('pvn_t').value, retry_interval:$('pvn_i').value};
  const r = await api('/api/model/provider',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('pvMsg', r.message, r.success); if(r.success) loadApi(true);
}
async function pvSave(i){
  const oldName = _api.providers[i].name;
  const body={old_name:oldName, name:$(`pv_n_${i}`).value.trim(), base_url:$(`pv_u_${i}`).value.trim(),
    api_key:$(`pv_k_${i}`).value, client_type:$(`pv_c_${i}`).value,
    max_retry:$(`pv_r_${i}`).value, timeout:$(`pv_t_${i}`).value, retry_interval:$(`pv_i_${i}`).value};
  const r = await api('/api/model/provider',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('pvMsg', r.message, r.success); if(r.success) loadApi(true);
}
async function pvDel(i){
  const name = _api.providers[i].name;
  if(!confirm(`确定删除提供商「${name}」？`)) return;
  const r = await api('/api/model/provider/'+encodeURIComponent(name),{method:'DELETE'});
  say('pvMsg', r.message, r.success); if(r.success) loadApi(true);
}
function renderMd(list){
  $('mdList').innerHTML = list.map((m,i)=>`
    <div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0">
      <label class="f" style="flex:1;min-width:220px"><span class="k">模型标识符</span><input id="md_i_${i}" value="${esc(m.model_identifier)}"></label>
      <label class="f" style="flex:1;min-width:200px"><span class="k">模型名称</span><input id="md_n_${i}" value="${esc(m.name)}"></label>
      <label class="f" style="width:170px"><span class="k">提供商</span><input id="md_p_${i}" value="${esc(m.api_provider)}" list="pvNames"></label>
      <label class="f" style="width:170px"><span class="k">输入价（元/百万token）</span><input type="number" step="0.01" id="md_pi_${i}" value="${esc(m.price_in)}"></label>
      <label class="f" style="width:170px"><span class="k">输出价（元/百万token）</span><input type="number" step="0.01" id="md_po_${i}" value="${esc(m.price_out)}"></label>
      <button class="p" onclick="mdSave(${i})">保存</button>
      <button class="d" onclick="mdDel(${i})">删除</button>
    </div>`).join('') || '<div class="hint">还没有模型。</div>';
  const names = (_api? _api.providers : []).map(p=>`<option value="${esc(p.name)}">`).join('');
  let dl = document.getElementById('pvNames');
  if(!dl){ document.body.insertAdjacentHTML('beforeend','<datalist id="pvNames"></datalist>'); dl=document.getElementById('pvNames'); }
  dl.innerHTML = names;
}
function mdNew(){
  $('mdList').insertAdjacentHTML('afterbegin',`
    <div class="row" style="background:#f0f7ff;padding:6px 0" id="mdNewRow">
      <label class="f" style="flex:1;min-width:220px"><span class="k">模型标识符</span><input id="mdn_i" placeholder="org/model-name"></label>
      <label class="f" style="flex:1;min-width:200px"><span class="k">模型名称</span><input id="mdn_n"></label>
      <label class="f" style="width:170px"><span class="k">提供商</span><input id="mdn_p" list="pvNames"></label>
      <label class="f" style="width:170px"><span class="k">输入价（元/百万token）</span><input type="number" step="0.01" id="mdn_pi" value="0"></label>
      <label class="f" style="width:170px"><span class="k">输出价（元/百万token）</span><input type="number" step="0.01" id="mdn_po" value="0"></label>
      <button class="p" onclick="mdSaveNew()">新增</button>
      <button onclick="document.getElementById('mdNewRow').remove()">取消</button>
    </div>`);
}
async function mdSaveNew(){
  const body={model_identifier:$('mdn_i').value.trim(), name:$('mdn_n').value.trim()||$('mdn_i').value.trim(),
    api_provider:$('mdn_p').value.trim(), price_in:$('mdn_pi').value, price_out:$('mdn_po').value};
  const r = await api('/api/model/model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('mdMsg', r.message, r.success); if(r.success) loadApi(true);
}
async function mdSave(i){
  const oldName = _api.models[i].name;
  const body={old_name:oldName, model_identifier:$(`md_i_${i}`).value.trim(), name:$(`md_n_${i}`).value.trim(),
    api_provider:$(`md_p_${i}`).value.trim(), price_in:$(`md_pi_${i}`).value, price_out:$(`md_po_${i}`).value};
  const r = await api('/api/model/model',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('mdMsg', r.message, r.success); if(r.success) loadApi(true);
}
async function mdDel(i){
  const name = _api.models[i].name;
  if(!confirm(`确定删除模型「${name}」？`)) return;
  const r = await api('/api/model/model/'+encodeURIComponent(name),{method:'DELETE'});
  say('mdMsg', r.message, r.success); if(r.success) loadApi(true);
}
function renderTk(list, names){
  $('tkList').innerHTML = list.map((t,i)=>`
    <div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0">
      <span style="width:250px;font-size:13px" title="${esc(t.name)}">${esc(t.label)}</span>
      <label class="f" style="flex:1;min-width:240px"><span class="k">使用的模型（逗号分隔）</span>
        <input id="tk_m_${i}" list="mdNames" value="${esc(t.model_list.join(', '))}"></label>
      <label class="f" style="width:100px"><span class="k">温度</span>
        <input type="number" step="0.1" id="tk_t_${i}" value="${t.temperature===null?'':esc(t.temperature)}" placeholder="不改"></label>
      <label class="f" style="width:120px"><span class="k">最大 token</span>
        <input type="number" id="tk_x_${i}" value="${t.max_tokens===null?'':esc(t.max_tokens)}" placeholder="不改"></label>
      <button class="p" onclick="tkSave(${i})">保存</button>
    </div>`).join('') || '<div class="hint">配置里没有角色定义。</div>';
}
async function tkSave(i){
  const name = _api.tasks[i].name;
  const list = $(`tk_m_${i}`).value.split(/[,，]/).map(s=>s.trim()).filter(Boolean);
  const body={name, model_list:list, temperature:$(`tk_t_${i}`).value, max_tokens:$(`tk_x_${i}`).value};
  const r = await api('/api/model/task',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('tkMsg', r.message, r.success); if(r.success) loadApi(true);
}
async function api(u,o){ const r=await fetch(u,o); return r.json(); }
function say(el,txt,ok=true){ const e=$(el); e.className='msg '+(ok?'ok':'err'); e.textContent=txt; setTimeout(()=>e.className='msg',6000); }

function svcHtml(s){
  const on = s.running;
  return `<div class="svc ${on?'on':''}">
    <span class="dot ${on?'on':''}"></span>
    <div class="info"><div class="name">${s.label}
      <span class="badge ${on?'ok':'off'}">${on?'运行中':'已停止'}</span></div>
    <div class="sub">端口 ${s.port||'-'} ${s.pid?'· PID '+s.pid:''} · ${s.desc||''}</div></div>
    <button class="p" onclick="act('${s.key}','start')" ${on?'disabled':''}>启动</button>
    <button class="d" onclick="act('${s.key}','stop')" ${on?'':'disabled'}>停止</button>
    <button onclick="act('${s.key}','restart')">重启</button>
    ${s.webui?`<button onclick="window.open('${s.webui}')">${s.webui_label||'打开面板'}</button>`:''}
  </div>`;
}
async function refresh(){
  const d = await api('/api/status');
  $('clock').textContent = d.time + (d.napcat_logged_in ? '  ·  QQ 已登录' : '');
  $('homeSvc').innerHTML = d.services.map(svcHtml).join('');
  $('svcList').innerHTML = d.services.map(svcHtml).join('');
  // SnowLuma（QQ 接入）卡片
  const sn = d.snowluma || {on:false, qq_on:false, webui:'http://127.0.0.1:5099/processes'};
  $('snowSvc').innerHTML = `<div class="svc ${sn.on?'on':''}">
    <span class="dot ${sn.on?'on':''}"></span>
    <div class="info"><div class="name">SnowLuma
      <span class="badge ${sn.on?'ok':'off'}">${sn.on?'运行中':'已停止'}</span>
      ${sn.qq_on?'<span class="badge ok">QQ 已登录</span>':'<span class="badge off">QQ 未登录</span>'}</div>
    <div class="sub">WebUI :5099 · 正向 WS :3001${sn.qq_on?' · 钩子已注入':''}</div></div>
    <button class="p" onclick="snowAct('start')" ${sn.on?'disabled':''}>启动</button>
    <button class="d" onclick="snowAct('stop')" ${sn.on?'':'disabled'}>停止</button>
    <button onclick="window.open('${sn.webui}')">打开 WebUI</button>
  </div>`;
  if(d.tip){ $('tipCard').style.display='block'; $('tipText').textContent=d.tip; }
  else { $('tipCard').style.display='none'; }
  const st = d.monitor_stats;
  // 「最后一条消息」多新，是判断"监控还在正常收消息吗"的最直接指标
  // （2026-09-18：WS 半死时它一直停在同一时刻，而导出也跟着停）
  let lastTxt = '—';
  if(st && st.last_message_time){
    const t = new Date(String(st.last_message_time).replace(/-/g,'/'));
    if(!isNaN(t)){ const m = Math.floor((Date.now()-t.getTime())/60000);
      lastTxt = m < 1 ? '刚刚' : (m < 60 ? m+' 分钟前' : Math.floor(m/60)+' 小时前'); }
  }
  $('homeStats').innerHTML = st ? `<div class="stat">
      <div class="i"><div class="v">${st.total_messages??'-'}</div><div class="l">已存消息</div></div>
      <div class="i"><div class="v" style="color:${st.ws_connected?'#1a7f37':'#b42318'}">${st.ws_connected?'已连接':'未连接'}</div><div class="l">QQ 连接</div></div>
      <div class="i"><div class="v">${lastTxt}</div><div class="l">最后一条消息</div></div>
      <div class="i"><div class="v">${st.total_alerts??'-'}</div><div class="l">违规告警</div></div>
      <div class="i"><div class="v">${st.storage_used_mb == null ? '计算中' : Number(st.storage_used_mb).toFixed(0)}</div><div class="l">占用 MB</div></div>
      <div class="i"><div class="v">${st.total_groups??'-'}</div><div class="l">监控群数</div></div>
    </div>` : '<span class="hint">监控服务未运行，启动后这里显示统计</span>';
  loadFav();
  loadHomeKpi(d);        // 一眼看板（内部自己限频，不会每 5 秒打接口）
}

// ==================== 一眼看板（图形化首页）====================
// ⚠️ refresh() 是每 5 秒跑一次的，所以这里：轻量的部分用已经拿到的 /api/status，
// 重的（怪话库统计 / 规则数 / 冷场）最多 60 秒拉一次 —— 别把接口打爆。
let _kpiExtra = null, _kpiAt = 0;
async function loadHomeKpi(d){
  if(!$('homeKpi')) return;
  const svc = d.services || [];
  const on = svc.filter(s=>s.running).length;
  const st = d.monitor_stats || {};
  if(Date.now() - _kpiAt > 60000){
    _kpiAt = Date.now();
    const [q, k, a] = await Promise.all([
      api('/api/quirky/stats').catch(()=>null),
      api('/api/keyword_reply').catch(()=>null),
      api('/api/quirky/auto').catch(()=>null)]);
    _kpiExtra = {q, k, a};
    // 顺带把模型花费也带上（同一档 60 秒限频，不会额外打接口）
    api('/api/model/usage?period=24').then(u => { if(u && u.success) _kpiExtra.u = u; }).catch(()=>{});
  }
  const ex = _kpiExtra || {};
  const q = (ex.q && ex.q.success) ? ex.q : null;
  const rules = ((ex.k && ex.k.data && ex.k.data.rules) || []).filter(r=>r.enabled!==false).length;
  const auto = ex.a || {};
  const groups = auto.groups || [];
  const thr = auto.threshold_min || 120;
  const cold = groups.filter(g=>(g.idle_min||0) >= thr && !g.dead).length;
  const dead = groups.filter(g=>g.dead).length;
  const kpi = [
    {ico:'🟢', lab:'服务在线', val:`${on}/${svc.length||0}`,
     sub: on===(svc.length||0) ? '全部在跑' : '有服务没起来', cls: on===(svc.length||0)?'ok':'bad'},
    {ico:'🔗', lab:'QQ 连接', val: st.ws_connected ? '正常' : '断开',
     sub: d.napcat_logged_in ? 'QQ 已登录' : 'QQ 未登录', cls: st.ws_connected?'ok':'bad'},
    {ico:'📨', lab:'已存消息', val: String(st.total_messages ?? '-'),
     sub: `${st.total_groups ?? '-'} 个群在审查`},
    {ico:'📚', lab:'怪话可发', val: q ? String(q.usable ?? '-') : '—',
     sub: q ? `库里共 ${q.total} 条 · ${q.too_long||0} 条太长不发` : '拿不到统计'},
    {ico:'🎭', lab:'怪话用过', val: q ? String(q.used ?? 0) : '—', sub:'条至少被发过一次'},
    {ico:'🗣', lab:'关键词规则', val: String(rules), sub:'条已启用',
     cls: rules ? '' : 'bad'},
    {ico:'❄️', lab:'冷场中', val: String(cold), sub:`${dead} 个死群（不暖场）`,
     cls: cold ? 'warn' : ''},
    {ico:'💰', lab:'24h 花费', val: ex.u ? ('¥' + (ex.u.total_cost || 0).toFixed(3)) : '—',
     sub: ex.u ? (ex.u.summary && ex.u.summary.requests ? `${ex.u.summary.requests} 次调用` : '')
               + ((ex.u.price_missing || []).length ? ` · ${ex.u.price_missing.length} 个模型没单价` : '')
               : '拿不到统计',
     cls: (ex.u && (ex.u.price_missing || []).length) ? 'warn' : ''},
  ];
  $('homeKpi').innerHTML = kpi.map(k=>`<div class="kpi ${k.cls||''}">
      <div class="k-top"><span class="k-ico">${k.ico}</span>${esc(k.lab)}</div>
      <div class="k-val">${esc(String(k.val))}</div>
      <div class="k-sub">${esc(k.sub)}</div>
    </div>`).join('');
  renderQuirkyDonut(q);
  renderColdBars(groups, auto);
}

// 怪话库构成：一个环形图（可发 / 太长 / 已停用）
function renderQuirkyDonut(q){
  if(!$('qLegend')) return;
  if(!q){ $('qLegend').innerHTML = '<span class="hint">怪话库统计拿不到</span>'; return; }
  const usable = q.usable || 0, long_ = q.too_long || 0, off = q.disabled || 0;
  const tot = Math.max(1, usable + long_ + off);
  const p = Math.round(usable * 100 / tot);
  const arc = $('qArc');
  if(arc){ arc.setAttribute('stroke-dasharray', `${p} ${100-p}`); }
  $('qLegend').innerHTML = `
    <div class="li"><span class="sw" style="background:linear-gradient(120deg,#4f5bd5,#8a5cf0)"></span>
      可发（≤200 字）<span class="lv">${usable}</span></div>
    <div class="li"><span class="sw" style="background:#f0a020"></span>
      太长 · 不会发<span class="lv">${long_}</span></div>
    <div class="li"><span class="sw" style="background:#c9ced9"></span>
      已停用<span class="lv">${off}</span></div>
    <div class="li" style="color:var(--t3)"><span class="sw" style="background:transparent"></span>
      共 ${q.total} 条 · 用过 ${q.used||0} 条</div>`;
}

// 各群冷场条形：越长说明越久没人说话（到阈值就会发怪话，死群不碰）
function renderColdBars(groups, auto){
  const box = $('coldBars');
  if(!box) return;
  if(!groups.length){ box.innerHTML = '<span class="hint">没有群数据</span>'; return; }
  const thr = (auto && auto.threshold_min) || 120;
  const cap = Math.max(thr * 2, ...groups.map(g=>Math.min(Math.max(g.idle_min||0,0), 100000)));
  box.innerHTML = groups.map(g=>{
    const idle = (g.idle_min === undefined || g.idle_min === null) ? -1 : g.idle_min;
    const w = idle < 0 ? 2 : Math.max(2, Math.min(100, Math.round(idle*100/Math.max(1,cap))));
    const cls = g.dead ? 'dead' : (idle >= thr ? 'warm' : '');
    const tag = g.dead ? '死群' : (idle >= thr ? '已冷场 → 会发' : '活跃');
    return `<div class="bar-row">
      <span class="lbl" title="${esc(String(g.group_id))}">群 ${esc(String(g.group_id))}</span>
      <span class="track"><span class="fill ${cls}" style="width:${w}%"></span></span>
      <span class="num">${idle < 0 ? '读不到' : idle + ' 分'} · ${tag}</span>
    </div>`;
  }).join('');
}

// ==================== 模型用量（图形化）====================
let _mu = null, _muPeriod = '24';
function fmtTok(n){
  n = Number(n) || 0;
  if(n >= 1e8) return (n / 1e8).toFixed(2) + ' 亿';
  if(n >= 1e4) return (n / 1e4).toFixed(1) + ' 万';
  return String(Math.round(n));
}
async function loadModelUsage(period){
  if(period) _muPeriod = String(period);
  if(!$('muKpi')) return;
  let d;
  try { d = await api('/api/model/usage?period=' + encodeURIComponent(_muPeriod)); }
  catch(e){ say('muWarn', '读取失败：' + e, false); return; }
  if(!d.success){ say('muWarn', d.message || '读取失败', false); return; }
  _mu = d;
  const PNAME = {'24': '最近 24 小时', '168': '最近 7 天', '720': '最近 30 天'};
  $('muPeriods').innerHTML = (d.periods || []).map(p =>
    `<button class="${String(p) === _muPeriod ? 'p' : ''}" onclick="loadModelUsage('${p}')">${
      esc(PNAME[p] || (p + ' 小时'))}</button>`).join(' ');
  const s = d.summary || {};
  const gen = d.generated_at
    ? new Date(d.generated_at * 1000).toLocaleString('zh-CN', {hour12: false}) : '—';
  $('muStat').textContent = `数据生成于 ${gen}`;
  const missing = d.price_missing || [];
  const hitPct = s.input_tokens ? (s.cache_hit_tokens * 100 / s.input_tokens) : 0;
  const kpi = [
    {ico: '💰', lab: '花费（按已填单价）', val: '¥' + (d.total_cost || 0).toFixed(3),
     sub: missing.length ? `${missing.length} 个模型没单价，没算进来` : '所有模型都有单价',
     cls: missing.length ? 'warn' : 'ok'},
    {ico: '📨', lab: '请求次数', val: String(s.requests || 0), sub: '次模型调用'},
    {ico: '🔤', lab: '总 token', val: fmtTok(s.tokens),
     sub: `输入 ${fmtTok(s.input_tokens)} / 输出 ${fmtTok(s.output_tokens)}`},
    {ico: '⚡', lab: '缓存命中', val: fmtTok(s.cache_hit_tokens),
     sub: s.input_tokens ? `占输入 ${hitPct.toFixed(1)}%` : '—',
     cls: hitPct > 30 ? 'ok' : ''},
  ];
  $('muKpi').innerHTML = kpi.map(k=>`<div class="kpi ${k.cls||''}">
      <div class="k-top"><span class="k-ico">${k.ico}</span>${esc(k.lab)}</div>
      <div class="k-val">${esc(String(k.val))}</div>
      <div class="k-sub">${esc(k.sub)}</div>
    </div>`).join('');
  const models = d.models || [];
  const maxTok = Math.max(1, ...models.map(m=>m.total_tokens));
  $('muBars').innerHTML = models.length ? models.map(m=>{
    const w = Math.max(2, Math.round(m.total_tokens * 100 / maxTok));
    const costTxt = m.cost > 0 ? ('¥' + m.cost.toFixed(3)) : '未配单价';
    return `<div class="bar-row">
      <span class="lbl" title="${esc(m.name)}">${esc(m.name)}</span>
      <span class="track"><span class="fill" style="width:${w}%"></span></span>
      <span class="num">${fmtTok(m.total_tokens)} · ${esc(costTxt)}</span>
    </div>`;
  }).join('') : '<span class="hint">这段时间没有调用记录</span>';
  say('muWarn', missing.length
      ? ('这些模型没填单价，花费算不出来：' + missing.join('、') + '　→ 去「🔌 API 管理」补上')
      : '', true);
  $('muTable').innerHTML = models.length
    ? ('<div class="hint" style="margin-bottom:6px">按模型明细</div>' + models.map(m=>`
      <div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0;font-size:12.5px">
        <span style="flex:1;min-width:140px">${esc(m.name)}</span>
        <span class="hint" style="width:74px;text-align:right">${m.requests} 次</span>
        <span class="hint" style="width:104px;text-align:right">入 ${fmtTok(m.input_tokens)}</span>
        <span class="hint" style="width:104px;text-align:right">出 ${fmtTok(m.output_tokens)}</span>
        <span class="hint" style="width:118px;text-align:right">缓存 ${fmtTok(m.cache_hit_tokens)}</span>
        <span class="hint" style="width:96px;text-align:right">${m.avg_response_time ? m.avg_response_time.toFixed(1) + 's' : '—'}</span>
        <span style="width:92px;text-align:right;font-weight:600;color:${m.cost>0?'#1a7f37':'#9aa0ae'}">${
          m.cost > 0 ? ('¥' + m.cost.toFixed(3)) : '—'}</span>
      </div>`).join(''))
    : '';
}

// 消息趋势：后端聚合 /api/trend（60 秒缓存），画 SVG 柱状图 + 群排行。
// 只在首次加载 / 点「刷新」时查，避免每 5 秒打 17 次 qq-monitor。
let _trendLoaded = false;
async function loadTrend(force){
  const box = $('homeTrend');
  if(!box) return;
  if(_trendLoaded && !force) return;
  let d;
  try { d = await api('/api/trend'); }
  catch(e){ box.innerHTML = '<span class="hint">读不到（监控没在跑？）</span>'; return; }
  if(!d.success){ box.innerHTML = '<span class="hint">' + esc(d.message || '读取失败') + '</span>'; return; }
  _trendLoaded = true;
  const days = d.days || [];
  const groups = (d.groups || []).slice(0, 5);
  if(!days.length){
    box.innerHTML = '<span class="hint">暂无数据（监控在跑但还没有聊天记录入库）</span>';
    return;
  }
  const max = Math.max(...days.map(x=>x.total), 1);
  const W = 680, H = 150, pad = 24;
  const bw = (W - pad*2) / days.length;
  let svg = `<svg width="100%" height="${H}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">`;
  days.forEach((x,i)=>{
    const h = Math.max(2, x.total/max*(H-pad*2));
    const px = pad + i*bw, py = H - pad - h;
    svg += `<rect x="${px+2}" y="${py}" width="${Math.max(bw-4,2)}" height="${h}" rx="2" fill="var(--brand)" opacity="${0.5 + (x.total/max)*0.5}"><title>${esc(x.date)} · ${x.total} 条</title></rect>`;
    if(i % 2 === 0) svg += `<text x="${px+bw/2}" y="${H-7}" font-size="9" fill="var(--t3)" text-anchor="middle">${x.date.slice(5)}</text>`;
  });
  svg += `</svg>`;
  let html = svg;
  if(groups.length){
    html += `<div style="margin-top:10px;font-size:13px">`;
    groups.forEach((g,i)=>{
      html += `<div class="row" style="border-bottom:1px solid var(--line2);padding:4px 0">
        <span style="flex:none;width:22px;color:var(--t3)">${i+1}</span>
        <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(g.group_name || g.group_id)}</span>
        <span class="badge off">${g.total} 条</span></div>`;
    });
    html += `</div>`;
  }
  box.innerHTML = html;
}

// 服务稳定性：24h 每 60 秒采样 → 24 个「小时桶」色块（绿=在线>50%、红=离线、灰=无数据）
let _healthLoaded = false;
async function loadHealth(force){
  const box = $('homeHealth');
  if(!box) return;
  if(_healthLoaded && !force) return;
  let d;
  try { d = await api('/api/health'); }
  catch(e){ box.innerHTML = '<span class="hint">读不到</span>'; return; }
  if(!d.success){ box.innerHTML = '<span class="hint">' + esc(d.message || '读取失败') + '</span>'; return; }
  _healthLoaded = true;
  const samples = d.samples || [];
  const now = d.now || Date.now()/1000;
  const svcs = d.services || [];
  if(!samples.length){
    box.innerHTML = '<span class="hint">面板刚启动，还没有采样数据（每 60 秒记一次，稍等片刻再刷新）</span>';
    return;
  }
  const H = 24;
  const buckets = [];
  for(let i=0;i<H;i++) buckets.push({cnt:0, on:0});
  for(const sm of samples){
    const ageH = Math.floor((now - sm.t)/3600);
    if(ageH < 0 || ageH >= H) continue;
    const b = buckets[H-1-ageH];
    b.cnt++;
    for(const k in sm.s){ if(sm.s[k]) b.on++; }
  }
  let html = '';
  for(const s of svcs){
    html += `<div class="row" style="gap:8px;align-items:center;padding:3px 0">
      <span style="flex:none;width:112px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12.5px">${esc(s.label)}</span>
      <div style="display:flex;gap:2px;flex:1">`;
    buckets.forEach((b,i)=>{
      const ratio = b.cnt ? b.on/b.cnt : -1;
      const cls = b.cnt===0 ? 'gray' : (ratio >= 0.5 ? 'ok' : 'bad');
      html += `<span class="hb hb-${cls}" title="${healthHour(i)}${b.cnt ? ' · ' + b.on + '/' + b.cnt + ' 在线' : ' · 无数据'}"></span>`;
    });
    html += `</div></div>`;
  }
  html += `<div class="hint" style="margin-top:6px">绿=该小时大部分时间在线 · 红=离线 · 灰=无数据（面板启动前）</div>`;
  box.innerHTML = html;
}
function healthHour(i){
  const t = new Date((Date.now()/1000 - (23-i)*3600) * 1000);
  return (t.getMonth()+1)+'/'+t.getDate()+' '+String(t.getHours()).padStart(2,'0')+':00';
}

// ==================== 冷场怪话（自动暖场） ====================
let _quirkyLoaded = false;
async function loadQuirkyAuto(force){
  const box = $('homeQuirky');
  if(!box) return;
  if(_quirkyLoaded && !force) return;
  let d;
  try { d = await api('/api/quirky/auto'); }
  catch(e){ box.innerHTML = '<span class="hint">读不到</span>'; return; }
  if(!d.success){ box.innerHTML = '<span class="hint">' + esc(d.message || '') + '</span>'; return; }
  _quirkyLoaded = true;
  const q = (v,dv) => (v===undefined||v===null)?dv:v;
  const on = d.enabled;
  const thr = q(d.threshold_min,30), cd = q(d.cooldown_min,120), maxIdle = q(d.max_idle_min,1440);
  const tp = q(d.topic_enabled,true), tprob = Math.round(q(d.topic_prob,0.8)*100), tcd = q(d.topic_cooldown_min,180);
  const sq = q(d.sched_quirky,true), gmin = q(d.gap_min,120), gmax = q(d.gap_max,240);
  const qs = q(d.quiet_start,1), qe = q(d.quiet_end,8);
  const fe = q(d.follow_enabled,true), fdelay = q(d.follow_delay_sec,25);
  const fwatch = q(d.follow_watch_min,20), fmax = q(d.follow_max,2);
  const quietTag = d.quiet_now ? '<span class="badge off" style="flex:none">凌晨静默中</span>' : '';
  let html = `<div class="row" style="gap:10px;align-items:center;margin-bottom:6px">
    <span class="badge ${on?'ok':'off'}">${on?'已开启':'已停用'}</span>
    ${quietTag}
    <button class="${on?'d':'p'}" onclick="quirkyToggle(${on?0:1})">${on?'全部停用':'全部启用'}</button>
    <span class="hint">冷场</span>
    <input id="qkThr" type="number" min="5" max="480" value="${thr}" style="width:70px" title="多久没人说话算冷场（分钟）">
    <span class="hint">冷却</span>
    <input id="qkCd" type="number" min="30" max="1440" value="${cd}" style="width:70px" title="发完至少隔多久再发（分钟）">
    <span class="hint">死群</span>
    <input id="qkMaxIdle" type="number" min="0" max="10080" value="${maxIdle}" style="width:80px" title="超过这么多分钟没人说话就不再主动发言；0 = 不限">
    <button onclick="quirkySetBase()">保存基础</button>
    <span class="hint" style="flex:1;text-align:right">${esc(d.message || '')}</span>
  </div>`;
  html += `<div class="row" style="gap:10px;align-items:center;margin-bottom:6px">
    <span class="badge ${tp?'ok':'off'}" style="flex:none">联网找话题</span>
    <button class="${tp?'d':'p'}" onclick="quirkySet({topic_enabled:${tp?'false':'true'}})">${tp?'关掉':'打开'}</button>
    <span class="hint">冷场时上网起话题的概率</span>
    <input id="qkProb" type="number" min="0" max="100" value="${tprob}" style="width:60px" title="剩下的是念怪话">%
    <span class="hint">话题自身冷却</span>
    <input id="qkTcd" type="number" min="10" max="1440" value="${tcd}" style="width:70px" title="两条联网话题之间至少隔多久（分钟）">
    <button onclick="quirkySetTopicCfg()">保存话题</button>
    <span class="hint" style="flex:1;text-align:right" title="写开场白用哪个模型">模型：${esc(d.llm || '')}</span>
  </div>`;
  html += `<div class="row" style="gap:10px;align-items:center;margin-bottom:6px">
    <span class="badge ${sq?'ok':'off'}" style="flex:none">白天定时怪话</span>
    <button class="${sq?'d':'p'}" onclick="quirkySet({sched_quirky:${sq?'false':'true'}})" title="不看有没有冷场，到点就发一条怪话">${sq?'关掉':'打开'}</button>
    <span class="hint">间隔</span>
    <input id="qkGmin" type="number" min="30" max="1440" value="${gmin}" style="width:70px" title="最短间隔（分钟）">
    <span class="hint">~</span>
    <input id="qkGmax" type="number" min="30" max="1440" value="${gmax}" style="width:70px" title="最长间隔（分钟）">
    <span class="hint">分钟</span>
    <span class="hint" style="margin-left:8px">凌晨静默</span>
    <input id="qkQs" type="number" min="0" max="23" value="${qs}" style="width:60px" title="从几点开始不发">
    <span class="hint">点 ~</span>
    <input id="qkQe" type="number" min="0" max="23" value="${qe}" style="width:60px" title="到几点恢复（起点大于终点表示跨零点）">
    <span class="hint">点</span>
    <button onclick="quirkySetSched()">保存定时</button>
  </div>`;
  html += `<div class="row" style="gap:10px;align-items:center;margin-bottom:8px">
    <span class="badge ${fe?'ok':'off'}" style="flex:none">接话跟进</span>
    <button class="${fe?'d':'p'}" onclick="quirkySet({follow_enabled:${fe?'false':'true'}})" title="它起了话头后有人接话，隔一会儿给一句实在的回应">${fe?'关掉':'打开'}</button>
    <span class="hint">等</span>
    <input id="qkFdelay" type="number" min="5" max="600" value="${fdelay}" style="width:60px" title="有人接话后先等几秒，让麦麦先接；麦麦接了我们就不抢">
    <span class="hint">秒后回</span>
    <span class="hint" style="margin-left:8px">观察</span>
    <input id="qkFwatch" type="number" min="3" max="180" value="${fwatch}" style="width:60px" title="一条话头盯多久（分钟）">
    <span class="hint">分钟，最多回</span>
    <input id="qkFmax" type="number" min="1" max="6" value="${fmax}" style="width:50px" title="同一条话头最多跟进几次">
    <span class="hint">次</span>
    <button onclick="quirkySetFollow()">保存接话</button>
  </div>`;
  if(d.groups && d.groups.length){
    html += `<div style="display:flex;flex-direction:column;gap:4px">`;
    for(const g of d.groups){
      const idle = g.idle_min;
      const idleTxt = idle < 0 ? '无数据' : (idle + ' 分钟前');
      const hot = idle >= 0 && idle < thr;
      const dead = g.dead === true;
      const nextTxt = (g.next_sched_min === undefined || g.next_sched_min < 0)
        ? '未排期' : ('定时怪话还有 ' + g.next_sched_min + ' 分钟');
      const tags = [];
      if(g.awaiting) tags.push('等接话');
      if(g.topic_ready === false) tags.push('话题冷却中');
      const sentTxt = dead ? '死群，不会主动发' : (g.last_sent_min < 0 ? '未发过' : ('上次发出：' + g.last_sent_min + ' 分钟前'));
      const gon = g.on !== false;
      html += `<div class="row" style="gap:8px;align-items:center;font-size:12.5px;${gon?'':'opacity:.5'}">
        <span style="flex:none;width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t2)">群 ${g.group_id}</span>
        <span class="hint" style="flex:none">最后发言：${idleTxt}</span>
        <span class="badge ${dead?'off':(hot?'':'off')}" style="flex:none">${dead?'死群':(hot?'活跃':'冷场中')}</span>
        <span class="hint" style="flex:1">${sentTxt} · ${nextTxt}${tags.length?(' · '+tags.join(' · ')):''}</span>
        <button class="p" onclick="quirkyTopicNow(${g.group_id},true)">预览话题</button>
        <button class="p" onclick="quirkyTopicNow(${g.group_id},false)">发话题</button>
        <button class="${gon?'d':'p'}" onclick="quirkyGroupToggle(${g.group_id},${gon?'false':'true'})">${gon?'本群开':'本群关'}</button>
        <button class="p" onclick="quirkySendGroup(${g.group_id})">发怪话</button>
      </div>`;
    }
    html += `</div>`;
  }
  box.innerHTML = html;
}
// 所有开关统一走这一个：POST 一小段 patch，回显结果并刷新卡片
async function quirkySet(obj){
  const r = await api('/api/quirky/auto',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(obj)});
  say('qkHomeMsg', r.message, r.success);
  loadQuirkyAuto(true);
  return r;
}
async function quirkyToggle(on){ await quirkySet({enabled:!!on}); }
async function quirkyGroupToggle(gid, on){ await quirkySet({group_id:gid, group_on:!!on}); }
async function quirkySetBase(){
  const v = (id,dv) => parseInt(($(id)||{}).value || dv, 10);
  await quirkySet({threshold_min:v('qkThr',30), cooldown_min:v('qkCd',120), max_idle_min:v('qkMaxIdle',0)});
}
async function quirkySetTopicCfg(){
  const v = (id,dv) => parseInt(($(id)||{}).value || dv, 10);
  await quirkySet({topic_prob:v('qkProb',80), topic_cooldown_min:v('qkTcd',180)});
}
async function quirkySetSched(){
  const v = (id,dv) => parseInt(($(id)||{}).value || dv, 10);
  await quirkySet({gap_min:v('qkGmin',120), gap_max:v('qkGmax',240),
    quiet_start:v('qkQs',1), quiet_end:v('qkQe',8)});
}
async function quirkySetFollow(){
  const v = (id,dv) => parseInt(($(id)||{}).value || dv, 10);
  await quirkySet({follow_delay_sec:v('qkFdelay',25), follow_watch_min:v('qkFwatch',20), follow_max:v('qkFmax',2)});
}
// 看机器人现在能抓到什么热点（游戏/动漫/比赛/热梗优先）
async function quirkyShowTopics(){
  const box = $('qkTopics');
  if(!box) return;
  box.textContent = '抓取中…';
  let d;
  try { d = await api('/api/quirky/auto/topics?force=1'); }
  catch(e){ box.textContent = '读不到'; return; }
  if(!d.success){ box.textContent = d.message || '抓取失败'; return; }
  const lines = d.items.map(x => x.score + '  [' + x.source + '] ' + x.title);
  box.textContent = '源：' + (d.sources||[]).join(' / ') + '　模型：' + (d.llm||'') +
    '\n共 ' + d.count + ' 条，按「游戏/动漫/比赛/梗」打分排序（前 40）：\n' + lines.join('\n');
}
// 手动起话题：dry=true 只生成不发（预览）
async function quirkyTopicNow(gid, dry){
  const box = $('qkTopics');
  if(box && dry) box.textContent = '生成中…';
  let r;
  try { r = await api('/api/quirky/auto/topic',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({group_id:gid||0, dry_run:!!dry})}); }
  catch(e){ say('qkHomeMsg', '请求失败', false); return; }
  say('qkHomeMsg', r.message || (dry ? ('预览：' + r.text) : '已发'), r.success);
  if(dry && box){ box.textContent = '【预览，没有真的发出去】\n' + (r.text||'') + '\n（取自：' + (r.title||'?') + '）'; }
  loadQuirkyAuto(true);
}
async function quirkySendNow(){ await quirkySendGroup(0); }
async function quirkySendGroup(gid){
  const r = await api('/api/quirky/auto/send',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({group_id:gid||0})});
  say('qkHomeMsg', r.message, r.success);
  loadQuirkyAuto(true);
}

// ==================== AI 发言：人工复盘 + 打分 ====================
// 数据来自麦麦自己的消息库（比 qq-monitor 的导出全：导出只从 reportSelfMessage
// 打开之后才有它自己的发言）。打分写回 behavior_score.json，和它自己扣分同一条通道。
let _spRows = [];
let _spOffset = 0;
let _spUsers = [];     // 好感度人物列表（每行的"选人"下拉复用同一份）
// ⚠️ 并发护栏（2026-10-09 加）：面板偶发卡顿（实测 /api/bot_speeches 会 30s+ 无响应），
// 反复点「AI 发言」页签会在同一秒打进来 4~5 个请求，把面板越压越死；卡住时页面还一片空白、
// 控制台无任何报错（await 挂着不抛异常），用户看到的就是「AI 发言查不到」。
let _spLoading = false;

async function loadSpeeches(reset){
  if(_spLoading) return;            // 上一次还没回来就别再打（见 _spLoading 注释）
  _spLoading = true;
  if(reset){ _spRows = []; _spOffset = 0; }
  const kw  = ($('spKw')    || {}).value || '';
  const gid = ($('spGroup') || {}).value || '';
  const qs = `limit=50&offset=${_spOffset}&q=${encodeURIComponent(kw)}&group=${encodeURIComponent(gid)}`;
  let d;
  try {
    d = await Promise.race([
      api('/api/bot_speeches?' + qs),
      new Promise((_,rej)=>setTimeout(
        ()=>rej(new Error('面板 25 秒没响应（多半正忙），稍后点「查询」重试')), 25000)),
    ]);
  }
  catch(e){ say('spMsg', '读取失败：' + e, false); _spLoading = false; return; }
  if(!d.success){ say('spMsg', d.message || '读取失败', false); _spLoading = false; return; }

  const sel = $('spGroup');
  if(sel && d.groups){
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部群</option>' + d.groups.map(g=>
      `<option value="${esc(g.group_id)}">${esc(g.group_name || g.group_id)}（${g.count}）</option>`).join('');
    sel.value = cur;
  }
  _spRows = _spRows.concat(d.rows);
  _spOffset = _spRows.length;
  $('spHint').textContent = `共 ${d.total} 条，已显示 ${_spRows.length}`;
  $('spMore').style.display = d.rows.length >= 50 ? '' : 'none';
  // 先拿到好感度人物列表：每一行的「选人」下拉要用它
  await spLoadFav();
  if(!_spRows.length){ $('spList').innerHTML = '<div class="hint">没有匹配的发言</div>'; }
  else { spRender(); }
  _spLoading = false;
}

function spUserOptions(sel){
  return _spUsers.map(u=>{
    const uid = String(u.user_id);
    return `<option value="${esc(uid)}"${uid === sel ? ' selected' : ''}>${esc(u.name || uid)}</option>`;
  }).join('');
}

function spRender(){
  $('spList').innerHTML = _spRows.map((r,i)=>`
    <div class="row" style="border-bottom:1px solid #f0f0f0;padding:8px 0;align-items:flex-start">
      <div style="flex:1;min-width:220px">
        <div class="hint">${esc(r.time)} · ${esc(r.group_name || r.group_id)}${
          r.reply_uid ? ` · 回复 @${esc(r.reply_name || r.reply_uid)}` : ''}</div>
        <div style="font-size:14px;line-height:1.6;white-space:pre-wrap">${esc(r.text)}</div>
      </div>
      <div style="flex:none;min-width:196px">
        <div style="font-size:12px;color:#888;margin-top:6px">好感度（对谁）</div>
        <div style="display:flex;gap:3px;flex-wrap:wrap">
          <select id="spu_${i}" style="max-width:104px;font-size:12px">
            <option value="">选人…</option>${spUserOptions(r.reply_uid || '')}
          </select>
          <button onclick="spFavRow(${i},-20)">-20</button>
          <button onclick="spFavRow(${i},-10)">-10</button>
          <button onclick="spFavRow(${i},10)">+10</button>
        </div>
      </div>
    </div>`).join('');
}

// 按"这条发言回复的那个人"调好感度；下拉里也能改选别人
async function spFavRow(i, delta){
  const sel = $('spu_' + i);
  const uid = sel ? sel.value : '';
  if(!uid){ say('spMsg', '先在右边的下拉里选一个人', false); return; }
  const u = _spUsers.find(x => String(x.user_id) === uid) || {};
  const res = await api('/api/favorability/set', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({user_id: uid, name: u.name || '', delta})});
  say('spMsg', (u.name || uid) + '：' + (res.message || (res.success ? '已调整' : '失败')), !!res.success);
  if(res.success) spLoadFav();
}

// 好感度数据：只负责把人物列表抓给 _spUsers ——「AI 发言」页每行的「选人」下拉要用它。
// 页面渲染搬到了独立的「好感度」页签（loadFavorPage），这里不再碰任何 DOM。
async function spLoadFav(){
  try {
    const d = await api('/api/favorability');
    _spUsers = d.users || [];
  } catch(e) { /* 拿不到就空着，不影响发言列表本身 */ }
}

// ==================== 好感度页签 ====================
let _fvUsers = [];

let _fvData = null;
async function loadFavorPage(){
  const box = $('fvList');
  if(!box) return;
  let d;
  try { d = await api('/api/favorability'); }
  catch(e){ say('fvMsg', '读取失败：' + e, false); return; }
  _fvData = d;
  _fvUsers = d.users || [];
  _spUsers = _fvUsers;                 // 顺手喂给 AI 发言页的下拉
  fvRender(d);
}

// 导出当前列表（全量）为 CSV —— 想拿去做表的时候方便
function fvExport(){
  const rows = (_fvData && _fvData.users) || [];
  if(!rows.length){ say('fvMsg', '没有数据可导出', false); return; }
  const head = ['全局名次','QQ','昵称','麦麦的称呼','身份','好感度','关系阶段','距下一阶段','已记录互动天数','今日净变动','历史计分次数','最近记录','最近原因','已记录有效互动次数'];
  const cell = v => '"' + String(v === undefined || v === null ? '' : v).replace(/"/g,'""') + '"';
  const lines = [head.map(cell).join(',')].concat(rows.map(u => [
    u.rank, u.user_id, u.name, u.nickname, u.identity, u.score,
    (u.relationship || {}).label, (u.relationship || {}).remaining, u.recorded_interaction_days,
    u.today_change ? u.today_change.net : '', u.hits,
    u.last_ts ? new Date(Number(u.last_ts)*1000).toLocaleString('zh-CN',{hour12:false}) : '',
    u.last_reason, u.interaction_count
  ].map(cell).join(',')));
  const blob = new Blob(['\ufeff' + lines.join('\r\n')], {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'favorability_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
  say('fvMsg', `已导出 ${rows.length} 条`, true);
}

function fvRender(d){
  d = d || _fvData || {};
  const users = d.users || _fvUsers || [];
  const kw = (($('fvKw') || {}).value || '').trim().toLowerCase();
  let rows = users.slice();
  if(kw) rows = rows.filter(u => [u.name, u.user_id, u.nickname, u.identity, u.last_reason, (u.relationship || {}).label]
      .map(v => String(v === undefined || v === null ? '' : v)).join(' ').toLowerCase().includes(kw));
  const mode = (($('fvSort') || {}).value || 'score_desc');
  const key = mode.split('_')[0], dir = mode.split('_')[1] || 'asc';
  const num = (v, dft) => { const n = Number(v); return isNaN(n) ? dft : n; };
  rows.sort((a, b) => {
    let r;
    if(key === 'name') r = String(a.name || '').localeCompare(String(b.name || ''), 'zh');
    else if(key === 'hits') r = num(a.hits, 0) - num(b.hits, 0);
    else if(key === 'last_ts') r = num(a.last_ts, 0) - num(b.last_ts, 0);
    else r = num(a.score, 100) - num(b.score, 100);
    return dir === 'desc' ? -r : r;
  });

  const all = num(d.all_total, users.length);
  const low = users.filter(u => num(u.score, 100) < 30).length;
  $('fvStat').textContent = `显示 ${rows.length} / 共 ${all} 人`
    + (low ? `　⚠ ${low} 人已低于翻脸线 30` : '');
  $('fvHint').textContent = d.updated_at ? `最近更新 ${d.updated_at}` : '';

  if(!rows.length){
    $('fvList').innerHTML = `<div class="hint">${esc(d.hint || (kw ? '没有匹配的人' : '还没有好感度记录'))}</div>`;
    return;
  }
  $('fvList').innerHTML = rows.map(u=>{
    const s = Number(u.score === undefined ? 100 : u.score);
    const c = s >= 80 ? '#1a7f37' : (s >= 30 ? '#9a6700' : '#b42318');
    const rel = u.relationship || {};
    const pct = Math.max(0, Math.min(100, Number(rel.progress || 0)));
    const uid = esc(String(u.user_id));
    const nm = esc(String(u.name || ''));
    const reason = esc(String(u.last_reason || ''));
    const call = u.nickname ? ` <span class="hint">（麦麦叫他 ${esc(String(u.nickname))}）</span>` : '';
    const ident = u.identity ? ` <span class="badge ok">${esc(String(u.identity))}</span>` : '';
    const hits = Number(u.hits || 0);
    const interactionCount = u.interaction_count === undefined || u.interaction_count === null
      ? '互动次数尚未记录' : `已记录有效互动 ${Number(u.interaction_count || 0)} 次`;
    const last = u.last_ts ? esc(new Date(Number(u.last_ts)*1000).toLocaleString('zh-CN',{hour12:false})) : '';
    const signed = n => (Number(n) > 0 ? '+' : '') + Number(n);
    const stage = rel.next_score !== null && rel.next_score !== undefined
      ? `距「${esc(String(rel.next_label))}」还差 ${Number(rel.remaining)} 分`
      : '最高已定义阶段，分数仍可继续变化';
    const today = u.today_change ? `今日 +${Number(u.today_change.gain)} / -${Number(u.today_change.loss)}（净 ${signed(u.today_change.net)}）` : '今日暂无已记录变动';
    const changes = (u.recent_changes || []).map(e => `<div class="hint">${esc(new Date(Number(e.ts)*1000).toLocaleString('zh-CN',{hour12:false}))} · ${signed(e.delta)} → ${Number(e.score)} · ${e.source === 'admin' ? '管理员调整' : '互动'} · ${esc(String(e.reason || ''))}</div>`).join('');
    return `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:8px 0;align-items:center">
      <div style="flex:1;min-width:200px">
        <div style="font-size:14px"><span class="badge">第 ${esc(String(u.rank || '—'))} 名</span> ${nm || '(未记昵称)'} <span class="hint">${uid}</span>${call}${ident}${
          rel.label ? ' <span class="badge">' + esc(String(rel.label)) + '</span>' : ''}</div>
        <div style="height:6px;background:#f0f0f0;border-radius:3px;margin-top:5px;max-width:260px">
          <div style="height:6px;width:${pct}%;background:${c};border-radius:3px"></div></div>
        <div class="hint" style="margin-top:3px">${stage} · 已记录互动 ${Number(u.recorded_interaction_days || 0)} 天 · ${today}</div>
        <div class="hint" style="margin-top:3px">${interactionCount} · 历史计分 ${hits} 次${
          last ? ' · 最近记录 ' + last : ''}${reason ? ' · ' + reason : ''}</div>
        <details style="margin-top:3px"><summary class="hint">最近分数变动</summary>${changes || '<div class="hint">暂无已记录变动，旧历史未追溯。</div>'}</details>
      </div>
      <span style="width:56px;text-align:right;font-weight:700;color:${c};flex:none">${s}</span>
      <span style="flex:none;display:flex;gap:4px;align-items:center">
        <button onclick="fvSet('${uid}','${nm}',-20)">-20</button>
        <button onclick="fvSet('${uid}','${nm}',-10)">-10</button>
        <button onclick="fvSet('${uid}','${nm}',10)">+10</button>
        <button onclick="fvPrompt('${uid}','${nm}',${s})">设值</button>
        <button onclick="fvReset('${uid}')">重置</button>
      </span>
    </div>`;
  }).join('');
}

async function fvSet(uid, name, delta){
  const res = await api('/api/favorability/set', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({user_id: uid, name, delta})});
  say('fvMsg', (name || uid) + '：' + (res.message || (res.success ? '已调整' : '失败')), !!res.success);
  if(res.success) loadFavorPage();
}

async function fvPrompt(uid, name, cur){
  const v = prompt(`把「${name || uid}」的好感度设为多少？\n（当前 ${cur}，初始 100，无上限）`, cur);
  if(v === null) return;
  const n = parseInt(v, 10);
  if(isNaN(n) || n < 0){ say('fvMsg', '要填一个不小于 0 的整数', false); return; }
  const res = await api('/api/favorability/set', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({user_id: uid, name, value: n})});
  say('fvMsg', (name || uid) + '：' + (res.message || (res.success ? '已设置' : '失败')), !!res.success);
  if(res.success) loadFavorPage();
}

async function fvReset(uid){
  const res = await api('/api/favorability/set', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({user_id: uid, reset_one: true})});
  say('fvMsg', res.success ? '已重置为 100' : (res.message || '失败'), !!res.success);
  if(res.success) loadFavorPage();
}

async function fvResetAll(){
  if(!confirm('把所有人的好感度都重置成 100？这个操作不可撤销。')) return;
  const res = await api('/api/favorability/set', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({reset_all: true})});
  say('fvMsg', res.success ? '已全部重置为 100' : (res.message || '失败'), !!res.success);
  if(res.success) loadFavorPage();
}

// ==================== 记忆库页签 ====================
// ⚠ 这个页签的删除/锁定会**直接写麦麦的 SQLite**（面板里唯一一处），
// 所以后端只接受单个 id，前端也不做批量。
let _mmRows = [];
let _mmOffset = 0;
let _mmSrc = 'amem';        // amem = 现役 A_memorix（只读）；legacy = memory_chest 老表
let _mmKind = 'paragraph';

// 切换数据源：现役那边只有"看/搜"，编辑删除锁定都只对老表开放
function mmSourceChanged(){
  _mmSrc = (($('mmSource') || {}).value || 'amem');
  const amem = _mmSrc === 'amem';
  if($('mmKind')) $('mmKind').style.display = amem ? '' : 'none';
  if($('mmDupBtn')) $('mmDupBtn').style.display = amem ? 'none' : '';
  if($('mmKw')) $('mmKw').placeholder = amem ? '搜内容…' : '搜内容 / 标题…';
  if(!amem && $('mmDupCard')) $('mmDupCard').style.display = 'none';
  _mmEditing = null;
  loadMemories(true);
}

async function loadMemories(reset){
  if(reset){ _mmRows = []; _mmOffset = 0; }
  const kw = (($('mmKw') || {}).value || '').trim();
  const gid = (($('mmGroup') || {}).value || '');
  _mmSrc = (($('mmSource') || {}).value || 'amem');
  _mmKind = (($('mmKind') || {}).value || 'paragraph');
  const qs = `source=${encodeURIComponent(_mmSrc)}&kind=${encodeURIComponent(_mmKind)}`
           + `&limit=40&offset=${_mmOffset}&q=${encodeURIComponent(kw)}&group=${encodeURIComponent(gid)}`;
  let d;
  try { d = await api('/api/memories?' + qs); }
  catch(e){ say('mmMsg', '读取失败：' + e, false); return; }
  if(!d.success){ say('mmMsg', d.message || '读取失败', false); return; }

  const sel = $('mmGroup');
  if(sel && d.groups){
    const cur = sel.value;
    sel.innerHTML = '<option value="">全部群</option>' + d.groups.map(g=>
      `<option value="${esc(g.group_id)}">${esc(g.group_name)}（${g.count}）</option>`).join('');
    sel.value = cur;
  }
  // 现役那边的库内合计（段落/实体/关系/画像）—— 一眼看出记忆到底有没有在长
  const sr = $('mmStatsRow');
  if(sr){
    if(d.stats && Object.keys(d.stats).length){
      sr.innerHTML = '库内合计：' + ['paragraph','entity','relation','profile']
        .filter(k=>d.stats[k]).map(k=>`${esc(d.stats[k].label)} <b>${d.stats[k].count}</b>`).join(' · ')
        + `　（库文件：<code>${esc(d.db || '')}</code>）`;
    } else if(d.db){
      sr.innerHTML = `库文件：<code>${esc(d.db)}</code>`;
    } else { sr.innerHTML = ''; }
  }
  _mmRows = _mmRows.concat(d.rows);
  _mmOffset = _mmRows.length;
  $('mmStat').textContent = `共 ${d.total} 条，已显示 ${_mmRows.length}`;
  $('mmMore').style.display = d.rows.length >= 40 ? '' : 'none';
  if(!_mmRows.length){ $('mmList').innerHTML = '<div class="hint">没有匹配的记忆</div>'; return; }
  mmRender();
}

// 正在编辑哪一条记忆（存 id；null = 没有在编辑）
let _mmEditing = null;

function mmRender(){
  $('mmList').innerHTML = _mmRows.map(r=>{
    if(_mmEditing === r.id){
      return `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:8px 0;background:#fffbe6;align-items:flex-start">
        <div style="flex:1;min-width:260px">
          <input id="mmT_${r.id}" value="${esc(r.title)}" placeholder="标题（可留空）"
                 style="width:100%;font-size:13px">
          <textarea id="mmC_${r.id}" rows="6" placeholder="内容：一行一条事实"
                    style="width:100%;font-size:13px;margin-top:4px;font-family:inherit;line-height:1.6"
                    onkeydown="if(event.ctrlKey&&event.key==='Enter'){mmSave(${r.id})}else if(event.key==='Escape'){mmCancel()}">${esc(r.content)}</textarea>
          <div class="hint">Ctrl+Enter 保存 · Esc 取消 · 手动改的内容<b>不会</b>被噪声过滤动</div>
        </div>
        <span style="flex:none;display:flex;gap:4px">
          <button class="p" onclick="mmSave(${r.id})">保存</button>
          <button onclick="mmCancel()">取消</button>
        </span>
      </div>`;
    }
    return `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:8px 0;align-items:flex-start">
      <div style="flex:1;min-width:240px">
        ${r.title ? `<div style="font-size:13px;color:#555">${esc(r.title)}</div>` : ''}
        <div class="hint">${esc(r.time)}${r.group_name ? ' · ' + esc(r.group_name) : (r.chat_id ? ' · ' + esc(r.chat_id) : '')}${r.chars ? ' · ' + r.chars + ' 字' : ''}${r.locked ? ' · <b>已锁定</b>' : ''}</div>
        <div style="font-size:13px;line-height:1.65;white-space:pre-wrap;margin-top:4px;color:#333">${esc(r.content)}</div>
      </div>
      <span style="flex:none;display:flex;gap:4px">${r.ro ? '<span class="hint">只读</span>' : `<button onclick="mmEdit(${r.id})">编辑</button>
        <button onclick="mmLock(${r.id},${r.locked ? 'false' : 'true'})">${r.locked ? '解锁' : '锁定'}</button>
        <button onclick="mmRemove(${r.id})">删除</button>`}</span>
    </div>`;
  }).join('');
}

function mmEdit(id){
  _mmEditing = id;
  mmRender();
  const el = $('mmT_' + id);
  if(el){ el.focus(); if(el.select) el.select(); }
}

function mmCancel(){
  _mmEditing = null;
  mmRender();
}

async function mmSave(id){
  const t = $('mmT_' + id);
  const c = $('mmC_' + id);
  const title = ((t && t.value) || '').trim();
  const content = ((c && c.value) || '').trim();
  if(!content){ say('mmMsg', '内容不能改成空 —— 想删掉就点「删除」', false); return; }
  const res = await api('/api/memories/update', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id, title, content})});
  say('mmMsg', res.message || (res.success ? '已保存' : '失败'), !!res.success);
  if(res.success){ _mmEditing = null; loadMemories(true); }
}

async function mmRemove(id, fromDup){
  if(!confirm('删掉这条记忆？这是直接删麦麦数据库里的一行，删了找不回来。')) return;
  const res = await api('/api/memories/remove', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  if(fromDup){ say('mmDupMsg', res.message || (res.success ? '已删除' : '失败'), !!res.success); if(res.success) mmDup(); }
  else { say('mmMsg', res.message || (res.success ? '已删除' : '失败'), !!res.success); if(res.success) loadMemories(true); }
}

async function mmLock(id, locked){
  const res = await api('/api/memories/lock', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id, locked})});
  say('mmMsg', res.message || (res.success ? '已更新' : '失败'), !!res.success);
  if(res.success) loadMemories(true);
}

async function mmDup(){
  say('mmMsg', '正在同群内两两比对内容…', true);
  let d;
  try { d = await api('/api/memories/duplicates'); }
  catch(e){ say('mmMsg', '比对失败：' + e, false); return; }
  if(!d.success){ say('mmMsg', d.message || '比对失败', false); return; }
  $('mmDupCard').style.display = '';
  $('mmDupHint').textContent = `扫了 ${d.scanned} 条 → 找到 ${d.groups} 组（相似度阈值 ${d.threshold}）`;
  if(!d.clusters.length){
    $('mmDupList').innerHTML = '<div class="hint">没有发现明显重复，挺好。</div>';
    return;
  }
  $('mmDupList').innerHTML = d.clusters.map(c=>`
    <div style="margin:10px 0;padding:8px 10px;background:#fafafa;border-radius:6px">
      <div class="hint"><b>${esc(c.group_name)}</b> · ${c.items.length} 条内容相似</div>
      ${c.items.map(it=>`
        <div class="row" style="padding:6px 0;border-top:1px solid #eee;align-items:flex-start">
          <div style="flex:1;min-width:220px">
            <div style="font-size:13px;color:#444">${esc(it.title).slice(0, 70)}</div>
            <div class="hint">${esc(it.time)} · 正文 ${it.content.length} 字${it.locked ? ' · 已锁定' : ''}</div>
            <div class="hint" style="margin-top:2px">${esc(it.content).slice(0, 120)}…</div>
          </div>
          <button style="flex:none" onclick="mmRemove(${it.id}, true)">删这条</button>
        </div>`).join('')}
    </div>`).join('');
}

// ==================== 怪话库页签 ====================
// 冷场时麦麦会从这里随机挑一条发出去。挑选逻辑在麦麦侧（quirky_lines.py::pick），
// 优先挑"用得最少"的那一半，所以这里的 used 计数就是它被说出去的次数。
let _qkItems = [];

async function loadQuirky(){
  let d;
  try { d = await api('/api/quirky'); }
  catch(e){ say('qkMsg', '读取失败：' + e, false); return; }
  if(!d.success){ say('qkMsg', d.message || '读取失败', false); return; }
  _qkItems = d.items || [];
  $('qkStat').textContent = `共 ${d.total} 条，启用 ${d.enabled} 条，累计说出去 ${d.used_total} 次`;
  $('qkHint').textContent = d.updated_at ? `最近更新 ${d.updated_at}` : '';
  if(!_qkItems.length){
    $('qkList').innerHTML = `<div class="hint">${esc(d.hint || '还没有怪话')}</div>`;
    return;
  }
  qkRender();
}

function qkRender(){
  const kw = (($('qkKw') || {}).value || '').trim();
  const len = (($('qkLen') || {}).value || 'all');
  const inLen = (t) => {
    const n = String(t || '').length;
    if(len==='s')  return n < 100;
    if(len==='m')  return n >= 100 && n < 200;
    if(len==='l')  return n >= 200 && n < 400;
    if(len==='xl') return n >= 400;
    return true;
  };
  let rows = kw ? _qkItems.filter(i => String(i.text || '').includes(kw)) : _qkItems;
  rows = rows.filter(i => inLen(i.text));
  if(!rows.length){ $('qkList').innerHTML = '<div class="hint">没有匹配的怪话</div>'; return; }
  $('qkList').innerHTML = rows.map(it=>{
    const on = it.enabled !== false;
    const used = Number(it.used || 0);
    const rid = esc(String(it.id));
    const ln = String(it.text || '').length;
    const lc = ln < 100 ? 'var(--t2)' : (ln < 200 ? '#0a66c2' : (ln < 400 ? '#1a7f37' : '#9a6700'));
    return `<div class="row" style="border-bottom:1px solid #f0f0f0;padding:6px 0;align-items:center;${on ? '' : 'opacity:.45'}">
      <span style="flex:1;min-width:240px;font-size:13px">${esc(it.text || '')}</span>
      <span class="hint" style="flex:none;width:170px;text-align:right">
        <b style="color:${lc}">${ln}字</b> · ${esc(it.kind || '')}${used ? ` · 说过 ${used} 次` : ' · 还没用过'}
      </span>
      <span style="flex:none;display:flex;gap:4px;margin-left:8px">
        <button onclick="qkToggle('${rid}',${on ? 'false' : 'true'})">${on ? '停用' : '启用'}</button>
        <button onclick="qkRemove('${rid}')">删除</button>
      </span>
    </div>`;
  }).join('');
}

async function qkAdd(){
  const el = $('qkNew');
  const text = ((el && el.value) || '').trim();
  if(!text){ say('qkMsg', '先在框里写点什么', false); return; }
  const res = await api('/api/quirky/add', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text})});
  if(res.success && el) el.value = '';
  say('qkMsg', res.message || (res.success ? '已塞进去' : '失败'), !!res.success);
  if(res.success) loadQuirky();
}

async function qkToggle(id, enabled){
  const res = await api('/api/quirky/toggle', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id, enabled})});
  say('qkMsg', res.message || (res.success ? '已更新' : '失败'), !!res.success);
  if(res.success) loadQuirky();
}

async function qkRemove(id){
  if(!confirm('删掉这条怪话？')) return;
  const res = await api('/api/quirky/remove', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({id})});
  say('qkMsg', res.message || (res.success ? '已删除' : '失败'), !!res.success);
  if(res.success) loadQuirky();
}


// 好感度：按分数从低到高排（快被拉黑的在最前面）
async function loadFav(){
  const box = $('homeFav');
  if(!box) return;
  let d;
  try { d = await api('/api/favorability'); }
  catch(e){ box.innerHTML = '<span class="hint">读不到（麦麦可能没在跑）</span>'; return; }
  const us = d.users || [];
  if(!us.length){
    box.innerHTML = `<span class="hint">${esc(d.hint || d.error || '暂无记录')}</span>`;
    return;
  }
  let h = '<div style="font-size:13px;line-height:2">';
  for(const u of us.slice(0, 12)){
    const s = u.score ?? 100;
    const c = s > 70 ? '#1a7f37' : (s > 30 ? '#9a6700' : '#b42318');
    const tag = s <= 30 ? ' <b style="color:#b42318">不理他了</b>' : '';
    const uid = esc(u.user_id);
    h += `<div style="display:flex;align-items:center;gap:6px;border-bottom:1px solid #f5f5f5;padding:3px 0">`
       + `<span style="color:${c};font-weight:600;min-width:40px">${s}</span>`
       + `<span style="flex:1">${esc(u.name || u.user_id)}${tag}`
       + (u.last_reason ? `<span class="hint">　${esc(u.last_reason)}</span>` : '') + `</span>`
       + `<input type="number" id="fv_${uid}" value="${s}" style="width:74px" title="改成这个数">`
       + `<button onclick="favSet('${uid}', document.getElementById('fv_${uid}').value)">设为</button>`
       + `<button onclick="favDelta('${uid}', -10)">-10</button>`
       + `<button onclick="favDelta('${uid}', 10)">+10</button>`
       + `</div>`;
  }
  h += '</div>';
  if(d.total > 12) h += `<div class="hint" style="margin-top:4px">共 ${d.total} 人，只显示最低的 12 个</div>`;
  box.innerHTML = h;
}

// 管理员：直接设定 / 加减 / 全部重置（面板直接改文件，插件会自动重读）
async function favSet(uid, value){
  const r = await api('/api/favorability/set', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:uid, value:Number(value)})});
  say('favMsg', r.message, r.success); loadFav();
}
async function favDelta(uid, delta){
  const r = await api('/api/favorability/set', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({user_id:uid, delta:Number(delta)})});
  say('favMsg', r.message, r.success); loadFav();
}
async function favResetAll(){
  if(!confirm('把所有人的好感度都重置为 100？')) return;
  const r = await api('/api/favorability/set', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({reset_all:true})});
  say('favMsg', r.message, r.success); loadFav();
}
// 导出聊天记录：目录选择框 + 全量导出
async function pickDir(){
  say('expMsg','正在打开目录选择框…（弹在这台机器上，没看到就看一眼任务栏）',true);
  const r = await api('/api/pick_dir', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  if(r.success){ $('expDir').value = r.path; say('expMsg','已选择：'+r.path,true); }
  else say('expMsg', r.message || '没有选择目录', false);
}
async function exportAll(){
  const dir = ($('expDir').value||'').trim();
  say('expMsg','正在导出…（历史多的话要几十秒，别关页面）',true);
  const r = await api('/api/export/chat', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dir})});
  if(r.success) say('expMsg', r.message || '导出完成', true);
  else say('expMsg', r.message || r.error || '导出失败', false);
}
// Word 导出：后台线程 + 轮询进度
let _wordTimer = null;
async function exportWord(){
  const dir = ($('expDir').value||'').trim();
  const r = await api('/api/export/word', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({dir})});
  if(!r.success){ say('expMsg', r.message || r.error || '启动失败', false); return; }
  say('expMsg','Word 导出已开始（图片要逐张缩图嵌入，1~3 分钟）…',true);
  if(_wordTimer) clearInterval(_wordTimer);
  _wordTimer = setInterval(wordProgress, 2000);
  wordProgress();
}
async function wordProgress(){
  let st;
  try { st = await api('/api/mon/export/word/status'); } catch(e){ return; }
  if(!st || st.success===false) return;
  const t = st.total||0, d = st.done||0;
  if(st.running){
    const pct = t ? Math.round(d*100/t) : 0;
    say('expMsg', `正在导出 Word：${d}/${t}（${pct}%）· ${st.messages||0} 条消息 · 已嵌 ${st.images||0} 张图 · ${st.current||''}`, true);
  } else {
    if(_wordTimer){ clearInterval(_wordTimer); _wordTimer = null; }
    if(st.error) say('expMsg','Word 导出失败：'+st.error, false);
    else if(t) say('expMsg', `Word 导出完成：${t} 个文档（失败 ${st.failed||0}）、${st.messages||0} 条消息、嵌了 ${st.images||0} 张图片（缺 ${st.missing_images||0} 张）→ ${st.out_dir||''}`, true);
    else say('expMsg','Word 导出没有产生任何文档（可能这个时间段没有消息）', false);
  }
}

// 历史补齐：从 NapCat 往回翻，把 AI 自己发的（和 WS 漏掉的）消息补进库里
let _bfTimer = null;
async function backfillHistory(){
  const r = await api('/api/mon/history/backfill', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({max_pages:0})});   // 0 = 一直翻到头
  if(!r.success){ say('expMsg', r.message || r.error || '启动失败', false); return; }
  say('expMsg','开始补齐历史（含 AI 发言），翻页可能需要几分钟…',true);
  if(_bfTimer) clearInterval(_bfTimer);
  _bfTimer = setInterval(backfillProgress, 2000);
  backfillProgress();
}
async function backfillProgress(){
  let st;
  try { st = await api('/api/mon/history/backfill/status'); } catch(e){ return; }
  if(!st || st.success===false) return;
  if(st.running){
    say('expMsg', `正在补齐历史：第 ${st.pages||0} 页 · 扫过 ${st.scanned||0} 条 · 新增 ${st.added||0} 条`
        + `（其中 AI 发言 ${st.self_added||0} 条）· ${st.current||''}`, true);
  } else {
    if(_bfTimer){ clearInterval(_bfTimer); _bfTimer = null; }
    if(st.error) say('expMsg','补齐历史失败：'+st.error, false);
    else say('expMsg', `补齐完成：扫过 ${st.scanned||0} 条，新增 ${st.added||0} 条`
        + `（其中 AI 发言 ${st.self_added||0} 条）。想立刻反映到文件里，再点一次「导出全部聊天记录（TXT）」。`, true);
  }
}

async function act(k,a){ const r=await api(`/api/service/${k}/${a}`,{method:'POST'}); say('svcMsg',r.message,r.success); say('homeMsg',r.message,r.success); setTimeout(refresh,1500); }
async function snowAct(a){ const r=await api('/api/snowluma/'+a,{method:'POST'}); say('snowMsg',r.message,r.success); setTimeout(refresh,4000); }
async function allStart(){ say('homeMsg','正在按顺序启动…',true); const r=await api('/api/service-all/start',{method:'POST'}); say('homeMsg',r.message,true); refresh(); }
async function allStop(){ const r=await api('/api/service-all/stop',{method:'POST'}); say('homeMsg',r.message,true); refresh(); }

function field(f){
  const id = `f_${f.section}_${f.key}`;
  const v = f.value;
  const lv = esc(f.label), ev = esc(v);
  if(f.kind==='bool') return `<label class="f"><span class="k">${lv}</span><input type="checkbox" id="${id}" ${v?'checked':''}></label>`;
  if(f.kind==='text') return `<label class="f"><span class="k">${lv}</span><textarea id="${id}">${ev}</textarea></label>`;
  if(f.kind==='list') return `<label class="f"><span class="k">${lv}</span><input type="text" id="${id}" value="${esc(Array.isArray(v)?v.join(', '):v)}"><div class="hint">多个用英文逗号分隔</div></label>`;
  return `<label class="f"><span class="k">${lv}</span><input type="${f.kind==='int'?'number':'text'}" ${f.kind==='float'?'step=0.01':''} id="${id}" value="${ev}"></label>`;
}
function collect(fields){
  return fields.map(f=>{
    const el=$(`f_${f.section}_${f.key}`); if(!el) return null;
    let v = f.kind==='bool' ? el.checked : el.value;
    return {section:f.section,key:f.key,kind:f.kind,value:v};
  }).filter(Boolean);
}
async function loadMb(){ const d=await api('/api/config/maibot'); $('mbForm').innerHTML=d.fields.map(field).join(''); $('mbPath').textContent=d.path; window._mb=d.fields; }
async function saveMb(){ const r=await api('/api/config/maibot',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({fields:collect(window._mb)})}); say('mbMsg',r.message,r.success&&!r.failed.length); }

async function loadMo(){
  const d=await api('/api/config/monitor');
  // 导出卡片里的目录跟着监控配置走（没手填过就自动带上）
  const ed=$('expDir'); if(ed && !ed.value && d.export_dir) ed.value=d.export_dir;
  $('moForm').innerHTML = `
    <div class="grid2">
      <label class="f"><span class="k">监控群号（逗号分隔）</span><input type="text" id="m_groups" value="${esc((d.monitor_groups||[]).join(', '))}"></label>
      <label class="f"><span class="k">告警接收 QQ（逗号分隔）</span><input type="text" id="m_qqto" value="${esc((d.qq_recipients||[]).join(', '))}"></label>
      <label class="f"><span class="k">QQ 私聊告警</span><input type="checkbox" id="m_qqon" ${d.qq_enabled?'checked':''}></label>
      <label class="f"><span class="k">聊天记录 TXT 导出目录</span><input type="text" id="m_export" value="${esc(d.export_dir||'')}"></label>
      <label class="f"><span class="k">AI 审查开关</span><input type="checkbox" id="m_aion" ${d.ai_enabled?'checked':''}></label>
      <label class="f"><span class="k">主审模型</span><input type="text" id="m_model" value="${esc(d.ai_model||'')}"></label>
      <label class="f"><span class="k">主审 API 地址</span><input type="text" id="m_base" value="${esc(d.ai_base||'')}"></label>
      <label class="f"><span class="k">审查间隔（分钟）</span><input type="number" id="m_iv" value="${esc(d.ai_interval||5)}"></label>
      <label class="f"><span class="k">二次复核开关</span><input type="checkbox" id="m_sec" ${d.secondary_enabled?'checked':''}></label>
      <label class="f"><span class="k">二次复核模型</span><input type="text" id="m_secm" value="${esc(d.secondary_model||'')}"></label>
      <label class="f"><span class="k">二次复核 API 地址</span><input type="text" id="m_secb" value="${esc(d.secondary_base||'')}"></label>
      <label class="f"><span class="k">陪聊开关（被 @ 时回一句）</span><input type="checkbox" id="m_cpon" ${d.companion_enabled?'checked':''}></label>
      <label class="f"><span class="k">陪聊模型</span><input type="text" id="m_cpm" value="${esc(d.companion_model||'')}"></label>
      <label class="f"><span class="k">陪聊 API 地址</span><input type="text" id="m_cpb" value="${esc(d.companion_base||'')}"></label>
      <label class="f"><span class="k">陪聊里的机器人名字</span><input type="text" id="m_cpn" value="${esc(d.companion_bot_name||'')}"></label>
      <label class="f"><span class="k">陪聊冷却（秒，防刷屏）</span><input type="number" id="m_cpc" value="${esc(d.companion_cooldown||10)}"></label>
      <label class="f"><span class="k">复读开关（≥2 人发同一句就跟一句）</span><input type="checkbox" id="m_rpon" ${d.repeater_enabled?'checked':''}></label>
      <label class="f"><span class="k">复读冷却（秒）</span><input type="number" id="m_rpc" value="${esc(d.repeater_cooldown||1800)}"></label>
      <label class="f"><span class="k">聊天记录保留</span><span>自动删除已禁用</span></label>
    </div>
    <label class="f"><span class="k">主审提示词</span><textarea id="m_prompt" style="min-height:110px">${esc(d.ai_prompt||'')}</textarea></label>
    <div class="hint">三个模型各管一摊：<b>主审</b>每 N 分钟批量审查（调用最频繁，本地即可）；<b>二次复核</b>只在疑似违规时跑（要准，建议云端）；<b>陪聊</b>被 @ 时按人设回一句（直接发到群里，最影响观感）。<br>
    API 地址里写 <code>localhost</code> 会被本机解析成 IPv6 <code>::1</code>，而 Ollama 只监听 IPv4，所以保存时会自动改成 <code>127.0.0.1</code>。</div>
    <div class="hint" style="color:#b06000">⚠ <b>陪聊</b>和<b>复读</b>都会用<b>同一个 QQ 账号</b>往群里发消息。
    麦麦也在同一个群里说话，两边人设不一样 —— 同时开会看起来像"人格分裂"（实测过一次：
    陪聊回「我是你失散多年的好姐妹」，麦麦回「我示例角色啊」）。
    <b>想让群里只有一个声音，就把这两个都关掉，只留麦麦。</b>
    改完这里需要重启「监控告警系统」才生效。</div>`;
}
async function saveMo(){
  const body={monitor_groups:$('m_groups').value,qq_recipients:$('m_qqto').value,qq_enabled:$('m_qqon').checked,
    export_dir:$('m_export').value,ai_enabled:$('m_aion').checked,ai_model:$('m_model').value,ai_base:$('m_base').value,
    ai_interval:$('m_iv').value,secondary_enabled:$('m_sec').checked,secondary_model:$('m_secm').value,
    secondary_base:$('m_secb').value,auto_cleanup:false,ai_prompt:$('m_prompt').value,
    companion_enabled:$('m_cpon').checked,companion_model:$('m_cpm').value,companion_base:$('m_cpb').value,
    companion_bot_name:$('m_cpn').value,companion_cooldown:$('m_cpc').value,
    repeater_enabled:$('m_rpon').checked,repeater_cooldown:$('m_rpc').value};
  const r=await api('/api/config/monitor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  say('moMsg',r.message,r.success);
}
async function loadRu(){ const d=await api('/api/config/rules'); $('kw').value=d['keywords.txt']||''; $('bw').value=d['banned_words.txt']||''; }
async function saveRu(){ const r=await api('/api/config/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({'keywords.txt':$('kw').value,'banned_words.txt':$('bw').value})}); say('ruMsg',r.message,r.success); }

// ==================== CG 与身份（提示词） ====================
// 数据在 MaiBot\data\cg_prompts.json，结构很深（identity.options / cg.identity_hint / cg.stages），
// 所以不像麦麦配置页那样用通用 field() 铺，而是照它自己的结构写表单。
// 关键：loadCg 把整个对象存在 window._cg，saveCg 只覆盖表单里露出来的键 ——
// _说明 / ask_keywords / decline_words / providers 这些页面不显示的键原样带回去，
// 否则一保存就等于把它们删了（插件那边会读不到关键词，功能静默失效）。
function cgCk(id,label,on){ return `<label class="f"><span class="k">${label}</span><input type="checkbox" id="${id}" ${on?'checked':''}></label>`; }
function cgIn(id,label,v,kind){ return `<label class="f"><span class="k">${label}</span><input type="${kind||'text'}" id="${id}" value="${esc(v==null?'':v)}"></label>`; }
function cgTa(id,label,v,rows){ return `<label class="f"><span class="k">${label}</span><textarea id="${id}" rows="${rows||4}">${esc(v||'')}</textarea></label>`; }

// 一档纪念图 = 一张小卡片。字段名刻意用 class 而不是 id：档数可以增删，id 会重。
function cgStageCard(s){
  s = s || {};
  return `<div class="card" style="background:#fff;margin:6px 0;padding:8px">
    <div class="grid2">
      <label class="f"><span class="k">第几档 level</span><input type="number" class="cg-st-lv" value="${esc(s.level==null?'':s.level)}"></label>
      <label class="f"><span class="k">所需好感度</span><input type="number" class="cg-st-fv" value="${esc(s.min_favor==null?'':s.min_favor)}"></label>
      <label class="f"><span class="k">这一档的名字</span><input type="text" class="cg-st-nm" value="${esc(s.name||'')}"></label>
      <label class="f"><span class="k">　</span><button onclick="cgDelStage(this)">删掉这一档</button></label>
    </div>
    <label class="f"><span class="k">画面提示词（英文，拼在 base_prompt 后面）</span><textarea class="cg-st-pm" rows="3">${esc(s.prompt||'')}</textarea></label>
  </div>`;
}
function cgAddStage(){ $('cgStages').insertAdjacentHTML('beforeend', cgStageCard({})); }
function cgDelStage(btn){ const c=btn.closest('.card'); if(c) c.remove(); }
function cgStagesCollect(){
  const out=[];
  document.querySelectorAll('#cgStages > .card').forEach(c=>{
    const num=(sel,dv)=>{ const t=parseInt(c.querySelector(sel).value,10); return isNaN(t)?dv:t; };
    out.push({level:num('.cg-st-lv',out.length+1), min_favor:num('.cg-st-fv',0),
      name:c.querySelector('.cg-st-nm').value, prompt:c.querySelector('.cg-st-pm').value});
  });
  return out;
}

// 每个身份的「场景追加词」scenes：有序对象（场景名 → 追加提示词）。插件那边按
// list(scenes.keys()) 的顺序轮换，所以这里一行一个场景、收值严格按 DOM 顺序 ——
// 不排序、不去重，页面上的先后就是轮换先后。
function cgSceneRow(name, prompt){
  return `<div class="card cg-sc-row" style="background:#fff;margin:6px 0;padding:8px">
    <div class="grid2">
      <label class="f"><span class="k">场景名</span><input type="text" class="cg-sc-nm" value="${esc(name==null?'':name)}"></label>
      <label class="f"><span class="k">　</span><button onclick="cgDelScene(this)">删掉这个场景</button></label>
    </div>
    <label class="f"><span class="k">追加提示词（英文，拼在该身份的 cg.prompt 后面）</span><textarea class="cg-sc-pm" rows="2">${esc(prompt||'')}</textarea></label>
  </div>`;
}
function cgAddScene(ix){ const box=$('cgScenes'+ix); if(box) box.insertAdjacentHTML('beforeend', cgSceneRow('','')); }
function cgDelScene(btn){ const c=btn.closest('.cg-sc-row'); if(c) c.remove(); }
// 空场景名的行不能让后端拒掉整份配置，保存前先拦一道（这里只看名字，不看提示词）
function cgScenesBadName(ix){
  const box=$('cgScenes'+ix);
  if(!box) return false;
  return Array.from(box.querySelectorAll('.cg-sc-nm')).some(e=>!e.value.trim());
}
function cgScenesCollect(ix){
  const out={};
  const box=$('cgScenes'+ix);
  if(!box) return out;
  box.querySelectorAll('.cg-sc-row').forEach(r=>{
    const k=r.querySelector('.cg-sc-nm').value.trim();
    // 注意：JS 对象会把「纯数字」的键排到最前面（普通中文场景名不受影响）
    if(k) out[k]=r.querySelector('.cg-sc-pm').value;  // 键序 = 行序 = 轮换顺序
  });
  return out;
}
// 本地 SD / ComfyUI 的参考参数（cg.sd_params）：只读展示（要改去 json 里改）
function cgSdRef(label, sd){
  if(!sd || typeof sd!=='object') return '';
  const line = n => { const x=sd[n]; return (x==null||x==='') ? '' : `<div><code>${n}</code>：${esc(String(x))}</div>`; };
  const ratios = (sd.ratios && typeof sd.ratios==='object')
    ? Object.entries(sd.ratios).map(([k,v])=>k+'='+v).join(' / ') : '';
  return `<div class="card" style="background:#fff;margin:6px 0;padding:8px">
    <div class="hint">${label} 的本地 SD 参考参数 <code>cg.sd_params</code>（只读，页面上不改；改要去 json）：</div>
    ${line('sampler')}${line('steps')}${line('cfg_scale')}
    ${ratios?'<div><code>ratios</code>：'+esc(ratios)+'</div>':''}
    ${line('note')}
  </div>`;
}

async function loadCg(){
  // 接口拿不到（面板旧版本、网络抽风）时要在页面上说一声，别让这个加载函数抛出去：
  // ui_smoke.js 会真的把每个页签点一遍，未捕获的 rejection 会直接把冒烟测试打挂。
  let d;
  try{ d = await api('/api/cg_prompts'); }
  catch(e){ say('cgMsg', '读不到 CG 提示词配置：' + (e && e.message ? e.message : e), false); return; }
  if(!d.ok){ say('cgMsg', d.message||'读不到 cg_prompts.json', false); return; }
  const c = d.data||{}, i = c.identity||{}, cn = c.callname||{}, g = c.cg||{}, sk = c.sticker||{};
  const opt = i.options||{}, hint = g.identity_hint||{};
  window._cg = c;
  $('cgPath').textContent = d.path||'';
  $('cgForm').innerHTML = `
  <div class="card" style="background:#fafafa;margin:6px 0">
    <h3 style="margin:0 0 6px">身份选择（identity）</h3>
    <div class="hint">好感度到 <code>min_favor</code> 时麦麦甩出下面这份菜单，用户回了字母/名字就换成对应身份的语气；
      回「不选」扣 <code>penalty_no_choice</code> 分，超过 <code>pending_seconds</code> 秒没回就当没问过。
      用户问「菜单 / 帮助」这类词时，回的是下面的「菜单解释」模板，里面的 <code>{options}</code> 会自动列上各身份的一句话解释。</div>
    <div class="grid2">
      ${cgCk('cg_i_on','身份选择开关',i.enabled)}
      ${cgIn('cg_i_min','开启所需好感度',i.min_favor,'number')}
      ${cgIn('cg_i_pen','不选的扣分',i.penalty_no_choice,'number')}
      ${cgIn('cg_i_pend','等多久作废（秒）',i.pending_seconds,'number')}
    </div>
    ${cgTa('cg_i_menu','菜单原文（{who} {cur} 会被替换）',i.menu,5)}
    ${cgIn('cg_i_hkw','菜单触发词（英文逗号分隔，命中就回下面的菜单解释）',(i.help_keywords||[]).join(', '))}
    ${cgTa('cg_i_help','菜单解释 help（可用占位符 {min_favor} {cg_start} {cg_step} {options} {cur} {identity} {nickname} {admin}）',i.help,6)}
    ${cgTa('cg_i_admin','管理员专属那几行（填进 help 的 {admin}；只有管理员问菜单时才显示，不是管理员整行消失。占位符同上）',i.admin_help,3)}
    <div class="hint">「管理员专属」那几行只对 <code>behavior_score.admin_qq</code> 里的人显示
      —— 生图 / 删表情包这些命令非管理员说了会静默放行（不当众说"你没权限"），
      写进通用菜单只会让人以为命令坏了。<code>help</code> 里要留着 <code>{admin}</code> 占位符才会出现。</div>
    ${cgTa('cg_i_no','好感度不够时的回复',i.not_enough,3)}
    ${cgTa('cg_i_ok','选好之后的回复',i.applied,3)}
    ${cgTa('cg_i_del','不选之后的回复',i.declined,3)}
    ${cgTa('cg_i_to','菜单末尾的有效期提示（可用 {seconds}，留空则不追加）',i.menu_timeout_hint,2)}
    ${cgTa('cg_i_exp','菜单过期后他再回答案时的提示（可用 {who} {seconds} {cur}，教他怎么重新发起）',i.pending_expired,2)}
    <div class="hint">下面三项就是菜单里的 A / B / C。字面是用户在群里要回的那个字母；
      人设提示词会拼进麦麦的系统提示词，等于换了个人格，别写太长。</div>
    ${['猫娘','鱼娘','示例角色'].map((k,ix)=>{
      const o = opt[k]||{};
      return `<div class="grid2">
        ${cgIn('cg_o_lb'+ix, k+'：菜单字母', o.label)}
        <label class="f"><span class="k">　</span><span class="hint">字母/名字都认，具体哪些词算「不选」在 json 的 decline_words 里改</span></label>
      </div>
      ${cgIn('cg_o_ds'+ix, k+'：一句话解释（菜单里列出来的那行）', o.desc)}
      ${cgTa('cg_o_st'+ix, k+'：人设提示词', o.style, 4)}
      ${cgIn('cg_o_al'+ix, k+'：别名（英文逗号分隔，用户打这些词也能选中该身份）',(o.aliases||[]).join(', '))}
      ${cgTa('cg_o_cgp'+ix, k+'：专属绘画正向词 cg.prompt（留空=用全局 base_prompt）',(o.cg||{}).prompt,4)}
      ${cgTa('cg_o_cgn'+ix, k+'：专属反向词 cg.negative（留空=用全局 negative）',(o.cg||{}).negative,3)}
      ${cgIn('cg_o_cgs'+ix, k+'：专属尺寸 cg.size（如 1280x720，留空=用全局宽高）',(o.cg||{}).size)}
      ${cgTa('cg_o_ch'+ix, k+'：Q版/梗图正向词 chibi',o.chibi,4)}
      ${cgTa('cg_o_chn'+ix, k+'：Q版反向词 chibi_negative',o.chibi_negative,3)}
      <div class="hint">场景追加词 <code>cg.scenes</code>：麦麦按下面的顺序轮换场景（写在前面的先用），
        每个场景名配一句英文追加提示词，拼在该身份的 <code>cg.prompt</code> 后面。删掉一行就少一个场景。</div>
      <div id="cgScenes${ix}">${Object.entries((o.cg||{}).scenes||{}).map(([n,p])=>cgSceneRow(n,p)).join('')}</div>
      <div class="row"><button onclick="cgAddScene(${ix})">＋ 添加场景</button>
        <span class="hint">行的先后就是轮换的先后，后端按写入顺序存对象。</span></div>
      ${cgSdRef(k,(o.cg||{}).sd_params)}`;
    }).join('')}
  </div>

  <div class="card" style="background:#fafafa;margin:6px 0">
    <h3 style="margin:0 0 6px">自定义称呼（callname）</h3>
    <div class="hint">用户说「以后叫我 XX」之类的就触发。关键词命中了才认，太长或者带怪符号会被拒
      （拒绝用的符号表在 json 的 banned_chars 里）。</div>
    <div class="grid2">
      ${cgCk('cg_cn_on','称呼开关',cn.enabled)}
      ${cgIn('cg_cn_max','称呼最长几个字',cn.max_len,'number')}
    </div>
    ${cgIn('cg_cn_kw','触发关键词（英文逗号分隔）',(cn.keywords||[]).join(', '))}
    ${cgTa('cg_cn_p','改完之后给麦麦的提示词',cn.prompt,3)}
    ${cgTa('cg_cn_ok','接受时的回复',cn.ok,2)}
    ${cgTa('cg_cn_bad','拒绝时的回复',cn.bad,2)}
  </div>

  <div class="card" style="background:#fafafa;margin:6px 0">
    <h3 style="margin:0 0 6px">里程碑纪念图（cg）</h3>
    <div class="hint">好感度从 <code>start_favor</code> 起算，每涨 <code>step</code> 分生成一张，
      每天最多 <code>daily_limit</code> 张。最终提示词 = <code>base_prompt</code> + 那一档的 <code>prompt</code>，
      身份不同时 <code>identity_hint</code> 会换成对应的一句英文短语。</div>
    <div class="grid2">
      ${cgCk('cg_cg_on','生图开关',g.enabled)}
      <label class="f"><span class="k">生图后端 provider</span><select id="cg_cg_pv">
        <option value="pollinations" ${g.provider==='pollinations'?'selected':''}>pollinations（免费、不要 key）</option>
        <option value="siliconflow" ${g.provider==='siliconflow'?'selected':''}>siliconflow（质量好、要余额）</option>
      </select></label>
      ${cgIn('cg_cg_md','模型名 model',g.model)}
      ${cgIn('cg_cg_w','宽 width',g.width,'number')}
      ${cgIn('cg_cg_h','高 height',g.height,'number')}
      ${cgIn('cg_cg_sf','从多少好感度开始',g.start_favor,'number')}
      ${cgIn('cg_cg_st','每涨多少分一张',g.step,'number')}
      ${cgIn('cg_cg_dl','每天最多几张',g.daily_limit,'number')}
    </div>
    ${cgTa('cg_cg_cap','配文（发图时带的那句话）',g.caption,2)}
    ${cgTa('cg_cg_neg','负面提示词 negative',g.negative,3)}
    ${cgTa('cg_cg_bp','基础提示词 base_prompt',g.base_prompt,3)}
    ${cgTa('cg_cg_sp','统一画风前缀 style_prefix（拼在最前面；所有身份共用，留空则关掉。改这条 = 全局换画风）',g.style_prefix,3)}
    <div class="hint">身份不同，画面里加的东西也不同（<code>identity_hint</code>，英文短语）：</div>
    <div class="grid2">
      ${['猫娘','鱼娘','示例角色'].map((k,ix)=>cgIn('cg_h_'+ix, k, hint[k]||'')).join('')}
    </div>
    <h3 style="margin:10px 0 0">每一档的画面（stages）</h3>
    <div id="cgStages">${(g.stages||[]).map(cgStageCard).join('')}</div>
    <div class="row"><button onclick="cgAddStage()">＋ 加一档</button>
      <span class="hint">level 是第几档（从 1 开始，插件按它排序），min_favor 是触发这一档所需的好感度。</span></div>
  </div>

  <div class="card" style="background:#fafafa;margin:6px 0">
    <h3 style="margin:0 0 6px">Q版表情包（梗图 / sticker）</h3>
    <div class="hint">用户 @我说到下面任一触发词时，用他当前身份的 <code>chibi</code> 提示词画一张 Q 版图并 @他；
      好感度要到 <code>min_favor</code>，每人每天最多 <code>daily_limit</code> 张，两张之间隔 <code>cooldown_seconds</code> 秒。
      该身份没写 <code>chibi</code> 时用兜底提示词，配文里的 <code>{who}</code> <code>{identity}</code> 会被替换。</div>
    <div class="grid2">
      ${cgCk('cg_sk_on','表情包开关',sk.enabled)}
      ${cgIn('cg_sk_mf','需要多少好感度 min_favor',sk.min_favor,'number')}
      ${cgIn('cg_sk_dl','每人每天最多几张',sk.daily_limit,'number')}
      ${cgIn('cg_sk_cd','两张之间冷却（秒）',sk.cooldown_seconds,'number')}
      ${cgIn('cg_sk_sz','尺寸 size（如 1024x1024）',sk.size)}
      ${cgIn('cg_sk_kw','触发词（英文逗号分隔）',(sk.keywords||[]).join(', '))}
    </div>
    ${cgTa('cg_sk_cap','配文 caption（可用 {who} {identity}）',sk.caption,2)}
    ${cgTa('cg_sk_fb','兜底提示词 fallback（可用 {identity_hint}）',sk.fallback,3)}
  </div>`;
}

async function saveCg(){
  if(!window._cg){ say('cgMsg','还没读到配置，先点「重新读取」', false); return; }
  // 深拷贝一份原对象再改：只覆盖表单露出来的键，其余键（_说明、ask_keywords…）原样带回去
  const c = JSON.parse(JSON.stringify(window._cg));
  const v = id => { const e=$(id); return e ? e.value : ''; };
  const b = id => { const e=$(id); return e ? !!e.checked : false; };
  const n = (id,dv) => { const t=parseInt(v(id),10); return isNaN(t)?dv:t; };
  // 逗号分隔的一行 → 字符串数组（和 help_keywords / callname.keywords 一个规矩）
  const arr = id => String(v(id)||'').split(/[,，\n]+/).map(s=>s.trim()).filter(Boolean);
  const i = c.identity = c.identity||{}, cn = c.callname = c.callname||{}, g = c.cg = c.cg||{};
  const sk = c.sticker = c.sticker||{};
  i.enabled=b('cg_i_on'); i.min_favor=n('cg_i_min',0);
  i.penalty_no_choice=n('cg_i_pen',0); i.pending_seconds=n('cg_i_pend',300);
  i.menu=v('cg_i_menu'); i.not_enough=v('cg_i_no'); i.applied=v('cg_i_ok'); i.declined=v('cg_i_del');
  // 2026-10-11 新增：菜单有效期提示 + 过期后怎么重来（用户要求「加时间限制 + 提示错过了怎么办」）
  i.menu_timeout_hint=v('cg_i_to'); i.pending_expired=v('cg_i_exp');
  // 菜单解释 + 触发词：前者是长模板（占位符由插件填），后者页面上一行逗号分隔、数组存盘
  i.help=v('cg_i_help');
  i.admin_help=v('cg_i_admin');
  i.help_keywords=String(v('cg_i_hkw')||'').split(/[,，\n]+/).map(s=>s.trim()).filter(Boolean);
  const opt = i.options = i.options||{};
  const iNames = ['猫娘','鱼娘','示例角色'];
  // 场景名空着不放行：后端的要求是非空文本，先提示比白跑一次请求强
  for(let ix=0; ix<iNames.length; ix++){
    if(cgScenesBadName(ix)){ say('cgMsg', iNames[ix]+' 的场景列表里有没填名字的行，场景名不能为空', false); return; }
  }
  iNames.forEach((k,ix)=>{
    const o = opt[k] = opt[k]||{};
    o.label=v('cg_o_lb'+ix); o.desc=v('cg_o_ds'+ix); o.style=v('cg_o_st'+ix);
    o.aliases=arr('cg_o_al'+ix);
    const oc = o.cg = o.cg||{};
    oc.prompt=v('cg_o_cgp'+ix); oc.negative=v('cg_o_cgn'+ix);
    oc.size=String(v('cg_o_cgs'+ix)||'').trim();
    // 场景追加词按 DOM 顺序收（键序 = 轮换顺序）；原来就有 scenes 键、或者页面上
    // 真加了场景，才写回去 —— 否则不给这个身份无端造一个空对象。
    // sd_params 是只读展示，深拷贝里原样带回去，这里不碰。
    const sc = cgScenesCollect(ix);
    if(Object.keys(sc).length || ('scenes' in oc)) oc.scenes = sc;
    o.chibi=v('cg_o_ch'+ix); o.chibi_negative=v('cg_o_chn'+ix);
  });
  cn.enabled=b('cg_cn_on'); cn.max_len=n('cg_cn_max',12);
  cn.keywords=String(v('cg_cn_kw')||'').split(/[,，\s]+/).filter(Boolean);
  cn.prompt=v('cg_cn_p'); cn.ok=v('cg_cn_ok'); cn.bad=v('cg_cn_bad');
  g.enabled=b('cg_cg_on'); g.provider=v('cg_cg_pv'); g.model=v('cg_cg_md');
  g.width=n('cg_cg_w',1024); g.height=n('cg_cg_h',1024); g.start_favor=n('cg_cg_sf',500);
  g.step=n('cg_cg_st',150); g.daily_limit=n('cg_cg_dl',10);
  g.caption=v('cg_cg_cap'); g.negative=v('cg_cg_neg'); g.base_prompt=v('cg_cg_bp');
  // 2026-10-11 新增：统一画风前缀（柚子社视觉小说 CG 基调）—— 所有身份共用，
  // 拼在提示词最前面（人物提示词整条替换 base_prompt，靠这个前缀才能统一画风）
  g.style_prefix=v('cg_cg_sp');
  const hint = g.identity_hint = g.identity_hint||{};
  ['猫娘','鱼娘','示例角色'].forEach((k,ix)=>{ hint[k]=v('cg_h_'+ix); });
  g.stages = cgStagesCollect();
  // Q 版表情包（sticker）：整数项按 0 收底，非法尺寸在这里先拦一道（后端也会拦），省一次白跑的请求
  sk.enabled=b('cg_sk_on'); sk.min_favor=n('cg_sk_mf',0); sk.daily_limit=n('cg_sk_dl',0);
  sk.cooldown_seconds=n('cg_sk_cd',0); sk.size=String(v('cg_sk_sz')||'').trim();
  sk.keywords=arr('cg_sk_kw'); sk.caption=v('cg_sk_cap'); sk.fallback=v('cg_sk_fb');
  // 后端也会拒，这里先拦一道：省得白跑一次请求才发现模型是空的
  if(!String(g.model||'').trim()){ say('cgMsg','生图模型 model 不能为空', false); return; }
  const badSize = (label,s)=>{ if(s && !/^\d+[xX]\d+$/.test(s)){ say('cgMsg', label+' 要写成 数字x数字（比如 1280x720），留空表示用全局宽高', false); return true; } return false; };
  for(const k of ['猫娘','鱼娘','示例角色']){ if(badSize(k+' 的专属尺寸 cg.size', (opt[k].cg||{}).size)) return; }
  if(badSize('表情包尺寸 sticker.size', sk.size)) return;
  const r = await api('/api/cg_prompts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({data:c})});
  say('cgMsg', r.message, !!r.ok);
}

// 日志按级别着色：一屏几百行纯文本很难扫，ERROR/WARN/DEBUG 一眼能跳出来。
// 注意内容必须转义后再拼 HTML（日志里会有 <、& 这些字符，直接 innerHTML 会破版）。
function logLineHtml(l){
  let cls='ln';
  if(/\bERROR\b|Traceback|失败|异常|拒绝访问/.test(l)) cls+=' e';
  else if(/\bWARN(ING)?\b|警告/.test(l)) cls+=' w';
  else if(/\bDEBUG\b/.test(l)) cls+=' d';
  else if(/\bINFO\b/.test(l)) cls+=' i';
  return `<span class="${cls}">${String(l).replace(/&/g,'&amp;').replace(/</g,'&lt;')}</span>`;
}
async function loadLog(){
  const k=$('logKey').value; $('logBox').textContent='加载中…';
  const d=await api('/api/logs/'+k+'?lines=300');
  $('logBox').innerHTML = `<span class="ln i">===== ${d.label} =====</span>\n`
    + (d.lines||[]).map(logLineHtml).join('\n');
  $('logBox').scrollTop = $('logBox').scrollHeight;
}
setInterval(refresh, 5000);
setInterval(()=>{ if($('p-logs').classList.contains('active') && $('logAuto').checked) loadLog(); }, 5000);
refresh(); loadMb(); loadMo(); loadRu(); loadTrend(); loadHealth(); loadQuirkyAuto();
// 支持 ?tab=mon 这种深链直接打开某个页签（方便收藏、截图、把某一页发给别人）。
// 必须放在上面那批初始加载之后：tab() 里会去调各页签的加载函数，面板得先存在。
// 外面套 try + typeof 判断：页面的 JS 会被 ui_smoke.js 抽到一个 Node 的 DOM 桩里跑，
// 那里没有 location/URLSearchParams，不防一下整个冒烟测试会直接崩（踩过）。
(function(){
  try{
    if(typeof location==='undefined' || typeof URLSearchParams==='undefined') return;
    var q = new URLSearchParams(location.search).get('tab');
    if(!q && location.pathname==='/diary') q='diary';
    if(!q && location.pathname==='/notebook') q='notebook';
    if(!q && location.hash.indexOf('#p-')===0) q = location.hash.slice(3);
    if(q && document.querySelector('.tab[data-k="'+q+'"]')) tab(q);
  }catch(e){}
})();
</script></body></html>
"""


def main():
    ap = argparse.ArgumentParser(description="QQ 机器人统一控制台")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    args = ap.parse_args()
    print(f"统一控制台: http://{args.host}:{args.port}")
    print(f"  监控目录 : {MONITOR_DIR}")
    print(f"  麦麦目录 : {MAIBOT_KEY}")
    
    _quirky_auto_load()
    threading.Thread(target=_quirky_auto_worker, daemon=True).start()
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
