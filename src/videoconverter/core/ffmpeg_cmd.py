"""ffmpeg 명령 구성, 출력 경로, 변환 판정 순수 헬퍼."""

import os
import uuid

from ..config import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_NVENC_PRESET,
    DEFAULT_VIDEO_MAXRATE_MBPS,
    FASTSTART_EXTENSIONS,
    VIDEO_BUFSIZE_MULTIPLIER,
)


def _stderr_suggests_nvenc_fail(stderr_text):
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return any(
        pattern in low
        for pattern in [
            "h264_nvenc",
            "hevc_nvenc",
            "no capable devices",
            "10 bit encode not supported",
            "could not open encoder",
            "error while opening encoder",
        ]
    )


def _stderr_suggests_fatal_input_error(stderr_text):
    """재시도해도 소용없는 입력/출력/경로성 치명 오류를 감지한다."""
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return any(
        pattern in low
        for pattern in [
            "no such file or directory",
            "same as input",
            "permission denied",
            "invalid data found when processing input",
        ]
    )


def _output_wants_faststart(output_path):
    return os.path.splitext(output_path)[1].lower() in FASTSTART_EXTENSIONS


def _estimate_bps(bit_rate, duration_sec, size_bytes):
    if bit_rate and bit_rate > 0:
        return int(bit_rate)
    if duration_sec and duration_sec > 0 and size_bytes and size_bytes > 0:
        return int(size_bytes * 8 / duration_sec)
    return 0


def should_remux(bit_rate, duration_sec, size_bytes, threshold_mbps, need_scale):
    """다운스케일이 필요 없고 비트레이트가 임계 이하일 때만 remux한다."""
    if need_scale:
        return False
    bps = _estimate_bps(bit_rate, duration_sec, size_bytes)
    return 0 < bps <= threshold_mbps * 1_000_000


def _force_mp4_ext(path):
    root, _ = os.path.splitext(path)
    return root + ".mp4"


def _tmp_output_path(dest_path):
    ext = os.path.splitext(dest_path)[1] or ".mp4"
    return f"{dest_path}.part-{os.getpid()}-{uuid.uuid4().hex[:8]}{ext}"


def _tmp_is_valid(path, min_bytes=1024):
    try:
        return os.path.exists(path) and os.path.getsize(path) > min_bytes
    except OSError:
        return False


def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _build_ffmpeg_cmd(
    input_path,
    output_path,
    remux_only,
    vf,
    faststart,
    mode,
    settings,
    text_sub_indices=None,
):
    """변환 모드와 사용자 설정에 따라 ffmpeg 인자를 구성한다."""
    add_faststart = bool(faststart) and _output_wants_faststart(output_path)

    if remux_only:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy"]
        if add_faststart:
            cmd += ["-movflags", "+faststart"]
        cmd += [output_path]
        return cmd

    video_value = settings.get(
        "video_maxrate_mbps", DEFAULT_VIDEO_MAXRATE_MBPS
    )
    video_maxrate = f"{video_value}M"
    video_bufsize = f"{float(video_value) * VIDEO_BUFSIZE_MULTIPLIER}M"
    audio_bitrate = settings.get("audio_bitrate", DEFAULT_AUDIO_BITRATE)
    nvenc_preset = settings.get("nvenc_preset", DEFAULT_NVENC_PRESET)

    cmd = ["ffmpeg", "-y"]
    if mode == "cuda":
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-i", input_path]
    cmd += ["-map", "0:v:0", "-map", "0:a?"]

    sub_codec_args = []
    if text_sub_indices and _output_wants_faststart(output_path):
        for index in text_sub_indices:
            cmd += ["-map", f"0:s:{index}?"]
        sub_codec_args = ["-c:s", "mov_text"]

    if mode == "cpu":
        cmd += ["-c:v", "libx264", "-preset", "medium"]
    else:
        cmd += [
            "-c:v",
            "h264_nvenc",
            "-preset",
            nvenc_preset,
            "-rc",
            "vbr",
        ]

    cmd += [
        "-b:v",
        video_maxrate,
        "-maxrate",
        video_maxrate,
        "-bufsize",
        video_bufsize,
        "-vf",
        vf,
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
    ]
    cmd += sub_codec_args
    cmd += [output_path]

    if add_faststart:
        cmd.insert(-1, "-movflags")
        cmd.insert(-1, "+faststart")
    return cmd


def resolve_output_path(file_path, output_dir, name_option, value=""):
    """출력 위치 및 파일명 옵션을 결합해 최종 경로를 생성한다."""
    src_dir = os.path.dirname(os.path.abspath(file_path))
    dest_dir = src_dir if not output_dir else os.path.abspath(output_dir)
    filename = os.path.basename(file_path)
    name, ext = os.path.splitext(filename)

    if name_option == "suffix":
        new_filename = f"{name}{value}{ext}"
    elif name_option == "prefix":
        new_filename = f"{value}{name}{ext}"
    else:
        new_filename = filename
    return os.path.join(dest_dir, new_filename)

