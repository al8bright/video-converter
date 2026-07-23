"""ffmpeg 프로세스 실행과 stderr 진행률 추적."""

import re
import subprocess
import sys
import threading

from .ffmpeg_cmd import _safe_remove
from .probe import SUBPROC_TEXT, _time_str_to_seconds


def run_ffmpeg_and_track(
    cmd, total_sec, progress_callback, cancel_event, output_path=None
):
    """
    ffmpeg 명령어를 실행하고 stderr에서 진행 정보를 실시간 파싱해 콜백 전송.
    취소 시 프로세스를 kill 하고 부분 생성된 출력 파일을 정리한다.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=creation_flags,
        **SUBPROC_TEXT,
    )
    stderr_lines = []

    def read_stderr():
        buf = ""
        while True:
            char = proc.stderr.read(1)
            if not char:
                break
            buf += char
            if char in ("\r", "\n"):
                line = buf.strip()
                buf = ""
                if line:
                    stderr_lines.append(line)
                    if "time=" in line:
                        time_match = re.search(r"time=(\S+)", line)
                        speed_match = re.search(r"speed=\s*(\S+)", line)
                        current_time = time_match.group(1) if time_match else "?"
                        speed = speed_match.group(1) if speed_match else "?"
                        pct = 0.0
                        if current_time != "?" and total_sec and total_sec > 0:
                            current_sec = _time_str_to_seconds(current_time)
                            if current_sec is not None:
                                pct = min(100.0, current_sec / total_sec * 100)
                        if progress_callback:
                            progress_callback(pct, current_time, speed)
        if buf.strip():
            stderr_lines.append(buf.strip())

    reader = threading.Thread(target=read_stderr, daemon=True)
    reader.start()

    try:
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
                _safe_remove(output_path)
                return -1, "USER_CANCELLED"
            proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    except Exception as exc:
        proc.kill()
        _safe_remove(output_path)
        return -1, f"Error: {exc}"

    reader.join(timeout=2.0)
    return proc.returncode, "\n".join(stderr_lines)

