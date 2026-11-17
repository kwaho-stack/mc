"""녹화 파일 정리."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

_BAD = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def safe_name(text: str, limit: int = 80) -> str:
    text = _BAD.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:limit].rstrip(" .") or "untitled"


def wait_until_stable(path: Path, timeout: float = 120, interval: float = 1.0) -> bool:
    """파일 크기가 더 이상 변하지 않을 때까지 기다린다 (녹화 프로그램이 다 쓸 때까지)."""
    deadline = time.time() + timeout
    last = -1
    stable = 0
    while time.time() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        if size > 0 and size == last:
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        last = size
        time.sleep(interval)
    return path.exists() and path.stat().st_size > 0


def move_recording(src: Path, out_dir: Path, number: int, title: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{number:03d}_{safe_name(title)}"
    dst = out_dir / f"{base}{src.suffix}"
    n = 2
    while dst.exists():
        dst = out_dir / f"{base} ({n}){src.suffix}"
        n += 1
    for _ in range(10):  # 녹화 프로그램이 파일을 잠깐 잡고 있을 수 있음
        try:
            shutil.move(str(src), str(dst))
            return dst
        except PermissionError:
            time.sleep(2)
    shutil.move(str(src), str(dst))
    return dst


def newest_file(folder: Path, since: float, exts=(".mp4", ".mkv", ".mov")) -> Path | None:
    if not folder.exists():
        return None
    files = [p for p in folder.iterdir() if p.suffix.lower() in exts and p.stat().st_mtime >= since]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None
