"""FFmpeg·ffprobe 찾기.

설치 파일은 둘을 백엔드 실행 파일 옆에 넣는다(PLAN.md Phase 5). 그것이 있으면 그것을, 없으면(개발 실행)
PATH의 것을 쓴다. VIDEOCONVERTER_TOOLS_DIR로 다른 폴더를 가리킬 수 있다(테스트, 직접 받은 빌드).
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

TOOLS_DIR_ENV = "VIDEOCONVERTER_TOOLS_DIR"


def bundled_tool(name: str) -> str | None:
    """실행 파일 옆(또는 VIDEOCONVERTER_TOOLS_DIR)에 있는 도구의 경로. 없으면 None."""
    exe = name + (".exe" if sys.platform == "win32" else "")
    override = os.environ.get(TOOLS_DIR_ENV)
    if override:
        p = Path(override) / exe
        return str(p) if p.is_file() else None
    if getattr(sys, "frozen", False):
        here = Path(sys.executable).parent
        for d in (here, here / "_internal"):
            if (d / exe).is_file():
                return str(d / exe)
    return None


def tool_path(name: str) -> str | None:
    """함께 넣은 것 → PATH 순서로 찾는다. 없으면 None."""
    return bundled_tool(name) or shutil.which(name)


def ffmpeg() -> str:
    """명령 첫 인자로 쓸 ffmpeg. 찾지 못하면 이름만 돌려줘 실행 때 '없음' 오류가 나게 한다."""
    return tool_path("ffmpeg") or "ffmpeg"


def ffprobe() -> str:
    return tool_path("ffprobe") or "ffprobe"
