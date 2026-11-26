"""pytest 공용 설정."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_conversion_log(tmp_path, monkeypatch):
    """변환 실패 로그가 테스트 중 사용자 홈(~/.videoconverter)을 오염시키지 않도록
    매 테스트마다 임시 디렉터리로 리다이렉트한다."""
    monkeypatch.setenv("VIDEOCONVERTER_LOG_DIR", str(tmp_path / "vclogs"))
