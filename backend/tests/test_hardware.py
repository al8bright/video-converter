"""넣을 수 있는 확장자와 GPU 메모리로 정하는 권장 동시 작업 수."""

import pytest

from videoconverter.config import SUPPORTED_EXTENSIONS
from videoconverter.hardware import recommend_parallel_jobs


class TestSupportedExtensions:
    @pytest.mark.parametrize("name", ["a.mp4", "b.MKV", "c.Mov", "d.avi", "e.wmv", "f.m4v", "g.ts"])
    def test_영상_파일은_대소문자와_관계없이_받는다(self, name):
        assert name.lower().endswith(SUPPORTED_EXTENSIONS)

    @pytest.mark.parametrize("name", ["notes.txt", "image.png", "archive.zip", "audio.mp3", "sub.srt", "noext"])
    def test_영상이_아닌_파일은_받지_않는다(self, name):
        assert not name.lower().endswith(SUPPORTED_EXTENSIONS)

    def test_문서에_적은_형식과_같다(self):
        assert set(SUPPORTED_EXTENSIONS) == {".mkv", ".avi", ".mov", ".wmv", ".mp4", ".m4v", ".ts"}


class TestRecommendParallelJobs:
    """GPU 없음 2, VRAM 4100MB 이하 1, 8200MB 이하 2, 12300MB 이하 3, 그 위 4."""

    def test_GPU가_없으면_2(self):
        assert recommend_parallel_jobs(None, 0) == 2

    @pytest.mark.parametrize("vram,expected", [
        (2048, 1), (4100, 1), (4101, 2), (8192, 2), (8200, 2), (8201, 3),
        (12288, 3), (12300, 3), (12301, 4), (24576, 4),
    ])
    def test_VRAM_구간(self, vram, expected):
        assert recommend_parallel_jobs("NVIDIA GeForce RTX", vram) == expected

    def test_설정에서_고를_수_있는_범위_안이다(self):
        for vram in (0, 4100, 8200, 12300, 99999):
            assert 1 <= recommend_parallel_jobs("gpu", vram) <= 8
