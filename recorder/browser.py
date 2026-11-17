"""크롬 제어: 로그인 유지, 차시 목록 읽기, '학습하기' 클릭."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

# 페이지(및 iframe) 안에서 '학습하기' 버튼과 그 버튼이 속한 차시 줄을 찾는 스크립트.
# 버튼마다 data-rec-idx 를 붙여 두고 나중에 그 표시로 클릭한다.
SCAN_JS = r"""
({texts, rowSel, titleSel, base}) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = el => norm(el.innerText || el.value || el.getAttribute('alt') || el.getAttribute('title') || '');
  const visible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const hit = t => texts.some(x => t === x || (t.includes(x) && t.length <= x.length + 12));

  document.querySelectorAll('[data-rec-idx]').forEach(el => el.removeAttribute('data-rec-idx'));

  let cands = Array.from(document.querySelectorAll(
      'a, button, input[type=button], input[type=submit], input[type=image], img, [onclick], [role=button], span, div, td'))
    .filter(el => hit(textOf(el)));
  // 버튼 안쪽 요소만 남김 (바깥 div 등 제외)
  cands = cands.filter(el => !cands.some(o => o !== el && el.contains(o)));
  cands = cands.filter(visible);

  const countIn = p => cands.filter(c => p.contains(c)).length;
  const rowOf = el => {
    if (rowSel) return el.closest(rowSel) || el;
    const tl = el.closest('tr, li');
    if (tl && countIn(tl) === 1) return tl;
    let row = el;
    while (row.parentElement && row.parentElement !== document.body && countIn(row.parentElement) === 1) {
      row = row.parentElement;
    }
    return row;
  };
  const isNoise = t => !t || hit(t) || /^[\d\s.:%\/\-~()분초시간]+$/.test(t);
  const titleOf = (row, btn) => {
    if (titleSel) {
      const t = row.querySelector(titleSel);
      if (t) return textOf(t);
    }
    let parts;
    if (row.tagName === 'TR') {
      parts = Array.from(row.cells).filter(c => !c.contains(btn)).map(textOf);
    } else {
      parts = (row.innerText || '').split('\n').map(norm);
    }
    parts = parts.filter(t => !isNoise(t));
    parts.sort((a, b) => b.length - a.length);
    return parts[0] || textOf(row);
  };

  return cands.map((el, i) => {
    const idx = base + i;
    el.setAttribute('data-rec-idx', String(idx));
    const row = rowOf(el);
    return { idx, button: textOf(el), title: titleOf(row, el), rowText: norm(row.innerText) };
  });
}
"""


@dataclass
class Lesson:
    number: int          # 목록에서의 순서 (1부터)
    title: str
    row_text: str
    button: str
    completed: bool
    key: str = ""
    frame: object = field(default=None, repr=False)
    idx: int = -1


class Browser:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.list_url: str = cfg["list_url"]
        self.lcfg = cfg.get("lessons", {})
        self.bcfg = cfg.get("browser", {})
        self._pw = None
        self.context = None
        self.page = None

    # ── 시작 / 종료 ──────────────────────────────────────────
    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        if self.bcfg.get("mode") == "cdp":
            browser = self._pw.chromium.connect_over_cdp(self.bcfg.get("cdp_url", "http://127.0.0.1:9222"))
            self.context = browser.contexts[0] if browser.contexts else browser.new_context()
            self.page = next((p for p in self.context.pages if "inzeum" in p.url), None)
        else:
            profile = self.cfg.path(self.bcfg.get("profile_dir", "./chrome-profile"))
            profile.mkdir(parents=True, exist_ok=True)
            self.context = self._pw.chromium.launch_persistent_context(
                str(profile),
                channel="chrome",
                headless=False,
                no_viewport=True,
                ignore_default_args=["--enable-automation"],
                args=["--start-maximized"],
            )
            self.page = self.context.pages[0] if self.context.pages else None
        if self.page is None:
            self.page = self.context.new_page()
        self.context.on("page", self._watch_page)
        for p in self.context.pages:
            self._watch_page(p)
        return self

    def __exit__(self, *exc):
        try:
            if self.bcfg.get("mode") != "cdp" and self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()

    @staticmethod
    def _watch_page(page):
        def on_dialog(d):
            log.info("웹 알림창: %s → 확인", d.message.replace("\n", " "))
            try:
                d.accept()
            except Exception:
                pass

        page.on("dialog", on_dialog)

    # ── 목록 ────────────────────────────────────────────────
    def open_list(self) -> None:
        self.page.bring_to_front()
        self.page.goto(self.list_url, wait_until="domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    def scan(self) -> list[Lesson]:
        texts = self.lcfg.get("study_button_texts") or ["학습하기"]
        patterns = [re.compile(p) for p in self.lcfg.get("completed_patterns", [])]
        lessons: list[Lesson] = []
        base = 0
        for frame in self.page.frames:
            try:
                items = frame.evaluate(SCAN_JS, {
                    "texts": texts,
                    "rowSel": self.lcfg.get("row_selector") or "",
                    "titleSel": self.lcfg.get("title_selector") or "",
                    "base": base,
                })
            except Exception as e:  # 다른 도메인 iframe 등
                log.debug("frame 스캔 실패 %s: %s", frame.url, e)
                continue
            base += len(items)
            for it in items:
                row = it["rowText"]
                done = any(p.search(row) for p in patterns)
                lessons.append(Lesson(
                    number=len(lessons) + 1,
                    title=it["title"] or f"{len(lessons) + 1}차시",
                    row_text=row,
                    button=it["button"],
                    completed=done,
                    frame=frame,
                    idx=it["idx"],
                ))
        # 같은 제목이 있으면 key 를 구분
        seen: dict[str, int] = {}
        for ls in lessons:
            seen[ls.title] = seen.get(ls.title, 0) + 1
            ls.key = ls.title if seen[ls.title] == 1 else f"{ls.title}#{seen[ls.title]}"
        return lessons

    def ensure_list(self) -> list[Lesson]:
        """목록을 열고, 차시가 안 보이면 사용자가 로그인/이동할 때까지 기다린다."""
        self.open_list()
        while True:
            lessons = self.scan()
            if lessons:
                if self.page.url != self.list_url:
                    log.info("목록 주소: %s", self.page.url)
                    self.list_url = self.page.url
                return lessons
            print()
            print("차시 목록(학습하기 버튼)을 찾지 못했습니다.")
            print("열린 크롬 창에서 로그인하고, 녹화할 강좌의 차시 목록 화면까지 이동한 뒤")
            input("여기서 Enter 를 누르세요 (그만두려면 Ctrl+C) > ")
            self.page = self._active_page()

    def _active_page(self):
        pages = [p for p in self.context.pages if not p.is_closed()]
        for p in reversed(pages):
            if "inzeum" in p.url:
                return p
        return pages[-1] if pages else self.context.new_page()

    def refresh(self) -> list[Lesson]:
        self.open_list()
        return self.scan()

    def click(self, lesson: Lesson) -> None:
        self.page.bring_to_front()
        loc = lesson.frame.locator(f'[data-rec-idx="{lesson.idx}"]')
        loc.scroll_into_view_if_needed(timeout=5000)
        loc.click(timeout=10000)

    # ── 정리 ────────────────────────────────────────────────
    def pages(self) -> list:
        return [p for p in self.context.pages if not p.is_closed()]

    def close_new_pages(self, before: list) -> None:
        for p in self.pages():
            if p not in before and p is not self.page:
                try:
                    p.close()
                except Exception:
                    pass

    def dump_html(self, folder: Path) -> list[Path]:
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for i, frame in enumerate(self.page.frames):
            try:
                html = frame.content()
            except Exception:
                continue
            path = folder / f"list_frame{i}.html"
            path.write_text(f"<!-- {frame.url} -->\n{html}", encoding="utf-8")
            out.append(path)
        return out
