"""Manage only services started by this checkout; never manage QQ/OneBot itself."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot" / "MaiBotOneKey"
VENV_PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
SERVICES = {
    "monitor": {"cwd": ROOT / "qq-monitor", "script": ROOT / "qq-monitor/src/main.py",
                "args": ["-c", "config/config.win.json", "--web-port", "8080"],
                "port": 8080, "logs": ROOT / "qq-monitor/logs", "log": "monwin.out.log"},
    "panel": {"cwd": ROOT / "panel", "script": ROOT / "panel/app.py",
              "args": ["--host", "127.0.0.1", "--port", "8090"],
              "port": 8090, "logs": ROOT / "panel/logs", "log": "panelwin.out.log"},
    "bot": {"cwd": BOT / "modules/MaiBot", "script": BOT / "modules/MaiBot/bot.py",
            "args": [], "port": 8000, "logs": BOT / "logs", "log": "maiwin.out.log"},
}


def tcp_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return True
    except OSError:
        return False


def state_file(name: str) -> Path:
    return SERVICES[name]["logs"] / "stack.pid.json"


def process_module():
    try:
        import psutil
        return psutil
    except ImportError as exc:
        raise RuntimeError("Missing psutil. Run setup.bat first.") from exc


def owned_process(name: str):
    """A PID alone is insufficient: confirm identity, birth time and checkout."""
    psutil = process_module()
    try:
        state = json.loads(state_file(name).read_text(encoding="utf-8"))
        process = psutil.Process(int(state["pid"]))
        service = SERVICES[name]
        if abs(process.create_time() - float(state["created"])) > 0.01:
            return None
        if Path(process.exe()).resolve() != Path(state["python"]).resolve():
            return None
        if Path(process.cwd()).resolve() != service["cwd"].resolve():
            return None
        scripts = [Path(arg).resolve() for arg in process.cmdline()[1:] if arg.endswith(".py")]
        if service["script"].resolve() not in scripts:
            return None
        return process
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        return None


def environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("no_proxy", "NO_PROXY"):
        env[key] = env.get(key, "").rstrip(",") + ",127.0.0.1,localhost,::1,"
    env.setdefault("BOT_DATA_DIR", str(ROOT / "local-data"))
    env.setdefault("MAIBOT_ROOT", str(BOT))
    env["PYTHONUTF8"] = "1"
    # Configure external QQ/OneBot manually; do not inject into another account.
    env["QQBOT_SNOWLUMA_WATCHDOG"] = "0"
    return env


def interpreter(name: str) -> Path:
    return Path(os.environ.get("BOT_PYTHON", str(VENV_PYTHON))) if name == "bot" else VENV_PYTHON


def preflight(names: list[str]) -> None:
    process_module()
    for name in names:
        if owned_process(name):
            continue
        service = SERVICES[name]
        if tcp_open(service["port"]):
            raise RuntimeError(f"{name}: port {service['port']} is occupied. Nothing on that port will be stopped.")
        if not interpreter(name).is_file():
            raise RuntimeError(f"Missing Python: {interpreter(name)}. Run setup.bat.")
        if not service["script"].is_file():
            raise RuntimeError(f"Missing source: {service['script']}")
        if name == "monitor" and not (service["cwd"] / "config/config.win.json").is_file():
            raise RuntimeError("Monitor config is missing. Run tools/setup.py first.")
        if name == "bot":
            for config in ("bot_config.toml", "model_config.toml"):
                if not (service["cwd"] / "config" / config).is_file():
                    raise RuntimeError(f"Missing MaiBot config/{config}. Follow its source setup guide.")


def start(name: str) -> None:
    if owned_process(name):
        print(f"{name}: already started by this checkout")
        return
    service = SERVICES[name]
    service["logs"].mkdir(parents=True, exist_ok=True)
    command = [str(interpreter(name)), "-u", str(service["script"]), *service["args"]]
    options = dict(cwd=str(service["cwd"]), env=environment(), stdin=subprocess.DEVNULL)
    with (service["logs"] / service["log"]).open("ab", buffering=0) as log:
        options.update(stdout=log, stderr=subprocess.STDOUT)
        if os.name == "nt":
            base_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            try:
                process = subprocess.Popen(command, creationflags=base_flags | subprocess.CREATE_BREAKAWAY_FROM_JOB, **options)
            except OSError as exc:
                if exc.winerror != 5:
                    raise
                process = subprocess.Popen(command, creationflags=base_flags, **options)
        else:
            process = subprocess.Popen(command, start_new_session=True, **options)
    psutil = process_module()
    try:
        identity = psutil.Process(process.pid)
    except psutil.NoSuchProcess as exc:
        raise RuntimeError(f"{name}: exited during startup; see {service['logs'] / service['log']}") from exc
    state = {"pid": process.pid, "created": identity.create_time(), "python": identity.exe()}
    target = state_file(name)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state), encoding="utf-8")
    temporary.replace(target)
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name}: exited ({process.returncode}); see {service['logs'] / service['log']}")
        if tcp_open(service["port"]):
            print(f"{name}: running, PID {process.pid}, port {service['port']}")
            return
        time.sleep(0.25)
    print(f"{name}: process started, port not ready yet; see {service['logs'] / service['log']}")


def stop(name: str) -> None:
    psutil = process_module()
    process = owned_process(name)
    if not process:
        print(f"{name}: no verified process owned by this checkout; nothing stopped")
        return
    # Only this verified process and its descendants, never an unrelated listener.
    children = []
    # The panel may invoke this stop worker as its own child. Keep this worker
    # and its subprocesses alive so stopping the panel can finish cleanly.
    protected_pids = {os.getpid()}
    try:
        protected_pids.update(child.pid for child in psutil.Process(os.getpid()).children(recursive=True))
    except psutil.Error:
        pass
    try:
        descendants = process.children(recursive=True)
    except psutil.NoSuchProcess:
        print(f"{name}: process already exited")
        state_file(name).unlink(missing_ok=True)
        return
    for child in descendants:
        try:
            # Panel can open external applications. They are never service children
            # to manage, even if their ancestry happens to include the panel.
            if (child.pid not in protected_pids
                    and Path(child.exe()).name.lower().startswith("python")
                    and Path(child.cwd()).resolve().is_relative_to(ROOT)):
                children.append(child)
        except psutil.Error:
            continue
    try:
        process.terminate()
    except psutil.NoSuchProcess:
        pass
    for child in children:
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    _, alive = psutil.wait_procs([process, *children], timeout=6)
    for remaining in alive:
        try:
            remaining.kill()
        except psutil.NoSuchProcess:
            pass
    state_file(name).unlink(missing_ok=True)
    print(f"{name}: stopped")


def status(name: str) -> None:
    service = SERVICES[name]
    process = owned_process(name)
    port = "listening" if tcp_open(service["port"]) else "closed"
    owner = f"owned PID {process.pid}" if process else "no verified owned process"
    print(f"{name}: {owner}; 127.0.0.1:{service['port']} {port}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "status"))
    choices = ("all", "monitor", "panel", "bot", "maibot")
    parser.add_argument("service", nargs="?", choices=choices)
    parser.add_argument("--service", dest="service_option", choices=choices)
    bot_group = parser.add_mutually_exclusive_group()
    bot_group.add_argument("--with-bot", action="store_true", help="Include configured MaiBot when service is all")
    bot_group.add_argument("--without-bot", action="store_true", help="Start monitor and panel only (default)")
    args = parser.parse_args()
    chosen = args.service_option or args.service or "all"
    if chosen == "maibot":
        chosen = "bot"
    names = ["monitor", "panel"] + (["bot"] if args.with_bot else []) if chosen == "all" else [chosen]
    # Stop/status includes an optional bot already started by this checkout.
    if chosen == "all" and args.action != "start" and not args.without_bot and "bot" not in names:
        names.append("bot")
    try:
        if args.action == "start":
            preflight(names)
        # A stop requested by the panel must finish other services first.
        ordered = [name for name in ("bot", "monitor", "panel") if name in names] if args.action == "stop" else names
        for name in ordered:
            {"start": start, "stop": stop, "status": status}[args.action](name)
        return 0
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
