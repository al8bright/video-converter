"""웹 화면(Tauri 웹뷰)이 쓰는 로컬 HTTP/WebSocket API.

보안(127.0.0.1 전용, Host 검사, 실행마다 바뀌는 토큰)은 공통 파일 `api/base.py` 가 맡는다.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from videoconverter import __version__
from videoconverter.api import base
from videoconverter.config import (
    MAX_SLOTS,
    SUPPORTED_EXTENSIONS,
    AudioRate,
    NameMode,
    Resolution,
    SaveMode,
    Sidebar,
    VideoRate,
)
from videoconverter.core import leftovers, tools
from videoconverter.core.proc import open_with_shell
from videoconverter.core.service import Service, ServiceError

PUSH_INTERVAL = 0.1  # 초. 진행률은 이보다 자주 바뀌어도 화면에는 이 간격으로 보낸다


class PathsBody(BaseModel):
    paths: list[str]


class StartBody(BaseModel):
    ids: list[str] | None = None  # None 이면 변환할 수 있는 항목 전부


class OpenBody(BaseModel):
    id: str | None = None  # None 이면 지정 저장 폴더(폴더 열기만)


class SettingsPatch(BaseModel):
    jobs: int | None = Field(default=None, ge=1, le=MAX_SLOTS)  # null 이면 권장값으로 되돌린다
    video_rate: VideoRate | None = None
    audio_rate: AudioRate | None = None
    resolution: Resolution | None = None
    delete_source: bool | None = None
    save_mode: SaveMode | None = None
    save_dir: str | None = None
    name_mode: NameMode | None = None
    suffix: str | None = None
    sidebar: Sidebar | None = None


def create_app(service: Service | None = None, token: str | None = None) -> FastAPI:
    token = base.env_token(token)
    svc = service or Service()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        leftovers.clean()  # 지난번에 강제로 끝나 남은 임시 결과 파일
        yield
        svc.shutdown()

    app = FastAPI(title="videoconverter", version=__version__, lifespan=lifespan)
    app.state.service = svc
    base.secure(app, token)

    @app.exception_handler(ServiceError)
    async def service_error(_request: Request, exc: ServiceError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    # -------------------------------------------------------------- 상태
    @app.get("/system")
    def system():
        return {"version": __version__, "ffmpeg": tools.tool_path("ffmpeg"), "ffprobe": tools.tool_path("ffprobe"),
                "extensions": list(SUPPORTED_EXTENSIONS), "max_jobs": MAX_SLOTS, **svc.hardware()}

    @app.get("/state")
    def state():
        return svc.snapshot()

    @app.websocket("/events")
    async def events(ws: WebSocket):
        if not await base.ws_allowed(ws, token):
            return
        await ws.accept()
        sent = -1
        try:
            while True:
                # 버전만 보고 바뀐 것만 보낸다. 진행률이 초당 수십 번 바뀌어도 화면에는 10번까지만 간다
                if svc.version != sent:
                    snap = svc.snapshot()
                    await ws.send_json({"type": "state", **snap})
                    sent = snap["version"]
                await asyncio.sleep(PUSH_INTERVAL)
        except (WebSocketDisconnect, RuntimeError):
            pass

    # -------------------------------------------------------------- 대기열
    @app.post("/queue/paths")
    def add_paths(body: PathsBody):
        return svc.add_paths(body.paths)

    @app.delete("/queue/{item_id}")
    def remove_item(item_id: str):
        svc.remove(item_id)
        return {"ok": True}

    @app.post("/queue/clear")
    def clear_queue():
        svc.clear()
        return {"ok": True}

    @app.post("/queue/clear-finished")
    def clear_finished():
        return {"removed": svc.clear_finished()}

    @app.post("/batch/start")
    def start_batch(body: StartBody):
        return svc.start(body.ids)

    @app.post("/batch/stop")
    def stop_batch():
        return {"ok": svc.stop()}

    # -------------------------------------------------------------- 설정
    @app.put("/settings")
    def put_settings(body: SettingsPatch):
        # 보낸 값만 바꾼다. jobs 는 null 을 보내 '권장값' 으로 되돌릴 수 있다
        patch = body.model_dump(exclude_unset=True)
        patch = {k: v for k, v in patch.items() if v is not None or k == "jobs"}
        return svc.update_settings(patch)

    # -------------------------------------------------------------- 열기
    def _open(target: str) -> dict:
        try:
            open_with_shell(target)
        except OSError as e:
            raise HTTPException(500, f"열지 못했습니다.\n\n{e.strerror or e}") from e
        return {"ok": True}

    @app.post("/open/file")
    def open_file(body: OpenBody):
        if body.id is None:
            raise HTTPException(400, "열 항목을 골라 주세요.")
        return _open(svc.open_target(body.id, folder=False))

    @app.post("/open/folder")
    def open_folder(body: OpenBody):
        return _open(svc.open_target(body.id, folder=True))

    return app
