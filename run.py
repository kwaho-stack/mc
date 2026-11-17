"""인줌 강의 자동 녹화기.

사용법
  python run.py                    차시 목록 확인 후 녹화 시작
  python run.py --list             차시 목록만 보기
  python run.py --only 1-5,8       해당 번호만 녹화
  python run.py --include-completed / --skip-completed
  python run.py --redo             이미 녹화한 차시도 다시 녹화
  python run.py --probe            목록 인식 결과와 페이지 HTML 저장 (문제 확인용)
  python run.py --probe-player 3   3번 차시를 녹화 없이 열어 재생창/알림창 정보 출력
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
    print(" 번호  사이트   녹화     제목")
    print(" ────  ──────  ──────  ───────────────────────────")
    for l in lessons:
        site = "완료" if l.completed else "-"
        mine = "완료" if progress.is_done(l.key) else ("실패" if progress.data.get(l.key, {}).get("status") == "failed" else "-")
        print(f" {l.number:>4}  {site:<6}  {mine:<6}  {l.title}")
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
        print(f"  {l.number:>3}. {l.title}")
    if targets and ask:
        print("\n※ 녹화가 진행되는 동안 마우스와 키보드를 건드리지 마세요.")
        input("시작하려면 Enter (취소: Ctrl+C) > ")
    return targets


def probe_player(br, cfg, lessons, number: int) -> None:
    from recorder import winutil
    from recorder.player import KollusPlayer, dialog_texts

    lesson = next((l for l in lessons if l.number == number), None)
    if not lesson:
        print(f"{number}번 차시가 없습니다.")
        return
    before = {w.hwnd for w in winutil.list_windows()}
    print(f"\n'{lesson.title}' 을(를) 녹화 없이 엽니다. 90초 동안 새로 뜨는 창을 기록합니다.")
    br.click(lesson)
    player = KollusPlayer(cfg.get("player", {}))
    seen: set[int] = set()
    end = time.time() + 90
    while time.time() < end:
        for w in winutil.list_windows():
            if w.hwnd in before or w.hwnd in seen or w.area == 0:
                continue
            seen.add(w.hwnd)
            tag = "★재생창 후보" if player._match(w) else ""
            print(f"  새 창: {w} {tag}")
            if w.area < 900 * 700:
                text, buttons = dialog_texts(w.hwnd)
                print(f"     글자: {text[:200]}")
                print(f"     버튼: {[b.window_text() for b in buttons]}")
        time.sleep(1)
    print("\n★ 표시가 없다면 config.yaml 의 player.process_names 에 위 프로세스 이름을 넣어 주세요.")


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
    ap.add_argument("--probe-player", type=int, metavar="N", help="N번 차시를 녹화 없이 열어 창 정보 출력")
    args = ap.parse_args()

    setup_logging()
    log = logging.getLogger("main")
    cfg = load_config(args.config)

    from recorder import winutil
    from recorder.browser import Browser
    from recorder.capture import RecorderError, make_recorder
    from recorder.pipeline import run_all
    from recorder.player import PlaybackBlocked
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
                    print(f"[{l.number}] 버튼='{l.button}' 완료={l.completed}\n     줄 글자: {l.row_text[:200]}")
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
