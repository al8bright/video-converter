"""FFmpeg 찾기: 함께 넣은 것 → PATH."""

import os

from videoconverter.core import tools
from videoconverter.core.ffmpeg_cmd import _build_ffmpeg_cmd


def test_도구_폴더의_것을_먼저_쓴다(tools_dir):
    assert os.path.dirname(tools.ffmpeg()) == str(tools_dir)
    assert os.path.dirname(tools.ffprobe()) == str(tools_dir)
    cmd = _build_ffmpeg_cmd("in.mkv", "out.mp4", True, "", False, "cpu", {})
    assert cmd[0] == tools.ffmpeg()


def test_도구_폴더에_없으면_없다고_한다(tmp_path, monkeypatch):
    monkeypatch.setenv(tools.TOOLS_DIR_ENV, str(tmp_path))
    assert tools.bundled_tool("ffmpeg") is None


def test_어디에도_없으면_이름만_돌려준다(tmp_path, monkeypatch):
    monkeypatch.delenv(tools.TOOLS_DIR_ENV, raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tools.tool_path("ffmpeg") is None
    assert tools.ffmpeg() == "ffmpeg"
