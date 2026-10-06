"""Open URLs as separate browser windows tiled across the screen (Windows).

Each URL launches in its own Chromium window; the newly-created windows are
then snapped into a grid via Win32 so they're all visible at once. Existing
browser windows are left untouched.
"""

import ctypes
import math
import os
import subprocess
import time
import webbrowser
from ctypes import wintypes

user32 = ctypes.windll.user32

BROWSER_CLASS = "Chrome_WidgetWin_1"  # Chrome and Edge top-level window class

_opened: list = []  # article/page windows (closed on a new lookup)
_music: list = []   # music/video windows (kept alive across lookups)


def _close_list(handles: list) -> int:
    WM_CLOSE = 0x0010
    count = 0
    for hwnd in handles:
        if user32.IsWindow(hwnd):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            count += 1
    handles.clear()
    return count


def close_all() -> int:
    """Close every window Jarvis opened — pages and music alike."""
    return _close_list(_opened) + _close_list(_music)


def close_pages() -> int:
    """Close only article/page windows (used when a new lookup starts)."""
    return _close_list(_opened)


def _open_tracked(url: str, track: list) -> bool:
    """Open one URL in its own window and remember its handle. Returns success."""
    browser = find_browser()
    if not browser:
        webbrowser.open_new_tab(url)  # untracked fallback
        return False
    before = _browser_windows()
    subprocess.Popen([browser, "--new-window", url])
    for _ in range(15):
        time.sleep(0.3)
        new = list(_browser_windows() - before)
        if new:
            track.extend(new)
            return True
    return True  # opened, just couldn't grab the handle in time


def open_music(url: str) -> bool:
    return _open_tracked(url, _music)


def find_browser() -> str | None:
    candidates = [
        os.path.expandvars(p) for p in (
            r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
            r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        )
    ]
    return next((p for p in candidates if os.path.exists(p)), None)


def _browser_windows() -> set:
    """Handles of visible, titled browser top-level windows."""
    found = set()

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindowTextLengthW(hwnd) == 0:
            return True
        buff = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buff, 256)
        if buff.value == BROWSER_CLASS:
            found.add(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found


def _work_area() -> tuple:
    rect = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top


def _tile(hwnds: list) -> None:
    n = len(hwnds)
    if not n:
        return
    wx, wy, ww, wh = _work_area()
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    cw, ch = ww // cols, wh // rows
    SW_RESTORE = 9
    SWP_SHOWWINDOW = 0x0040
    for i, hwnd in enumerate(hwnds):
        c, r = i % cols, i // cols
        # last row may have fewer windows — stretch them to fill the width
        in_row = min(cols, n - r * cols)
        cell_w = ww // in_row if r == rows - 1 else cw
        x = wx + (c * cell_w if r == rows - 1 else c * cw)
        y = wy + r * ch
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetWindowPos(hwnd, 0, x, y, cell_w, ch, SWP_SHOWWINDOW)


def open_tiled(urls: list) -> bool:
    """Open each URL in its own window, then tile the new windows. Returns
    True if tiling ran, False if no browser was found (caller should fall back)."""
    browser = find_browser()
    if not browser:
        return False

    close_pages()  # clear the previous lookup's page windows (keep music)
    time.sleep(0.3)

    before = _browser_windows()
    for u in urls:
        subprocess.Popen([browser, "--new-window", u])
        time.sleep(1.0)

    # wait for the new windows to appear
    new: list = []
    for _ in range(20):
        time.sleep(0.4)
        new = list(_browser_windows() - before)
        if len(new) >= len(urls):
            break
    _tile(new)
    _opened[:] = new  # remember these so we can close them later
    return True
