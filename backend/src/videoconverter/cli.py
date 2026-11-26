"""명령줄 진입점: `videoconverter serve`, `videoconverter doctor`."""

from __future__ import annotations

import argparse
import subprocess
import sys

from videoconverter import __version__


def _first_line(cmd: list[str]) -> str:
    """명령을 실행해 표준 출력 첫 줄을 돌려준다. 실행하지 못하면 빈 문자열."""
    from videoconverter.core.proc import CREATE_NO_WINDOW

    try:
        out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30, creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.splitlines()[0].strip() if out.returncode == 0 and out.stdout else ""


def cmd_doctor(args: argparse.Namespace) -> int:
    """변환에 필요한 것이 있는지 확인한다. --bundled 는 설치 파일을 만들기 전에 쓴다."""
    from videoconverter import hardware
    from videoconverter.core import tools
    from videoconverter.core.proc import CREATE_NO_WINDOW

    ok = True

    def row(name: str, good: bool | None, detail: str) -> None:
        nonlocal ok
        ok = ok and good is not False
        mark = "--" if good is None else "OK" if good else "NO"
        print(f"[{mark}] {name:<8} {detail}")

    for name in ("ffmpeg", "ffprobe"):
        path = tools.bundled_tool(name) if args.bundled else tools.tool_path(name)
        version = _first_line([path, "-version"]) if path else ""
        where = "next to the executable" if args.bundled else "on PATH (winget install Gyan.FFmpeg)"
        row(name, bool(version), f"{version} ({path})" if version else f"{path} does not run" if path else f"not found {where}")

    ffmpeg = tools.bundled_tool("ffmpeg") if args.bundled else tools.tool_path("ffmpeg")
    encoders = ""
    if ffmpeg:
        try:
            encoders = subprocess.run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True,
                                      encoding="utf-8", errors="replace", timeout=30,
                                      creationflags=CREATE_NO_WINDOW).stdout
        except (OSError, subprocess.SubprocessError):
            encoders = ""
    # 설치 파일에 넣는 FFmpeg 에는 둘 다 있어야 한다(GPU 변환과 CPU 폴백). PATH 의 것은 알리기만 한다
    need = True if args.bundled else None
    for enc, missing in (("h264_nvenc", "missing (CPU only)"), ("libx264", "missing (no CPU fallback)")):
        have = enc in encoders
        row(enc.removeprefix("h264_").removeprefix("lib"), have if need else None,
            f"{enc} in this FFmpeg" if have else f"{enc} {missing}")
    hw = hardware.detect()
    gpu = f"{hw['gpu']} ({hw['vram_mb']} MB)" if hw["gpu"] else "no NVIDIA GPU found (CPU only)"
    row("gpu", None, f"{gpu}, {hw['recommended_jobs']} jobs recommended")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="videoconverter", description="Video Converter backend")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    from videoconverter.api.base import add_serve_command

    add_serve_command(sub)

    d = sub.add_parser("doctor", help="check FFmpeg, ffprobe and NVENC")
    d.add_argument("--bundled", action="store_true", help="require the FFmpeg shipped next to the executable")
    d.set_defaults(fn=cmd_doctor)

    args = p.parse_args(argv)
    sys.exit(args.fn(args))
