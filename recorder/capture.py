"""녹화 프로그램 제어: OBS (기본) / 윈도우 캡처 도구 (Win+Shift+R, 실험적)."""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from .files import newest_file, wait_until_stable

log = logging.getLogger(__name__)


class RecorderError(Exception):
    pass


# ─────────────────────────────────────────────────────────────
#  OBS (obs-websocket 5, OBS 28 이상에 기본 포함)
# ─────────────────────────────────────────────────────────────
class ObsRecorder:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.cl = None

    def _connect(self):
        import obsws_python as obs

        return obs.ReqClient(
            host=self.cfg.get("host", "localhost"),
            port=int(self.cfg.get("port", 4455)),
            password=self.cfg.get("password") or "",
            timeout=10,
        )

    def prepare(self) -> None:
        try:
            self.cl = self._connect()
        except Exception as first:
            exe = self.cfg.get("launch_path") or ""
            if not exe or not Path(exe).exists():
                raise RecorderError(
                    f"OBS 에 연결하지 못했습니다 ({first}).\n"
                    "OBS 를 켜고 [도구 → WebSocket 서버 설정]에서 서버 사용을 켰는지, "
                    "포트/비밀번호가 config.yaml 과 같은지 확인하세요."
                ) from first
            log.info("OBS 실행: %s", exe)
            subprocess.Popen([exe, "--minimize-to-tray", "--disable-shutdown-check"],
                             cwd=str(Path(exe).parent))
            deadline = time.time() + 40
            while True:
                time.sleep(3)
                try:
                    self.cl = self._connect()
                    break
                except Exception as e:
                    if time.time() > deadline:
                        raise RecorderError(
                            "OBS 를 실행했지만 연결되지 않습니다. "
                            "[도구 → WebSocket 서버 설정]에서 서버 사용을 켜 주세요."
                        ) from e
        ver = self.cl.get_version()
        log.info("OBS 연결됨 (OBS %s, websocket %s)", ver.obs_version, ver.obs_web_socket_version)
        if self.cl.get_record_status().output_active:
            raise RecorderError("OBS 가 이미 녹화 중입니다. OBS 녹화를 먼저 멈춰 주세요.")

    def start(self) -> None:
        self.cl.start_record()
        for _ in range(20):
            if self.cl.get_record_status().output_active:
                log.info("● 녹화 시작 (OBS)")
                return
            time.sleep(0.5)
        raise RecorderError("OBS 녹화가 시작되지 않았습니다.")

    def stop(self) -> Path:
        resp = self.cl.stop_record()
        path = Path(resp.output_path)
        log.info("■ 녹화 중지 (OBS): %s", path)
        wait_until_stable(path)
        return path

    def abort(self) -> Path | None:
        try:
            return self.stop()
        except Exception as e:
            log.warning("녹화 중지 실패: %s", e)
            return None


# ─────────────────────────────────────────────────────────────
#  윈도우 캡처 도구 (Win+Shift+R) — 실험적
#  캡처 도구 설정에서 '화면 녹화 자동 저장'을 켜 두어야 합니다.
# ─────────────────────────────────────────────────────────────
class SnippingRecorder:
    START_NAMES = ["시작", "Start"]
    STOP_NAMES = ["중지", "Stop"]

    def __init__(self, cfg: dict):
        folder = cfg.get("save_dir") or os.path.join(os.environ.get("USERPROFILE", ""), "Videos",
                                                     "Screen Recordings")
        self.save_dir = Path(folder)
        self.t0 = 0.0

    def prepare(self) -> None:
        log.info("캡처 도구 녹화 저장 폴더: %s", self.save_dir)

    @staticmethod
    def _find_button(names: list[str], timeout: float = 10):
        from pywinauto import Desktop

        from .winutil import proc_name

        deadline = time.time() + timeout
        while time.time() < deadline:
            for w in Desktop(backend="uia").windows():
                try:
                    if proc_name(w.process_id()).lower() != "snippingtool.exe":
                        continue
                    for b in w.descendants(control_type="Button"):
                        if b.window_text().strip() in names:
                            return b
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def start(self) -> None:
        from . import winutil

        self.t0 = time.time() - 1
        winutil.press("win", "shift", "r")
        time.sleep(2.5)
        w, h = winutil.screen_size()
        winutil.mouse_drag(0, 0, w - 1, h - 1)
        time.sleep(1.5)
        btn = self._find_button(self.START_NAMES)
        if not btn:
            raise RecorderError("캡처 도구의 [시작] 버튼을 찾지 못했습니다.")
        btn.click_input()
        winutil.park_cursor()
        time.sleep(4)  # 3초 카운트다운
        log.info("● 녹화 시작 (캡처 도구)")

    def stop(self) -> Path:
        btn = self._find_button(self.STOP_NAMES)
        if not btn:
            raise RecorderError("캡처 도구의 [중지] 버튼을 찾지 못했습니다.")
        btn.click_input()
        log.info("■ 녹화 중지 (캡처 도구)")
        deadline = time.time() + 120
        path = None
        while time.time() < deadline and not path:
            time.sleep(2)
            path = newest_file(self.save_dir, self.t0)
        if not path:
            raise RecorderError(
                f"녹화 파일이 {self.save_dir} 에 저장되지 않았습니다. "
                "캡처 도구 설정에서 '화면 녹화 자동 저장'을 켜 주세요.")
        wait_until_stable(path)
        self._close_preview()
        return path

    @staticmethod
    def _close_preview() -> None:
        from . import winutil

        for w in winutil.list_windows():
            if w.proc.lower() == "snippingtool.exe" and w.area > 0:
                winutil.close_window(w.hwnd)

    def abort(self) -> Path | None:
        try:
            return self.stop()
        except Exception as e:
            log.warning("녹화 중지 실패: %s", e)
            return None


def make_recorder(cfg: dict):
    kind = (cfg.get("type") or "obs").lower()
    if kind == "obs":
        return ObsRecorder(cfg.get("obs", {}))
    if kind == "snipping":
        return SnippingRecorder(cfg.get("snipping", {}))
    raise ValueError(f"recorder.type 은 obs 또는 snipping 이어야 합니다: {kind}")
