"""개발 환경과 PyInstaller 번들에서 공통으로 쓰는 리소스 경로."""

import os
import sys


def resource_path(relative_path):
    """패키지 기준 또는 PyInstaller ``_MEIPASS`` 기준 절대 경로를 반환한다."""
    if hasattr(sys, "_MEIPASS"):
        base_dir = os.path.join(sys._MEIPASS, "videoconverter")
    else:
        base_dir = os.path.dirname(__file__)
    return os.path.join(base_dir, relative_path)

