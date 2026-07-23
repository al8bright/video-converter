"""병렬 변환 실행과 대시보드 슬롯 상태 관리."""

import os
import sys
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from enum import Enum

from .. import theme
from ..core import process_video


class QueueItemState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    COPY = "COPY"
    SUCCESS_DEL = "SUCCESS_DEL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


PROCESS_STATUS_TO_STATE = {
    "SUCCESS": QueueItemState.SUCCESS,
    "SUCCESS_DEL": QueueItemState.SUCCESS_DEL,
    "COPY": QueueItemState.COPY,
    "FAIL": QueueItemState.FAILED,
    "CANCELLED": QueueItemState.CANCELLED,
}

STATE_PRESENTATION = {
    QueueItemState.QUEUED: ("대기", theme.COLOR_QUEUED),
    QueueItemState.RUNNING: ("변환 중...", theme.COLOR_WARNING),
    QueueItemState.SUCCESS: ("완료", theme.COLOR_SUCCESS),
    QueueItemState.COPY: ("복사완료", theme.COLOR_SUCCESS),
    QueueItemState.SUCCESS_DEL: ("완료(삭제)", theme.COLOR_SUCCESS),
    QueueItemState.FAILED: ("실패 ⓘ", theme.COLOR_DANGER),
    QueueItemState.CANCELLED: ("취소됨 ⓘ", theme.COLOR_DANGER),
}


def process_status_to_state(status):
    return PROCESS_STATUS_TO_STATE.get(status, QueueItemState.FAILED)


def should_reprocess(state):
    try:
        normalized = (
            state if isinstance(state, QueueItemState) else QueueItemState(state)
        )
    except (TypeError, ValueError):
        return False
    return normalized == QueueItemState.QUEUED


def summarize_item_states(states):
    counts = {
        QueueItemState.SUCCESS: 0,
        QueueItemState.COPY: 0,
        QueueItemState.SUCCESS_DEL: 0,
        QueueItemState.FAILED: 0,
        QueueItemState.CANCELLED: 0,
    }
    for state in states:
        try:
            normalized = (
                state
                if isinstance(state, QueueItemState)
                else QueueItemState(state)
            )
        except (TypeError, ValueError):
            continue
        if normalized in counts:
            counts[normalized] += 1
    return counts


def format_result_summary(counts):
    completed = (
        counts[QueueItemState.SUCCESS]
        + counts[QueueItemState.COPY]
        + counts[QueueItemState.SUCCESS_DEL]
    )
    return (
        f"완료 {completed}개 "
        f"(변환 {counts[QueueItemState.SUCCESS]} / "
        f"복사 {counts[QueueItemState.COPY]} / "
        f"원본삭제 {counts[QueueItemState.SUCCESS_DEL]}) · "
        f"실패 {counts[QueueItemState.FAILED]}개 · "
        f"취소 {counts[QueueItemState.CANCELLED]}개"
    )


def empty_slot_data():
    return {
        "filename": "대기 중...",
        "pct": 0.0,
        "time_str": "-",
        "speed": "-",
        "active": False,
        "visible": False,
        "result_text": "",
    }


def cancel_pending_futures(future_items, ui_event_queue):
    """시작하지 않은 future를 취소하고 각 항목의 취소 결과를 알린다."""
    cancelled = set()
    for future, item in future_items.items():
        if future.cancelled():
            continue
        if future.cancel():
            cancelled.add(future)
            ui_event_queue.put(
                (
                    "item_result",
                    item,
                    QueueItemState.CANCELLED,
                    "변환 시작 전에 사용자가 작업을 취소했습니다.",
                )
            )
    return cancelled


def run_parallel_executor(
    items,
    settings,
    output_dir,
    name_option,
    value,
    jobs,
    cancel_event,
    slot_data,
    slot_lock,
    ui_event_queue,
):
    """기존 ThreadPoolExecutor 배치 구동을 GUI 밖에서 실행한다."""
    executor = ThreadPoolExecutor(max_workers=jobs)
    try:
        future_items = {}
        for item in items:
            future = executor.submit(
                encode_task_worker,
                item,
                settings,
                output_dir,
                name_option,
                value,
                jobs,
                cancel_event,
                slot_data,
                slot_lock,
                ui_event_queue,
            )
            future_items[future] = item

        pending = set(future_items)
        cancellation_reported = set()
        while pending:
            if cancel_event.is_set():
                cancellation_reported.update(
                    cancel_pending_futures(
                        {
                            future: future_items[future]
                            for future in pending
                            if future not in cancellation_reported
                        },
                        ui_event_queue,
                    )
                )

            done, pending = wait(
                pending,
                timeout=0.1,
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                if future.cancelled():
                    continue
                item = future_items[future]
                try:
                    future.result()
                except Exception as exc:
                    ui_event_queue.put(
                        (
                            "item_result",
                            item,
                            QueueItemState.FAILED,
                            f"작업 스레드가 비정상 종료되었습니다: {exc}",
                        )
                    )
    finally:
        executor.shutdown(
            wait=True,
            cancel_futures=cancel_event.is_set(),
        )
        ui_event_queue.put(("batch_finished",))


def encode_task_worker(
    item,
    settings,
    output_dir,
    name_option,
    value,
    jobs,
    cancel_event,
    slot_data,
    slot_lock,
    ui_event_queue,
):
    """개별 비디오 파일을 변환하고 UI 이벤트만 큐에 기록한다."""
    if cancel_event.is_set():
        ui_event_queue.put(
            (
                "item_result",
                item,
                QueueItemState.CANCELLED,
                "변환 시작 전에 사용자가 작업을 취소했습니다.",
            )
        )
        return

    filename = os.path.basename(item.file_path)
    ui_event_queue.put(("item_state", item, QueueItemState.RUNNING, ""))
    slot_id = None
    with slot_lock:
        for index in range(jobs):
            if not slot_data[index]["active"]:
                slot_id = index
                slot_data[slot_id] = {
                    "filename": filename,
                    "pct": 0.0,
                    "time_str": "-",
                    "speed": "-",
                    "active": True,
                    "visible": True,
                    "result_text": "",
                }
                break

    def progress_callback(pct, time_str, speed):
        if slot_id is None:
            return
        with slot_lock:
            slot_data[slot_id]["pct"] = pct
            slot_data[slot_id]["time_str"] = time_str
            slot_data[slot_id]["speed"] = speed

    state = QueueItemState.FAILED
    message = "알 수 없는 변환 오류가 발생했습니다."
    try:
        status, message = process_video(
            item.file_path,
            output_dir,
            name_option,
            value,
            settings,
            progress_callback,
            cancel_event,
        )
        state = process_status_to_state(status)
        if not message:
            message = "변환 모듈이 상세 결과 메시지를 제공하지 않았습니다."
    except Exception as exc:
        state = QueueItemState.FAILED
        message = f"변환 처리 중 예외가 발생했습니다: {exc}"
        print(f"변환 스레드 에러: {exc}", file=sys.stderr)
    finally:
        if slot_id is not None:
            with slot_lock:
                slot = slot_data[slot_id]
                slot["active"] = False
                slot["visible"] = True
                slot["result_text"] = STATE_PRESENTATION[state][0]
                if state in {
                    QueueItemState.SUCCESS,
                    QueueItemState.SUCCESS_DEL,
                    QueueItemState.COPY,
                }:
                    slot["pct"] = 100.0
        ui_event_queue.put(("item_result", item, state, message))
