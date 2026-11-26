import os
import queue
import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

from .. import theme
from ..config import (
    AUDIO_BITRATE_OPTIONS,
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_RESOLUTION,
    DEFAULT_VIDEO_MAXRATE_MBPS,
    MAX_SLOTS,
    RESOLUTION_OPTIONS,
    SUPPORTED_EXTENSIONS,
    VIDEO_BITRATE_OPTIONS,
    build_settings,
)
from ..core import get_video_info

try:
    from videoconverter.core import terminate_all_processes
except ImportError:
    terminate_all_processes = None

from ..hardware import (
    get_nvidia_gpu_info,
    get_system_ram_gb,
    recommend_parallel_jobs,
)
from ..jobs.executor import (
    QueueItemState,
    empty_slot_data,
    format_result_summary,
    run_parallel_executor,
    should_reprocess,
    summarize_item_states,
)
from ..resources import resource_path
from .dnd import DND_FILES, HAS_DND, build_base_class, parse_dropped_files
from .help_text import PERFORMANCE_HELP, SETTINGS_HELP
from .widgets import ProgressSlotFrame, ScrollableQueueFrame

BaseClass = build_base_class()


def signal_conversion_shutdown(cancel_event, process_terminator):
    """취소 이벤트를 설정하고 사용 가능한 변환 프로세스 종료기를 호출한다."""
    cancel_event.set()
    if process_terminator is None:
        return False
    process_terminator()
    return True


class VideoConverterApp(BaseClass):
    def __init__(self):
        super().__init__()

        self.title("CUDA/NVENC Video Converter v1.0.0")
        self.geometry("820x820")
        self.minsize(780, 650)

        # 윈도우 타이틀바 아이콘 지정
        try:
            icon_path = resource_path("assets/video_icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception:
            pass


        # 데이터 변수 바인딩
        # 하드웨어 정보 탐지 및 권장 작업수 세팅
        self.gpu_name, self.vram_mb = get_nvidia_gpu_info()
        self.sys_ram_gb = get_system_ram_gb()

        rec_jobs = recommend_parallel_jobs(self.gpu_name, self.vram_mb)
        self.parallel_jobs = ctk.IntVar(value=rec_jobs)
        self.video_bitrate = ctk.StringVar(
            value=str(DEFAULT_VIDEO_MAXRATE_MBPS)
        )
        self.audio_bitrate = ctk.StringVar(value=DEFAULT_AUDIO_BITRATE)
        self.resolution_limit = ctk.StringVar(value=DEFAULT_RESOLUTION)
        self.delete_source = ctk.BooleanVar(value=False)


        self.save_mode = ctk.StringVar(value="same")
        self.custom_output_path = ctk.StringVar(value="")
        self.name_option = ctk.StringVar(value="suffix")
        self.name_value = ctk.StringVar(value="_cuda")

        self.is_processing = False
        self.cancel_event = threading.Event()
        self.processed_count = 0
        self.total_count = 0
        self.batch_results = {}
        self.last_result_summary = ""
        self.executor_thread = None
        self.ui_event_queue = queue.Queue()
        self._ui_loop_running = True

        # 병렬 진행 슬롯 데이터 스토리지
        # 구조: { slot_id: {filename, pct, time_str, speed, active, visible, result_text} }
        self.slot_data = {
            index: empty_slot_data() for index in range(MAX_SLOTS)
        }
        self.slot_lock = threading.Lock()

        # UI 위젯 생성
        self._create_widgets()
        self.protocol("WM_DELETE_WINDOW", self._on_close_requested)

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
        self.dnd_panel = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL, height=90, corner_radius=8)
        self.dnd_panel.grid(row=0, column=0, padx=15, pady=(15, 6), sticky="ew")

        dnd_label = ctk.CTkLabel(
            self.dnd_panel,
            text="변환할 비디오 파일 또는 폴더를 여기에 끌어다 놓으세요 (NVIDIA GPU 가속 권장)",
            font=theme.font(12, "bold"),
            text_color=theme.COLOR_TEXT_DROP
        )
        dnd_label.pack(pady=(12, 5))

        btn_frame = ctk.CTkFrame(self.dnd_panel, fg_color="transparent")
        btn_frame.pack(pady=(0, 12))

        self.btn_add_files = ctk.CTkButton(
            btn_frame, text="파일 추가...", command=self._browse_files, width=120, height=28, fg_color=theme.COLOR_PRIMARY, hover_color=theme.COLOR_PRIMARY_HOVER
        )
        self.btn_add_files.pack(side="left", padx=10)

        self.btn_add_folder = ctk.CTkButton(
            btn_frame, text="폴더 추가...", command=self._browse_folder, width=120, height=28, fg_color=theme.COLOR_PRIMARY, hover_color=theme.COLOR_PRIMARY_HOVER
        )
        self.btn_add_folder.pack(side="left", padx=10)

        # 1.5 시스템 정보 바 패널 (row=1)
        sys_info_bar = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL_DARK, height=32, corner_radius=6)
        sys_info_bar.grid(row=1, column=0, padx=15, pady=(4, 4), sticky="ew")

        if self.gpu_name:
            gpu_desc = f"{self.gpu_name} ({self.vram_mb/1024:.1f}GB VRAM)"
        else:
            gpu_desc = "NVIDIA GPU 미감지 (CPU/S/W 모드 작동)"

        sys_ram_desc = f"{self.sys_ram_gb} GB" if self.sys_ram_gb > 0 else "감지 불가"

        info_text = f"🖥️ 시스템 사양 감지  |  NVIDIA GPU: [{gpu_desc}]  |  시스템 RAM: [{sys_ram_desc}]"
        lbl_sys_info = ctk.CTkLabel(
            sys_info_bar, text=info_text, font=theme.font(11, "bold"), text_color=theme.COLOR_TEXT_MUTED
        )
        lbl_sys_info.pack(side="left", padx=15, pady=4)

        # 2. 상세 설정 영역 패널
        self.settings_panel = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL, corner_radius=8)
        self.settings_panel.grid(row=2, column=0, padx=15, pady=4, sticky="ew")
        self.settings_panel.grid_columnconfigure(1, weight=1)
        self.settings_panel.grid_columnconfigure(3, weight=1)

        # 2.1 동시 작업수 슬라이더
        lbl_jobs = ctk.CTkLabel(self.settings_panel, text="동시 변환 작업 수:", font=theme.font(11, "bold"))
        lbl_jobs.grid(row=0, column=0, padx=15, pady=5, sticky="w")

        slider_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        slider_frame.grid(row=0, column=1, padx=15, pady=5, sticky="ew")

        self.slider_jobs = ctk.CTkSlider(
            slider_frame, from_=1, to=8, number_of_steps=7, variable=self.parallel_jobs, command=self._on_jobs_slider_changed, height=16
        )
        self.slider_jobs.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.lbl_jobs_val = ctk.CTkLabel(slider_frame, text=f"{self.parallel_jobs.get()}개", font=theme.font(11, "bold"), width=30)
        self.lbl_jobs_val.pack(side="right")


        # 2.2 비트레이트 설정
        lbl_v_bitrate = ctk.CTkLabel(self.settings_panel, text="최대 비디오 대역폭:", font=theme.font(11, "bold"))
        lbl_v_bitrate.grid(row=0, column=2, padx=15, pady=5, sticky="w")

        combo_v_bitrate = ctk.CTkOptionMenu(
            self.settings_panel, values=list(VIDEO_BITRATE_OPTIONS), variable=self.video_bitrate, width=90, height=24
        )
        combo_v_bitrate.grid(row=0, column=3, padx=15, pady=5, sticky="w")

        # 2.3 오디오 비트레이트 & 해상도 한도 & 원본 삭제 토글
        lbl_a_bitrate = ctk.CTkLabel(self.settings_panel, text="오디오 비트레이트:", font=theme.font(11, "bold"))
        lbl_a_bitrate.grid(row=1, column=0, padx=15, pady=5, sticky="w")

        combo_a_bitrate = ctk.CTkOptionMenu(
            self.settings_panel, values=list(AUDIO_BITRATE_OPTIONS), variable=self.audio_bitrate, width=100, height=24
        )
        combo_a_bitrate.grid(row=1, column=1, padx=15, pady=5, sticky="w")

        lbl_res = ctk.CTkLabel(self.settings_panel, text="해상도 제한:", font=theme.font(11, "bold"))
        lbl_res.grid(row=1, column=2, padx=15, pady=5, sticky="w")

        combo_res = ctk.CTkOptionMenu(
            self.settings_panel, values=list(RESOLUTION_OPTIONS), variable=self.resolution_limit, width=110, height=24
        )
        combo_res.grid(row=1, column=3, padx=15, pady=5, sticky="w")

        self.chk_delete_src = ctk.CTkSwitch(
            self.settings_panel,
            text="변환 완료 후 원본 파일 자동 삭제",
            variable=self.delete_source,
            command=self._on_delete_source_toggle,
            font=theme.font(11, "bold")
        )
        self.chk_delete_src.grid(row=2, column=0, columnspan=2, padx=15, pady=5, sticky="w")

        # 2.4 저장 및 파일명 변경 규칙
        lbl_save_loc = ctk.CTkLabel(self.settings_panel, text="저장 위치 설정:", font=theme.font(11, "bold"))
        lbl_save_loc.grid(row=3, column=0, padx=15, pady=4, sticky="nw")

        save_loc_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        save_loc_frame.grid(row=3, column=1, columnspan=3, padx=15, pady=6, sticky="ew")

        self.rdo_save_same = ctk.CTkRadioButton(
            save_loc_frame, text="원본과 동일한 폴더에 저장", variable=self.save_mode, value="same", command=self._toggle_save_ui, font=theme.font(11)
        )
        self.rdo_save_same.pack(side="left", padx=(0, 15))

        self.rdo_save_custom = ctk.CTkRadioButton(
            save_loc_frame, text="지정 폴더 저장:", variable=self.save_mode, value="custom", command=self._toggle_save_ui, font=theme.font(11)
        )
        self.rdo_save_custom.pack(side="left", padx=(0, 10))

        self.entry_custom_path = ctk.CTkEntry(
            save_loc_frame, textvariable=self.custom_output_path, state="disabled", width=250, height=22
        )
        self.entry_custom_path.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.btn_browse_out = ctk.CTkButton(
            save_loc_frame, text="변경", state="disabled", command=self._browse_output_dir, width=50, height=22, fg_color=theme.COLOR_SECONDARY, hover_color=theme.COLOR_SECONDARY_HOVER
        )
        self.btn_browse_out.pack(side="right")

        lbl_name_opt = ctk.CTkLabel(self.settings_panel, text="파일명 규칙:", font=theme.font(11, "bold"))
        lbl_name_opt.grid(row=4, column=0, padx=15, pady=6, sticky="nw")

        name_opt_frame = ctk.CTkFrame(self.settings_panel, fg_color="transparent")
        name_opt_frame.grid(row=4, column=1, columnspan=3, padx=15, pady=6, sticky="ew")

        self.rdo_name_overwrite = ctk.CTkRadioButton(
            name_opt_frame, text="덮어쓰기", variable=self.name_option, value="overwrite", command=self._toggle_name_ui, font=theme.font(11)
        )
        self.rdo_name_overwrite.pack(side="left", padx=(0, 15))

        self.rdo_name_suffix = ctk.CTkRadioButton(
            name_opt_frame, text="접미사 추가:", variable=self.name_option, value="suffix", command=self._toggle_name_ui, font=theme.font(11)
        )
        self.rdo_name_suffix.pack(side="left", padx=(0, 5))

        self.entry_name_value = ctk.CTkEntry(
            name_opt_frame, textvariable=self.name_value, width=100, height=22
        )
        self.entry_name_value.pack(side="left")

        # 2.5 가이드/도움말 팝업 버튼 추가
        self.btn_help = ctk.CTkButton(
            self.settings_panel,
            text="❔ 설정 도움말 & 성능 팁",
            font=theme.font(11, "bold"),
            fg_color=theme.COLOR_SECONDARY,
            hover_color=theme.COLOR_SECONDARY_HOVER,
            width=150,
            height=24,
            command=self._show_help_popup
        )
        self.btn_help.grid(row=2, column=2, columnspan=2, padx=15, pady=5, sticky="e")


        # 3. 실시간 병렬 인코딩 대시보드 영역 (실시간 진행 상황 뷰어 - 처음엔 grid하지 않고 변환 시작 시 노출)
        self.dashboard_panel = ctk.CTkFrame(self, fg_color=theme.COLOR_DASHBOARD, corner_radius=8)

        lbl_dash = ctk.CTkLabel(self.dashboard_panel, text="현재 실행 중인 변환 작업", font=theme.font(12, "bold"), text_color=theme.COLOR_TEXT_MUTED)
        lbl_dash.pack(anchor="w", padx=15, pady=(8, 4))

        # 8개의 진행바 슬롯 생성
        self.slot_frames = []
        for _i in range(MAX_SLOTS):
            slot = ProgressSlotFrame(self.dashboard_panel)
            self.slot_frames.append(slot)

        # 초기 작업 수 기준 슬롯 프레임 노출
        self._arrange_progress_slots()

        # 4. 대기열 테이블 타이틀 헤더 프레임
        self.table_header = ctk.CTkFrame(self, fg_color=theme.COLOR_PANEL, height=28, corner_radius=4)
        self.table_header.grid(row=4, column=0, padx=15, pady=(8, 0), sticky="ew")

        lbl_h_name = ctk.CTkLabel(self.table_header, text="파일명", anchor="w", font=theme.font(11, "bold"), text_color=theme.COLOR_TEXT_MUTED)
        lbl_h_name.pack(side="left", fill="x", expand=True, padx=(15, 5), pady=2)

        lbl_h_size = ctk.CTkLabel(self.table_header, text="원본 크기", width=90, font=theme.font(11, "bold"), text_color=theme.COLOR_TEXT_MUTED)
        lbl_h_size.pack(side="left", padx=5, pady=2)

        lbl_h_res = ctk.CTkLabel(self.table_header, text="설정 해상도", width=90, font=theme.font(11, "bold"), text_color=theme.COLOR_TEXT_MUTED)
        lbl_h_res.pack(side="left", padx=5, pady=2)

        lbl_h_status = ctk.CTkLabel(self.table_header, text="상태", width=90, font=theme.font(11, "bold"), text_color=theme.COLOR_TEXT_MUTED)
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

        self.overall_progress_bar = ctk.CTkProgressBar(self.control_panel, height=12, fg_color=theme.COLOR_PROGRESS_TRACK, progress_color=theme.COLOR_SUCCESS)
        self.overall_progress_bar.grid(row=0, column=0, columnspan=3, pady=(0, 10), sticky="ew")
        self.overall_progress_bar.set(0.0)

        self.lbl_progress = ctk.CTkLabel(self.control_panel, text="대기 중 (0개 파일)", font=theme.font(12))
        self.lbl_progress.grid(row=1, column=0, sticky="w")

        self.btn_clear = ctk.CTkButton(
            self.control_panel, text="대기열 비우기", command=self._clear_queue, width=120, height=35, fg_color=theme.COLOR_SECONDARY, hover_color=theme.COLOR_SECONDARY_HOVER
        )
        self.btn_clear.grid(row=1, column=1, padx=5, sticky="e")

        self.btn_start = ctk.CTkButton(
            self.control_panel, text="변환 시작", command=self._start_conversion, width=120, height=35, fg_color=theme.COLOR_SUCCESS, hover_color=theme.COLOR_SUCCESS_HOVER, text_color=theme.COLOR_BUTTON_TEXT, font=theme.font(12, "bold")
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

    def _on_delete_source_toggle(self):
        if not self.delete_source.get() or self.save_mode.get() != "same":
            return
        confirmed = messagebox.askyesno(
            "원본 파일 삭제 경고",
            "이 옵션을 켜면 변환에 성공한 원본 파일이 영구 삭제됩니다.\n"
            "현재 저장 위치도 원본과 같은 폴더입니다.\n\n"
            "원본 자동 삭제를 사용하시겠습니까?",
            parent=self,
        )
        if not confirmed:
            self.delete_source.set(False)

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
        self.batch_results.clear()
        self.last_result_summary = ""
        with self.slot_lock:
            for idx in range(MAX_SLOTS):
                self.slot_data[idx] = empty_slot_data()
        self.dashboard_panel.grid_forget()
        self._update_progress_display()
        self.overall_progress_bar.set(0.0)

    def _update_progress_display(self):
        count = len(self.queue_frame.items)
        if self.is_processing:
            self.lbl_progress.configure(text=f"처리 중 ({self.processed_count}/{self.total_count})")
            prog_val = self.processed_count / max(1, self.total_count)
            self.overall_progress_bar.set(prog_val)
        elif self.last_result_summary:
            self.lbl_progress.configure(text=self.last_result_summary)
            self.overall_progress_bar.set(
                self.processed_count / max(1, self.total_count)
            )
        else:
            self.lbl_progress.configure(text=f"대기 중 ({count}개 파일)")
            self.overall_progress_bar.set(0.0)

    # 비동기 파일 속성 획득 스레드
    def _analyze_videos_info_thread(self, items):
        for item in items:
            try:
                info = get_video_info(item.file_path)
                if info:
                    res_text = f"{info['width']}x{info['height']}"
                else:
                    res_text = "분석 실패"
                self.ui_event_queue.put(("analysis_result", item, info, res_text))
            except Exception as exc:
                self.ui_event_queue.put(
                    ("analysis_result", item, None, f"에러: {exc}")
                )

    def _drain_ui_events(self):
        while True:
            try:
                event = self.ui_event_queue.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]
            if event_type == "analysis_result":
                _, item, info, res_text = event
                if item in self.queue_frame.items:
                    item.video_info = info
                    item.res_label.configure(text=res_text)
            elif event_type == "item_state":
                _, item, state, message = event
                if item in self.queue_frame.items:
                    item.set_state(state, message)
            elif event_type == "item_result":
                _, item, state, message = event
                self.batch_results[item] = state
                if item in self.queue_frame.items:
                    item.set_state(state, message)
                self.processed_count += 1
                self._update_progress_display()
            elif event_type == "batch_finished":
                self._on_conversion_finished()

    # 스레드 안전 UI 업데이트 루프
    def _update_ui_loop(self):
        """백그라운드 스레드가 기록해둔 slot_data 상태값을 100ms 주기로 실제 UI 위젯에 바인딩"""
        self._drain_ui_events()
        if not self._ui_loop_running:
            return

        with self.slot_lock:
            for idx, slot_frame in enumerate(self.slot_frames):
                data = self.slot_data[idx]
                if data['active'] or data.get('visible', False):
                    # 축약 파일명 설정
                    name = data['filename']
                    short_name = name if len(name) <= 30 else name[:27] + "..."
                    slot_frame.lbl_filename.configure(text=short_name, text_color=theme.COLOR_TEXT)

                    # 진행률 반영
                    slot_frame.progress.set(data['pct'] / 100.0)
                    result_text = data.get('result_text', '')
                    if result_text:
                        slot_frame.lbl_status.configure(text=result_text)
                    else:
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

        items_to_process = [
            item for item in self.queue_frame.items
            if should_reprocess(item.state)
        ]
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

        if self.delete_source.get() and save_m == "same":
            ans = messagebox.askyesno(
                "원본 파일 삭제 경고",
                f"변환에 성공한 원본 파일 최대 {len(items_to_process)}개가 영구 삭제됩니다.\n"
                "출력 파일은 원본과 같은 폴더에 저장됩니다.\n\n"
                "원본 자동 삭제를 적용해 변환을 시작하시겠습니까?",
                parent=self,
            )
            if not ans:
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
        self.btn_start.configure(
            state="normal",
            command=self._request_cancel,
            fg_color=theme.COLOR_CANCEL,
            hover_color=theme.COLOR_CANCEL_HOVER,
            text_color=theme.COLOR_TEXT,
            text="취소",
        )
        self.btn_clear.configure(state="disabled")
        self.btn_add_files.configure(state="disabled")
        self.btn_add_folder.configure(state="disabled")
        self.slider_jobs.configure(state="disabled")

        self.processed_count = 0
        self.total_count = len(items_to_process)
        self.batch_results = {}
        self.last_result_summary = ""
        self._update_progress_display()

        # 전역 슬롯 초기화
        with self.slot_lock:
            for idx in range(MAX_SLOTS):
                self.slot_data[idx] = empty_slot_data()
        self.dashboard_panel.grid(
            row=3, column=0, padx=15, pady=4, sticky="ew"
        )
        self._arrange_progress_slots()

        settings = build_settings(
            self.video_bitrate.get(),
            self.audio_bitrate.get(),
            self.resolution_limit.get(),
            self.delete_source.get(),
        )

        jobs = self.parallel_jobs.get()
        # 스레드풀 및 대기열 실행 스레드
        self.executor_thread = threading.Thread(
            target=run_parallel_executor,
            args=(
                items_to_process,
                settings,
                out_dir,
                name_o,
                name_val,
                jobs,
                self.cancel_event,
                self.slot_data,
                self.slot_lock,
                self.ui_event_queue,
            ),
            daemon=True,
        )
        self.executor_thread.start()

    def _signal_conversion_shutdown(self):
        try:
            signal_conversion_shutdown(
                self.cancel_event,
                terminate_all_processes,
            )
        except Exception as exc:
            print(f"변환 프로세스 종료 중 오류: {exc}")

    def _wait_for_executor_shutdown(self, timeout=1.0):
        worker = self.executor_thread
        if (
            worker is not None
            and worker is not threading.current_thread()
            and worker.is_alive()
        ):
            worker.join(timeout=timeout)

    def _shutdown_app(self):
        self._signal_conversion_shutdown()
        self._wait_for_executor_shutdown()
        self._ui_loop_running = False
        self.destroy()

    def _begin_cancel(self):
        if not self.is_processing:
            return
        self._signal_conversion_shutdown()
        self.btn_start.configure(
            state="disabled",
            fg_color=theme.COLOR_DISABLED,
            text="취소 중...",
        )
        self.lbl_progress.configure(
            text=f"취소 요청 중 ({self.processed_count}/{self.total_count})"
        )
        self._wait_for_executor_shutdown()

    def _request_cancel(self):
        if not self.is_processing:
            return
        confirmed = messagebox.askyesno(
            "변환 취소",
            "현재 실행 중인 변환과 아직 시작하지 않은 대기 작업을 모두 취소하시겠습니까?\n"
            "처리 중이던 출력 파일은 완전하지 않을 수 있습니다.",
            parent=self,
        )
        if confirmed:
            self._begin_cancel()

    def _on_close_requested(self):
        if not self.is_processing:
            self._shutdown_app()
            return

        confirmed = messagebox.askyesno(
            "변환 취소 후 종료",
            "변환이 진행 중입니다.\n"
            "실행 및 대기 작업을 모두 취소한 뒤 프로그램을 종료하시겠습니까?",
            parent=self,
        )
        if confirmed:
            self._shutdown_app()

    def _on_conversion_finished(self):
        self.is_processing = False
        self.executor_thread = None
        counts = summarize_item_states(self.batch_results.values())
        self.last_result_summary = format_result_summary(counts)
        self.btn_start.configure(
            state="normal",
            command=self._start_conversion,
            fg_color=theme.COLOR_SUCCESS,
            hover_color=theme.COLOR_SUCCESS_HOVER,
            text_color=theme.COLOR_BUTTON_TEXT,
            text="변환 시작",
        )
        self.btn_clear.configure(state="normal")
        self.btn_add_files.configure(state="normal")
        self.btn_add_folder.configure(state="normal")
        self.slider_jobs.configure(state="normal")

        self._update_progress_display()

        detail = (
            f"전체 {self.total_count}개 작업 결과\n\n"
            f"{self.last_result_summary}\n\n"
            "실패 또는 취소 항목의 상태를 클릭하면 상세 사유를 확인할 수 있습니다."
        )
        has_problem = (
            counts[QueueItemState.FAILED] > 0
            or counts[QueueItemState.CANCELLED] > 0
        )
        if has_problem:
            messagebox.showwarning("작업 결과 확인", detail, parent=self)
        else:
            messagebox.showinfo("작업 완료", detail, parent=self)

    def _show_help_popup(self):
        """세련된 도움말/팁 안내 팝업창(Toplevel) 호출"""
        popup = ctk.CTkToplevel(self)
        popup.title("NVIDIA Video Converter 설정 가이드 & 팁")
        popup.geometry("600x480")
        popup.resizable(False, False)

        # 메인 윈도우 위에 항상 표시되도록 모달화
        popup.transient(self)
        popup.grab_set()

        # 내부 메인 스크롤 프레임 구성
        scroll = ctk.CTkScrollableFrame(popup, fg_color=theme.COLOR_PANEL_DARK, corner_radius=8)
        scroll.pack(fill="both", expand=True, padx=15, pady=(15, 10))

        # 타이틀
        lbl_title = ctk.CTkLabel(
            scroll, text="💡 설정 가이드 & 성능 팁", font=theme.font(16, "bold"), text_color=theme.COLOR_SUCCESS
        )
        lbl_title.pack(anchor="w", padx=10, pady=(10, 15))

        # 섹션 1: NVIDIA GPU 가속과 100% 가용량
        lbl_sec1_title = ctk.CTkLabel(
            scroll, text="⚡ NVIDIA GPU 가속 & 100% 가용 정보", font=theme.font(13, "bold"), text_color=theme.COLOR_PRIMARY
        )
        lbl_sec1_title.pack(anchor="w", padx=10, pady=(5, 5))

        lbl_sec1_desc = ctk.CTkLabel(
            scroll, text=PERFORMANCE_HELP, font=theme.font(11), text_color=theme.COLOR_TEXT, justify="left", anchor="w"
        )
        lbl_sec1_desc.pack(anchor="w", padx=15, pady=(0, 15))

        # 섹션 2: 세부 설정 가이드
        lbl_sec2_title = ctk.CTkLabel(
            scroll, text="⚙️ 세부 변환 설정 안내", font=theme.font(13, "bold"), text_color=theme.COLOR_PRIMARY
        )
        lbl_sec2_title.pack(anchor="w", padx=10, pady=(5, 5))

        lbl_sec2_desc = ctk.CTkLabel(
            scroll, text=SETTINGS_HELP, font=theme.font(11), text_color=theme.COLOR_TEXT, justify="left", anchor="w"
        )
        lbl_sec2_desc.pack(anchor="w", padx=15, pady=(0, 10))

        # 닫기 버튼
        btn_close = ctk.CTkButton(
            popup, text="닫기", command=popup.destroy, width=100, height=30, fg_color=theme.COLOR_SECONDARY, hover_color=theme.COLOR_SECONDARY_HOVER
        )
        btn_close.pack(pady=10)


def main():
    """애플리케이션 테마를 설정하고 Tk 이벤트 루프를 시작한다."""
    ctk.set_appearance_mode("Dark")
    ctk.set_default_color_theme("blue")
    app = VideoConverterApp()
    app.mainloop()


