"""크롬 제어: 로그인 유지, 주차 펼치기, 차시 목록 읽기, 완료 판단, '학습하기' 클릭."""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

# 페이지(및 iframe) 안에서
#   - 주차 제목(예: "(3주차) 마음근력훈련의 의미")  → data-rec-sec 표시
#   - '학습하기' 버튼과 그 버튼이 속한 차시 줄      → data-rec-idx 표시
# 을 찾아서 돌려준다. 접힌 주차 안의 버튼은 화면에 안 보이므로 제외된다.
SCAN_JS = r"""
({texts, rowSel, titleSel, secPattern, secSel, base}) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const textOf = el => norm(el.innerText || el.value || el.getAttribute('alt') || el.getAttribute('title') || '');
  const visible = el => {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
  };
  const hit = t => texts.some(x => t === x || (t.includes(x) && t.length <= x.length + 12));

  // 같은 블록 안의 글자는 띄어쓰기로 이어 붙인 덩어리들로 나눈다 ("3차시" + "호흡 명상" → "3차시 호흡 명상")
  const blockParts = (root, skip) => {
    const groups = new Map();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walker.nextNode())) {
      const t = norm(n.nodeValue);
      if (!t) continue;
      let p = n.parentElement;
      if (!p || p.closest('script, style, noscript') || (skip && skip.contains(p))) continue;
      if (!visible(p)) continue;
      while (p !== root && getComputedStyle(p).display.startsWith('inline')) p = p.parentElement;
      if (!groups.has(p)) groups.set(p, []);
      groups.get(p).push(t);
    }
    return Array.from(groups.values()).map(a => norm(a.join(' ')));
  };

  document.querySelectorAll('[data-rec-idx]').forEach(el => el.removeAttribute('data-rec-idx'));
  document.querySelectorAll('[data-rec-sec]').forEach(el => el.removeAttribute('data-rec-sec'));

  // ── 주차 제목 ──
  let heads = [];
  if (secSel) {
    heads = Array.from(document.querySelectorAll(secSel)).filter(visible);
  } else if (secPattern) {
    const re = new RegExp(secPattern);
    heads = Array.from(document.body.querySelectorAll('*'))
      .filter(el => !['SCRIPT', 'STYLE', 'OPTION'].includes(el.tagName) && re.test(el.textContent || ''));
    heads = heads.filter(el => !heads.some(o => o !== el && el.contains(o))).filter(visible);
    // 같은 제목이 여러 번 나오면(메뉴 등) 마지막 것만 사용
    const last = new Map();
    heads.forEach(h => last.set(norm(textOf(h)), h));
    heads = heads.filter(h => last.get(norm(textOf(h))) === h);
  }
  const headInfo = heads.map((h, i) => {
    h.setAttribute('data-rec-sec', String(i));
    return { sec: i, title: norm(textOf(h)).replace(/\s*\d+\s*분\s*$/, '') };
  });

  // ── 학습하기 버튼 ──
  let cands = Array.from(document.querySelectorAll(
      'a, button, input[type=button], input[type=submit], input[type=image], img, [onclick], [role=button], span, div, td'))
    .filter(el => hit(textOf(el)));
  cands = cands.filter(el => !cands.some(o => o !== el && el.contains(o)));
  cands = cands.filter(visible);

  const countIn = p => cands.filter(c => p.contains(c)).length;
  const rowOf = el => {
    if (rowSel) return el.closest(rowSel) || el;
    const tl = el.closest('tr, li');
    if (tl && countIn(tl) === 1) return tl;
    let row = el;
    while (row.parentElement && row.parentElement !== document.body && countIn(row.parentElement) === 1
           && !heads.some(h => row.parentElement.contains(h))) {
      row = row.parentElement;
    }
    return row;
  };
  // 숫자·시간·기호(⏰ 등)만 있는 덩어리는 제목 후보에서 뺀다
  const isNoise = t => !t || hit(t) || !t.replace(/\d+\s*(분|초|시간)/g, '').replace(/[^\p{L}]/gu, '');
  const titleOf = (row, btn) => {
    if (titleSel) {
      const t = row.querySelector(titleSel);
      if (t) return norm(blockParts(t).join(' '));
    }
    const parts = blockParts(row, btn).filter(t => !isNoise(t));
    parts.sort((a, b) => b.length - a.length);
    return parts[0] || textOf(row);
  };
  // 완료 아이콘 구분용: 줄 안의 클래스·아이콘 정보 (버튼 제외)
  const tokensOf = (row, btn) => {
    const s = new Set();
    for (const el of [row, ...row.querySelectorAll('*')]) {
      if (el === btn || btn.contains(el)) continue;
      const tag = el.tagName.toLowerCase();
      el.classList.forEach(c => s.add(tag + '.' + c));
      for (const a of ['aria-label', 'aria-checked', 'alt', 'title', 'data-status', 'data-state']) {
        const v = el.getAttribute(a);
        if (v) s.add(`${tag}[${a}=${v}]`);
      }
      if (tag === 'img' && el.getAttribute('src')) s.add('img:' + el.getAttribute('src').split('/').pop().split('?')[0]);
      if (tag === 'use') { const h = el.getAttribute('href') || el.getAttribute('xlink:href'); if (h) s.add('use:' + h); }
      if (tag === 'path') { const d = el.getAttribute('d'); if (d) s.add('path:' + d.slice(0, 40)); }
      if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) s.add('input:' + (el.checked ? 'checked' : 'unchecked'));
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.width <= 48 && r.height <= 48) {   // 작은 아이콘의 색/배경
        const st = getComputedStyle(el);
        if (st.backgroundImage && st.backgroundImage !== 'none') s.add('bg:' + st.backgroundImage.slice(-60));
        s.add('bgc:' + st.backgroundColor);
        for (const pseudo of ['::before', '::after']) {
          const ps = getComputedStyle(el, pseudo);
          if (ps.content && ps.content !== 'none') s.add(`${pseudo}:${ps.content}|${ps.backgroundColor}|${ps.backgroundImage.slice(-40)}`);
        }
      }
    }
    return Array.from(s);
  };
  const secOf = el => {
    let k = -1;
    heads.forEach((h, i) => { if (h.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) k = i; });
    return k;
  };

  const items = cands.map((el, i) => {
    const idx = base + i;
    el.setAttribute('data-rec-idx', String(idx));
    const row = rowOf(el);
    return {
      idx, sec: secOf(el), button: textOf(el), title: titleOf(row, el),
      rowText: norm(blockParts(row).join(' ')), tokens: tokensOf(row, el),
    };
  });
  return { heads: headInfo, items };
}
"""


@dataclass
class Lesson:
    number: int          # 전체 목록에서의 순서 (1부터)
    section: str         # 주차 제목 (없으면 "")
    title: str           # 차시 제목
    row_text: str
    button: str
    completed: bool = False
    how: str = ""        # 완료 판단 근거
    watched: int | None = None
    total: int | None = None
    key: str = ""
    tokens: list = field(default_factory=list, repr=False)
    frame: object = field(default=None, repr=False)
    idx: int = -1

    @property
    def full_title(self) -> str:
        return f"{self.section} {self.title}".strip()


class Browser:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.list_url: str = cfg["list_url"]
        self.lcfg = cfg.get("lessons", {})
        self.bcfg = cfg.get("browser", {})
        self._pw = None
        self.context = None
        self.page = None
        self.events: list[tuple[str, str]] = []
        self.dialog_rules = [
            {**r, "_re": re.compile(r.get("match", ".*"))}
            for r in cfg.get("player", {}).get("dialogs", [])
        ]

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

    def _watch_page(self, page):
        page.on("dialog", self._on_dialog)

    def _on_dialog(self, d) -> None:
        """웹 알림창(alert/confirm)을 규칙대로 처리하고, 종료/오류 신호를 기록한다."""
        msg = (d.message or "").replace("\n", " ").strip()
        rule = next((r for r in self.dialog_rules if r["_re"].search(msg)), {})
        answer = rule.get("answer", "accept")
        action = rule.get("action", "")
        log.info("웹 알림창: %s → %s", msg, "확인" if answer == "accept" else "취소")
        self.events.append((action, msg))
        try:
            d.accept() if answer == "accept" else d.dismiss()
        except Exception:
            pass

    def take_events(self) -> list[tuple[str, str]]:
        ev, self.events = self.events, []
        return ev

    def wait(self, ms: int) -> None:
        """기다리는 동안에도 알림창 등 브라우저 이벤트가 처리되도록 한다 (time.sleep 대신 사용)."""
        try:
            self.page.wait_for_timeout(ms)
        except Exception:
            time.sleep(ms / 1000)

    # ── 페이지 읽기 ──────────────────────────────────────────
    def open_list(self) -> None:
        self.page.bring_to_front()
        self.page.goto(self.list_url, wait_until="domcontentloaded")
        self._settle()

    def _settle(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

    def _scan_visible(self) -> tuple[list[dict], list[Lesson]]:
        """지금 화면에 보이는 주차 제목들과 차시들."""
        heads: list[dict] = []
        lessons: list[Lesson] = []
        base = 0
        for frame in self.page.frames:
            try:
                res = frame.evaluate(SCAN_JS, {
                    "texts": self.lcfg.get("study_button_texts") or ["학습하기"],
                    "rowSel": self.lcfg.get("row_selector") or "",
                    "titleSel": self.lcfg.get("title_selector") or "",
                    "secPattern": self.lcfg.get("section_pattern") or "",
                    "secSel": self.lcfg.get("section_selector") or "",
                    "base": base,
                })
            except Exception as e:  # 다른 도메인 iframe 등
                log.debug("frame 스캔 실패 %s: %s", frame.url, e)
                continue
            base += len(res["items"])
            fheads = {h["sec"]: h["title"] for h in res["heads"]}
            for h in res["heads"]:
                heads.append({"frame": frame, **h})
            for it in res["items"]:
                lessons.append(Lesson(
                    number=0,
                    section=fheads.get(it["sec"], ""),
                    title=it["title"] or "제목없음",
                    row_text=it["rowText"],
                    button=it["button"],
                    tokens=it["tokens"],
                    frame=frame,
                    idx=it["idx"],
                ))
        return heads, lessons

    def _expand(self, head: dict) -> list[Lesson]:
        """주차 제목을 눌러 펼치고, 그 주차의 차시들을 돌려준다."""
        title = head["title"]
        # 이미 펼쳐져 있는데 내용이 늦게 그려지는 중일 수 있으니 잠깐 지켜본 뒤 누른다
        mine = self._wait_section(title, 1.5)
        if mine:
            return mine
        timeout = float(self.lcfg.get("section_open_timeout_sec", 6))
        for _ in range(2):  # 눌렀더니 오히려 접혔다면 한 번 더 누름
            log.debug("주차 펼치기: %s", title)
            heads, _ = self._scan_visible()
            cur = next((h for h in heads if h["title"] == title), head)
            try:
                cur["frame"].locator(f'[data-rec-sec="{cur["sec"]}"]').click(timeout=5000)
            except Exception as e:
                log.warning("주차 '%s' 를 펼치지 못했습니다: %s", title, e)
                return []
            mine = self._wait_section(title, timeout)
            if mine:
                return mine
        return []

    def _wait_section(self, title: str, timeout: float) -> list[Lesson]:
        deadline = time.time() + timeout
        while True:
            _, lessons = self._scan_visible()
            mine = [l for l in lessons if l.section == title]
            if mine:
                time.sleep(0.5)  # 목록이 다 그려질 때까지 한 번 더
                _, lessons = self._scan_visible()
                return [l for l in lessons if l.section == title]
            if time.time() >= deadline:
                return []
            time.sleep(0.5)

    def collect(self, reload: bool = True) -> list[Lesson]:
        """모든 주차를 차례로 펼쳐 전체 차시 목록을 만든다."""
        if reload:
            self.open_list()
        heads, visible = self._scan_visible()
        if not heads:
            result = visible
        else:
            result = []
            for h in heads:
                got = self._expand(h)
                log.info("  %s: %d개", h["title"], len(got))
                result.extend(got)
        self._finish(result)
        return result

    # ── 번호·완료 판단 ────────────────────────────────────────
    def _finish(self, lessons: list[Lesson]) -> None:
        time_re = re.compile(self.lcfg.get("time_pattern") or r"(\d+)\s*분\s*/\s*(\d+)\s*분")
        for i, l in enumerate(lessons, 1):
            l.number = i
            m = time_re.search(l.row_text)
            if m:
                l.watched, l.total = int(m.group(1)), int(m.group(2))
        seen: dict[str, int] = {}
        for l in lessons:
            k = f"{l.section} | {l.title}"
            seen[k] = seen.get(k, 0) + 1
            l.key = k if seen[k] == 1 else f"{k}#{seen[k]}"
        self._judge_completed(lessons)

    def _judge_completed(self, lessons: list[Lesson]) -> None:
        sel = self.lcfg.get("completed_selector") or ""
        patterns = [re.compile(p) for p in self.lcfg.get("completed_patterns", [])]
        ratio = float(self.lcfg.get("completed_time_ratio", 1.0))

        # 시청시간이 확실한 차시(다 봄 / 0분)로 완료 아이콘 모양을 배운다
        sure_done = [l for l in lessons if l.total and l.watched is not None and l.watched >= l.total]
        sure_not = [l for l in lessons if l.total and l.watched == 0]
        markers: set[str] = set()
        if sure_done and sure_not:
            common = set.intersection(*(set(l.tokens) for l in sure_done))
            neg = set().union(*(set(l.tokens) for l in sure_not))
            markers = common - neg
            log.info("완료 아이콘 표식 %d개 학습 (기준: 다 본 차시 %d개, 안 본 차시 %d개)",
                     len(markers), len(sure_done), len(sure_not))
            log.debug("표식: %s", sorted(markers))

        for l in lessons:
            if sel:
                l.completed, l.how = self._has_selector(l, sel), "선택자"
            elif markers:
                l.completed, l.how = bool(markers & set(l.tokens)), "아이콘"
            elif any(p.search(l.row_text) for p in patterns):
                l.completed, l.how = True, "글자"
            elif l.total and l.watched is not None:
                l.completed, l.how = l.watched >= l.total * ratio, "시간"
            else:
                l.completed, l.how = False, ""

    @staticmethod
    def _has_selector(l: Lesson, sel: str) -> bool:
        try:
            return bool(l.frame.evaluate(
                "([i, s]) => { const b = document.querySelector(`[data-rec-idx=\"${i}\"]`);"
                " if (!b) return false; let r = b; while (r && !r.querySelector(s)) r = r.parentElement;"
                " return !!r && r !== document.body; }", [l.idx, sel]))
        except Exception:
            return False

    # ── 외부에서 쓰는 기능 ────────────────────────────────────
    def ensure_list(self) -> list[Lesson]:
        """목록을 열고, 차시가 안 보이면 사용자가 로그인/이동할 때까지 기다린다."""
        self.open_list()
        reload = False
        while True:
            lessons = self.collect(reload=reload)
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

    def locate(self, target: Lesson) -> Lesson | None:
        """목록을 새로 열고 target 차시가 있는 주차를 펼쳐서 클릭 가능한 차시를 돌려준다."""
        self.open_list()
        heads, visible = self._scan_visible()
        cands = visible
        if target.section:
            head = next((h for h in heads if h["title"] == target.section), None)
            if head:
                cands = self._expand(head)
        same = [l for l in cands if l.section == target.section and l.title == target.title]
        # 같은 제목이 여러 개면 key 의 #번호로 구분
        n = int(target.key.rsplit("#", 1)[1]) if "#" in target.key else 1
        return same[n - 1] if len(same) >= n else None

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
