"""변환 상수, 사용자 설정과 그 저장.

설정은 %APPDATA%\\VideoConverter\\settings.json 에 둔다(VIDEOCONVERTER_HOME 으로 바꿀 수 있다).
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

SUPPORTED_EXTENSIONS = (".mkv", ".avi", ".mov", ".wmv", ".mp4", ".m4v", ".ts")

VIDEO_BITRATE_OPTIONS = ("5.0", "4.0", "3.5", "2.5", "1.5")
AUDIO_BITRATE_OPTIONS = ("192k", "128k", "96k")

# 해상도 제한: 설정에는 코드 값을 저장한다. 이 크기보다 큰 원본만 비율을 지켜 줄인다
RESOLUTIONS = {"1080p": (1920, 1080), "720p": (1280, 720), "none": (9999, 9999)}

# 옛 화면(gui/)이 쓰는 표시 문구. 옛 화면과 함께 지운다(PLAN.md Phase 6)
RESOLUTION_OPTIONS = ("1080p (FHD)", "720p (HD)", "제한 없음")
RESOLUTION_LIMITS = {
    "1080p (FHD)": (1920, 1080),
    "720p (HD)": (1280, 720),
    "제한 없음": (9999, 9999),
}

VRAM_JOB_TIERS = (
    (4100, 1),
    (8200, 2),
    (12300, 3),
)
DEFAULT_PARALLEL_JOBS = 2
MAX_SLOTS = 8

DEFAULT_VIDEO_MAXRATE_MBPS = 3.5
DEFAULT_AUDIO_BITRATE = "128k"
DEFAULT_RESOLUTION = "1080p (FHD)"
DEFAULT_NVENC_PRESET = "p5"
REMUX_THRESHOLD_MBPS = 4.0
FASTSTART_DEFAULT = True
VIDEO_BUFSIZE_MULTIPLIER = 2

# 진행(time=) 로그가 이 시간(초)을 넘도록 갱신되지 않으면 ffmpeg가 행(hang)된 것으로
# 간주하고 강제 종료한다. (원본 CLI convert_video_win.py 의 STUCK_TIMEOUT_SEC 포팅)
STUCK_TIMEOUT_SEC = 600

# 실패 stderr 요약 시 걸러낼 ffmpeg 부트 로그 접두사와 최대 유지 라인 수.
FFMPEG_STDERR_SKIP_PREFIXES = (
    "ffmpeg version", "built with", "configuration:", "libavutil",
    "libavcodec", "libavformat", "libavdevice", "libavfilter",
    "libswscale", "libswresample",
)
FFMPEG_STDERR_MAX_LINES = 20

TEXT_SUB_CODECS = frozenset(
    {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
)
FASTSTART_EXTENSIONS = (".mp4", ".mov", ".m4v")


def build_settings(video_maxrate_mbps, audio_bitrate, resolution, delete_source):
    """옛 화면의 표시 문구로 encode_settings와 같은 딕셔너리를 만든다."""
    max_width, max_height = RESOLUTION_LIMITS.get(
        resolution, RESOLUTION_LIMITS["제한 없음"]
    )
    return {
        "video_maxrate_mbps": float(video_maxrate_mbps),
        "audio_bitrate": audio_bitrate,
        "max_width": max_width,
        "max_height": max_height,
        "remux_threshold_mbps": REMUX_THRESHOLD_MBPS,
        "faststart": FASTSTART_DEFAULT,
        "delete_source": delete_source,
        "nvenc_preset": DEFAULT_NVENC_PRESET,
    }



# ---------------------------------------------------------------------- 사용자 설정
VideoRate = Literal["5.0", "4.0", "3.5", "2.5", "1.5"]
AudioRate = Literal["192k", "128k", "96k"]
Resolution = Literal["1080p", "720p", "none"]
SaveMode = Literal["same", "folder"]  # 원본과 같은 폴더 | 지정 폴더
NameMode = Literal["suffix", "overwrite"]  # 접미사 붙이기 | 같은 이름으로 덮어쓰기
Sidebar = Literal["open", "closed"]


class Settings(BaseModel):
    jobs: int | None = Field(default=None, ge=1, le=MAX_SLOTS)  # None 이면 GPU 메모리로 정한 권장값
    video_rate: VideoRate = "3.5"  # 최대 비디오 비트레이트(Mbps)
    audio_rate: AudioRate = "128k"
    resolution: Resolution = "1080p"
    delete_source: bool = False  # 변환에 성공하면 원본을 지운다
    save_mode: SaveMode = "same"
    save_dir: str = ""  # save_mode 가 folder 일 때만 쓴다
    name_mode: NameMode = "suffix"
    suffix: str = Field(default="_cuda", max_length=40)
    sidebar: Sidebar = "open"  # 사이드바 접기/펴기. 다음 실행에도 그대로 연다


def encode_settings(s: Settings) -> dict:
    """변환 파이프라인(core.process_video)이 받는 딕셔너리."""
    max_width, max_height = RESOLUTIONS[s.resolution]
    return {
        "video_maxrate_mbps": float(s.video_rate),
        "audio_bitrate": s.audio_rate,
        "max_width": max_width,
        "max_height": max_height,
        "remux_threshold_mbps": REMUX_THRESHOLD_MBPS,
        "faststart": FASTSTART_DEFAULT,
        "delete_source": s.delete_source,
        "nvenc_preset": DEFAULT_NVENC_PRESET,
    }


def app_home() -> Path:
    override = os.environ.get("VIDEOCONVERTER_HOME")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    return Path(base) / "VideoConverter"


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or app_home() / "settings.json"
        self.lock = threading.Lock()
        self.value = self._load()

    def _load(self) -> Settings:
        try:
            return Settings.model_validate_json(self.path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError):
            return Settings()

    def get(self) -> Settings:
        with self.lock:
            return self.value.model_copy()

    def save(self, value: Settings) -> None:
        with self.lock:
            self.value = value.model_copy()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
