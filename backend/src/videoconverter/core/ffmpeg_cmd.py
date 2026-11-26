"""ffmpeg 명령 구성, 출력 경로, 변환 판정 순수 헬퍼."""

import os
import time
import uuid

from ..config import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_NVENC_PRESET,
    DEFAULT_VIDEO_MAXRATE_MBPS,
    FASTSTART_EXTENSIONS,
    FFMPEG_STDERR_MAX_LINES,
    FFMPEG_STDERR_SKIP_PREFIXES,
    VIDEO_BUFSIZE_MULTIPLIER,
)
from . import tools


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


def _stderr_suggests_faststart_failure(stderr_text):
    """`-movflags +faststart`(moov atom 이동) 단계가 특정 파일시스템/네트워크에서
    'Error writing trailer/closing file: Invalid argument'로 깨질 때를 감지한다.
    이 경우 faststart 없이 1회 재시도하면 성공하는 경우가 많다.
    (원본 CLI convert_one_file 506-528행 포팅)"""
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return (
        "error writing trailer: invalid argument" in low
        or "error closing file: invalid argument" in low
    )


def _summarize_ffmpeg_stderr(stderr_text):
    """실패 메시지/로그용으로 ffmpeg stderr를 요약한다.
    부트 로그(버전/설정/라이브러리) 라인을 걸러내고 최대 라인 수로 캡한다.
    (원본 CLI _summarize_ffmpeg_stderr 포팅; None 안전 처리 보강)"""
    if not stderr_text or not stderr_text.strip():
        return "(stderr 없음)"
    lines = [ln.strip() for ln in stderr_text.strip().splitlines() if ln.strip()]
    filtered = [
        ln
        for ln in lines
        if not any(ln.startswith(prefix) for prefix in FFMPEG_STDERR_SKIP_PREFIXES)
    ]
    if len(filtered) <= FFMPEG_STDERR_MAX_LINES:
        return "\n".join(filtered)
    head = 5
    tail = FFMPEG_STDERR_MAX_LINES - head - 1
    return "\n".join(filtered[:head] + ["..."] + filtered[-tail:])


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


def _safe_remove(path, wait=2.0):
    """있으면 지운다. 실패해도 예외를 내지 않는다.

    ffmpeg 를 끊은 직후에는 파일이 아직 잡혀 있을 수 있다. 특히 Chocolatey 등의 대리 실행 파일(shim)은
    자신이 먼저 끝나고 진짜 ffmpeg 가 조금 늦게 끝난다. 그 사이에 지우면 '사용 중' 으로 실패해 만들다 만
    파일이 남으므로, 잠겨 있으면 wait 초까지 다시 시도한다.
    """
    if not path:
        return
    deadline = time.monotonic() + wait
    while True:
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                return
            time.sleep(0.1)
        except OSError:
            return


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

    # 담을 스트림을 명시한다. 기본 선택에 맡기면 오디오는 한 트랙만, 자막은 mp4가 못 담는 형식이면
    # 조용히 빠진다. 비디오 첫 트랙 + 오디오 전부 + (mp4면) 텍스트 자막을 mov_text로.
    maps = ["-map", "0:v:0", "-map", "0:a?"]
    sub_codec_args = []
    if text_sub_indices and _output_wants_faststart(output_path):
        for index in text_sub_indices:
            maps += ["-map", f"0:s:{index}?"]
        sub_codec_args = ["-c:s", "mov_text"]

    if remux_only:
        # 자막은 mov_text로 옮겨야 하므로 -c copy 뒤에 -c:s 로 덮어쓴다(텍스트 변환은 순식간이다)
        cmd = [tools.ffmpeg(), "-y", "-i", input_path, *maps, "-c", "copy", *sub_codec_args]
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

    cmd = [tools.ffmpeg(), "-y"]
    if mode == "cuda":
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-i", input_path, *maps]

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

