"""변환 실패 영구 로그(conversion_errors.log) 기록.

로그는 설정과 같은 데이터 폴더(%APPDATA%\\VideoConverter)에 둔다. 설치 폴더는 쓰기가 막혀 있을 수
있고, 현재 폴더는 실행 방법에 따라 달라진다. 테스트에서는 VIDEOCONVERTER_LOG_DIR 로 바꾼다.
기록은 항상 best-effort 이며, 로깅 실패가 변환 결과에 영향을 주지 않는다.
"""

import os

from ..config import app_home
from .ffmpeg_cmd import _summarize_ffmpeg_stderr

_LOG_FILENAME = "conversion_errors.log"
_LOG_DIR_ENV = "VIDEOCONVERTER_LOG_DIR"


def _resolve_log_dir(log_dir=None):
    if log_dir:
        return log_dir
    env_dir = os.environ.get(_LOG_DIR_ENV)
    if env_dir:
        return env_dir
    return str(app_home())


def log_conversion_error(
    display_name, return_code, stderr_text, reason="", log_dir=None
):
    """실패 정보를 UTF-8 로그에 append 한다. 성공 시 로그 경로, 실패 시 None 반환.

    한글 경로/ffmpeg UTF-8 stderr 가 cp949 로 깨지지 않도록 반드시 encoding='utf-8'.
    """
    summary = _summarize_ffmpeg_stderr(stderr_text or "")
    try:
        directory = _resolve_log_dir(log_dir)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, _LOG_FILENAME)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(
                f"Failed: {display_name}\n"
                f"Return Code: {return_code}{reason}\n"
                f"Error:\n{summary}\n"
                f"{'-' * 60}\n"
            )
        return path
    except OSError:
        return None
