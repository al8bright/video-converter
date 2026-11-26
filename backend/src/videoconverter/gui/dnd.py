"""tkinterdnd2 로딩과 드롭 경로 파싱."""

import os
import re

import customtkinter as ctk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    HAS_DND = True
except Exception as exc:
    print(f"TkinterDnD2 로드 실패: {exc}")
    DND_FILES = None
    TkinterDnD = None
    HAS_DND = False


def parse_dropped_files(dropped_str):
    """tkinterdnd2 드롭 데이터를 개별 파일/폴더 경로로 파싱한다."""
    braced_paths = re.findall(r"\{(.*?)\}", dropped_str)
    cleaned_str = re.sub(r"\{.*?\}", " ", dropped_str)

    files = [path.strip() for path in braced_paths if path.strip()]
    for path in cleaned_str.split():
        if path.strip():
            files.append(os.path.normpath(path.strip()))

    normalized_files = []
    for path in files:
        fixed_path = path.replace("/", "\\")
        if os.path.exists(fixed_path):
            normalized_files.append(fixed_path)
        elif os.path.exists(path):
            normalized_files.append(path)
    return normalized_files


def build_base_class():
    """DnD를 사용할 수 있으면 래퍼 CTk 클래스를, 아니면 기본 CTk를 반환한다."""
    if not HAS_DND:
        return ctk.CTk

    class DnDApp(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self):
            super().__init__()
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_active = True
            except Exception as exc:
                print(f"TkinterDnD2 연동 실패: {exc}")
                self.dnd_active = False

    return DnDApp

