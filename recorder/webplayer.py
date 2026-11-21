"""크롬 새 창으로 열리는 웹 재생기 제어.

학습하기 → 재생 창(새 창) 열림 → F11 전체화면 → (녹화 시작) → [시작] 클릭
→ 영상 끝 알림("강의영상이 완료 되었습니다. 창을 닫으시겠습니까?") → 확인 → 끝
"""
from __future__ import annotations

import logging
import time

from .browser import Browser

log = logging.getLogger(__name__)

VIDEO_JS = """() => Array.from(document.querySelectorAll('video')).map(v => ({
  t: v.currentTime || 0, d: isFinite(v.duration) ? v.duration : 0, ended: v.ended, paused: v.paused }))"""

START_JS = r"""
(texts) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = el => norm(el.innerText || el.value || el.getAttribute('alt') || el.getAttribute('title') || el.getAttribute('aria-label') || '');
  const visible = el => { const r = el.getBoundingClientRect(); const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
  document.querySelectorAll('[data-rec-start]').forEach(el => el.removeAttribute('data-rec-start'));
  for (const want of texts) {
    let c = Array.from(document.querySelectorAll('a, button, input[type=button], input[type=submit], img, [onclick], [role=button], span, div'))
      .filter(el => { const t = textOf(el); return t === want || (t.includes(want) && t.length <= want.length + 6); });
    c = c.filter(el => !c.some(o => o !== el && el.contains(o))).filter(visible);
    if (c.length) { c[0].setAttribute('data-rec-start', '1'); return textOf(c[0]); }
  }
  return null;
}
"""


class PlaybackBlocked(Exception):
    """녹화 프로그램 감지 등으로 재생이 막힘 → 전체 중단."""


class WebPlayer:
    def __init__(self, br: Browser, cfg: dict):
        self.br = br
        self.cfg = cfg
        self.same_tab = False

    # ── 재생 창 잡기 ─────────────────────────────────────────
    def wait_open(self, before: list, list_url: str):
        """학습하기 클릭 뒤 새로 열린 창(또는 같은 탭에서 바뀐 페이지)을 돌려준다."""
        deadline = time.time() + float(self.cfg.get("appear_timeout_sec", 30))
        main = self.br.page
        while time.time() < deadline:
            self.br.wait(500)
            self._check_events(during_start=True)
            new = [p for p in self.br.pages() if p not in before]
            if new:
                page = new[-1]
                self.same_tab = False
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                log.info("재생 창 열림: %s", page.url)
                return page
            if main.url not in (list_url, "about:blank") and not main.url.startswith(list_url.split("?")[0]):
                self.same_tab = True
                try:
                    main.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                log.info("재생 화면이 같은 탭에서 열림: %s", main.url)
                return main
        return None

    def is_player(self, page, timeout: float = 8) -> bool:
        """영상 요소나 [시작] 버튼이 있거나, 주소가 재생 페이지 주소면 재생 화면으로 본다."""
        pats = self.cfg.get("player_url_patterns") or []
        texts = self.cfg.get("start_button_texts") or ["시작"]
        deadline = time.time() + timeout
        while time.time() < deadline and not page.is_closed():
            if any(p in page.url for p in pats):
                return True
            if self._videos(page):
                return True
            for frame in page.frames:
                try:
                    if frame.evaluate(START_JS, texts):
                        return True
                except Exception:
                    pass
            self.br.wait(700)
        return False

    # ── 전체화면 ─────────────────────────────────────────────
    def _window_state(self, page, state: str) -> bool:
        try:
            cdp = page.context.new_cdp_session(page)
            win = cdp.send("Browser.getWindowForTarget")
            wid = win["windowId"]
            if state == "fullscreen" and win["bounds"].get("windowState") != "normal":
                cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": state}})
            cdp.detach()
            return True
        except Exception as e:
            log.debug("창 상태 변경 실패(%s): %s", state, e)
            return False

    def make_fullscreen(self, page) -> None:
        mode = self.cfg.get("window_mode", "f11")
        page.bring_to_front()
        if mode == "f11":
            if not self._window_state(page, "fullscreen"):
                # 예비: 실제 F11 키 입력
                from . import winutil
                winutil.press("F11")
            log.info("전체화면 (F11)")
        elif mode == "maximize":
            self._window_state(page, "maximized")
        self.br.wait(int(float(self.cfg.get("fullscreen_settle_sec", 4)) * 1000))
        try:
            full = page.evaluate("() => [innerWidth, innerHeight, screen.width, screen.height]")
            if mode == "f11" and (full[0] < full[2] or full[1] < full[3]):
                log.warning("전체화면이 확인되지 않습니다 (창 %sx%s / 화면 %sx%s)", *full)
        except Exception:
            pass

    def exit_fullscreen(self, page) -> None:
        if page and not page.is_closed():
            self._window_state(page, "normal")
            self._window_state(page, "maximized")

    # ── 시작 버튼 ───────────────────────────────────────────
    def click_start(self, page) -> bool:
        texts = self.cfg.get("start_button_texts") or ["시작"]
        deadline = time.time() + float(self.cfg.get("start_button_timeout_sec", 20))
        while time.time() < deadline and not page.is_closed():
            for frame in page.frames:
                try:
                    found = frame.evaluate(START_JS, texts)
                except Exception:
                    continue
                if found:
                    try:
                        frame.locator('[data-rec-start="1"]').first.click(timeout=5000)
                        log.info("'%s' 버튼 클릭 → 재생 시작", found)
                        return True
                    except Exception as e:
                        log.debug("시작 버튼 클릭 실패: %s", e)
            if self._playing(page):
                log.info("시작 버튼 없이 이미 재생 중입니다")
                return True
            self.br.wait(700)
        log.warning("시작 버튼을 찾지 못했습니다 (자동 재생으로 보고 계속 진행)")
        return False

    # ── 영상 상태 ───────────────────────────────────────────
    @staticmethod
    def _videos(page) -> list[dict]:
        out = []
        for frame in page.frames:
            try:
                out.extend(frame.evaluate(VIDEO_JS))
            except Exception:
                pass
        return out

    def _playing(self, page) -> bool:
        return any(not v["paused"] and v["t"] > 0 for v in self._videos(page))

    def _check_events(self, during_start: bool = False) -> str | None:
        for action, msg in self.br.take_events():
            if action == "error":
                raise PlaybackBlocked(msg)
            if action == "end" and not during_start:
                return "end"
        return None

    # ── 끝날 때까지 기다리기 ─────────────────────────────────
    def wait_finish(self, page, max_sec: float) -> str:
        """'end' (완료 알림) / 'closed' (창 닫힘) / 'ended' (영상 끝) / 'timeout'"""
        start = time.time()
        last_report = start
        check_video = self.cfg.get("end_on_video_ended", True)
        n = 0
        while True:
            self.br.wait(1000)
            n += 1
            if self._check_events() == "end":
                return "end"
            if page.is_closed():
                return "closed"
            if check_video and n % 3 == 0:
                vids = self._videos(page)
                if vids and all(v["ended"] for v in vids):
                    self.br.wait(3000)          # 완료 알림이 곧 뜰 수 있으니 잠깐 기다림
                    return "end" if self._check_events() == "end" else "ended"
            now = time.time()
            if now - start > max_sec:
                return "timeout"
            if now - last_report >= 300:
                vids = self._videos(page) if not page.is_closed() else []
                pos = f" (영상 {int(vids[0]['t'] // 60)}/{int(vids[0]['d'] // 60)}분)" if vids and vids[0]["d"] else ""
                log.info("  녹화 중… %d분 경과%s", (now - start) // 60, pos)
                last_report = now

    # ── 정리 ────────────────────────────────────────────────
    def close(self, page) -> None:
        if page is None:
            return
        if self.same_tab:
            self.exit_fullscreen(page)
            return
        if not page.is_closed():
            log.info("재생 창 닫기")
            try:
                page.close()
            except Exception:
                pass
