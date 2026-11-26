"""테스트 공통: 실제 ffmpeg·ffprobe·스레드 없이 Service 를 돌린다."""

from __future__ import annotations

import os

import pytest

from videoconverter.config import Settings, SettingsStore
from videoconverter.core.service import Service

INFO = {"width": 1920, "height": 1080, "duration_sec": 60.0, "bit_rate": 8_000_000, "sub_codecs": []}


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """로그·설정이 사용자 데이터 폴더에 쌓이지 않게 한다."""
    monkeypatch.setenv("VIDEOCONVERTER_LOG_DIR", str(tmp_path / "vclogs"))
    monkeypatch.setenv("VIDEOCONVERTER_HOME", str(tmp_path / "home"))


@pytest.fixture
def tools_dir(tmp_path, monkeypatch):
    """ffmpeg·ffprobe 가 있는 것처럼 보이는 폴더(실행하지는 않는다)."""
    d = tmp_path / "tools"
    d.mkdir()
    for name in ("ffmpeg.exe", "ffprobe.exe", "ffmpeg", "ffprobe"):
        (d / name).write_bytes(b"")
    monkeypatch.setenv("VIDEOCONVERTER_TOOLS_DIR", str(d))
    return d


def video(folder, name: str, data: bytes = b"v" * 100) -> str:
    """빈 영상 파일을 만든다(내용은 보지 않는다)."""
    p = folder / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return str(p)


class FakeConvert:
    """process_video 대신. 파일 이름별로 결과를 정하고, 받은 인자를 기록한다."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.results: dict[str, object] = {}  # 파일 이름 -> (코드, 문구) | 예외 | callable(progress, cancel)

    def __call__(self, path, out_dir, name_mode, value, settings, progress, cancel):
        self.calls.append({"path": path, "out_dir": out_dir, "name_mode": name_mode, "value": value,
                           "settings": settings})
        r = self.results.get(os.path.basename(path), ("SUCCESS", "변환 완료 (모드: cuda)"))
        if isinstance(r, BaseException):
            raise r
        if callable(r):
            return r(progress, cancel)
        progress(50.0, "00:00:30.00", "3.1x")
        return r


def run_now(fn, *args):
    """스레드 대신 그 자리에서 돌린다."""
    fn(*args)


@pytest.fixture
def store(tmp_path):
    return SettingsStore(tmp_path / "settings.json")


@pytest.fixture
def convert():
    return FakeConvert()


@pytest.fixture
def probes():
    """파일 이름 -> ffprobe 결과(None 이면 실패). 없으면 INFO."""
    return {}


@pytest.fixture
def killed():
    return []


@pytest.fixture
def make_svc(store, convert, probes, killed, tools_dir):
    def make(spawn=run_now, recommended=2):
        return Service(settings=store, convert=convert, spawn=spawn, kill=lambda: killed.append(1),
                       probe=lambda p: probes.get(os.path.basename(p), dict(INFO)),
                       detect=lambda: {"gpu": "RTX", "vram_mb": 8000, "ram_gb": 32.0, "recommended_jobs": recommended})

    return make


@pytest.fixture
def svc(make_svc):
    return make_svc()


__all__ = ["INFO", "FakeConvert", "Settings", "run_now", "video"]
