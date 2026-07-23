"""pytest 공용 설정: src 패키지와 프로젝트 루트를 import 경로에 추가한다.

마이그레이션 중에는 신규 `videoconverter` 패키지와 구 셰임 모듈을 모두 찾을 수
있도록 두 경로를 명시한다.
"""
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(PROJECT_ROOT, "src")
for path in (PROJECT_ROOT, SRC_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def _isolate_conversion_log(tmp_path, monkeypatch):
    """변환 실패 로그가 테스트 중 사용자 홈(~/.videoconverter)을 오염시키지 않도록
    매 테스트마다 임시 디렉터리로 리다이렉트한다."""
    monkeypatch.setenv("VIDEOCONVERTER_LOG_DIR", str(tmp_path / "vclogs"))
