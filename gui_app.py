import os
import re
import sys
import queue
import shutil
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from concurrent.futures import ThreadPoolExecutor
import customtkinter as ctk

# core_converter에서 핵심 변환 모듈 임포트
from core_converter import get_video_info, process_video, resolve_output_path, get_system_ram_gb, get_nvidia_gpu_info


# 드래그 앤 드롭 라이브러리 예외 처리 로딩
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except Exception as e:
    print(f"TkinterDnD2 로드 실패: {e}")
    HAS_DND = False

# 시스템 인코딩 및 테마 설정
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# 지원하는 비디오 확장자
SUPPORTED_EXTENSIONS = (".mkv", ".avi", ".mov", ".wmv", ".mp4", ".m4v", ".ts")

def parse_dropped_files(dropped_str):
    """
    tkinterdnd2 드롭 데이터를 파싱하여 개별 파일/폴더 경로 리스트를 반환.
    """
    braced_paths = re.findall(r'\{(.*?)\}', dropped_str)
    cleaned_str = re.sub(r'\{.*?\}', ' ', dropped_str)
    
    files = [p.strip() for p in braced_paths if p.strip()]
    for p in cleaned_str.split():
        if p.strip():
            files.append(os.path.normpath(p.strip()))
            
    normalized_files = []
    for f in files:
        f_fixed = f.replace('/', '\\')
        if os.path.exists(f_fixed):
            normalized_files.append(f_fixed)
        elif os.path.exists(f):
            normalized_files.append(f)
            
    return normalized_files


class QueueItemFrame(ctk.CTkFrame):
    """대기열 목록의 개별 파일 행 컴포넌트"""
    def __init__(self, master, file_path, delete_callback, **kwargs):
        super().__init__(master, fg_color="#1E1E2E", corner_radius=6, **kwargs)
        self.file_path = file_path
        self.video_info = None

        filename = os.path.basename(file_path)
        self.name_label = ctk.CTkLabel(
            self, text=filename, anchor="w", font=("Malgun Gothic", 12), text_color="#E0E0E6"
        )
        self.name_label.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=8)

        # 원본 크기 표시
        size_bytes = os.path.getsize(file_path)
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{size_mb/1024:.2f} GB"
        self.size_label = ctk.CTkLabel(
            self, text=size_str, width=90, font=("Malgun Gothic", 11), text_color="#888888"
        )
        self.size_label.pack(side="left", padx=5)

        # 해상도 정보 표시
        self.res_label = ctk.CTkLabel(
            self, text="분석 중...", width=90, font=("Malgun Gothic", 11), text_color="#888888"
        )
        self.res_label.pack(side="left", padx=5)

        # 상태 라벨
        self.status_label = ctk.CTkLabel(
            self, text="대기", width=90, font=("Malgun Gothic", 11, "bold"), text_color="#E5C158"
        )
        self.status_label.pack(side="left", padx=5)

        # 개별 제거 버튼
        self.del_btn = ctk.CTkButton(
            self,
            text="✕",
            width=28,
            height=24,
            fg_color="#FF4D4D",
            hover_color="#CC3333",
            font=("Malgun Gothic", 10, "bold"),
            command=lambda: delete_callback(self)
        )
        self.del_btn.pack(side="right", padx=(5, 10))

    def update_status(self, status, text_color=None):
        self.status_label.configure(text=status)
        if text_color:
            self.status_label.configure(text_color=text_color)


class ScrollableQueueFrame(ctk.CTkScrollableFrame):
    """대기열 스크롤 리스트 영역"""
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0F0F1A", label_text="대기열 목록", label_font=("Malgun Gothic", 13, "bold"), label_text_color="#A0A0B0", **kwargs)
        self.items = []

    def add_item(self, file_path, delete_callback):
        for item in self.items:
            if item.file_path == file_path:
                return None
        item_frame = QueueItemFrame(self, file_path, delete_callback)
        item_frame.pack(fill="x", pady=4, padx=5)
        self.items.append(item_frame)
        return item_frame

    def remove_item(self, item_frame):
        if item_frame in self.items:
            self.items.remove(item_frame)
            item_frame.destroy()

    def clear(self):
        for item in self.items:
            item.destroy()
        self.items.clear()


class ProgressSlotFrame(ctk.CTkFrame):
    """실시간 병렬 작업 대시보드에 쓰일 진행바 슬롯 컴포넌트"""
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#181824", corner_radius=6, **kwargs)
        
        self.lbl_filename = ctk.CTkLabel(
            self, text="대기 중...", anchor="w", font=("Malgun Gothic", 11, "bold"), text_color="#E0E0E6", width=220
        )
        self.lbl_filename.pack(side="left", padx=(10, 5), pady=6)
        
        self.progress = ctk.CTkProgressBar(self, height=8, fg_color="#2D2D3D", progress_color="#3A86FF")
        self.progress.pack(side="left", fill="x", expand=True, padx=10)
        self.progress.set(0.0)
        
        self.lbl_status = ctk.CTkLabel(
            self, text="0.0% (speed: -)", font=("Malgun Gothic", 11), text_color="#A0A0B0", width=140, anchor="e"
        )
        self.lbl_status.pack(side="right", padx=(5, 10))

    def reset(self):
        self.lbl_filename.configure(text="대기 중...", text_color="#A0A0B0")
        self.progress.set(0.0)
        self.lbl_status.configure(text="0.0% (speed: -)")


BaseClass = ctk.CTk
if HAS_DND:
    class DnDApp(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self):
            super().__init__()
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_active = True
            except Exception as e:
                print(f"TkinterDnD2 연동 실패: {e}")
                self.dnd_active = False
    BaseClass = DnDApp


class VideoConverterApp(BaseClass):
    def __init__(self):
        super().__init__()

        self.title("CUDA/NVENC Video Converter v1.0.0")
        self.geometry("820x760")
        self.minsize(780, 700)

        # 데이터 변수 바인딩
        # 하드웨어 정보 탐지 및 권장 작업수 세팅
        self.gpu_name, self.vram_mb = get_nvidia_gpu_info()
        self.sys_ram_gb = get_system_ram_gb()
        
        # 권장 작업수 기본값 계산 (VRAM 4GB 이하 -> 1 / 8GB 이하 -> 2 / 12GB 이하 -> 3 / 그 이상 -> 4)
        if self.gpu_name:
            if self.vram_mb <= 4100:
                rec_jobs = 1
            elif self.vram_mb <= 8200:
                rec_jobs = 2
            elif self.vram_mb <= 12300:
                rec_jobs = 3
            else:
                rec_jobs = 4
        else:
            rec_jobs = 2  # GPU 미검출 시 기본 권장 2개
            
        self.parallel_jobs = ctk.IntVar(value=rec_jobs)
        self.video_bitrate = ctk.StringVar(value="3.5")
        self.audio_bitrate = ctk.StringVar(value="128k")
        self.resolution_limit = ctk.StringVar(value="1080p (FHD)")
        self.delete_source = ctk.BooleanVar(value=True)


        self.save_mode = ctk.StringVar(value="same")
        self.custom_output_path = ctk.StringVar(value="")
        self.name_option = ctk.StringVar(value="suffix")
        self.name_value = ctk.StringVar(value="_cuda")

        self.is_processing = False
        self.cancel_event = threading.Event()
        self.processed_count = 0
        self.total_count = 0

        # 병렬 진행 슬롯 데이터 스토리지
        # 구조: { slot_id: { 'filename': str, 'pct': float, 'time_str': str, 'speed': str, 'active': bool } }
        self.slot_data = {i: {'filename': '대기 중...', 'pct': 0.0, 'time_str': '-', 'speed': '-', 'active': False} for i in range(8)}
        self.slot_lock = threading.Lock()

        # UI 위젯 생성
        self._create_widgets()

        # UI 업데이트 루프 가동 (100ms 주기로 슬롯 갱신)
        self._update_ui_loop()

        # 드래그 앤 드롭 등록
        if HAS_DND and getattr(self, 'dnd_active', False):
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self._on_dnd_drop)
            print("드래그 앤 드롭 기능이 활성화되었습니다.")
        else:
            self.dnd_panel.configure(label_text="[ 드래그 앤 드롭 기능 비활성 - 아래 버튼을 사용해 주세요 ]")

    def _create_widgets(self):
        self.grid_rowconfigure(5, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # 1. 드래그앤드롭 영역 패널
        self.dnd_panel = ctk.CTkFrame(self, fg_color="#1E1E2E", height=90, corner_radius=8)
        self.dnd_panel.grid(row=0, column=0, padx=15, pady=(15, 6), sticky="ew")

        dnd_label = ctk.CTkLabel(
            self.dnd_panel,
            text="변환할 비디오 파일 또는 폴더를 여기에 끌어다 놓으세요 (NVIDIA GPU 가속 권장)",
            font=("Malgun Gothic", 12, "bold"),
            text_color="#88889C"
        )
        dnd_label.pack(pady=(12, 5))

        btn_frame = ctk.CTkFrame(self.dnd_panel, fg_color="transparent")
        btn_frame.pack(pady=(0, 12))

        self.btn_add_files = ctk.CTkButton(
            btn_frame, text="파일 추가...", command=self._browse_files, width=120, height=28, fg_color="#3A86FF", hover_color="#2563EB"
        )
        self.btn_add_files.pack(side="left", padx=10)

        self.btn_add_folder = ctk.CTkButton(
            btn_frame, text="폴더 추가...", command=self._browse_folder, width=120, height=28, fg_color="#3A86FF", hover_color="#2563EB"
        )
        self.btn_add_folder.pack(side="left", padx=10)

        # 1.5 시스템 정보 바 패널 (row=1)
        sys_info_bar = ctk.CTkFrame(self, fg_color="#181824", height=32, corner_radius=6)
        sys_info_bar.grid(row=1, column=0, padx=15, pady=(4, 4), sticky="ew")

        if self.gpu_name:
            gpu_desc = f"{self.gpu_name} ({self.vram_mb/1024:.1f}GB VRAM)"
        else:
            gpu_desc = "NVIDIA GPU 미감지 (CPU/S/W 모드 작동)"
            
        sys_ram_desc = f"{self.sys_ram_gb} GB" if self.sys_ram_gb > 0 else "감지 불가"
        
        info_text = f"🖥️ 시스템 사양 감지  |  NVIDIA GPU: [{gpu_desc}]  |  시스템 RAM: [{sys_ram_desc}]"
        lbl_sys_info = ctk.CTkLabel(
            sys_info_bar, text=info_text, font=("Malgun Gothic", 11, "bold"), text_color="#A0A0B0"
        )
        lbl_sys_info.pack(side="left", padx=15, pady=4)

        # 2. 상세 설정 영역 패널
        self.settings_panel = ctk.CTkFrame(self, fg_color="#1E1E2E", corner_radius=8)
        self.settings_panel.grid(row=2, column=0, padx=15, pady=4, sticky="ew")
        self.settings_panel.grid_columnconfigure(1, weight=1)
        self.settings_panel.grid_columnconfigure(3, weight=1)

        # 2.1 동시 작업수 슬라이더
        lbl_jobs = ctk.CTkLabel(self.settings_panel, text="동시 변환 작업 수:", font=("Malgun Gothic", 11, "bold"))
        lbl_jobs.grid(row=0, column=0, padx=15, pady=8, sticky="w")
        
        slider_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        slider_frame.grid(row=0, column=1, padx=15, pady=8, sticky="ew")
        
        self.slider_jobs = ctk.CTkSlider(
            slider_frame, from_=1, to=8, number_of_steps=7, variable=self.parallel_jobs, command=self._on_jobs_slider_changed, height=16
        )
        self.slider_jobs.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        self.lbl_jobs_val = ctk.CTkLabel(slider_frame, text=f"{self.parallel_jobs.get()}개", font=("Malgun Gothic", 11, "bold"), width=30)
        self.lbl_jobs_val.pack(side="right")


        # 2.2 비트레이트 설정
        lbl_v_bitrate = ctk.CTkLabel(self.settings_panel, text="최대 비디오 대역폭:", font=("Malgun Gothic", 11, "bold"))
        lbl_v_bitrate.grid(row=0, column=2, padx=15, pady=8, sticky="w")

        combo_v_bitrate = ctk.CTkOptionMenu(
            self.settings_panel, values=["5.0", "4.0", "3.5", "2.5", "1.5"], variable=self.video_bitrate, width=90, height=24
        )
        combo_v_bitrate.grid(row=0, column=3, padx=15, pady=8, sticky="w")

        # 2.3 오디오 비트레이트 & 해상도 한도 & 원본 삭제 토글
        lbl_a_bitrate = ctk.CTkLabel(self.settings_panel, text="오디오 비트레이트:", font=("Malgun Gothic", 11, "bold"))
        lbl_a_bitrate.grid(row=1, column=0, padx=15, pady=8, sticky="w")

        combo_a_bitrate = ctk.CTkOptionMenu(
            self.settings_panel, values=["192k", "128k", "96k"], variable=self.audio_bitrate, width=100, height=24
        )
        combo_a_bitrate.grid(row=1, column=1, padx=15, pady=8, sticky="w")

        lbl_res = ctk.CTkLabel(self.settings_panel, text="해상도 제한:", font=("Malgun Gothic", 11, "bold"))
        lbl_res.grid(row=1, column=2, padx=15, pady=8, sticky="w")

        combo_res = ctk.CTkOptionMenu(
            self.settings_panel, values=["1080p (FHD)", "720p (HD)", "제한 없음"], variable=self.resolution_limit, width=110, height=24
        )
        combo_res.grid(row=1, column=3, padx=15, pady=8, sticky="w")

        self.chk_delete_src = ctk.CTkSwitch(
            self.settings_panel, text="변환 완료 후 원본 파일 자동 삭제", variable=self.delete_source, font=("Malgun Gothic", 11, "bold")
        )
        self.chk_delete_src.grid(row=2, column=0, columnspan=2, padx=15, pady=8, sticky="w")

        # 2.4 저장 및 파일명 변경 규칙
        lbl_save_loc = ctk.CTkLabel(self.settings_panel, text="저장 위치 설정:", font=("Malgun Gothic", 11, "bold"))
        lbl_save_loc.grid(row=3, column=0, padx=15, pady=6, sticky="nw")

        save_loc_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        save_loc_frame.grid(row=3, column=1, columnspan=3, padx=15, pady=6, sticky="ew")

        self.rdo_save_same = ctk.CTkRadioButton(
            save_loc_frame, text="원본과 동일한 폴더에 저장", variable=self.save_mode, value="same", command=self._toggle_save_ui, font=("Malgun Gothic", 11)
        )
        self.rdo_save_same.pack(side="left", padx=(0, 15))

        self.rdo_save_custom = ctk.CTkRadioButton(
            save_loc_frame, text="지정 폴더 저장:", variable=self.save_mode, value="custom", command=self._toggle_save_ui, font=("Malgun Gothic", 11)
        )
        self.rdo_save_custom.pack(side="left", padx=(0, 10))

        self.entry_custom_path = ctk.CTkEntry(
            save_loc_frame, textvariable=self.custom_output_path, state="disabled", width=250, height=22
        )
        self.entry_custom_path.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_browse_out = ctk.CTkButton(
            save_loc_frame, text="변경", state="disabled", command=self._browse_output_dir, width=50, height=22, fg_color="#4F5D75", hover_color="#3D4A5E"
        )
        self.btn_browse_out.pack(side="right")

        lbl_name_opt = ctk.CTkLabel(self.settings_panel, text="파일명 규칙:", font=("Malgun Gothic", 11, "bold"))
        lbl_name_opt.grid(row=4, column=0, padx=15, pady=6, sticky="nw")

        name_opt_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        name_opt_frame.grid(row=4, column=1, columnspan=3, padx=15, pady=6, sticky="ew")

        self.rdo_name_overwrite = ctk.CTkRadioButton(
            name_opt_frame, text="덮어쓰기", variable=self.name_option, value="overwrite", command=self._toggle_name_ui, font=("Malgun Gothic", 11)
        )
        self.rdo_name_overwrite.pack(side="left", padx=(0, 15))

        self.rdo_name_suffix = ctk.CTkRadioButton(
            name_opt_frame, text="접미사 추가:", variable=self.name_option, value="suffix", command=self._toggle_name_ui, font=("Malgun Gothic", 11)
        )
        self.rdo_name_suffix.pack(side="left", padx=(0, 5))

        self.entry_name_value = ctk.CTkEntry(
            name_opt_frame, textvariable=self.name_value, width=100, height=22
        )
        self.entry_name_value.pack(side="left")

        # 2.5 가이드/팁 정보 패널 추가
        tip_frame = ctk.CTkFrame(self.settings_panel, fg_color="#181824", corner_radius=6)
        tip_frame.grid(row=5, column=0, columnspan=4, padx=15, pady=(8, 12), sticky="ew")

        lbl_tip_title = ctk.CTkLabel(
            tip_frame, text="💡 설정 가이드 & 팁 (Tip)", font=("Malgun Gothic", 11, "bold"), text_color="#06D6A0"
        )
        lbl_tip_title.pack(anchor="w", padx=12, pady=(8, 2))

        tip_text = (
            "• 동시 변환 수: 그래픽카드 VRAM 용량에 맞춰 조절 (4GB 이하는 1~2개, 8GB는 3~4개, 12GB 이상은 4개 이상 권장)\n"
            "• 최대 비디오 대역폭: 기본 3.5 Mbps 권장. 낮출수록 용량이 축소되나 격동적인 장면에서 픽셀 깨짐이 발생할 수 있습니다.\n"
            "• 해상도 제한: 1080p FHD 권장. 원본 해상도가 설정 제한보다 큰 경우에만 종횡비를 유지하며 스케일링을 가동합니다.\n"
            "• 지능적 복사(Remux): 원본 비트레이트가 4 Mbps 이하면 화질 손실 없이 초고속으로 원본 스트림을 복사해 저장합니다."
        )
        lbl_tip_desc = ctk.CTkLabel(
            tip_frame, text=tip_text, font=("Malgun Gothic", 10), text_color="#A0A0B0", justify="left", anchor="w"
        )
        lbl_tip_desc.pack(anchor="w", padx=12, pady=(0, 8))

        # 3. 실시간 병렬 인코딩 대시보드 영역 (실시간 진행 상황 뷰어)
        self.dashboard_panel = ctk.CTkFrame(self, fg_color="#13131F", corner_radius=8)
        self.dashboard_panel.grid(row=3, column=0, padx=15, pady=6, sticky="ew")

        lbl_dash = ctk.CTkLabel(self.dashboard_panel, text="현재 실행 중인 변환 작업", font=("Malgun Gothic", 12, "bold"), text_color="#A0A0B0")
        lbl_dash.pack(anchor="w", padx=15, pady=(8, 4))
        
        # 8개의 진행바 슬롯 생성
        self.slot_frames = []
        for i in range(8):
            slot = ProgressSlotFrame(self.dashboard_panel)
            self.slot_frames.append(slot)
            
        # 초기 작업 수 기준 슬롯 프레임 노출
        self._arrange_progress_slots()

        # 4. 대기열 테이블 타이틀 헤더 프레임
        self.table_header = ctk.CTkFrame(self, fg_color="#1E1E2E", height=28, corner_radius=4)
        self.table_header.grid(row=4, column=0, padx=15, pady=(8, 0), sticky="ew")

        lbl_h_name = ctk.CTkLabel(self.table_header, text="파일명", anchor="w", font=("Malgun Gothic", 11, "bold"), text_color="#A0A0B0")
        lbl_h_name.pack(side="left", fill="x", expand=True, padx=(15, 5), pady=2)

        lbl_h_size = ctk.CTkLabel(self.table_header, text="원본 크기", width=90, font=("Malgun Gothic", 11, "bold"), text_color="#A0A0B0")
        lbl_h_size.pack(side="left", padx=5, pady=2)

        lbl_h_res = ctk.CTkLabel(self.table_header, text="설정 해상도", width=90, font=("Malgun Gothic", 11, "bold"), text_color="#A0A0B0")
        lbl_h_res.pack(side="left", padx=5, pady=2)

        lbl_h_status = ctk.CTkLabel(self.table_header, text="상태", width=90, font=("Malgun Gothic", 11, "bold"), text_color="#A0A0B0")
        lbl_h_status.pack(side="left", padx=5, pady=2)

        lbl_h_dummy = ctk.CTkLabel(self.table_header, text="", width=38)
        lbl_h_dummy.pack(side="right", padx=(5, 10), pady=2)

        # 5. 스크롤 대기열 영역
        self.queue_frame = ScrollableQueueFrame(self)
        self.queue_frame.grid(row=5, column=0, padx=15, pady=(0, 8), sticky="nsew")

        # 6. 진행바 및 제어 버튼
        self.control_panel = ctk.CTkFrame(self, fg_color="transparent")
        self.control_panel.grid(row=6, column=0, padx=15, pady=15, sticky="ew")
        self.control_panel.grid_columnconfigure(0, weight=1)

        self.overall_progress_bar = ctk.CTkProgressBar(self.control_panel, height=12, fg_color="#2D2D3D", progress_color="#06D6A0")
        self.overall_progress_bar.grid(row=0, column=0, columnspan=3, pady=(0, 10), sticky="ew")
        self.overall_progress_bar.set(0.0)

        self.lbl_progress = ctk.CTkLabel(self.control_panel, text="대기 중 (0개 파일)", font=("Malgun Gothic", 12))
        self.lbl_progress.grid(row=1, column=0, sticky="w")

        self.btn_clear = ctk.CTkButton(
            self.control_panel, text="대기열 비우기", command=self._clear_queue, width=120, height=35, fg_color="#4F5D75", hover_color="#3D4A5E"
        )
        self.btn_clear.grid(row=1, column=1, padx=5, sticky="e")

        self.btn_start = ctk.CTkButton(
            self.control_panel, text="변환 시작", command=self._start_conversion, width=120, height=35, fg_color="#06D6A0", hover_color="#05B98A", text_color="#1E1E2E", font=("Malgun Gothic", 12, "bold")
        )
        self.btn_start.grid(row=1, column=2, padx=5, sticky="e")


    def _arrange_progress_slots(self):
        """설정된 동시 변환 개수(PARALLEL_JOBS)에 맞게 진행바 슬롯 위젯을 노출/배치"""
        jobs = self.parallel_jobs.get()
        
        # 전체 언팩 후 지정된 개수만 팩
        for slot in self.slot_frames:
            slot.pack_forget()
            
        for i in range(jobs):
            self.slot_frames[i].pack(fill="x", padx=10, pady=4)

    def _on_jobs_slider_changed(self, val):
        jobs = int(float(val))
        self.parallel_jobs.set(jobs)
        self.lbl_jobs_val.configure(text=f"{jobs}개")
        self._arrange_progress_slots()

    def _toggle_save_ui(self):
        mode = self.save_mode.get()
        if mode == "custom":
            self.entry_custom_path.configure(state="normal")
            self.btn_browse_out.configure(state="normal")
        else:
            self.entry_custom_path.configure(state="disabled")
            self.btn_browse_out.configure(state="disabled")

    def _toggle_name_ui(self):
        opt = self.name_option.get()
        if opt == "overwrite":
            self.entry_name_value.configure(state="disabled")
        else:
            self.entry_name_value.configure(state="normal")

    # 브라우즈 제어
    def _browse_files(self):
        file_paths = filedialog.askopenfilenames(
            title="비디오 파일 선택",
            filetypes=[("Video Files", "*.mp4 *.mkv *.mov *.avi *.wmv *.ts *.m4v")]
        )
        if file_paths:
            self._add_files_to_queue(file_paths)

    def _browse_folder(self):
        dir_path = filedialog.askdirectory(title="비디오 폴더 선택")
        if dir_path:
            self._add_files_to_queue([dir_path])

    def _browse_output_dir(self):
        dir_path = filedialog.askdirectory(title="저장 폴더 선택")
        if dir_path:
            self.custom_output_path.set(dir_path)

    def _on_dnd_drop(self, event):
        paths = parse_dropped_files(event.data)
        if paths:
            self._add_files_to_queue(paths)

    def _add_files_to_queue(self, paths):
        scanned_files = []
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for f in files:
                        if f.lower().endswith(SUPPORTED_EXTENSIONS):
                            scanned_files.append(os.path.join(root, f))
            elif os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
                scanned_files.append(path)

        new_items = []
        for f in scanned_files:
            item = self.queue_frame.add_item(f, self._delete_queue_item)
            if item:
                new_items.append(item)

        self._update_progress_display()

        if new_items:
            # 백그라운드 스레드에서 비디오 해상도 분석
            threading.Thread(target=self._analyze_videos_info_thread, args=(new_items,), daemon=True).start()

    def _delete_queue_item(self, item_frame):
        if self.is_processing:
            return
        self.queue_frame.remove_item(item_frame)
        self._update_progress_display()

    def _clear_queue(self):
        if self.is_processing:
            return
        self.queue_frame.clear()
        self._update_progress_display()
        self.overall_progress_bar.set(0.0)

    def _update_progress_display(self):
        count = len(self.queue_frame.items)
        if self.is_processing:
            self.lbl_progress.configure(text=f"처리 중 ({self.processed_count}/{self.total_count})")
            prog_val = self.processed_count / max(1, self.total_count)
            self.overall_progress_bar.set(prog_val)
        else:
            self.lbl_progress.configure(text=f"대기 중 ({count}개 파일)")
            self.overall_progress_bar.set(0.0)

    # 비동기 파일 속성 획득 스레드
    def _analyze_videos_info_thread(self, items):
        for item in items:
            try:
                info = get_video_info(item.file_path)
                if info:
                    item.video_info = info
                    res_text = f"{info['width']}x{info['height']}"
                    item.res_label.configure(text=res_text)
                else:
                    item.res_label.configure(text="분석 실패")
            except Exception:
                item.res_label.configure(text="에러")

    # 스레드 안전 UI 업데이트 루프
    def _update_ui_loop(self):
        """백그라운드 스레드가 기록해둔 slot_data 상태값을 100ms 주기로 실제 UI 위젯에 바인딩"""
        with self.slot_lock:
            for idx, slot_frame in enumerate(self.slot_frames):
                data = self.slot_data[idx]
                if data['active']:
                    # 축약 파일명 설정
                    name = data['filename']
                    short_name = name if len(name) <= 30 else name[:27] + "..."
                    slot_frame.lbl_filename.configure(text=short_name, text_color="#E0E0E6")
                    
                    # 진행률 반영
                    slot_frame.progress.set(data['pct'] / 100.0)
                    slot_frame.lbl_status.configure(
                        text=f"{data['pct']:.1f}% ({data['time_str']} / speed: {data['speed']})"
                    )
                else:
                    slot_frame.reset()

        # 100ms 후 반복 실행
        self.after(100, self._update_ui_loop)

    # 변환 시작 클릭 핸들러
    def _start_conversion(self):
        if self.is_processing:
            return

        items_to_process = [item for item in self.queue_frame.items if item.status_label.cget("text") not in ["완료", "실패"]]
        if not items_to_process:
            messagebox.showwarning("경고", "대기열에 처리할 대기 상태의 파일이 없습니다.")
            return

        save_m = self.save_mode.get()
        name_o = self.name_option.get()
        out_dir = self.custom_output_path.get() if save_m == "custom" else ""
        name_val = self.name_value.get() if name_o != "overwrite" else ""

        if save_m == "custom" and not out_dir:
            messagebox.showwarning("경고", "저장 폴더 경로를 지정해 주세요.")
            return

        # 덮어쓰기 경고창
        if name_o == "overwrite":
            if save_m == "same":
                ans = messagebox.askyesno("경고", "원본 파일과 같은 위치에 '덮어쓰기'를 설정하셨습니다.\n원본 파일이 즉시 변경됩니다. 계속하시겠습니까?")
                if not ans:
                    return
            else:
                ans = messagebox.askyesno("확인", "지정 폴더 내에 동일한 파일이 있을 경우 원본 파일이 대체됩니다. 계속하시겠습니까?")
                if not ans:
                    return

        # UI Lock 적용
        self.is_processing = True
        self.cancel_event.clear()
        self.btn_start.configure(state="disabled", fg_color="#5A5A5A", text="처리 중...")
        self.btn_clear.configure(state="disabled")
        self.btn_add_files.configure(state="disabled")
        self.btn_add_folder.configure(state="disabled")
        self.slider_jobs.configure(state="disabled")

        self.processed_count = 0
        self.total_count = len(items_to_process)
        self._update_progress_display()

        # 전역 슬롯 초기화
        for idx in range(8):
            self.slot_data[idx] = {'filename': '대기 중...', 'pct': 0.0, 'time_str': '-', 'speed': '-', 'active': False}

        # 사용자 설정 딕셔너리 구축
        res_limit = self.resolution_limit.get()
        if res_limit == "1080p (FHD)":
            max_w, max_h = 1920, 1080
        elif res_limit == "720p (HD)":
            max_w, max_h = 1280, 720
        else:
            max_w, max_h = 9999, 9999 # 제한 없음
            
        settings = {
            'video_maxrate_mbps': float(self.video_bitrate.get()),
            'audio_bitrate': self.audio_bitrate.get(),
            'max_width': max_w,
            'max_height': max_h,
            'remux_threshold_mbps': 4.0, # 기본값
            'faststart': True,
            'delete_source': self.delete_source.get(),
            'nvenc_preset': 'p5'
        }

        # 스레드풀 및 대기열 실행 스레드
        threading.Thread(
            target=self._run_parallel_executor_thread,
            args=(items_to_process, settings, out_dir, name_o, name_val),
            daemon=True
        ).start()

    def _run_parallel_executor_thread(self, items, settings, output_dir, name_option, value):
        jobs = self.parallel_jobs.get()
        
        # ThreadPoolExecutor를 이용해 병렬 인코딩 처리
        with ThreadPoolExecutor(max_workers=jobs) as executor:
            futures = []
            for item in items:
                futures.append(
                    executor.submit(
                        self._encode_task_worker, 
                        item, 
                        settings, 
                        output_dir, 
                        name_option, 
                        value
                    )
                )
            
            # 각 스레드가 끝날 때마다 결과 취합
            for future in futures:
                future.result()

        # 모든 스레드 작업 완료
        self.after(0, self._on_conversion_finished)

    def _encode_task_worker(self, item, settings, output_dir, name_option, value):
        """개별 비디오 파일을 변환하는 스레드 워커"""
        if self.cancel_event.is_set():
            item.after(0, lambda: item.update_status("취소됨", "#FF007F"))
            return

        filename = os.path.basename(item.file_path)
        item.after(0, lambda: item.update_status("변환 중...", "#F77F00"))

        # 빈 슬롯 획득
        slot_id = None
        jobs = self.parallel_jobs.get()
        with self.slot_lock:
            for idx in range(jobs):
                if not self.slot_data[idx]['active']:
                    slot_id = idx
                    self.slot_data[slot_id] = {
                        'filename': filename, 'pct': 0.0, 'time_str': '-', 'speed': '-', 'active': True
                    }
                    break
        
        # 가용한 슬롯이 없으면 0번 슬롯 강제 할당
        if slot_id is None:
            slot_id = 0

        # 실시간 진행 콜백 함수 정의
        def progress_callback(pct, time_str, speed):
            with self.slot_lock:
                self.slot_data[slot_id]['pct'] = pct
                self.slot_data[slot_id]['time_str'] = time_str
                self.slot_data[slot_id]['speed'] = speed

        # 오디오/비디오 변환 프로세스 구동
        try:
            status, msg = process_video(
                item.file_path,
                output_dir,
                name_option,
                value,
                settings,
                progress_callback,
                self.cancel_event
            )
            
            # 대기열 항목 UI 상태 업데이트
            if status == 'SUCCESS':
                item.after(0, lambda: item.update_status("완료", "#06D6A0"))
            elif status == 'SUCCESS_DEL':
                item.after(0, lambda: item.update_status("완료(삭제)", "#06D6A0"))
            elif status == 'COPY':
                item.after(0, lambda: item.update_status("복사완료", "#06D6A0"))
            else:
                item.after(0, lambda: item.update_status("실패", "#FF007F"))
        except Exception as e:
            item.after(0, lambda: item.update_status("에러", "#FF007F"))
            print(f"변환 스레드 에러: {e}", file=sys.stderr)
        finally:
            # 슬롯 반환
            with self.slot_lock:
                self.slot_data[slot_id]['active'] = False

            # 전체 카운트 갱신
            self.processed_count += 1
            self.after(0, self._update_progress_display)

    def _on_conversion_finished(self):
        self.is_processing = False
        self.btn_start.configure(state="normal", fg_color="#06D6A0", text="변환 시작")
        self.btn_clear.configure(state="normal")
        self.btn_add_files.configure(state="normal")
        self.btn_add_folder.configure(state="normal")
        self.slider_jobs.configure(state="normal")

        self._update_progress_display()
        
        # 슬롯 리셋
        for idx in range(8):
            self.slot_data[idx]['active'] = False
            
        messagebox.showinfo("완료", "모든 비디오 변환/복사 작업이 완료되었습니다!")


if __name__ == "__main__":
    app = VideoConverterApp()
    app.mainloop()
