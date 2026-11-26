"""ffprobe 기반 비디오 메타데이터 조회."""

import subprocess
import sys

from . import tools

SUBPROC_TEXT = {"encoding": "utf-8", "errors": "replace"}


def get_video_info(file_path):
    """
    ffprobe를 사용하여 비디오 정보(duration_sec, bit_rate, width, height)를 추출.
    실패 시 None 반환.
    """
    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    info = {
        "duration_sec": 0.0,
        "bit_rate": 0,
        "width": 0,
        "height": 0,
        "sub_codecs": [],
    }
    try:
        cmd_res = [
            tools.ffprobe(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", file_path,
        ]
        result = subprocess.run(
            cmd_res,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flags,
            timeout=15,
        )
        line = result.stdout.strip()
        if line:
            width, height = line.split(",")
            info["width"] = int(width)
            info["height"] = int(height)

        cmd_dur = [
            tools.ffprobe(), "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", file_path,
        ]
        result = subprocess.run(
            cmd_dur,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flags,
            timeout=15,
        )
        line = result.stdout.strip()
        if line and line != "N/A":
            info["duration_sec"] = float(line)

        cmd_br = [
            tools.ffprobe(), "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate", "-of", "csv=p=0", file_path,
        ]
        result = subprocess.run(
            cmd_br,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flags,
            timeout=15,
        )
        line = result.stdout.strip()
        if line and line != "N/A":
            info["bit_rate"] = int(line)
        else:
            cmd_br_fmt = [
                tools.ffprobe(), "-v", "error", "-show_entries", "format=bit_rate",
                "-of", "csv=p=0", file_path,
            ]
            result = subprocess.run(
                cmd_br_fmt,
                capture_output=True,
                text=True,
                check=True,
                creationflags=creation_flags,
                timeout=15,
            )
            line = result.stdout.strip()
            if line and line != "N/A":
                info["bit_rate"] = int(line)

        try:
            cmd_sub = [
                tools.ffprobe(), "-v", "error", "-select_streams", "s",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path,
            ]
            res_sub = subprocess.run(
                cmd_sub,
                capture_output=True,
                text=True,
                check=False,
                creationflags=creation_flags,
                timeout=15,
            )
            for line in res_sub.stdout.splitlines():
                line = line.strip()
                if line and line != "N/A":
                    info["sub_codecs"].append(line)
        except Exception:
            pass

        return info
    except Exception as exc:
        print(f"ffprobe 에러 ({file_path}): {exc}", file=sys.stderr)
    return None


def _time_str_to_seconds(t_str):
    try:
        parts = t_str.strip().split(":")
        if len(parts) != 3:
            return None
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    except (ValueError, IndexError):
        return None

