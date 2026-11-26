"""비디오 remux/인코딩 파이프라인."""

import os

from ..config import (
    FASTSTART_DEFAULT,
    REMUX_THRESHOLD_MBPS,
    TEXT_SUB_CODECS,
)
from . import leftovers
from .errorlog import log_conversion_error
from .ffmpeg_cmd import (
    _build_ffmpeg_cmd,
    _force_mp4_ext,
    _output_wants_faststart,
    _safe_remove,
    _stderr_suggests_faststart_failure,
    _stderr_suggests_fatal_input_error,
    _stderr_suggests_nvenc_fail,
    _tmp_is_valid,
    _tmp_output_path,
    resolve_output_path,
    should_remux,
)
from .probe import get_video_info
from .runner import run_ffmpeg_and_track

_STUCK_MARKER = "STUCK_TIMEOUT"


def _is_stuck(stderr_text):
    return isinstance(stderr_text, str) and stderr_text.startswith(_STUCK_MARKER)


def _strip_stuck_marker(stderr_text):
    if _is_stuck(stderr_text):
        return stderr_text[len(_STUCK_MARKER):].lstrip("\n")
    return stderr_text


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

    def _is_cancel(stderr_text):
        return _cancelled() or stderr_text == "USER_CANCELLED"

    display_name = os.path.basename(file_path)
    src_path = os.path.abspath(os.path.normpath(file_path))
    max_width = settings.get("max_width", 1920)
    max_height = settings.get("max_height", 1080)
    need_scale = info["width"] > max_width or info["height"] > max_height

    remux_threshold = settings.get("remux_threshold_mbps", REMUX_THRESHOLD_MBPS)
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

    # 출력은 remux/재인코딩 모두 .mp4 로 통일한다(item 5).
    # remux(-c copy)를 mp4 로 담다가 코덱 비호환으로 실패하면 재인코딩 경로로 폴백한다.
    dest_path = _force_mp4_ext(
        os.path.abspath(
            os.path.normpath(
                resolve_output_path(file_path, output_dir, name_option, value)
            )
        )
    )
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    is_same_file = src_path == dest_path
    scale_filter = (
        f"scale={max_width}:{max_height}:"
        "force_original_aspect_ratio=decrease,"
        "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    )
    base_vf = scale_filter if need_scale else "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    vf = f"{base_vf},format=yuv420p"
    total_sec = info["duration_sec"]
    faststart = settings.get("faststart", FASTSTART_DEFAULT)
    text_sub_indices = [
        index
        for index, codec in enumerate(info.get("sub_codecs", []))
        if str(codec).lower() in TEXT_SUB_CODECS
    ]
    tmp_path = _tmp_output_path(dest_path)

    def _run(cmd):
        # 항상 5개 위치 인자만 전달(테스트가 monkeypatch 하는 시그니처와 일치).
        return run_ffmpeg_and_track(
            cmd, total_sec, progress_callback, cancel_event, tmp_path
        )

    def _attempt(is_remux, mode):
        """한 번의 변환 시도. faststart 트레일러 오류면 faststart 없이 1회 재시도."""
        def build(use_faststart):
            if is_remux:
                return _build_ffmpeg_cmd(
                    src_path, tmp_path, True, "", use_faststart, "cpu", settings,
                    text_sub_indices,
                )
            return _build_ffmpeg_cmd(
                src_path,
                tmp_path,
                False,
                vf,
                use_faststart,
                mode,
                settings,
                text_sub_indices,
            )

        rc, stderr_text = _run(build(faststart))
        if (
            rc != 0
            and not _is_cancel(stderr_text)
            and not _is_stuck(stderr_text)
            and faststart
            and _output_wants_faststart(dest_path)
            and _stderr_suggests_faststart_failure(stderr_text)
        ):
            _safe_remove(tmp_path)
            rc, stderr_text = _run(build(False))
        return rc, stderr_text

    def _fail(msg, rc, stderr_text, reason=""):
        _safe_remove(tmp_path)
        log_conversion_error(
            display_name, rc, _strip_stuck_marker(stderr_text), reason=reason
        )
        return "FAIL", msg

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
                return "COPY_DEL", "Remux 완료 및 원본 삭제됨"
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

    _STUCK_MSG = "진행 없음으로 강제 종료 (STUCK_TIMEOUT_SEC 초과)"

    # 앱이 강제로 끝나 지우지 못하면 다음 시작 때 지운다(core/leftovers.py)
    leftovers.remember(tmp_path)
    try:
        # ---- Remux 경로 ----
        if remux_only:
            rc, stderr_text = _attempt(True, "cpu")
            if _is_cancel(stderr_text):
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"
            if _is_stuck(stderr_text):
                return _fail(_STUCK_MSG, rc, stderr_text, reason=" (진행 없음으로 강제 종료)")
            if rc == 0:
                return _finalize_success("remux", copy=True)
            # remux 실패: 경로/입력 치명 오류면 중단, 아니면 재인코딩으로 폴백.
            _safe_remove(tmp_path)
            if _stderr_suggests_fatal_input_error(stderr_text):
                return _fail("입력/출력 경로 오류로 변환 중단", rc, stderr_text)
            print(
                "Remux(mp4 -c copy) 실패 -> 재인코딩 경로로 폴백 "
                f"({file_path})"
            )
            remux_only = False  # 아래 재인코딩 체인으로 진행

        # ---- 재인코딩 경로 (단계별 폴백) ----
        mode = "cuda"
        rc, stderr_text = _attempt(False, mode)
        if _is_cancel(stderr_text):
            _safe_remove(tmp_path)
            return "CANCELLED", "사용자 취소됨"
        if _is_stuck(stderr_text):
            return _fail(_STUCK_MSG, rc, stderr_text, reason=" (진행 없음으로 강제 종료)")

        if rc != 0 and _stderr_suggests_fatal_input_error(stderr_text):
            return _fail("입력/출력 경로 오류로 변환 중단", rc, stderr_text)

        if rc != 0 and _stderr_suggests_nvenc_fail(stderr_text):
            print(
                "CUDA 하드웨어 디코드 실패 -> CPU 디코딩 + GPU 인코딩 "
                f"폴백 시도 ({file_path})"
            )
            mode = "cpu_decode"
            rc, stderr_text = _attempt(False, mode)
            if _is_cancel(stderr_text):
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"
            if _is_stuck(stderr_text):
                return _fail(_STUCK_MSG, rc, stderr_text, reason=" (진행 없음으로 강제 종료)")

        if rc != 0:
            print(
                "NVENC 가속 실패 -> 완전 CPU 인코딩(libx264) 최종 폴백 "
                f"시도 ({file_path})"
            )
            mode = "cpu"
            rc, stderr_text = _attempt(False, mode)
            if _is_cancel(stderr_text):
                _safe_remove(tmp_path)
                return "CANCELLED", "사용자 취소됨"
            if _is_stuck(stderr_text):
                return _fail(_STUCK_MSG, rc, stderr_text, reason=" (진행 없음으로 강제 종료)")

        if rc == 0:
            return _finalize_success(mode, copy=False)
        return _fail(f"인코딩 오류 (반환코드: {rc})", rc, stderr_text)
    except Exception as exc:
        _safe_remove(tmp_path)
        log_conversion_error(display_name, -1, str(exc))
        return "FAIL", f"변환 예외: {exc}"
    finally:
        if not os.path.exists(tmp_path):
            leftovers.forget(tmp_path)
