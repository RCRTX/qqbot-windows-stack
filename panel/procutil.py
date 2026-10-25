"""QQ bot stack component."""








from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess

k32 = ctypes.windll.kernel32

TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wt.DWORD),
        ("cntUsage", wt.DWORD),
        ("th32ProcessID", wt.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wt.DWORD),
        ("cntThreads", wt.DWORD),
        ("th32ParentProcessID", wt.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wt.DWORD),
        ("szExeFile", ctypes.c_wchar * 260),
    ]


def image_path(pid):
    """QQ bot stack component."""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value
        return None
    finally:
        k32.CloseHandle(h)


def creation_time(pid):
    """QQ bot stack component."""
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        c, e, k, u = (wt.FILETIME() for _ in range(4))
        if not k32.GetProcessTimes(h, ctypes.byref(c), ctypes.byref(e),
                                   ctypes.byref(k), ctypes.byref(u)):
            return None
        ticks = (c.dwHighDateTime << 32) | c.dwLowDateTime
        return ticks / 10_000_000 - 11644473600        
    finally:
        k32.CloseHandle(h)


def processes():
    """QQ bot stack component."""
    out = []
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = entry.th32ProcessID
            out.append((pid, entry.th32ParentProcessID, entry.szExeFile, image_path(pid)))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


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


def kill_tree(pid):
    """QQ bot stack component."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
        capture_output=True, timeout=30)
        return True
    except Exception:
        return False


def kill_by_path_mark(name, mark, exclude_pids=()):
    """QQ bot stack component."""
    hits = []
    for pid, _ppid, pname, path in processes():
        if pname.lower() != name.lower():
            continue
        if pid in exclude_pids:
            continue
        if path and mark.lower() in path.lower():
            kill_tree(pid)
            hits.append(pid)
    return hits
