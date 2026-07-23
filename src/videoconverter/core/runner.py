"""ffmpeg 프로세스 실행과 stderr 진행률 추적.

- 모든 Popen 을 모듈 레벨 레지스트리(스레드 안전)에 등록/해제하여
  terminate_all_processes() 로 언제든 일괄 강제 종료할 수 있게 한다.
- 진행(time=)이 STUCK_TIMEOUT_SEC 를 초과해 갱신되지 않으면 행(hang)으로 보고
  프로세스를 강제 종료한다(원본 CLI 의 stuck_watcher 포팅).
"""

import re
import subprocess
import sys
import threading
import time

from ..config import STUCK_TIMEOUT_SEC
from .ffmpeg_cmd import _safe_remove
from .probe import SUBPROC_TEXT, _time_str_to_seconds


# ---------------------------------------------------------------------------
# 실행 중 ffmpeg 프로세스 레지스트리 (GUI 강제 종료용)
# ---------------------------------------------------------------------------
_active_procs = set()
_active_procs_lock = threading.Lock()


def _register_proc(proc):
    with _active_procs_lock:
        _active_procs.add(proc)


def _unregister_proc(proc):
    with _active_procs_lock:
        _active_procs.discard(proc)


def _kill_process_tree(proc):
    """proc와 그 자식 프로세스까지 모두 종료한다.

    "ffmpeg"가 PATH 상에서 Chocolatey/scoop 등의 쉼(shim) 실행파일로 해석되면,
    그 쉼이 실제 ffmpeg.exe를 자식 프로세스로 띄운다. 이 경우 proc.kill()은
    쉼(부모)만 죽이고 실제 인코딩 중인 ffmpeg.exe는 오펀으로 남아 계속 실행된다
    (파일 핸들도 계속 잡고 있어 부분 출력 삭제도 실패함). Windows에서는
    `taskkill /F /T /PID`로 프로세스 트리 전체를 종료해 이를 방지한다.
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
                timeout=5,
            )
            return
        except Exception:
            pass
    try:
        proc.kill()
    except Exception:
        pass


def terminate_all_processes():
    """실행 중인 모든 ffmpeg 프로세스(자식 포함)를 즉시·동기·best-effort 로 kill 한다.

    - 인자 없음. 멱등이며 아무 때나 호출해도 안전(실행 중 프로세스가 없으면 no-op).
    - 각 프로세스는 자신을 실행한 run_ffmpeg_and_track 의 finally 에서 레지스트리에서
      해제되므로, 여기서는 kill 만 하고 레지스트리를 비우지 않는다.
    - GUI 가 강제 종료(창 닫기 등) 시 이 함수를 호출한다.
    """
    with _active_procs_lock:
        procs = list(_active_procs)
    for proc in procs:
        _kill_process_tree(proc)


def run_ffmpeg_and_track(
    cmd,
    total_sec,
    progress_callback,
    cancel_event,
    output_path=None,
    stuck_timeout_sec=None,
):
    """
    ffmpeg 명령어를 실행하고 stderr에서 진행 정보를 실시간 파싱해 콜백 전송.
    - 취소 시: 프로세스 kill + 부분 출력 정리 후 (-1, "USER_CANCELLED") 반환.
    - 행(hang) 감지 시: kill + 부분 출력 정리 후 (rc, "STUCK_TIMEOUT\\n<stderr>") 반환.
    - 그 외: (returncode, stderr_full) 반환.
    stuck_timeout_sec 가 None 이면 config.STUCK_TIMEOUT_SEC 를 사용한다.
    """
    if stuck_timeout_sec is None:
        stuck_timeout_sec = STUCK_TIMEOUT_SEC

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
    _register_proc(proc)
    # 등록 직전에 이미 취소가 들어왔다면 곧바로 종료(레이스 방지).
    if cancel_event and cancel_event.is_set():
        try:
            proc.kill()
        except Exception:
            pass

    stderr_lines = []
    last_progress = [time.monotonic()]

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
                        last_progress[0] = time.monotonic()
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

    stuck = False
    try:
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                _kill_process_tree(proc)
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
                _safe_remove(output_path)
                return -1, "USER_CANCELLED"
            if (
                stuck_timeout_sec
                and (time.monotonic() - last_progress[0]) > stuck_timeout_sec
            ):
                stuck = True
                _kill_process_tree(proc)
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
                _safe_remove(output_path)
                break
            # 0.5초 타임아웃은 취소/hang 조건을 재확인하기 위한 폴링 간격일 뿐,
            # 여기서 잡지 않으면 예외가 while 밖으로 빠져나가 루프가 재개되지
            # 않는다(실행 0.5초 넘는 모든 실제 변환에서 조기 반환되는 치명적 버그).
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
    except Exception as exc:
        _kill_process_tree(proc)
        _safe_remove(output_path)
        return -1, f"Error: {exc}"
    finally:
        _unregister_proc(proc)

    reader.join(timeout=2.0)
    stderr_full = "\n".join(stderr_lines)
    if stuck:
        # 행 감지로 죽인 경우: pipeline 이 FAIL 로 매핑하도록 마커를 앞에 붙인다.
        return proc.returncode, "STUCK_TIMEOUT\n" + stderr_full
    return proc.returncode, stderr_full
