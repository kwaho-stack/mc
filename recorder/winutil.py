"""Windows 기본 기능: 창 목록, 키/마우스 입력, 절전 방지."""
from __future__ import annotations

import ctypes
import time
from dataclasses import dataclass

import psutil
import win32api
import win32con
import win32gui
import win32process

user32 = ctypes.windll.user32


def set_dpi_aware() -> None:
    """화면 배율(125%, 150%)과 상관없이 실제 픽셀 좌표를 쓰도록 설정."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def keep_awake(on: bool = True) -> None:
    """녹화 중 절전/화면 꺼짐 방지."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x1, 0x2
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0)
    ctypes.windll.kernel32.SetThreadExecutionState(flags)


def screen_size() -> tuple[int, int]:
    return win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)


@dataclass
class Win:
    hwnd: int
    title: str
    cls: str
    pid: int
    proc: str
    rect: tuple[int, int, int, int]

    @property
    def width(self) -> int:
        return self.rect[2] - self.rect[0]

    @property
    def height(self) -> int:
        return self.rect[3] - self.rect[1]

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    def covers_screen(self) -> bool:
        sw, sh = screen_size()
        l, t, r, b = self.rect
        return l <= 0 and t <= 0 and r >= sw and b >= sh

    def __str__(self) -> str:
        return f"[{self.proc} pid={self.pid}] '{self.title}' class={self.cls} {self.width}x{self.height}"


_proc_cache: dict[int, str] = {}


def proc_name(pid: int) -> str:
    name = _proc_cache.get(pid)
    if name is None:
        try:
            name = psutil.Process(pid).name()
        except Exception:
            name = "?"
        _proc_cache[pid] = name
    return name


def list_windows() -> list[Win]:
    out: list[Win] = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            rect = win32gui.GetWindowRect(hwnd)
            out.append(Win(hwnd, win32gui.GetWindowText(hwnd), win32gui.GetClassName(hwnd),
                           pid, proc_name(pid), rect))
        except Exception:
            pass
        return True

    win32gui.EnumWindows(cb, None)
    return out


def window_alive(hwnd: int) -> bool:
    return bool(win32gui.IsWindow(hwnd) and win32gui.IsWindowVisible(hwnd))


def focus(hwnd: int) -> None:
    """창을 맨 앞으로. (Alt 키를 살짝 눌러야 Windows 가 포커스 이동을 허락함)"""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass
    time.sleep(0.3)


def maximize(hwnd: int) -> None:
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)


def close_window(hwnd: int) -> None:
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception:
        pass


_KEYS = {
    "enter": 0x0D, "space": 0x20, "esc": 0x1B, "escape": 0x1B, "tab": 0x09,
    "home": 0x24, "end": 0x23, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "win": 0x5B, "shift": 0x10, "ctrl": 0x11, "alt": 0x12,
}


def vk(name: str) -> int:
    n = name.strip().lower()
    if n in _KEYS:
        return _KEYS[n]
    if n.startswith("f") and n[1:].isdigit() and 1 <= int(n[1:]) <= 24:
        return 0x70 + int(n[1:]) - 1
    if len(n) == 1:
        return ord(n.upper())
    raise ValueError(f"알 수 없는 키: {name}")


def press(*names: str) -> None:
    """키 조합 누르기. 예: press('F11'), press('win', 'shift', 'r')"""
    codes = [vk(n) for n in names]
    for c in codes:
        win32api.keybd_event(c, 0, 0, 0)
        time.sleep(0.03)
    for c in reversed(codes):
        win32api.keybd_event(c, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.03)


def mouse_move(x: int, y: int) -> None:
    win32api.SetCursorPos((int(x), int(y)))


def mouse_click(x: int, y: int, double: bool = False) -> None:
    mouse_move(x, y)
    for _ in range(2 if double else 1):
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
        time.sleep(0.05)


def mouse_drag(x1: int, y1: int, x2: int, y2: int, steps: int = 20) -> None:
    mouse_move(x1, y1)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    for i in range(1, steps + 1):
        mouse_move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        time.sleep(0.02)
    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def park_cursor() -> None:
    """녹화에 마우스가 보이지 않게 화면 오른쪽 아래 구석으로."""
    w, h = screen_size()
    mouse_move(w - 1, h - 1)


def kill_pids(pids: set[int]) -> None:
    for pid in pids:
        try:
            psutil.Process(pid).kill()
        except Exception:
            pass
