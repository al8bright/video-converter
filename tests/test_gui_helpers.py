"""videoconverter 패키지의 GUI 비의존 순수 헬퍼 로직 테스트.

- parse_dropped_files: 드래그앤드롭 문자열 파싱
- SUPPORTED_EXTENSIONS 를 이용한 폴더 스캔 필터 규칙
- hardware.recommend_parallel_jobs 실제 구현의 VRAM 티어
- 변환 반환 상태와 내부 대기열 상태의 매핑·재처리 판정·결과 집계

CTk 위젯 생성이나 이벤트 루프(mainloop)가 필요한 코드는 대상에서 제외한다.
각 신규 모듈은 위젯을 인스턴스화하지 않고 임포트만 하므로 헤드리스에서도 안전하다.
"""
import os

import pytest

from videoconverter.config import SUPPORTED_EXTENSIONS
from videoconverter.gui.dnd import parse_dropped_files
from videoconverter.hardware import recommend_parallel_jobs
from videoconverter.jobs.executor import (
    QueueItemState,
    format_result_summary,
    process_status_to_state,
    should_reprocess,
    summarize_item_states,
)


# ---------------------------------------------------------------------------
# parse_dropped_files : tkinterdnd2 드롭 데이터 파싱
# 존재하는 경로만 반환하므로 tmp_path 로 실제 파일을 만들어 검증한다.
# ---------------------------------------------------------------------------
class TestParseDroppedFiles:
    def test_single_plain_path(self, tmp_path):
        f = tmp_path / "movie.mp4"
        f.write_text("x")
        result = parse_dropped_files(str(f))
        assert len(result) == 1
        assert os.path.normcase(result[0]) == os.path.normcase(str(f))

    def test_braced_path_with_spaces(self, tmp_path):
        f = tmp_path / "my movie clip.mp4"
        f.write_text("x")
        # 공백이 포함된 경로는 tkinterdnd2 가 { } 로 감싼다.
        dropped = "{" + str(f) + "}"
        result = parse_dropped_files(dropped)
        assert len(result) == 1
        assert os.path.basename(result[0]) == "my movie clip.mp4"

    def test_multiple_braced_paths(self, tmp_path):
        f1 = tmp_path / "a b.mp4"
        f2 = tmp_path / "c d.mkv"
        f1.write_text("x")
        f2.write_text("x")
        dropped = "{" + str(f1) + "} {" + str(f2) + "}"
        result = parse_dropped_files(dropped)
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["a b.mp4", "c d.mkv"]

    def test_mixed_braced_and_plain(self, tmp_path):
        f1 = tmp_path / "with space.mp4"
        f2 = tmp_path / "plain.mp4"
        f1.write_text("x")
        f2.write_text("x")
        dropped = "{" + str(f1) + "} " + str(f2)
        result = parse_dropped_files(dropped)
        names = sorted(os.path.basename(p) for p in result)
        assert names == ["plain.mp4", "with space.mp4"]

    def test_forward_slashes_are_normalized(self, tmp_path):
        f = tmp_path / "clip.mp4"
        f.write_text("x")
        forward = str(f).replace("\\", "/")
        result = parse_dropped_files(forward)
        assert len(result) == 1
        assert os.path.basename(result[0]) == "clip.mp4"

    def test_nonexistent_paths_are_dropped(self, tmp_path):
        exists = tmp_path / "real.mp4"
        exists.write_text("x")
        missing = tmp_path / "ghost.mp4"  # 생성하지 않음
        dropped = "{" + str(exists) + "} {" + str(missing) + "}"
        result = parse_dropped_files(dropped)
        assert len(result) == 1
        assert os.path.basename(result[0]) == "real.mp4"

    def test_empty_string_returns_empty_list(self):
        assert parse_dropped_files("") == []


# ---------------------------------------------------------------------------
# SUPPORTED_EXTENSIONS : 대기열 추가 시 파일 필터 규칙
# gui.app._add_files_to_queue 가 f.lower().endswith(SUPPORTED_EXTENSIONS) 로 판정한다.
# ---------------------------------------------------------------------------
class TestSupportedExtensions:
    @pytest.mark.parametrize(
        "name",
        ["a.mp4", "b.MKV", "c.Mov", "d.avi", "e.wmv", "f.m4v", "g.ts"],
    )
    def test_supported_video_files_match_case_insensitive(self, name):
        assert name.lower().endswith(SUPPORTED_EXTENSIONS)

    @pytest.mark.parametrize(
        "name",
        ["notes.txt", "image.png", "archive.zip", "audio.mp3", "sub.srt", "noext"],
    )
    def test_non_video_files_are_rejected(self, name):
        assert not name.lower().endswith(SUPPORTED_EXTENSIONS)

    def test_extension_set_matches_documented_formats(self):
        assert set(SUPPORTED_EXTENSIONS) == {
            ".mkv", ".avi", ".mov", ".wmv", ".mp4", ".m4v", ".ts"
        }


# ---------------------------------------------------------------------------
# 병렬 job 권장 수 계산
#
# hardware.recommend_parallel_jobs의 규칙:
#   GPU 없음        -> 2
#   VRAM <= 4100MB  -> 1
#   VRAM <= 8200MB  -> 2
#   VRAM <= 12300MB -> 3
#   그 외           -> 4
#
# 실제 구현을 직접 임포트해 경계값 회귀를 고정한다.
# ---------------------------------------------------------------------------


class TestRecommendParallelJobs:
    def test_no_gpu_defaults_to_two(self):
        assert recommend_parallel_jobs(None, 0) == 2

    @pytest.mark.parametrize(
        "vram,expected",
        [
            (2048, 1),    # 2GB 급
            (4100, 1),    # 경계 (<=4100)
            (4101, 2),    # 경계 바로 위
            (8192, 2),    # 8GB 급
            (8200, 2),    # 경계 (<=8200)
            (8201, 3),
            (12288, 3),   # 12GB 급
            (12300, 3),   # 경계 (<=12300)
            (12301, 4),
            (24576, 4),   # 24GB 급
        ],
    )
    def test_vram_tiers(self, vram, expected):
        assert recommend_parallel_jobs("NVIDIA GeForce RTX", vram) == expected

    def test_result_within_slider_range(self):
        # GUI 슬라이더는 1~8 범위이므로 권장값은 항상 그 안에 있어야 한다.
        for vram in (0, 4100, 8200, 12300, 99999):
            jobs = recommend_parallel_jobs("gpu", vram)
            assert 1 <= jobs <= 8


# ---------------------------------------------------------------------------
# QueueItemState : 표시 문자열과 분리된 내부 상태 모델
# ---------------------------------------------------------------------------
class TestQueueItemState:
    @pytest.mark.parametrize(
        "process_status,expected",
        [
            ("SUCCESS", QueueItemState.SUCCESS),
            ("SUCCESS_DEL", QueueItemState.SUCCESS_DEL),
            ("COPY", QueueItemState.COPY),
            ("FAIL", QueueItemState.FAILED),
            ("CANCELLED", QueueItemState.CANCELLED),
        ],
    )
    def test_all_process_statuses_are_mapped(self, process_status, expected):
        assert process_status_to_state(process_status) == expected

    def test_unknown_process_status_fails_safe(self):
        assert (
            process_status_to_state("UNEXPECTED")
            == QueueItemState.FAILED
        )

    @pytest.mark.parametrize(
        "state",
        [
            QueueItemState.RUNNING,
            QueueItemState.SUCCESS,
            QueueItemState.SUCCESS_DEL,
            QueueItemState.COPY,
            QueueItemState.FAILED,
            QueueItemState.CANCELLED,
        ],
    )
    def test_only_queued_items_are_reprocessed(self, state):
        assert not should_reprocess(state)

    def test_queued_item_is_processable_for_enum_and_string(self):
        assert should_reprocess(QueueItemState.QUEUED)
        assert should_reprocess("QUEUED")

    @pytest.mark.parametrize("state", [None, "", "완료", "UNKNOWN"])
    def test_invalid_or_display_state_is_not_reprocessed(self, state):
        assert not should_reprocess(state)


class TestResultSummary:
    def test_summary_counts_each_terminal_state(self):
        counts = summarize_item_states(
            [
                QueueItemState.SUCCESS,
                QueueItemState.SUCCESS,
                QueueItemState.COPY,
                QueueItemState.SUCCESS_DEL,
                QueueItemState.FAILED,
                QueueItemState.CANCELLED,
                QueueItemState.QUEUED,
            ]
        )

        assert counts == {
            QueueItemState.SUCCESS: 2,
            QueueItemState.COPY: 1,
            QueueItemState.SUCCESS_DEL: 1,
            QueueItemState.FAILED: 1,
            QueueItemState.CANCELLED: 1,
        }

    def test_summary_format_includes_all_user_relevant_counts(self):
        counts = summarize_item_states(
            [
                QueueItemState.SUCCESS,
                QueueItemState.COPY,
                QueueItemState.SUCCESS_DEL,
                QueueItemState.FAILED,
                QueueItemState.CANCELLED,
            ]
        )
        summary = format_result_summary(counts)

        assert "완료 3개" in summary
        assert "변환 1" in summary
        assert "복사 1" in summary
        assert "원본삭제 1" in summary
        assert "실패 1개" in summary
        assert "취소 1개" in summary
