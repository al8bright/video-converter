"""비디오 remux/인코딩 파이프라인."""

import os

from ..config import (
    FASTSTART_DEFAULT,
    REMUX_THRESHOLD_MBPS,
    TEXT_SUB_CODECS,
)
from .ffmpeg_cmd import (
    _build_ffmpeg_cmd,
    _force_mp4_ext,
    _safe_remove,
    _stderr_suggests_fatal_input_error,
    _stderr_suggests_nvenc_fail,
    _tmp_is_valid,
    _tmp_output_path,
    resolve_output_path,
    should_remux,
)
from .probe import get_video_info
from .runner import run_ffmpeg_and_track


def process_video(
    file_path,
    output_dir,
    name_option,
    value,
    settings,
    progress_callback=None,
    cancel_event=None,
):
    """비디오 변환 핵심 파이프라인."""
    if not os.path.exists(file_path):
        return "FAIL", "파일이 존재하지 않습니다."

    info = get_video_info(file_path)
    if not info:
        return "FAIL", "비디오 메타데이터 분석 실패."

    def _cancelled():
        return bool(cancel_event and cancel_event.is_set())

    src_path = os.path.abspath(os.path.normpath(file_path))
    max_width = settings.get("max_width", 1920)
    max_height = settings.get("max_height", 1080)
    need_scale = info["width"] > max_width or info["height"] > max_height

    remux_threshold = settings.get(
        "remux_threshold_mbps", REMUX_THRESHOLD_MBPS
    )
    try:
        size_bytes = os.path.getsize(file_path)
    except OSError:
        size_bytes = 0
    remux_only = should_remux(
        info["bit_rate"],
        info["duration_sec"],
        size_bytes,
        remux_threshold,
        need_scale,
    )

    dest_path = os.path.abspath(
        os.path.normpath(
            resolve_output_path(file_path, output_dir, name_option, value)
        )
    )
    if not remux_only:
        dest_path = _force_mp4_ext(dest_path)
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    is_same_file = src_path == dest_path
    scale_filter = (
        f"scale={max_width}:{max_height}:"
        "force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    base_vf = (
        scale_filter if need_scale else "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    vf = f"{base_vf},format=yuv420p"
    total_sec = info["duration_sec"]
    faststart = settings.get("faststart", FASTSTART_DEFAULT)
    text_sub_indices = [
        index
        for index, codec in enumerate(info.get("sub_codecs", []))
        if str(codec).lower() in TEXT_SUB_CODECS
    ]
    tmp_path = _tmp_output_path(dest_path)

    def _finalize_success(mode_label, copy=False):
        if not _tmp_is_valid(tmp_path):
            _safe_remove(tmp_path)
            return "FAIL", "산출물 무결성 검증 실패(빈 파일/손상)"
        try:
            os.replace(tmp_path, dest_path)
        except OSError as exc:
            _safe_remove(tmp_path)
            return "FAIL", f"결과 파일 교체 실패: {exc}"
        if copy:
            if settings.get("delete_source", False) and not is_same_file:
                _safe_remove(file_path)
                return "SUCCESS_DEL", "Remux 완료 및 원본 삭제됨"
            return "COPY", "Remux 완료 (비트레이트 기준 미달, 재인코딩 없이 복사)"
        if settings.get("delete_source", False) and not is_same_file:
            try:
                os.remove(file_path)
                return (
                    "SUCCESS_DEL",
                    f"변환 완료 및 원본 삭제됨 (모드: {mode_label})",
                )
            except OSError as exc:
                return "SUCCESS", f"변환 완료 (원본 삭제 실패: {exc})"
        return "SUCCESS", f"변환 완료 (모드: {mode_label})"

    try:
        if remux_only:
            cmd = _build_ffmpeg_cmd(
                src_path, tmp_path, True, "", faststart, "cpu", settings
            )
            rc, stderr_full = run_ffmpeg_and_track(
                cmd,
                total_sec,
                progress_callback,
                cancel_event,
                tmp_path,
            )
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"
            if rc == 0:
                return _finalize_success("remux", copy=True)
            _safe_remove(tmp_path)
            return "FAIL", f"Remux 실패 (코드: {rc})"

        mode = "cuda"
        cmd = _build_ffmpeg_cmd(
            src_path,
            tmp_path,
            False,
            vf,
            faststart,
            mode,
            settings,
            text_sub_indices,
        )
        rc, stderr_full = run_ffmpeg_and_track(
            cmd, total_sec, progress_callback, cancel_event, tmp_path
        )
        if _cancelled() or stderr_full == "USER_CANCELLED":
            _safe_remove(tmp_path)
            return "CANCELLED", "사용자 취소됨"

        if rc != 0 and _stderr_suggests_fatal_input_error(stderr_full):
            _safe_remove(tmp_path)
            return "FAIL", "입력/출력 경로 오류로 변환 중단"

        if rc != 0 and _stderr_suggests_nvenc_fail(stderr_full):
            print(
                "CUDA 하드웨어 디코드 실패 -> CPU 디코딩 + GPU 인코딩 "
                f"폴백 시도 ({file_path})"
            )
            mode = "cpu_decode"
            cmd = _build_ffmpeg_cmd(
                src_path,
                tmp_path,
                False,
                vf,
                faststart,
                mode,
                settings,
                text_sub_indices,
            )
            rc, stderr_full = run_ffmpeg_and_track(
                cmd, total_sec, progress_callback, cancel_event, tmp_path
            )
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"

        if rc != 0:
            print(
                "NVENC 가속 실패 -> 완전 CPU 인코딩(libx264) 최종 폴백 "
                f"시도 ({file_path})"
            )
            mode = "cpu"
            cmd = _build_ffmpeg_cmd(
                src_path,
                tmp_path,
                False,
                vf,
                faststart,
                mode,
                settings,
                text_sub_indices,
            )
            rc, stderr_full = run_ffmpeg_and_track(
                cmd, total_sec, progress_callback, cancel_event, tmp_path
            )
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"

        if rc == 0:
            return _finalize_success(mode, copy=False)
        _safe_remove(tmp_path)
        return "FAIL", f"인코딩 오류 (반환코드: {rc})"
    except Exception as exc:
        _safe_remove(tmp_path)
        return "FAIL", f"변환 예외: {exc}"

