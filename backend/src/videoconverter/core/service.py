"""앱 상태와 작업: 대기열, 영상 분석, 일괄 변환.

화면(웹뷰)은 이 상태의 사본만 받아 그린다. 상태를 바꿀 때마다 version 을 올리고,
API 의 WebSocket 이 바뀐 것을 화면에 밀어 준다. 모든 변경은 lock 안에서 한다.

항목 상태: analyzing(영상 정보 읽는 중) → waiting → converting → done | copied | failed | stopped
  copied 는 비트레이트가 이미 낮아 다시 인코딩하지 않고 mp4 로 옮겨 담은 것이다.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any

from videoconverter import hardware
from videoconverter.config import (
    MAX_SLOTS,
    REMUX_THRESHOLD_MBPS,
    RESOLUTIONS,
    SUPPORTED_EXTENSIONS,
    Settings,
    SettingsStore,
    encode_settings,
)
from videoconverter.core import tools
from videoconverter.core.ffmpeg_cmd import _force_mp4_ext, resolve_output_path, should_remux
from videoconverter.core.pipeline import process_video
from videoconverter.core.probe import get_video_info
from videoconverter.core.runner import terminate_all_processes

NOTICE_KEEP = 20
ANALYZE_WORKERS = 4  # ffprobe 를 동시에 몇 개 돌릴지. 폴더째 넣으면 수백 개가 한꺼번에 들어온다

STARTABLE = ("waiting", "stopped", "failed")
FINISHED = ("done", "copied")
# process_video 결과 → (항목 상태, 원본을 지웠는지)
RESULTS = {
    "SUCCESS": ("done", False),
    "SUCCESS_DEL": ("done", True),
    "COPY": ("copied", False),
    "COPY_DEL": ("copied", True),
    "CANCELLED": ("stopped", False),
}
BAD_NAME_CHARS = '\\/:*?"<>|'
# 변환 결과에 영향을 주는 설정. 변환 중에는 바꾸지 못한다
BATCH_KEYS = ("jobs", "video_rate", "audio_rate", "resolution", "delete_source", "save_mode", "save_dir",
              "name_mode", "suffix")


class ServiceError(Exception):
    """사용자에게 그대로 보여 줄 문구. status 는 HTTP 상태 코드로 쓴다."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Item:
    path: str
    name: str
    size: int = 0  # 바이트
    width: int = 0
    height: int = 0
    duration: float = 0.0  # 초
    bit_rate: int = 0  # 비디오 비트레이트(bps). 모르면 0
    status: str = "analyzing"
    message: str | None = None  # 결과 설명 또는 실패 사유
    source_deleted: bool = False
    output: str | None = None  # 만든 파일(완료 후)
    percent: float = 0.0  # 0~1
    time: str = ""  # 변환한 지점(ffmpeg time=)
    speed: str = ""  # 재생 속도 대비 배속(ffmpeg speed=)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class Batch:
    running: bool = False
    stop_requested: bool = False
    total: int = 0
    finished: int = 0  # 결과가 난 항목 수(시작하기 전에 멈춘 것은 세지 않는다)
    jobs: int = 0
    started_at: float | None = None
    result: dict | None = None  # 끝난 뒤 '지난 변환 결과'
    added_during: int = 0


def _spawn_thread(fn: Callable, *args: Any) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


def _key(path: str) -> str:
    """같은 파일인지 비교하는 열쇠. Windows 는 대소문자와 / \\ 를 가리지 않는다."""
    return os.path.normcase(os.path.abspath(path))


def scan_paths(paths: Iterable[str]) -> tuple[list[str], int]:
    """파일·폴더(하위 폴더까지)에서 변환할 수 있는 영상을 찾는다. (영상 경로들, 건너뛴 파일 수)."""
    found: list[str] = []
    skipped = 0
    for raw in paths:
        p = os.path.abspath(os.path.normpath(raw))
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs.sort()
                for f in sorted(files):
                    if f.lower().endswith(SUPPORTED_EXTENSIONS):
                        found.append(os.path.join(root, f))
                    else:
                        skipped += 1
        elif os.path.isfile(p) and p.lower().endswith(SUPPORTED_EXTENSIONS):
            found.append(p)
        else:
            skipped += 1
    return found, skipped


def output_path(source: str, out_dir: str, name_mode: str, suffix: str) -> str:
    """process_video 가 만들 파일의 경로(항상 .mp4)."""
    value = suffix if name_mode == "suffix" else ""
    return _force_mp4_ext(os.path.abspath(resolve_output_path(source, out_dir, name_mode, value)))


def plan_for(item: dict, s: Settings) -> str | None:
    """지금 설정으로 변환하면 무엇을 할지: scale(줄여서 변환) | encode(변환) | copy(mp4로 복사). 정보가 없으면 None.

    process_video 와 같은 규칙이다. 실제로는 복사가 실패하면 변환으로 넘어간다.
    """
    if not item["width"]:
        return None
    max_w, max_h = RESOLUTIONS[s.resolution]
    if item["width"] > max_w or item["height"] > max_h:
        return "scale"
    if should_remux(item["bit_rate"], item["duration"], item["size"], REMUX_THRESHOLD_MBPS, False):
        return "copy"
    return "encode"


def describe_result(tally: dict, total: int) -> tuple[str, bool]:
    ok = tally["done"] + tally["copied"]
    parts = [f"{total}개 중 {ok}개 완료"]
    if tally["failed"]:
        parts.append(f"실패 {tally['failed']}개")
    if tally["stopped"]:
        parts.append(f"중단 {tally['stopped']}개")
    return ", ".join(parts), ok == total


class Service:
    def __init__(self, settings: SettingsStore | None = None, probe: Callable[[str], dict | None] | None = None,
                 convert: Callable[..., tuple[str, str]] | None = None, spawn: Callable[..., None] | None = None,
                 kill: Callable[[], None] | None = None, detect: Callable[[], dict] | None = None) -> None:
        self.settings = settings or SettingsStore()
        self.probe = probe or get_video_info
        self.convert = convert or process_video
        self.spawn = spawn or _spawn_thread
        self.kill = kill or terminate_all_processes
        self.detect = detect or hardware.detect
        self.lock = threading.RLock()
        self.items: list[Item] = []
        self.batch = Batch()
        self.notices: list[dict] = []
        self._notice_id = 0
        self._cancel = threading.Event()
        self._hw: dict | None = None
        self._hw_lock = threading.Lock()
        self.version = 0  # 대기열·변환·설정·알림이 바뀌면 올린다

    # ------------------------------------------------------------------ 공통
    def _touch(self) -> None:
        self.version += 1

    def _notice(self, text: str, tone: str = "info") -> None:
        self._notice_id += 1
        self.notices.append({"id": self._notice_id, "text": text, "tone": tone})
        del self.notices[:-NOTICE_KEEP]

    def _find(self, item_id: str) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def _guard_idle(self, message: str = "변환 중에는 대기열을 수정할 수 없습니다.") -> None:
        if self.batch.running:
            raise ServiceError(message, 409)

    def hardware(self) -> dict:
        """GPU·RAM과 권장 동시 작업 수. 처음 한 번만 알아본다."""
        with self._hw_lock:
            if self._hw is None:
                self._hw = self.detect()
            return dict(self._hw)

    def snapshot(self) -> dict:
        with self.lock:
            b = asdict(self.batch)
            running = sum(i.percent for i in self.items if i.status == "converting")
            b["overall"] = (b["finished"] + running) / b["total"] if b["total"] else 0.0
            s = self.settings.get()
            items = [asdict(i) for i in self.items]
            for d in items:
                d["plan"] = plan_for(d, s)
            return {
                "version": self.version,
                "items": items,
                "batch": b,
                "settings": s.model_dump(),
                "notices": list(self.notices),
            }

    # ------------------------------------------------------------------ 설정
    def update_settings(self, patch: dict) -> Settings:
        with self.lock:
            current = self.settings.get()
            if self.batch.running and any(k in patch and patch[k] != getattr(current, k) for k in BATCH_KEYS):
                # 바꿔도 이번 변환에는 적용되지 않아, 화면과 실제 결과가 어긋나 보인다
                raise ServiceError("변환 중에는 변환 설정과 저장 위치를 바꿀 수 없습니다.", 409)
            merged = current.model_dump() | patch
            if patch.get("save_dir"):
                path = os.path.abspath(os.path.expandvars(os.path.expanduser(patch["save_dir"].strip())))
                if not os.path.isdir(path):
                    raise ServiceError(f"폴더를 찾을 수 없습니다: {patch['save_dir']}")
                merged["save_dir"] = path
            if "suffix" in patch and any(c in BAD_NAME_CHARS for c in patch["suffix"] or ""):
                raise ServiceError(f"접미사에는 다음 문자를 쓸 수 없습니다: {' '.join(BAD_NAME_CHARS)}")
            try:
                value = Settings.model_validate(merged)
            except ValueError as e:
                raise ServiceError(f"설정 값이 올바르지 않습니다.\n\n{e}", 422) from e
            self.settings.save(value)
            self._touch()
            return value

    # ------------------------------------------------------------------ 대기열에 담기
    def add_paths(self, paths: list[str]) -> dict:
        """파일·폴더를 담고 영상 정보를 읽기 시작한다. 화면의 끌어다 놓기와 '파일 추가'가 같은 길을 쓴다."""
        found, skipped = scan_paths(p for p in paths if p and p.strip())
        if not found:
            raise ServiceError("추가할 영상이 없습니다.\n\n지원 형식: " + ", ".join(SUPPORTED_EXTENSIONS))
        with self.lock:
            known = {_key(i.path) for i in self.items}
            new: list[Item] = []
            for p in found:
                k = _key(p)
                if k in known:
                    continue
                known.add(k)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                new.append(Item(path=p, name=os.path.basename(p), size=size))
            self.items.extend(new)
            message = None
            if not new:
                message = "고른 영상이 모두 이미 대기열에 있습니다."
            elif self.batch.running:
                self.batch.added_during += len(new)
                message = (f"{len(new)}개를 대기열에 담았습니다.\n\n"
                           "지금은 변환 중이라 이번 변환에는 포함되지 않습니다.\n"
                           "변환이 끝난 뒤 다시 시작해 주세요.")
            if new:
                self._touch()
        if new:
            self.spawn(self._analyze_worker, [i.id for i in new])
        return {"added": len(new), "duplicates": len(found) - len(new), "skipped": skipped, "message": message}

    def _analyze_worker(self, ids: list[str]) -> None:
        with ThreadPoolExecutor(max_workers=ANALYZE_WORKERS) as pool:
            list(pool.map(self._analyze_one, ids))

    def _analyze_one(self, item_id: str) -> None:
        with self.lock:
            item = self._find(item_id)
            if item is None or item.status != "analyzing":
                return  # 그사이 대기열에서 지웠다
            path = item.path
        try:
            info = self.probe(path)
        except Exception:  # noqa: BLE001 - 어떤 실패든 항목에 사유를 남긴다
            info = None
        with self.lock:
            item = self._find(item_id)
            if item is None or item.status != "analyzing":
                return
            if info:
                item.width, item.height = info.get("width", 0), info.get("height", 0)
                item.duration = info.get("duration_sec", 0.0)
                item.bit_rate = info.get("bit_rate", 0)
                item.status = "waiting"
            else:
                item.status = "failed"
                item.message = ("ffprobe를 찾을 수 없어 영상 정보를 읽지 못했습니다." if not tools.tool_path("ffprobe")
                                else "영상 정보를 읽지 못했습니다. 손상되었거나 영상이 아닌 파일입니다.")
            self._touch()

    # ------------------------------------------------------------------ 대기열 정리
    def remove(self, item_id: str) -> None:
        with self.lock:
            self._guard_idle()
            item = self._find(item_id)
            if item is None:
                raise ServiceError("대기열에 없는 항목입니다.", 404)
            self.items.remove(item)
            self._touch()

    def clear(self) -> None:
        with self.lock:
            self._guard_idle("변환 중에는 대기열을 비울 수 없습니다.")
            self.items.clear()
            # 비운 대기열에 지난 결과가 남아 있으면 무엇의 결과인지 알 수 없다
            self.batch = Batch()
            self._touch()

    def clear_finished(self) -> int:
        with self.lock:
            self._guard_idle()
            before = len(self.items)
            self.items = [i for i in self.items if i.status not in FINISHED]
            removed = before - len(self.items)
            if not removed:
                raise ServiceError("대기열에 완료된 항목이 없습니다.")
            self._touch()
            return removed

    # ------------------------------------------------------------------ 일괄 변환
    def start(self, ids: list[str] | None) -> dict:
        """ids 가 None 이면 변환할 수 있는 항목(대기·중단·실패) 전부를 변환한다."""
        recommended = self.hardware()["recommended_jobs"]  # nvidia-smi 를 lock 밖에서 부른다
        with self.lock:
            if self.batch.running:
                raise ServiceError("이미 변환 중입니다.", 409)
            wanted = None if ids is None else set(ids)
            picked = [i for i in self.items if i.status in STARTABLE and (wanted is None or i.id in wanted)]
            if not picked:
                if any(i.status == "analyzing" for i in self.items):
                    raise ServiceError("아직 영상 정보를 읽는 중입니다. 잠시 뒤 다시 시작해 주세요.")
                raise ServiceError("변환할 영상이 없습니다. 영상을 대기열에 넣어 주세요.")
            if not tools.tool_path("ffmpeg"):
                raise ServiceError("FFmpeg를 찾을 수 없습니다.\n\n"
                                   "앱을 다시 설치하거나, 개발 실행이면 FFmpeg를 PATH에 넣어 주세요.")
            s = self.settings.get()
            out_dir = ""
            if s.save_mode == "folder":
                if not s.save_dir:
                    raise ServiceError("저장 폴더를 지정해 주세요.")
                if not os.path.isdir(s.save_dir):
                    # 그대로 진행하면 파이프라인이 폴더를 새로 만들어 엉뚱한 곳에 쌓인다
                    raise ServiceError(f"저장 폴더를 찾을 수 없어 변환을 시작하지 않았습니다.\n\n지정된 경로: {s.save_dir}")
                out_dir = s.save_dir
            job = {
                "out_dir": out_dir, "name_mode": s.name_mode, "suffix": s.suffix,
                "encode": encode_settings(s),
                "jobs": max(1, min(s.jobs or recommended, MAX_SLOTS, len(picked))),
            }
            self._cancel = threading.Event()
            self.batch = Batch(running=True, total=len(picked), jobs=job["jobs"], started_at=time.time())
            for i in picked:
                i.status, i.message, i.percent, i.time, i.speed = "waiting", None, 0.0, "", ""
                i.source_deleted, i.output = False, None
            order = [i.id for i in picked]
            self._touch()
        self.spawn(self._batch_worker, order, job, self._cancel)
        return {"count": len(order), "jobs": job["jobs"]}

    def stop(self) -> bool:
        with self.lock:
            if not self.batch.running:
                return False
            self.batch.stop_requested = True
            self._cancel.set()
            self._touch()
        # 취소 표시만으로도 0.5초 안에 멈추지만, 바로 끊어야 '중단' 을 누른 느낌이 난다
        self.kill()
        return True

    def _batch_worker(self, order: list[str], job: dict, cancel: threading.Event) -> None:
        b = self.batch
        tally = {"done": 0, "copied": 0, "deleted": 0, "failed": 0, "stopped": 0}
        # try/finally 가 없으면 예외 한 번에 running 이 True 로 굳어 다시 시작할 수 없다
        try:
            with ThreadPoolExecutor(max_workers=job["jobs"]) as pool:
                for f in [pool.submit(self._convert_one, item_id, job, cancel, tally) for item_id in order]:
                    f.result()
        finally:
            with self.lock:
                for it in self.items:
                    if it.status == "converting":  # 예외로 빠져나온 항목이 '변환 중' 으로 남지 않게 한다
                        it.status = "stopped"
                message, all_ok = describe_result(tally, b.total)
                b.result = {"message": message, "all_ok": all_ok, **tally, "total": b.total}
                if b.added_during:
                    self._notice(f"변환 중에 추가한 {b.added_during}개는 이번 변환에 포함되지 않았습니다.\n\n"
                                 "대기열에 그대로 있으니 '변환 시작' 을 다시 눌러 주세요.")
                    b.added_during = 0
                b.running, b.stop_requested = False, False
                self._touch()

    def _convert_one(self, item_id: str, job: dict, cancel: threading.Event, tally: dict) -> None:
        with self.lock:
            item = self._find(item_id)
            if item is None or cancel.is_set():
                # 시작하지 않은 항목은 '대기' 그대로 둔다. 다음에 '변환 시작' 으로 이어서 변환한다
                tally["stopped"] += 1
                return
            item.status = "converting"
            path = item.path
            self._touch()

        def progress(pct: float, time_str: str, speed: str) -> None:
            with self.lock:
                item.percent, item.time, item.speed = pct / 100.0, time_str, speed
                self._touch()

        try:
            code, message = self.convert(path, job["out_dir"], job["name_mode"],
                                         job["suffix"] if job["name_mode"] == "suffix" else "",
                                         dict(job["encode"]), progress, cancel)
        except Exception as e:  # noqa: BLE001 - 한 항목의 예외가 나머지 변환을 멈추지 않게 한다
            code, message = "FAIL", f"변환 중 예외가 발생했습니다: {e}"
        status, deleted = RESULTS.get(code, ("failed", False))
        with self.lock:
            item.status, item.message, item.source_deleted = status, message or None, deleted
            if status in FINISHED:
                item.percent = 1.0
                item.output = output_path(path, job["out_dir"], job["name_mode"], job["suffix"])
            tally[status if status in tally else "failed"] += 1
            tally["deleted"] += deleted
            self.batch.finished += 1
            self._touch()

    # ------------------------------------------------------------------ 열기
    def open_target(self, item_id: str | None, folder: bool) -> str:
        """화면이 '파일 열기'·'폴더 열기' 로 여는 경로. 대기열에 있는 파일과 그 폴더만 연다."""
        if item_id is None:
            s = self.settings.get()
            if folder and s.save_mode == "folder" and os.path.isdir(s.save_dir):
                return s.save_dir
            raise ServiceError("열 폴더가 없습니다.", 404)
        with self.lock:
            item = self._find(item_id)
            if item is None:
                raise ServiceError("대기열에 없는 항목입니다.", 404)
            target = next((p for p in (item.output, item.path) if p and os.path.exists(p)), None)
        if target is None:
            raise ServiceError("파일을 찾을 수 없습니다. 옮기거나 지웠을 수 있습니다.", 404)
        return os.path.dirname(target) if folder else target

    # ------------------------------------------------------------------ 종료
    def shutdown(self) -> None:
        self._cancel.set()
        self.kill()
