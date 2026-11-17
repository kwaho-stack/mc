"""녹화 진행 기록(progress.json). 중간에 끊겨도 끝난 차시는 다시 녹화하지 않는다."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Progress:
    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, dict] = {}
        if path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.data = {}

    def is_done(self, key: str) -> bool:
        return self.data.get(key, {}).get("status") == "done"

    def mark(self, key: str, status: str, **extra) -> None:
        self.data[key] = {
            "status": status,
            "time": datetime.now().isoformat(timespec="seconds"),
            **extra,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def forget(self, key: str) -> None:
        if self.data.pop(key, None) is not None:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
