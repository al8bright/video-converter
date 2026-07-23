"""애플리케이션 전역 상수와 기본 인코딩 설정."""

SUPPORTED_EXTENSIONS = (".mkv", ".avi", ".mov", ".wmv", ".mp4", ".m4v", ".ts")

VIDEO_BITRATE_OPTIONS = ("5.0", "4.0", "3.5", "2.5", "1.5")
AUDIO_BITRATE_OPTIONS = ("192k", "128k", "96k")
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

TEXT_SUB_CODECS = frozenset(
    {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}
)
FASTSTART_EXTENSIONS = (".mp4", ".mov", ".m4v")


def build_settings(video_maxrate_mbps, audio_bitrate, resolution, delete_source):
    """기존 GUI의 settings 딕셔너리를 동일한 키와 값으로 구성한다."""
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

