"""대기열과 진행 상황을 표시하는 CustomTkinter 위젯."""

import os
from tkinter import messagebox

import customtkinter as ctk

from .. import theme
from ..jobs.executor import STATE_PRESENTATION, QueueItemState


class QueueItemFrame(ctk.CTkFrame):
    def __init__(self, master, file_path, delete_callback, **kwargs):
        super().__init__(
            master, fg_color=theme.COLOR_PANEL, corner_radius=6, **kwargs
        )
        self.file_path = file_path
        self.video_info = None
        self.state = QueueItemState.QUEUED
        self.result_message = ""

        filename = os.path.basename(file_path)
        self.name_label = ctk.CTkLabel(
            self,
            text=filename,
            anchor="w",
            font=theme.font(12),
            text_color=theme.COLOR_TEXT,
        )
        self.name_label.pack(
            side="left", fill="x", expand=True, padx=(10, 5), pady=8
        )

        size_bytes = os.path.getsize(file_path)
        size_mb = size_bytes / (1024 * 1024)
        size_str = (
            f"{size_mb:.1f} MB"
            if size_mb < 1024
            else f"{size_mb / 1024:.2f} GB"
        )
        self.size_label = ctk.CTkLabel(
            self,
            text=size_str,
            width=90,
            font=theme.font(11),
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.size_label.pack(side="left", padx=5)

        self.res_label = ctk.CTkLabel(
            self,
            text="분석 중...",
            width=90,
            font=theme.font(11),
            text_color=theme.COLOR_TEXT_DIM,
        )
        self.res_label.pack(side="left", padx=5)

        self.status_label = ctk.CTkLabel(
            self,
            text="대기",
            width=90,
            font=theme.font(11, "bold"),
            text_color=theme.COLOR_QUEUED,
        )
        self.status_label.pack(side="left", padx=5)
        self.status_label.bind("<Button-1>", self._show_result_detail)

        self.del_btn = ctk.CTkButton(
            self,
            text="✕",
            width=28,
            height=24,
            fg_color=theme.COLOR_DELETE,
            hover_color=theme.COLOR_DELETE_HOVER,
            font=theme.font(10, "bold"),
            command=lambda: delete_callback(self),
        )
        self.del_btn.pack(side="right", padx=(5, 10))

    def set_state(self, state, message=""):
        self.state = (
            state if isinstance(state, QueueItemState) else QueueItemState(state)
        )
        self.result_message = message or ""
        text, text_color = STATE_PRESENTATION[self.state]
        self.status_label.configure(
            text=text,
            text_color=text_color,
            cursor="hand2" if self.result_message else "arrow",
        )

    def _show_result_detail(self, _event=None):
        if not self.result_message:
            return
        title = (
            "실패 상세"
            if self.state == QueueItemState.FAILED
            else "작업 상세"
        )
        messagebox.showinfo(
            title, self.result_message, parent=self.winfo_toplevel()
        )


class ScrollableQueueFrame(ctk.CTkScrollableFrame):
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            fg_color=theme.COLOR_APP_BG,
            label_text="대기열 목록",
            label_font=theme.font(13, "bold"),
            label_text_color=theme.COLOR_TEXT_MUTED,
            **kwargs,
        )
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
    def __init__(self, master, **kwargs):
        super().__init__(
            master, fg_color=theme.COLOR_PANEL_DARK, corner_radius=6, **kwargs
        )
        self.lbl_filename = ctk.CTkLabel(
            self,
            text="대기 중...",
            anchor="w",
            font=theme.font(11, "bold"),
            text_color=theme.COLOR_TEXT,
            width=220,
        )
        self.lbl_filename.pack(side="left", padx=(10, 5), pady=6)
        self.progress = ctk.CTkProgressBar(
            self,
            height=8,
            fg_color=theme.COLOR_PROGRESS_TRACK,
            progress_color=theme.COLOR_PRIMARY,
        )
        self.progress.pack(side="left", fill="x", expand=True, padx=10)
        self.progress.set(0.0)
        self.lbl_status = ctk.CTkLabel(
            self,
            text="0.0% (speed: -)",
            font=theme.font(11),
            text_color=theme.COLOR_TEXT_MUTED,
            width=140,
            anchor="e",
        )
        self.lbl_status.pack(side="right", padx=(5, 10))

    def reset(self):
        self.lbl_filename.configure(
            text="대기 중...", text_color=theme.COLOR_TEXT_MUTED
        )
        self.progress.set(0.0)
        self.lbl_status.configure(text="0.0% (speed: -)")

