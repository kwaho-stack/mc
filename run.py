"""인줌 강의 자동 녹화기.

사용법
  python run.py                    차시 목록 확인 후 녹화 시작
  python run.py --list             차시 목록만 보기
  python run.py --only 1-5,8       해당 번호만 녹화
  python run.py --include-completed / --skip-completed
  python run.py --redo             이미 녹화한 차시도 다시 녹화
  python run.py --probe            목록 인식 결과와 페이지 HTML 저장 (문제 확인용)
  python run.py --probe-player 3   3번 차시를 녹화 없이 열어 재생 창 구조 확인
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from recorder.config import ROOT, load_config


def setup_logging() -> None:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(logs / f"run_{datetime.now():%Y%m%d}.log", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(sh)
    root.addHandler(fh)


def parse_range(text: str, maximum: int) -> set[int]:
    nums: set[int] = set()
    for part in text.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            nums.update(range(int(a or 1), int(b or maximum) + 1))
        else:
            nums.add(int(part))
    return nums


def print_lessons(lessons, progress) -> None:
    print()
    print(" 번호  사이트  녹화   시청시간    제목")
    section = None
    for l in lessons:
        if l.section != section:
            section = l.section
            print(f"\n ■ {section or '(주차 없음)'}")
        site = "완료" if l.completed else "-"
        st = progress.data.get(l.key, {}).get("status")
        mine = {"done": "완료", "failed": "실패"}.get(st, "-")
        tm = f"{l.watched}/{l.total}분" if l.total else ""
        print(f" {l.number:>4}  {site:<4}  {mine:<4}  {tm:<10}  {l.title}")
    print()


def choose(lessons, progress, cfg, args) -> list:
    lcfg = cfg.get("lessons", {})
    skip_completed = lcfg.get("skip_completed", True)
    if args.include_completed:
        skip_completed = False
    if args.skip_completed:
        skip_completed = True
    only = parse_range(args.only, len(lessons)) if args.only else None

    print_lessons(lessons, progress)
    ask = lcfg.get("ask_on_start", True) and not args.yes
    if ask:
        cur = "건너뜀" if skip_completed else "녹화함"
        ans = input(f"사이트에서 '완료'로 표시된 차시: 현재 [{cur}]. 바꾸려면 y, 그대로면 Enter > ").strip().lower()
        if ans in ("y", "ㅛ", "yes"):
            skip_completed = not skip_completed
        if only is None:
            ans = input("녹화할 번호 (예: 1-5,8 / Enter = 전체) > ").strip()
            if ans:
                only = parse_range(ans, len(lessons))

    targets = []
    for l in lessons:
        if only is not None and l.number not in only:
            continue
        if skip_completed and l.completed:
            continue
        if not args.redo and progress.is_done(l.key):
            continue
        targets.append(l)

    print(f"\n녹화 대상 {len(targets)}개 (완료 차시 {'건너뜀' if skip_completed else '포함'})")
    for l in targets:
        print(f"  {l.number:>3}. {l.full_title}")
    if targets and ask:
        print("\n※ 녹화가 진행되는 동안 마우스와 키보드를 건드리지 마세요.")
        input("시작하려면 Enter (취소: Ctrl+C) > ")
    return targets


def probe_player(br, cfg, lessons, number: int) -> None:
    """녹화 없이 재생 창을 열어 구조를 확인하고 probe 폴더에 저장한다."""
    from recorder.webplayer import START_JS, WebPlayer

    lesson = next((l for l in lessons if l.number == number), None)
    if not lesson:
        print(f"{number}번 차시가 없습니다.")
        return
    lesson = br.locate(lesson) or lesson
    print(f"\n'{lesson.full_title}' 을(를) 녹화 없이 엽니다.")
    wp = WebPlayer(br, cfg.get("player", {}))
    before = br.pages()
    br.click(lesson)
    page = wp.wait_open(before, br.list_url)
    if page is None:
        print("재생 창이 열리지 않았습니다.")
        return
    print("재생 창 주소:", page.url, "(같은 탭)" if wp.same_tab else "(새 창)")
    folder = ROOT / "probe"
    folder.mkdir(exist_ok=True)
    br.wait(3000)
    texts = cfg.get("player", {}).get("start_button_texts") or ["시작"]
    for i, frame in enumerate(page.frames):
        try:
            found = frame.evaluate(START_JS, texts)
            vids = frame.evaluate("() => document.querySelectorAll('video').length")
            (folder / f"player_frame{i}.html").write_text(f"<!-- {frame.url} -->\n{frame.content()}", encoding="utf-8")
        except Exception as e:
            print(f"  frame{i} {frame.url} 읽기 실패: {e}")
            continue
        print(f"  frame{i} {frame.url}\n     시작 버튼: {found}  / 영상 요소: {vids}개")
    print("probe 폴더에 player_frame*.html 저장. 10초 뒤 창을 닫습니다.")
    br.wait(10000)
    wp.close(page)


def main() -> int:
    ap = argparse.ArgumentParser(description="인줌 강의 자동 녹화기")
    ap.add_argument("--config")
    ap.add_argument("--list", action="store_true", help="차시 목록만 보기")
    ap.add_argument("--only", help="녹화할 번호, 예: 1-5,8")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--include-completed", action="store_true", help="사이트 완료 차시도 녹화")
    g.add_argument("--skip-completed", action="store_true", help="사이트 완료 차시 건너뛰기")
    ap.add_argument("--redo", action="store_true", help="이미 녹화한 차시도 다시")
    ap.add_argument("-y", "--yes", action="store_true", help="묻지 않고 바로 시작")
    ap.add_argument("--probe", action="store_true", help="목록 인식 결과와 HTML 저장")
    ap.add_argument("--probe-player", type=int, metavar="N", help="N번 차시를 녹화 없이 열어 재생 창 구조 확인")
    args = ap.parse_args()

    setup_logging()
    log = logging.getLogger("main")
    cfg = load_config(args.config)

    from recorder import winutil
    from recorder.browser import Browser
    from recorder.capture import RecorderError, make_recorder
    from recorder.pipeline import run_all
    from recorder.webplayer import PlaybackBlocked
    from recorder.state import Progress

    winutil.set_dpi_aware()
    out_dir = cfg.path(cfg.get("output_dir", "./recordings"))
    progress = Progress(out_dir / "progress.json")

    with Browser(cfg) as br:
        lessons = br.ensure_list()
        log.info("차시 %d개 인식", len(lessons))

        if args.list or args.probe:
            print_lessons(lessons, progress)
            if args.probe:
                for l in lessons:
                    print(f"[{l.number}] 버튼='{l.button}' 완료={l.completed}({l.how})\n     줄 글자: {l.row_text[:200]}")
                for p in br.dump_html(ROOT / "probe"):
                    print("HTML 저장:", p)
            return 0
        if args.probe_player:
            probe_player(br, cfg, lessons, args.probe_player)
            return 0

        targets = choose(lessons, progress, cfg, args)
        if not targets:
            print("녹화할 차시가 없습니다.")
            return 0

        rec = make_recorder(cfg.get("recorder", {}))
        try:
            rec.prepare()
        except RecorderError as e:
            log.error("%s", e)
            return 1

        winutil.keep_awake(True)
        console = None
        if cfg.get("minimize_console", True):
            console = winutil.minimize_console()   # 녹화 화면에 명령 창이 가리지 않게
        try:
            result = run_all(targets, br, rec, cfg, progress)
        except PlaybackBlocked as e:
            log.error("재생이 차단되었습니다: %s", e)
            log.error("녹화 프로그램 감지로 보입니다. 이 경우 자동 녹화를 진행할 수 없습니다.")
            return 2
        except KeyboardInterrupt:
            log.warning("사용자가 중단했습니다. 다시 실행하면 남은 차시부터 이어서 합니다.")
            return 130
        finally:
            winutil.keep_awake(False)
            winutil.restore_window(console)

    log.info("━━━ 끝: 성공 %d개, 실패 %d개 ━━━", len(result["done"]), len(result["failed"]))
    for t in result["failed"]:
        log.info("  실패: %s", t)
    log.info("저장 폴더: %s", out_dir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n중단했습니다.")
        sys.exit(130)
