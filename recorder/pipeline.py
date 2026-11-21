"""차시 하나 녹화 / 전체 순서대로 녹화."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import winutil
from .browser import Browser, Lesson
from .files import move_recording
from .webplayer import PlaybackBlocked, WebPlayer
from .state import Progress

log = logging.getLogger(__name__)


class LessonError(Exception):
    pass


def record_lesson(lesson: Lesson, br: Browser, wp: WebPlayer, rec, cfg) -> tuple[Path, str]:
    pcfg, rcfg = cfg.get("player", {}), cfg.get("recorder", {})
    before = br.pages()
    br.take_events()  # 이전 알림 기록 비우기
    recording = False
    ok = False
    page = None
    try:
        if rcfg.get("start_before_click", False):
            rec.start()
            recording = True

        methods = cfg.get("lessons", {}).get("click_methods") or ["normal", "js", "mouse"]
        page = None
        for n, method in enumerate(methods):
            if n:
                # 앞의 방법이 실패 → 목록으로 돌아가 같은 차시를 다시 찾는다
                br.close_new_pages(before)
                lesson = br.locate(lesson) or lesson
                before = br.pages()
            log.info("'%s' 클릭 (방법: %s)", lesson.button, method)
            br.click(lesson, method, attempt=n + 1)
            page = wp.wait_open(before, br.list_url)
            if page is None:
                log.warning("재생 창이 열리지 않았습니다")
                continue
            if not wp.same_tab or wp.is_player(page):
                break
            log.warning("재생 화면이 아닌 페이지로 이동했습니다: %s → 다른 방법으로 다시 누릅니다", page.url)
            page = None
        if page is None:
            raise LessonError("학습하기를 눌러도 재생 창이 열리지 않았습니다. logs 폴더의 로그를 보내 주세요.")

        wp.make_fullscreen(page)      # 기본: F11 전체화면
        winutil.park_cursor()

        if not recording:
            rec.start()
            recording = True

        wp.click_start(page)          # [시작] 버튼
        winutil.park_cursor()

        outcome = wp.wait_finish(page, float(pcfg.get("max_minutes_per_lesson", 240)) * 60)
        log.info("차시 종료 감지: %s", {"end": "완료 알림", "closed": "재생 창 닫힘",
                                    "ended": "영상 끝", "timeout": "최대 시간 초과"}.get(outcome, outcome))
        br.wait(int(float(rcfg.get("tail_sec", 2)) * 1000))
        path = rec.stop()
        recording = False
        ok = True
        return path, outcome
    finally:
        if recording:
            path = rec.abort()
            if path and path.exists() and not ok:
                log.info("중단된 녹화 파일: %s", path)
        wp.close(page)
        br.close_new_pages(before)


def run_all(targets: list[Lesson], br: Browser, rec, cfg, progress: Progress) -> dict:
    wp = WebPlayer(br, cfg.get("player", {}))
    out_dir = cfg.path(cfg.get("output_dir", "./recordings"))
    gap = float(cfg.get("between_lessons_sec", 5))
    result = {"done": [], "failed": []}

    for i, target in enumerate(targets, 1):
        name = target.full_title
        log.info("━━━ [%d/%d] %03d. %s ━━━", i, len(targets), target.number, name)
        attempt = 0
        while True:
            attempt += 1
            # 목록을 새로 열고 해당 주차를 펼쳐서 같은 차시를 다시 찾는다
            lesson = br.locate(target)
            if lesson is None:
                log.error("목록에서 '%s' 차시를 찾지 못했습니다", name)
                if attempt >= 2:
                    result["failed"].append(name)
                    progress.mark(target.key, "failed", reason="목록에서 찾지 못함")
                    break
                time.sleep(5)
                continue
            try:
                path, outcome = record_lesson(lesson, br, wp, rec, cfg)
                dst = move_recording(path, out_dir, target.number, name)
                progress.mark(target.key, "done", file=str(dst), outcome=outcome)
                log.info("저장: %s", dst)
                result["done"].append(name)
                break
            except PlaybackBlocked:
                raise
            except Exception as e:
                log.error("실패 (%d번째 시도): %s", attempt, e)
                if attempt >= 2:
                    progress.mark(target.key, "failed", reason=str(e)[:300])
                    result["failed"].append(name)
                    break
                time.sleep(5)
        if i < len(targets):
            time.sleep(gap)
    return result
