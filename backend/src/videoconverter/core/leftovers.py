"""만들다 만 임시 결과 파일 기록.

변환 결과는 `<결과>.part-<pid>-<hex8>.mp4` 에 먼저 쓰고 다 만든 뒤 제 이름으로 바꾼다. 중단·실패하면
그 자리에서 지우지만, 앱이 강제로 끝나면(작업 관리자, 전원) 지울 기회가 없다. 그래서 만들기 시작할 때
경로를 `<앱 데이터>/partials.json` 에 적어 두고 끝나면 지우며, 다음에 앱이 시작할 때 남은 것을 지운다.

다른 실행이 아직 쓰고 있을 수 있으므로 이름에 든 pid 의 프로세스가 살아 있으면 지우지 않고 남겨 둔다.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from pathlib import Path

from ..config import app_home

_lock = threading.Lock()
PART_RE = re.compile(r"\.part-(\d+)-[0-9a-f]{8}\.mp4$")


def _file() -> Path:
    return app_home() / "partials.json"


def _read() -> list[str]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []


def _write(paths: list[str]) -> None:
    f = _file()
    try:
        if not paths:
            f.unlink(missing_ok=True)
            return
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(paths, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, f)
    except OSError:
        pass  # 기록을 못 해도 변환은 계속한다. 다음 시작 때 못 지울 뿐이다


def remember(path: str) -> None:
    with _lock:
        paths = _read()
        if path not in paths:
            _write([*paths, path])


def forget(path: str) -> None:
    with _lock:
        paths = _read()
        if path in paths:
            _write([p for p in paths if p != path])


def _alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = k32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not h:
            return False
        try:
            return k32.WaitForSingleObject(h, 0) == 0x102  # WAIT_TIMEOUT: 아직 돈다
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def clean() -> int:
    """지난 실행이 남긴 임시 파일을 지우고 지운 개수를 돌려준다."""
    removed = 0
    with _lock:
        keep: list[str] = []
        for p in _read():
            m = PART_RE.search(p)
            if not m:
                continue  # 임시 파일 이름이 아니면 건드리지 않고 기록에서도 뺀다
            if _alive(int(m.group(1))):
                keep.append(p)
                continue
            try:
                os.remove(p)
                removed += 1
            except FileNotFoundError:
                pass
            except OSError:
                keep.append(p)  # 아직 잡혀 있다. 다음에 다시 시도한다
        _write(keep)
    return removed
