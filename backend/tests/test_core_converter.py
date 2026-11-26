"""videoconverter.core 의 순수 로직 함수 단위 테스트.

gui.app이 공개 API로 임포트해 사용하는 핵심 로직
(파일 경로 생성 = resolve_output_path, 명령 생성 = _build_ffmpeg_cmd 등)을 대상으로 한다.
subprocess / ffmpeg / ctypes / GUI 이벤트 루프가 필요한 함수는 제외했다.
"""
import os
import threading

import pytest

import videoconverter.core as cc
from videoconverter.core import pipeline


# ---------------------------------------------------------------------------
# resolve_output_path : 출력 경로 및 파일명 규칙 결합 로직
# ---------------------------------------------------------------------------
class TestResolveOutputPath:
    def test_suffix_appends_before_extension(self):
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "movie.mp4"),
            output_dir="",
            name_option="suffix",
            value="_cuda",
        )
        assert os.path.basename(result) == "movie_cuda.mp4"

    def test_prefix_prepends_before_name(self):
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "movie.mkv"),
            output_dir="",
            name_option="prefix",
            value="enc_",
        )
        assert os.path.basename(result) == "enc_movie.mkv"

    def test_overwrite_keeps_original_filename(self):
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "movie.mov"),
            output_dir="",
            name_option="overwrite",
            value="ignored",
        )
        assert os.path.basename(result) == "movie.mov"

    def test_empty_output_dir_uses_source_directory(self):
        src = os.path.join(os.getcwd(), "clip.mp4")
        result = cc.resolve_output_path(src, "", "suffix", "_x")
        # 출력 디렉터리를 지정하지 않으면 원본과 동일한 폴더에 저장된다.
        assert os.path.dirname(result) == os.path.dirname(os.path.abspath(src))

    def test_custom_output_dir_is_used(self, tmp_path):
        out_dir = str(tmp_path / "out")
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "movie.mp4"), out_dir, "suffix", "_c"
        )
        assert os.path.dirname(result) == os.path.abspath(out_dir)
        assert os.path.basename(result) == "movie_c.mp4"

    def test_extension_preserved_with_multidot_name(self):
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "my.show.s01e01.ts"), "", "suffix", "_cuda"
        )
        # splitext는 마지막 확장자만 분리하므로 앞쪽 점들은 이름에 남는다.
        assert os.path.basename(result) == "my.show.s01e01_cuda.ts"

    def test_empty_suffix_value_produces_same_name(self):
        result = cc.resolve_output_path(
            os.path.join("C:", "vids", "movie.mp4"), "", "suffix", ""
        )
        assert os.path.basename(result) == "movie.mp4"


# ---------------------------------------------------------------------------
# _build_ffmpeg_cmd : ffmpeg 인자 생성 로직
# ---------------------------------------------------------------------------
BASE_SETTINGS = {
    "video_maxrate_mbps": 3.5,
    "audio_bitrate": "128k",
    "nvenc_preset": "p5",
}


class TestBuildFfmpegCmd:
    def test_remux_uses_stream_copy(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mp4", "out.mp4", remux_only=True, vf="", faststart=False,
            mode="cpu", settings=BASE_SETTINGS,
        )
        assert os.path.splitext(os.path.basename(cmd[0]))[0].lower() == "ffmpeg"  # PATH 에 있으면 전체 경로
        assert "-c" in cmd and "copy" in cmd
        # remux 모드에서는 재인코딩 코덱 인자가 없어야 한다.
        assert "h264_nvenc" not in cmd
        assert "libx264" not in cmd
        assert cmd[-1] == "out.mp4"

    def test_remux_faststart_flag_added(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mp4", "out.mp4", remux_only=True, vf="", faststart=True,
            mode="cpu", settings=BASE_SETTINGS,
        )
        assert "-movflags" in cmd
        assert "+faststart" in cmd

    def test_cuda_mode_uses_nvenc_and_hwaccel(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="scale=1920:1080",
            faststart=False, mode="cuda", settings=BASE_SETTINGS,
        )
        assert "-hwaccel" in cmd and "cuda" in cmd
        assert "h264_nvenc" in cmd
        assert "-preset" in cmd and "p5" in cmd
        assert cmd[-1] == "out.mp4"

    def test_cpu_decode_mode_uses_nvenc_without_hwaccel(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="scale=1920:1080",
            faststart=False, mode="cpu_decode", settings=BASE_SETTINGS,
        )
        assert "h264_nvenc" in cmd
        assert "-hwaccel" not in cmd  # CPU 디코딩이므로 하드웨어 가속 없음

    def test_cpu_mode_uses_libx264(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="scale=1920:1080",
            faststart=False, mode="cpu", settings=BASE_SETTINGS,
        )
        assert "libx264" in cmd
        assert "h264_nvenc" not in cmd
        assert "-hwaccel" not in cmd

    def test_bitrate_and_bufsize_derived_from_settings(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="x", faststart=False,
            mode="cuda", settings={"video_maxrate_mbps": 5.0, "audio_bitrate": "192k"},
        )
        assert "5.0M" in cmd           # b:v / maxrate
        assert "10.0M" in cmd          # bufsize = maxrate * 2
        assert "192k" in cmd           # audio bitrate

    def test_audio_defaults_when_missing(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="x", faststart=False,
            mode="cuda", settings={},
        )
        # 기본값: 3.5Mbps, 128k
        assert "3.5M" in cmd
        assert "128k" in cmd

    def test_encode_faststart_inserted_before_output(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="x", faststart=True,
            mode="cuda", settings=BASE_SETTINGS,
        )
        assert cmd[-1] == "out.mp4"
        assert cmd[-2] == "+faststart"
        assert cmd[-3] == "-movflags"

    def test_vf_filter_passed_through(self):
        vf = "scale=1280:720:force_original_aspect_ratio=decrease,format=yuv420p"
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf=vf, faststart=False,
            mode="cuda", settings=BASE_SETTINGS,
        )
        assert "-vf" in cmd
        assert cmd[cmd.index("-vf") + 1] == vf


# ---------------------------------------------------------------------------
# _time_str_to_seconds : ffmpeg time= 문자열 -> 초 변환
# ---------------------------------------------------------------------------
class TestTimeStrToSeconds:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("00:00:00.00", 0.0),
            ("00:01:30.00", 90.0),
            ("01:00:00.00", 3600.0),
            ("01:02:03.50", 3723.5),
            ("  00:00:10.25  ", 10.25),  # 공백은 strip 처리
        ],
    )
    def test_valid_time_strings(self, text, expected):
        assert cc._time_str_to_seconds(text) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "text",
        ["", "N/A", "90", "00:90", "aa:bb:cc", "1:2:3:4"],
    )
    def test_invalid_time_strings_return_none(self, text):
        assert cc._time_str_to_seconds(text) is None


# ---------------------------------------------------------------------------
# _stderr_suggests_nvenc_fail : NVENC 실패 감지 로직
# ---------------------------------------------------------------------------
class TestStderrSuggestsNvencFail:
    @pytest.mark.parametrize(
        "text",
        [
            "Cannot load h264_nvenc",
            "[hevc_nvenc @ ...] error",
            "No capable devices found",
            "10 bit encode not supported",
            "Could not open encoder before EOF",
            "Error while opening encoder for output stream",
        ],
    )
    def test_detects_known_failure_markers(self, text):
        assert cc._stderr_suggests_nvenc_fail(text) is True

    def test_case_insensitive_match(self):
        assert cc._stderr_suggests_nvenc_fail("H264_NVENC FAILED") is True

    def test_empty_or_none_returns_false(self):
        assert cc._stderr_suggests_nvenc_fail("") is False
        assert cc._stderr_suggests_nvenc_fail(None) is False

    def test_unrelated_stderr_returns_false(self):
        assert cc._stderr_suggests_nvenc_fail("frame=100 fps=30 time=00:00:03") is False


# ---------------------------------------------------------------------------
# _stderr_suggests_fatal_input_error : 재시도 무의미한 입력/경로 오류 감지
# ---------------------------------------------------------------------------
class TestStderrSuggestsFatalInputError:
    @pytest.mark.parametrize(
        "text",
        [
            "in.mp4: No such file or directory",
            "Output out.mp4 same as Input #0 - exiting",
            "Permission denied",
            "Invalid data found when processing input",
        ],
    )
    def test_detects_fatal_markers(self, text):
        assert cc._stderr_suggests_fatal_input_error(text) is True

    def test_empty_or_none_returns_false(self):
        assert cc._stderr_suggests_fatal_input_error("") is False
        assert cc._stderr_suggests_fatal_input_error(None) is False

    def test_nvenc_error_is_not_fatal_input(self):
        # NVENC 인코더 실패는 폴백 대상이지 입력/경로 치명오류가 아니다.
        assert cc._stderr_suggests_fatal_input_error("Cannot load h264_nvenc") is False


# ---------------------------------------------------------------------------
# should_remux (H-1) : Remux 판정 로직
# ---------------------------------------------------------------------------
class TestShouldRemux:
    def test_low_bitrate_no_scale_remuxes(self):
        assert cc.should_remux(2_000_000, 100.0, 999, threshold_mbps=4.0, need_scale=False) is True

    def test_high_bitrate_does_not_remux(self):
        assert cc.should_remux(8_000_000, 100.0, 999, threshold_mbps=4.0, need_scale=False) is False

    def test_need_scale_never_remuxes_even_if_low_bitrate(self):
        # 저비트레이트라도 다운스케일이 필요하면 remux 금지 (해상도 제한 준수).
        assert cc.should_remux(1_000_000, 100.0, 999, threshold_mbps=4.0, need_scale=True) is False

    def test_na_bitrate_estimated_from_size_and_duration(self):
        # bit_rate=0(N/A). 10초 동안 1,000,000 bytes -> 800,000 bps < 4Mbps -> remux.
        assert cc.should_remux(0, 10.0, 1_000_000, threshold_mbps=4.0, need_scale=False) is True

    def test_na_bitrate_high_estimate_does_not_remux(self):
        # 10초 동안 20,000,000 bytes -> 16Mbps -> remux 안 함.
        assert cc.should_remux(0, 10.0, 20_000_000, threshold_mbps=4.0, need_scale=False) is False

    def test_unknown_bitrate_and_duration_does_not_remux(self):
        # 추정 불가(둘 다 0)면 안전하게 재인코딩.
        assert cc.should_remux(0, 0.0, 0, threshold_mbps=4.0, need_scale=False) is False


# ---------------------------------------------------------------------------
# _force_mp4_ext (H-3) : 재인코딩 출력 확장자 강제
# ---------------------------------------------------------------------------
class TestForceMp4Ext:
    @pytest.mark.parametrize(
        "src,expected",
        [
            (os.path.join("d", "a.mkv"), "a.mp4"),
            (os.path.join("d", "a.avi"), "a.mp4"),
            (os.path.join("d", "a.mp4"), "a.mp4"),
            (os.path.join("d", "my.show.s01.ts"), "my.show.s01.mp4"),
        ],
    )
    def test_forces_mp4(self, src, expected):
        assert os.path.basename(cc._force_mp4_ext(src)) == expected


# ---------------------------------------------------------------------------
# faststart 게이팅 (L-1) : mp4/mov 계열에만 +movflags
# ---------------------------------------------------------------------------
class TestFaststartGating:
    def test_mkv_output_gets_no_faststart_on_remux(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mkv", remux_only=True, vf="", faststart=True,
            mode="cpu", settings=BASE_SETTINGS,
        )
        assert "-movflags" not in cmd

    def test_ts_output_gets_no_faststart_on_encode(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.ts", "out.ts", remux_only=False, vf="x", faststart=True,
            mode="cuda", settings=BASE_SETTINGS,
        )
        assert "-movflags" not in cmd

    def test_mov_output_gets_faststart(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mov", remux_only=False, vf="x", faststart=True,
            mode="cuda", settings=BASE_SETTINGS,
        )
        assert "-movflags" in cmd and "+faststart" in cmd


# ---------------------------------------------------------------------------
# 트랙 보존 / 자막 매핑 (H-2)
# ---------------------------------------------------------------------------
class TestStreamMapping:
    def test_encode_maps_video_and_all_audio(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="x", faststart=False,
            mode="cuda", settings=BASE_SETTINGS,
        )
        # 비디오 첫 트랙 + 모든 오디오(옵셔널) 매핑
        assert "0:v:0" in cmd
        assert "0:a?" in cmd

    def test_text_subs_mapped_as_mov_text_for_mp4(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mp4", remux_only=False, vf="x", faststart=False,
            mode="cuda", settings=BASE_SETTINGS, text_sub_indices=[0, 2],
        )
        assert "0:s:0?" in cmd and "0:s:2?" in cmd
        assert "-c:s" in cmd and "mov_text" in cmd

    def test_subs_not_mapped_for_non_mp4_output(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mkv", remux_only=False, vf="x", faststart=False,
            mode="cpu", settings=BASE_SETTINGS, text_sub_indices=[0],
        )
        assert "mov_text" not in cmd
        assert not any(str(a).startswith("0:s:") for a in cmd)

    def test_remux_preserves_all_streams_with_copy(self):
        cmd = cc._build_ffmpeg_cmd(
            "in.mkv", "out.mkv", remux_only=True, vf="", faststart=False,
            mode="cpu", settings=BASE_SETTINGS,
        )
        assert "-c" in cmd and "copy" in cmd


# ---------------------------------------------------------------------------
# process_video : 임시파일 스테이징 / 원자 교체 / 취소 (C-1, H-4, 계약#2)
# run_ffmpeg_and_track 와 get_video_info 를 monkeypatch 하여 ffmpeg 없이 검증.
# ---------------------------------------------------------------------------
ENCODE_INFO = {"duration_sec": 100.0, "bit_rate": 20_000_000, "width": 1920, "height": 1080, "sub_codecs": []}
REMUX_INFO = {"duration_sec": 100.0, "bit_rate": 1_000_000, "width": 1280, "height": 720, "sub_codecs": []}

BASE_PV_SETTINGS = {
    "video_maxrate_mbps": 3.5, "audio_bitrate": "128k",
    "max_width": 1920, "max_height": 1080, "remux_threshold_mbps": 4.0,
    "faststart": True, "delete_source": False, "nvenc_preset": "p5",
}


class TestProcessVideoStaging:
    def _patch(self, monkeypatch, info, run_impl):
        monkeypatch.setattr(pipeline, "get_video_info", lambda p: dict(info))
        monkeypatch.setattr(pipeline, "run_ffmpeg_and_track", run_impl)

    def test_success_uses_tmp_then_atomic_replace(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"original-source-bytes" * 100)
        seen = {}

        def fake_run(cmd, total, cb, ev, output_path=None):
            out = output_path or cmd[-1]
            seen["out"] = out
            # 인코딩 중에는 임시 파일만 존재해야 하고, dest 는 아직 없어야 한다.
            assert ".part-" in os.path.basename(out)
            with open(out, "wb") as f:
                f.write(b"x" * 5000)
            return 0, ""

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS))
        assert status == "SUCCESS"
        # 재인코딩이므로 .mp4 로 강제
        dest = tmp_path / "movie_c.mp4"
        assert dest.exists() and dest.stat().st_size == 5000
        # 임시파일은 남지 않아야 함
        assert not any(p.name.startswith("movie_c.mp4.part-") for p in tmp_path.iterdir())

    def test_same_file_overwrite_is_safe(self, monkeypatch, tmp_path):
        # 덮어쓰기 + 동일폴더 mp4 → dest == src. 임시 스테이징으로 안전 교체(C-1).
        src = tmp_path / "clip.mp4"
        src.write_bytes(b"orig" * 100)

        def fake_run(cmd, total, cb, ev, output_path=None):
            out = output_path or cmd[-1]
            # ffmpeg 입력과 출력이 물리적으로 달라야 한다(임시파일).
            in_idx = cmd.index("-i") + 1
            assert os.path.abspath(cmd[in_idx]) != os.path.abspath(out)
            with open(out, "wb") as f:
                f.write(b"converted-content" * 100)
            return 0, ""

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(str(src), "", "overwrite", "", dict(BASE_PV_SETTINGS))
        assert status == "SUCCESS"
        assert src.exists()
        assert src.read_bytes().startswith(b"converted-content")

    def test_cancel_returns_cancelled_and_cleans_tmp(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)

        def fake_run(cmd, total, cb, ev, output_path=None):
            # ffmpeg 가 취소로 kill 된 상황을 흉내 (tmp 미생성)
            return -1, "USER_CANCELLED"

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        ev = threading.Event()
        ev.set()
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS), None, ev)
        assert status == "CANCELLED"
        assert not any(".part-" in p.name for p in tmp_path.iterdir())

    def test_failure_cleans_tmp_and_reports_fail(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)
        calls = {"n": 0}

        def fake_run(cmd, total, cb, ev, output_path=None):
            calls["n"] += 1
            out = output_path or cmd[-1]
            with open(out, "wb") as f:
                f.write(b"partial")  # < 1024 bytes → 무결성 실패로도 걸러짐
            return 1, "generic encoder meltdown"

        self._patch(monkeypatch, REMUX_INFO if False else ENCODE_INFO, fake_run)
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS))
        assert status == "FAIL"
        # cuda -> cpu 폴백까지 재시도(입력오류 아님 & nvenc아님 → step3만) 되었어야 함
        assert calls["n"] >= 2
        assert not any(".part-" in p.name for p in tmp_path.iterdir())

    def test_fatal_input_error_short_circuits_fallback(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)
        calls = {"n": 0}

        def fake_run(cmd, total, cb, ev, output_path=None):
            calls["n"] += 1
            return 1, "movie.mkv: No such file or directory"

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS))
        assert status == "FAIL"
        assert calls["n"] == 1  # 폴백 반복 없이 조기 중단

    def test_remux_forces_mp4_extension(self, monkeypatch, tmp_path):
        # item 5: remux 출력도 .mp4 로 통일된다(과거엔 원본 확장자 유지였음).
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)

        def fake_run(cmd, total, cb, ev, output_path=None):
            out = output_path or cmd[-1]
            # remux(-c copy) 이므로 재인코딩 코덱 인자가 없어야 하고 출력은 .mp4 여야 한다.
            assert "copy" in cmd
            assert out.endswith(".mp4")
            with open(out, "wb") as f:
                f.write(b"y" * 5000)
            return 0, ""

        self._patch(monkeypatch, REMUX_INFO, fake_run)
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS))
        assert status == "COPY"
        assert (tmp_path / "movie_c.mp4").exists()
        assert not (tmp_path / "movie_c.mkv").exists()

    def test_delete_source_removes_original_when_different(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)

        def fake_run(cmd, total, cb, ev, output_path=None):
            out = output_path or cmd[-1]
            with open(out, "wb") as f:
                f.write(b"z" * 5000)
            return 0, ""

        s = dict(BASE_PV_SETTINGS)
        s["delete_source"] = True
        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(str(src), str(tmp_path), "suffix", "_c", s)
        assert status == "SUCCESS_DEL"
        assert not src.exists()
        assert (tmp_path / "movie_c.mp4").exists()


# ---------------------------------------------------------------------------
# _summarize_ffmpeg_stderr : 부트로그 필터 + 라인 캡 (포팅 항목 4)
# ---------------------------------------------------------------------------
class TestSummarizeFfmpegStderr:
    def test_none_and_empty_return_placeholder(self):
        assert cc._summarize_ffmpeg_stderr(None) == "(stderr 없음)"
        assert cc._summarize_ffmpeg_stderr("") == "(stderr 없음)"
        assert cc._summarize_ffmpeg_stderr("   \n  ") == "(stderr 없음)"

    def test_filters_boot_log_prefixes(self):
        text = (
            "ffmpeg version 8.1 blah\n"
            "built with gcc\n"
            "configuration: --enable-cuda\n"
            "libavutil 58\n"
            "Real error line: could not open encoder\n"
        )
        out = cc._summarize_ffmpeg_stderr(text)
        assert "Real error line: could not open encoder" in out
        assert "ffmpeg version" not in out
        assert "libavutil" not in out
        assert "configuration:" not in out

    def test_caps_long_output_with_ellipsis(self):
        lines = "\n".join(f"error line {i}" for i in range(100))
        out = cc._summarize_ffmpeg_stderr(lines)
        result_lines = out.splitlines()
        # 최대 라인 수(20) 이내 + 생략 표시(...) 포함
        assert len(result_lines) <= 20
        assert "..." in result_lines
        assert result_lines[0] == "error line 0"
        assert result_lines[-1] == "error line 99"


# ---------------------------------------------------------------------------
# _stderr_suggests_faststart_failure : faststart 트레일러 오류 감지 (포팅 항목 2)
# ---------------------------------------------------------------------------
class TestStderrSuggestsFaststartFailure:
    @pytest.mark.parametrize(
        "text",
        [
            "Error writing trailer: Invalid argument",
            "av_interleaved_write_frame(): Error closing file: Invalid argument",
            "ERROR WRITING TRAILER: INVALID ARGUMENT",
        ],
    )
    def test_detects_faststart_trailer_errors(self, text):
        assert cc._stderr_suggests_faststart_failure(text) is True

    def test_unrelated_and_empty_return_false(self):
        assert cc._stderr_suggests_faststart_failure("") is False
        assert cc._stderr_suggests_faststart_failure(None) is False
        assert cc._stderr_suggests_faststart_failure("could not open encoder") is False


# ---------------------------------------------------------------------------
# 프로세스 레지스트리 + terminate_all_processes (포팅 항목 6 / 계약 3)
# ---------------------------------------------------------------------------
class _DummyProc:
    def __init__(self):
        self.kill_count = 0

    def kill(self):
        self.kill_count += 1


class TestProcessRegistry:
    def test_public_api_is_exported(self):
        # 계약: from videoconverter.core import terminate_all_processes
        from videoconverter.core import terminate_all_processes

        assert callable(terminate_all_processes)

    def test_terminate_kills_all_registered(self):
        from videoconverter.core import runner

        runner._active_procs.clear()
        procs = [_DummyProc(), _DummyProc(), _DummyProc()]
        for proc in procs:
            runner._register_proc(proc)
        try:
            cc.terminate_all_processes()
            assert all(proc.kill_count == 1 for proc in procs)
        finally:
            runner._active_procs.clear()

    def test_terminate_is_idempotent_and_safe(self):
        from videoconverter.core import runner

        runner._active_procs.clear()
        proc = _DummyProc()
        runner._register_proc(proc)
        try:
            cc.terminate_all_processes()
            cc.terminate_all_processes()  # 두 번째 호출도 예외 없이 안전
            assert proc.kill_count >= 1
        finally:
            runner._active_procs.clear()

    def test_terminate_noop_when_empty(self):
        from videoconverter.core import runner

        runner._active_procs.clear()
        cc.terminate_all_processes()  # 실행 중 프로세스 없으면 no-op

    def test_unregister_removes_from_registry(self):
        from videoconverter.core import runner

        runner._active_procs.clear()
        proc = _DummyProc()
        runner._register_proc(proc)
        runner._unregister_proc(proc)
        try:
            cc.terminate_all_processes()
            assert proc.kill_count == 0  # 이미 해제되어 kill 대상 아님
        finally:
            runner._active_procs.clear()


# ---------------------------------------------------------------------------
# log_conversion_error : UTF-8 영구 에러 로그 (포팅 항목 3)
# ---------------------------------------------------------------------------
class TestConversionErrorLog:
    def test_writes_utf8_log_with_summary(self, tmp_path):
        log_dir = tmp_path / "logs"
        path = cc.log_conversion_error(
            "한글파일.mkv",
            1,
            "ffmpeg version 8.1\nReal failure: could not open encoder",
            log_dir=str(log_dir),
        )
        assert path is not None and os.path.exists(path)
        content = open(path, encoding="utf-8").read()
        assert "한글파일.mkv" in content
        assert "Return Code: 1" in content
        assert "could not open encoder" in content
        # 부트 로그는 요약에서 제거됨
        assert "ffmpeg version" not in content

    def test_never_raises_on_bad_dir(self, tmp_path):
        # 파일을 디렉터리 자리에 두어 makedirs 실패를 유도 → None 반환(예외 없음)
        clash = tmp_path / "notadir"
        clash.write_text("x")
        result = cc.log_conversion_error(
            "f.mkv", 1, "boom", log_dir=str(clash / "sub")
        )
        assert result is None


# ---------------------------------------------------------------------------
# pipeline 포팅 동작: faststart 재시도 / stuck / remux→재인코딩 폴백
# ---------------------------------------------------------------------------
class TestPipelinePortedBehavior:
    def _patch(self, monkeypatch, info, run_impl):
        monkeypatch.setattr(pipeline, "get_video_info", lambda p: dict(info))
        monkeypatch.setattr(pipeline, "run_ffmpeg_and_track", run_impl)

    def test_faststart_invalid_argument_retries_without_faststart(
        self, monkeypatch, tmp_path
    ):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)
        cmds = []

        def fake_run(cmd, total, cb, ev, output_path=None):
            cmds.append(list(cmd))
            out = output_path or cmd[-1]
            if len(cmds) == 1:
                # 1차: faststart 포함, trailer invalid argument 로 실패
                assert "+faststart" in cmd
                return 1, "Error writing trailer: Invalid argument"
            # 2차: faststart 없이 재시도 → 성공
            assert "+faststart" not in cmd
            with open(out, "wb") as f:
                f.write(b"ok" * 3000)
            return 0, ""

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(
            str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS)
        )
        assert status == "SUCCESS"
        assert len(cmds) == 2
        assert (tmp_path / "movie_c.mp4").exists()

    def test_stuck_timeout_returns_fail(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)

        def fake_run(cmd, total, cb, ev, output_path=None):
            # 러너가 행 감지로 죽인 상황 재현: STUCK_TIMEOUT 마커 반환
            return 1, "STUCK_TIMEOUT\nframe=10 time=00:00:01"

        self._patch(monkeypatch, ENCODE_INFO, fake_run)
        status, msg = cc.process_video(
            str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS)
        )
        assert status == "FAIL"
        assert "강제 종료" in msg
        assert not any(".part-" in p.name for p in tmp_path.iterdir())

    def test_remux_falls_back_to_reencode_on_codec_incompat(
        self, monkeypatch, tmp_path
    ):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)
        modes = []

        def fake_run(cmd, total, cb, ev, output_path=None):
            out = output_path or cmd[-1]
            if "copy" in cmd:
                # remux(-c copy) → mp4 코덱 비호환으로 실패(치명 입력오류 아님)
                modes.append("remux")
                return 1, "Could not write header ... codec not currently supported in container"
            # 재인코딩 폴백 → 성공
            modes.append("encode")
            with open(out, "wb") as f:
                f.write(b"enc" * 2000)
            return 0, ""

        self._patch(monkeypatch, REMUX_INFO, fake_run)
        status, msg = cc.process_video(
            str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS)
        )
        assert status == "SUCCESS"
        assert modes[0] == "remux" and "encode" in modes
        assert (tmp_path / "movie_c.mp4").exists()

    def test_remux_fatal_input_error_does_not_fallback(self, monkeypatch, tmp_path):
        src = tmp_path / "movie.mkv"
        src.write_bytes(b"orig" * 100)
        calls = {"n": 0}

        def fake_run(cmd, total, cb, ev, output_path=None):
            calls["n"] += 1
            return 1, "movie.mkv: No such file or directory"

        self._patch(monkeypatch, REMUX_INFO, fake_run)
        status, msg = cc.process_video(
            str(src), str(tmp_path), "suffix", "_c", dict(BASE_PV_SETTINGS)
        )
        assert status == "FAIL"
        assert calls["n"] == 1  # 치명 입력오류는 재인코딩 폴백 없이 즉시 중단
