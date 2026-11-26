"""HTTP API: 보안 장치와 주요 경로."""

import pytest
from conftest import video
from fastapi.testclient import TestClient

from videoconverter.api.server import create_app

TOKEN = "t0ken"


@pytest.fixture
def client(svc):
    with TestClient(create_app(svc, token=TOKEN), headers={"x-videoconverter-token": TOKEN}) as c:
        yield c


class TestGuard:
    def test_토큰이_없으면_거절한다(self, svc):
        with TestClient(create_app(svc, token=TOKEN)) as c:
            assert c.get("/state").status_code == 401
            assert c.get("/health").status_code == 200, "연결 확인은 토큰 없이 된다"

    def test_다른_호스트는_거절한다(self, client):
        assert client.get("/state", headers={"host": "evil.example"}).status_code == 403

    def test_웹소켓도_토큰을_요구한다(self, svc):
        from starlette.websockets import WebSocketDisconnect

        with TestClient(create_app(svc, token=TOKEN)) as c:
            with pytest.raises(WebSocketDisconnect):
                with c.websocket_connect("/events") as ws:
                    ws.receive_json()

    def test_대기열에_없는_파일은_열지_않는다(self, client, tmp_path):
        assert client.post("/open/file", json={"id": "C:/Windows/notepad.exe"}).status_code == 404
        assert client.post("/open/folder", json={}).status_code == 404


class TestFlow:
    def test_담기_변환_결과(self, client, tmp_path):
        r = client.post("/queue/paths", json={"paths": [video(tmp_path, "a.mkv"), video(tmp_path, "b.txt")]})
        assert r.json() == {"added": 1, "duplicates": 0, "skipped": 1, "message": None}
        assert client.post("/batch/start", json={}).json() == {"count": 1, "jobs": 1}
        state = client.get("/state").json()
        assert state["items"][0]["status"] == "done"
        assert state["batch"]["result"]["message"] == "1개 중 1개 완료"
        assert client.post("/queue/clear-finished").json() == {"removed": 1}

    def test_오류는_문구와_상태_코드로(self, client):
        r = client.post("/batch/start", json={})
        assert r.status_code == 400 and "변환할 영상이 없습니다" in r.json()["detail"]
        assert client.delete("/queue/nope").status_code == 404

    def test_설정은_보낸_값만_바꾸고_jobs_null_은_권장값(self, client):
        assert client.put("/settings", json={"jobs": 4, "suffix": "_x"}).json()["jobs"] == 4
        s = client.put("/settings", json={"resolution": "720p"}).json()
        assert (s["jobs"], s["suffix"], s["resolution"]) == (4, "_x", "720p")
        assert client.put("/settings", json={"jobs": None}).json()["jobs"] is None
        assert client.put("/settings", json={"resolution": "4k"}).status_code == 422
        assert client.put("/settings", json={"jobs": 9}).status_code == 422

    def test_system(self, client):
        s = client.get("/system").json()
        assert s["recommended_jobs"] == 2 and s["gpu"] == "RTX" and ".mkv" in s["extensions"]
        assert s["ffmpeg"].endswith(("ffmpeg", "ffmpeg.exe"))

    def test_웹소켓이_상태를_보낸다(self, client, tmp_path):
        with client.websocket_connect(f"/events?token={TOKEN}") as ws:
            first = ws.receive_json()
            assert first["type"] == "state" and first["items"] == []
            client.post("/queue/paths", json={"paths": [video(tmp_path, "a.mkv")]})
            nxt = ws.receive_json()
            assert nxt["version"] > first["version"] and len(nxt["items"]) == 1
