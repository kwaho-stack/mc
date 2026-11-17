"""Kollus 재생창 찾기 · 전체화면 · 알림창 처리 · 종료 감지 · 닫기."""
from __future__ import annotations

import logging
import re
import time

from . import winutil
from .winutil import Win

log = logging.getLogger(__name__)

MIN_PLAYER_AREA = 480 * 270
# 제목에 'Kollus' 가 들어가도 재생창으로 보면 안 되는 프로그램들
DEFAULT_EXCLUDE = ["chrome.exe", "msedge.exe", "whale.exe", "obs64.exe", "python.exe",
                   "pythonw.exe", "py.exe", "explorer.exe", "cmd.exe", "windowsterminal.exe",
                   "snippingtool.exe"]


class PlaybackBlocked(Exception):
    """녹화 프로그램 감지 등으로 재생이 막힘 → 전체 중단."""


def _clean_button(text: str) -> str:
    # '예(&Y)', '&OK' 같은 단축키 표시 제거
    return re.sub(r"\(&?\w\)|&", "", text or "").strip()


def dialog_texts(hwnd: int) -> tuple[str, list]:
    """알림창 안의 글자와 버튼 목록. win32 방식으로 먼저 읽고, 부족하면 UIA 로 읽는다."""
    from pywinauto import Desktop

    texts: list[str] = []
    buttons: list = []
    for backend in ("win32", "uia"):
        try:
            w = Desktop(backend=backend).window(handle=hwnd)
            texts = [w.window_text()]
            buttons = []
            for c in w.descendants():
                t = c.window_text()
                if t:
                    texts.append(t)
                ctype = c.friendly_class_name()
                if ctype == "Button":
                    buttons.append(c)
            if len(texts) > 1:
                break
        except Exception as e:
            log.debug("알림창 읽기 실패(%s): %s", backend, e)
    return " ".join(texts), buttons


def press_button(buttons: list, names: list[str]) -> str | None:
    for want in names:
        for b in buttons:
            if _clean_button(b.window_text()) == want:
                try:
                    if hasattr(b, "invoke"):
                        b.invoke()
                    else:
                        b.click()
                except Exception:
                    b.click_input()
                return want
    return None


class KollusPlayer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.procs = [s.lower() for s in cfg.get("process_names", ["kollus"])]
        self.titles = [s.lower() for s in cfg.get("window_title_patterns", ["kollus"])]
        self.exclude = {s.lower() for s in cfg.get("exclude_processes", DEFAULT_EXCLUDE)}
        self.rules = [
            {**r, "_re": re.compile(r["match"], re.I)} for r in cfg.get("dialogs", [])
        ]
        self.pids: set[int] = set()
        self.main: Win | None = None
        self._handled: dict[int, float] = {}

    # ── 찾기 ────────────────────────────────────────────────
    def _match(self, w: Win) -> bool:
        if w.proc.lower() in self.exclude:
            return False
        if w.pid in self.pids:
            return True
        p, t = w.proc.lower(), w.title.lower()
        return any(s in p for s in self.procs) or any(s and s in t for s in self.titles)

    def windows(self) -> list[Win]:
        return [w for w in winutil.list_windows() if self._match(w)]

    @staticmethod
    def _is_dialog(w: Win, ref: int) -> bool:
        return w.cls == "#32770" or w.area < MIN_PLAYER_AREA or w.area < ref * 0.5

    def split(self) -> tuple[list[Win], list[Win]]:
        """(재생창들, 알림창들). 처음 찾은 재생창 크기를 기준으로 작은 창은 알림창으로 본다."""
        ws = self.windows()
        ref = max([w.area for w in ws] + [self.main.area if self.main else 0])
        mains = [w for w in ws if not self._is_dialog(w, ref)]
        dialogs = [w for w in ws if self._is_dialog(w, ref) and w.area > 0]
        return mains, dialogs

    def wait_appear(self, timeout: float) -> Win | None:
        self.pids.clear()
        self.main = None
        self._handled.clear()
        deadline = time.time() + timeout
        while time.time() < deadline:
            mains, dialogs = self.split()
            self.handle_dialogs(dialogs)
            if mains:
                self.main = max(mains, key=lambda w: w.area)
                self.pids = {self.main.pid}
                log.info("재생창 발견: %s", self.main)
                return self.main
            time.sleep(1)
        return None

    # ── 화면 ────────────────────────────────────────────────
    def make_fullscreen(self) -> None:
        if not self.main:
            return
        mode = self.cfg.get("window_mode", "key")
        time.sleep(float(self.cfg.get("fullscreen_delay_sec", 2)))
        winutil.park_cursor()
        mains, _ = self.split()
        if mode != "none" and any(w.covers_screen() for w in mains):
            log.info("이미 전체화면입니다")
            return
        hwnd = self.main.hwnd
        winutil.focus(hwnd)
        if mode == "maximize":
            winutil.maximize(hwnd)
        elif mode == "key":
            key = self.cfg.get("fullscreen_key", "F11")
            log.info("전체화면: %s 키", key)
            winutil.press(key)
        elif mode == "doubleclick":
            l, t, r, b = self.main.rect
            winutil.mouse_click((l + r) // 2, (t + b) // 2, double=True)
        winutil.park_cursor()
        time.sleep(1.5)
        mains, _ = self.split()
        if mode in ("key", "doubleclick") and not any(w.covers_screen() for w in mains):
            log.warning("전체화면이 확인되지 않습니다 (재생창 크기: %s)",
                        ", ".join(f"{w.width}x{w.height}" for w in mains) or "없음")

    # ── 알림창 ──────────────────────────────────────────────
    def handle_dialogs(self, dialogs: list[Win]) -> str | None:
        """규칙에 맞는 알림창을 처리. 'end' 규칙에 걸리면 'end' 를 돌려준다."""
        result = None
        now = time.time()
        for d in dialogs:
            if now - self._handled.get(d.hwnd, 0) < 3:
                continue
            self._handled[d.hwnd] = now
            text, buttons = dialog_texts(d.hwnd)
            if not text.strip():
                continue
            for rule in self.rules:
                if not rule["_re"].search(text):
                    continue
                log.info("알림창: %s", text[:200])
                if rule.get("action") == "error":
                    raise PlaybackBlocked(text[:300])
                clicked = press_button(buttons, rule.get("click", []))
                if clicked:
                    log.info("  → '%s' 클릭", clicked)
                if rule.get("action") == "end":
                    result = "end"
                break
            else:
                log.info("알림창(규칙 없음, 그대로 둠): %s", text[:200])
        return result

    # ── 종료 감지 ───────────────────────────────────────────
    def wait_finish(self, max_sec: float) -> str:
        """'closed' (재생창이 닫힘) / 'end' (종료 알림) / 'timeout'"""
        start = time.time()
        gone = 0
        last_report = start
        while True:
            mains, dialogs = self.split()
            if self.handle_dialogs(dialogs) == "end":
                return "end"
            if mains:
                gone = 0
            else:
                gone += 1
                if gone >= 3:
                    return "closed"
            now = time.time()
            if now - start > max_sec:
                return "timeout"
            if now - last_report >= 300:
                log.info("  녹화 중… %d분 경과", (now - start) // 60)
                last_report = now
            time.sleep(1)

    # ── 닫기 ────────────────────────────────────────────────
    def close(self) -> None:
        mains, dialogs = self.split()
        if not mains and not dialogs:
            return
        log.info("재생창 닫는 중")
        for w in mains:
            winutil.close_window(w.hwnd)
        deadline = time.time() + float(self.cfg.get("close_wait_sec", 15))
        while time.time() < deadline:
            mains, dialogs = self.split()
            try:
                self.handle_dialogs(dialogs)
            except PlaybackBlocked:
                pass
            if not mains:
                for w in dialogs:
                    winutil.close_window(w.hwnd)
                return
            time.sleep(1)
        if self.cfg.get("kill_if_stuck", True) and self.pids:
            log.warning("재생창이 닫히지 않아 강제 종료합니다 (pid %s)", self.pids)
            winutil.kill_pids(self.pids)
            time.sleep(2)
