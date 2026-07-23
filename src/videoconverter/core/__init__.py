"""비디오 프로브와 변환 파이프라인 공개 API."""

from .errorlog import log_conversion_error
from .ffmpeg_cmd import (
    _build_ffmpeg_cmd,
    _force_mp4_ext,
    _stderr_suggests_fatal_input_error,
    _stderr_suggests_faststart_failure,
    _stderr_suggests_nvenc_fail,
    _summarize_ffmpeg_stderr,
    resolve_output_path,
    should_remux,
)
from .pipeline import process_video
from .probe import _time_str_to_seconds, get_video_info
from .runner import run_ffmpeg_and_track, terminate_all_processes

__all__ = [
    "get_video_info",
    "process_video",
    "resolve_output_path",
    "run_ffmpeg_and_track",
    "terminate_all_processes",
    "log_conversion_error",
    "should_remux",
    "_build_ffmpeg_cmd",
    "_force_mp4_ext",
    "_stderr_suggests_fatal_input_error",
    "_stderr_suggests_faststart_failure",
    "_stderr_suggests_nvenc_fail",
    "_summarize_ffmpeg_stderr",
    "_time_str_to_seconds",
]
