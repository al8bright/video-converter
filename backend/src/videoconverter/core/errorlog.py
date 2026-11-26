"""변환 실패 영구 로그(conversion_errors.log) 기록.

로그 경로 결정 근거:
- 이 패키지는 PyInstaller 로 동결(freeze)되어 배포될 수 있고, 그 경우 실행 파일이
  위치한 디렉터리(sys._MEIPASS / Program Files 등)는 읽기 전용이거나 사용자 쓰기가
  막혀 있을 수 있다. 또한 CWD 는 실행 위치에 따라 달라져 신뢰할 수 없다.
- 따라서 기본 로그 위치를 사용자 홈의 `~/.videoconverter/conversion_errors.log` 로 둔다
  (어느 환경에서도 사용자 쓰기가 보장되는 위치). 테스트나 특수 배포에서는 환경변수
  `VIDEOCONVERTER_LOG_DIR` 로 재정의할 수 있다.
- 기록은 항상 best-effort 이며, 로깅 실패가 변환 결과에 영향을 주지 않는다.
"""

import os

from .ffmpeg_cmd import _summarize_ffmpeg_stderr

_LOG_FILENAME = "conversion_errors.log"
_LOG_DIR_ENV = "VIDEOCONVERTER_LOG_DIR"


def _resolve_log_dir(log_dir=None):
    if log_dir:
        return log_dir
    env_dir = os.environ.get(_LOG_DIR_ENV)
    if env_dir:
        return env_dir
    return os.path.join(os.path.expanduser("~"), ".videoconverter")


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
