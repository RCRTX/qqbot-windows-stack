"""QQ bot stack component."""









from __future__ import annotations

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def visible_window_titles():
    """QQ bot stack component."""
    out = []

    def cb(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            n = user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                out.append(buf.value)
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def any_window_title_contains(*needles):
    """QQ bot stack component."""
    if not needles:
        return False
    for t in visible_window_titles():
        low = t.lower()
        for n in needles:
            if n.lower() in low:
                return True
    return False
