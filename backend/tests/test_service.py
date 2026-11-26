"""Service: 대기열·분석·일괄 변환·중단·설정. FFmpeg 대신 FakeConvert 를 쓴다."""

import os
import threading

import pytest
from conftest import Settings, run_now, video

from videoconverter.core.service import Service, ServiceError


def statuses(svc):
    return {i["name"]: i["status"] for i in svc.snapshot()["items"]}


class TestAdd:
    def test_폴더는_하위까지_영상만_담고_정보를_읽는다(self, svc, tmp_path):
        video(tmp_path / "in", "a.mkv")
        video(tmp_path / "in" / "sub", "b.MP4")
        video(tmp_path / "in", "notes.txt")
        r = svc.add_paths([str(tmp_path / "in")])
        assert (r["added"], r["skipped"], r["message"]) == (2, 1, None)
        items = svc.snapshot()["items"]
        assert [i["name"] for i in items] == ["a.mkv", "b.MP4"]
        assert all(i["status"] == "waiting" and i["width"] == 1920 and i["size"] == 100 for i in items)

    def test_같은_파일은_한_번만_담는다(self, svc, tmp_path):
        p = video(tmp_path, "a.mkv")
        svc.add_paths([p])
        r = svc.add_paths([p.upper(), p.replace("\\", "/")] if os.name == "nt" else [p])
        assert r["added"] == 0 and "이미 대기열" in r["message"]
        assert len(svc.items) == 1

    def test_영상이_없으면_알린다(self, svc, tmp_path):
        with pytest.raises(ServiceError, match="추가할 영상이 없습니다"):
            svc.add_paths([video(tmp_path, "a.txt"), str(tmp_path / "없는파일.mkv")])

    def test_정보를_못_읽으면_실패로_둔다(self, svc, tmp_path, probes):
        probes["broken.mkv"] = None
        svc.add_paths([video(tmp_path, "broken.mkv")])
        item = svc.snapshot()["items"][0]
        assert item["status"] == "failed" and "영상 정보를 읽지 못했습니다" in item["message"]

    def test_지운_항목의_분석_결과는_버린다(self, make_svc, tmp_path):
        later = []
        svc = make_svc(spawn=lambda fn, *a: later.append((fn, a)))
        svc.add_paths([video(tmp_path, "a.mkv")])
        svc.clear()
        fn, a = later.pop()
        fn(*a)
        assert svc.items == []


class TestBatch:
    def test_결과별_상태와_집계(self, svc, convert, tmp_path):
        names = ["ok.mkv", "copy.mkv", "copydel.mkv", "bad.mkv"]
        svc.add_paths([video(tmp_path, n) for n in names])
        convert.results.update({
            "copy.mkv": ("COPY", "Remux 완료"),
            "copydel.mkv": ("COPY_DEL", "Remux 완료 및 원본 삭제됨"),
            "bad.mkv": ("FAIL", "인코딩 오류 (반환코드: 1)"),
        })
        assert svc.start(None)["count"] == 4
        snap = svc.snapshot()
        items = {i["name"]: i for i in snap["items"]}
        assert {n: i["status"] for n, i in items.items()} == {
            "ok.mkv": "done", "copy.mkv": "copied", "copydel.mkv": "copied", "bad.mkv": "failed"}
        assert items["copydel.mkv"]["source_deleted"] and not items["copy.mkv"]["source_deleted"]
        assert items["bad.mkv"]["message"] == "인코딩 오류 (반환코드: 1)"
        assert items["ok.mkv"]["output"] == os.path.abspath(tmp_path / "ok_cuda.mp4")
        assert items["bad.mkv"]["output"] is None
        b = snap["batch"]
        assert not b["running"] and b["overall"] == 1.0
        assert b["result"]["message"] == "4개 중 3개 완료, 실패 1개"
        assert (b["result"]["done"], b["result"]["copied"], b["result"]["deleted"]) == (1, 2, 1)

    def test_설정이_변환에_전달된다(self, svc, store, convert, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        store.save(Settings(save_mode="folder", save_dir=str(out), video_rate="2.5", audio_rate="96k",
                            resolution="720p", delete_source=True, name_mode="overwrite"))
        svc.add_paths([video(tmp_path, "a.mkv")])
        svc.start(None)
        call = convert.calls[0]
        assert (call["out_dir"], call["name_mode"], call["value"]) == (str(out), "overwrite", "")
        s = call["settings"]
        assert (s["video_maxrate_mbps"], s["audio_bitrate"], s["max_width"], s["max_height"], s["delete_source"]) == (
            2.5, "96k", 1280, 720, True)
        assert svc.snapshot()["items"][0]["output"] == os.path.abspath(out / "a.mp4")

    def test_동시_작업_수는_권장값이고_항목_수를_넘지_않는다(self, make_svc, store, tmp_path):
        svc = make_svc(recommended=3)
        svc.add_paths([video(tmp_path, f"{n}.mkv") for n in "ab"])
        assert svc.start(None)["jobs"] == 2
        store.save(Settings(jobs=1))
        svc.add_paths([video(tmp_path, f"{n}.mkv") for n in "cd"])
        assert svc.start(None)["jobs"] == 1

    def test_실패와_중단은_다시_변환하고_완료는_건너뛴다(self, svc, convert, tmp_path):
        svc.add_paths([video(tmp_path, n) for n in ("ok.mkv", "bad.mkv")])
        convert.results["bad.mkv"] = ("FAIL", "x")
        svc.start(None)
        del convert.results["bad.mkv"]
        convert.calls.clear()
        svc.start(None)
        assert [os.path.basename(c["path"]) for c in convert.calls] == ["bad.mkv"]
        assert statuses(svc) == {"ok.mkv": "done", "bad.mkv": "done"}

    def test_골라서_변환한다(self, svc, convert, tmp_path):
        svc.add_paths([video(tmp_path, n) for n in ("a.mkv", "b.mkv")])
        svc.start([svc.items[1].id])
        assert statuses(svc) == {"a.mkv": "waiting", "b.mkv": "done"}

    def test_한_항목의_예외가_나머지를_막지_않는다(self, svc, convert, tmp_path):
        svc.add_paths([video(tmp_path, n) for n in ("boom.mkv", "ok.mkv")])
        convert.results["boom.mkv"] = RuntimeError("터짐")
        svc.start(None)
        items = {i["name"]: i for i in svc.snapshot()["items"]}
        assert items["boom.mkv"]["status"] == "failed" and "터짐" in items["boom.mkv"]["message"]
        assert items["ok.mkv"]["status"] == "done"
        assert not svc.batch.running

    @pytest.mark.parametrize("setup, message", [
        ("empty", "변환할 영상이 없습니다"),
        ("analyzing", "영상 정보를 읽는 중"),
        ("no_dir", "저장 폴더를 지정해 주세요"),
        ("gone_dir", "저장 폴더를 찾을 수 없어"),
        ("no_ffmpeg", "FFmpeg를 찾을 수 없습니다"),
    ])
    def test_시작할_수_없으면_이유를_알린다(self, make_svc, store, tmp_path, monkeypatch, setup, message):
        svc = make_svc(spawn=(lambda fn, *a: None) if setup == "analyzing" else run_now)
        if setup != "empty":
            svc.add_paths([video(tmp_path, "a.mkv")])
        if setup == "no_dir":
            store.save(Settings(save_mode="folder"))
        if setup == "gone_dir":
            store.save(Settings(save_mode="folder", save_dir=str(tmp_path / "gone")))
        if setup == "no_ffmpeg":
            monkeypatch.setenv("VIDEOCONVERTER_TOOLS_DIR", str(tmp_path / "nothing"))
            monkeypatch.setenv("PATH", "")
        with pytest.raises(ServiceError, match=message):
            svc.start(None)
        assert not svc.batch.running


class TestStop:
    def test_중단하면_변환_중인_것은_중단_나머지는_대기로_남는다(self, make_svc, convert, killed, tmp_path):
        threads = []

        def spawn(fn, *a):
            t = threading.Thread(target=fn, args=a)
            threads.append(t)
            t.start()

        started = threading.Event()

        def slow(progress, cancel):
            started.set()
            assert cancel.wait(5), "중단 신호가 오지 않았다"
            return "CANCELLED", "사용자 취소됨"

        svc = make_svc(spawn=spawn)
        svc.add_paths([video(tmp_path, n) for n in ("a.mkv", "b.mkv", "c.mkv")])
        svc.settings.save(Settings(jobs=1))
        convert.results["a.mkv"] = slow
        svc.start(None)
        assert started.wait(5)
        assert svc.stop() is True
        for t in threads:
            t.join(5)
        assert killed, "실행 중인 ffmpeg 를 바로 끊는다"
        assert statuses(svc) == {"a.mkv": "stopped", "b.mkv": "waiting", "c.mkv": "waiting"}
        result = svc.snapshot()["batch"]["result"]
        assert result["stopped"] == 3 and result["message"] == "3개 중 0개 완료, 중단 3개"
        assert not svc.batch.running and not svc.stop()

    def test_변환_중에는_대기열과_변환_설정을_바꾸지_못한다(self, make_svc, tmp_path):
        later = []
        svc = make_svc(spawn=lambda fn, *a: later.append((fn, a)))
        svc.add_paths([video(tmp_path, "a.mkv")])
        fn, a = later.pop()
        fn(*a)  # 분석
        svc.start(None)  # 변환 작업은 later 에 남겨 둔다
        for call in (lambda: svc.remove(svc.items[0].id), svc.clear, svc.clear_finished,
                     lambda: svc.update_settings({"video_rate": "5.0"}), lambda: svc.start(None)):
            with pytest.raises(ServiceError) as e:
                call()
            assert e.value.status == 409
        svc.update_settings({"sidebar": "closed"})  # 화면 설정은 바꿀 수 있다
        r = svc.add_paths([video(tmp_path, "b.mkv")])
        assert "이번 변환에는 포함되지 않습니다" in r["message"]
        fn, a = later.pop(0)
        fn(*a)
        assert any("포함되지 않았습니다" in n["text"] for n in svc.snapshot()["notices"])


class TestSettings:
    def test_저장되고_다시_읽힌다(self, svc, store, tmp_path):
        svc.update_settings({"jobs": 3, "resolution": "none", "suffix": "_small"})
        again = type(store)(store.path).get()
        assert (again.jobs, again.resolution, again.suffix) == (3, "none", "_small")
        svc.update_settings({"jobs": None})
        assert store.get().jobs is None

    def test_없는_폴더와_파일_이름에_못_쓰는_문자는_거절한다(self, svc, tmp_path):
        with pytest.raises(ServiceError, match="폴더를 찾을 수 없습니다"):
            svc.update_settings({"save_dir": str(tmp_path / "gone")})
        with pytest.raises(ServiceError, match="접미사"):
            svc.update_settings({"suffix": "a/b"})
        svc.update_settings({"save_dir": str(tmp_path)})
        assert svc.settings.get().save_dir == str(tmp_path)

    def test_망가진_설정_파일은_기본값으로_읽는다(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text("{ broken", encoding="utf-8")
        from videoconverter.config import SettingsStore

        assert SettingsStore(p).get() == Settings()


class TestQueue:
    def test_완료_항목만_비운다(self, svc, convert, tmp_path):
        svc.add_paths([video(tmp_path, n) for n in ("ok.mkv", "bad.mkv")])
        convert.results["bad.mkv"] = ("FAIL", "x")
        svc.start(None)
        assert svc.clear_finished() == 1
        assert statuses(svc) == {"bad.mkv": "failed"}
        with pytest.raises(ServiceError):
            svc.clear_finished()

    def test_열기는_대기열의_파일만(self, svc, tmp_path):
        svc.add_paths([video(tmp_path, "a.mkv")])
        item = svc.items[0]
        assert svc.open_target(item.id, folder=False) == item.path
        assert svc.open_target(item.id, folder=True) == str(tmp_path)
        with pytest.raises(ServiceError):
            svc.open_target("nope", folder=False)
        os.remove(item.path)
        with pytest.raises(ServiceError, match="찾을 수 없습니다"):
            svc.open_target(item.id, folder=False)

    def test_예정_동작은_지금_설정을_따른다(self, svc, probes, tmp_path):
        probes["low.mkv"] = {"width": 1280, "height": 720, "duration_sec": 60.0, "bit_rate": 1_000_000}
        probes["mid.mkv"] = {"width": 1920, "height": 1080, "duration_sec": 60.0, "bit_rate": 8_000_000}
        probes["big.mkv"] = {"width": 2560, "height": 1440, "duration_sec": 60.0, "bit_rate": 1_000_000}
        probes["bad.mkv"] = None
        svc.add_paths([video(tmp_path, n) for n in ("low.mkv", "mid.mkv", "big.mkv", "bad.mkv")])
        plans = lambda: {i["name"]: i["plan"] for i in svc.snapshot()["items"]}  # noqa: E731
        assert plans() == {"low.mkv": "copy", "mid.mkv": "encode", "big.mkv": "scale", "bad.mkv": None}
        svc.update_settings({"resolution": "720p"})
        assert plans()["mid.mkv"] == "scale"
        svc.update_settings({"resolution": "none"})
        assert plans()["big.mkv"] == "copy", "줄일 필요가 없으면 비트레이트로 정한다"

    def test_변환_중_전체_진행률(self, svc, tmp_path):
        svc.add_paths([video(tmp_path, n) for n in ("a.mkv", "b.mkv")])
        svc.batch.total, svc.batch.finished = 2, 1
        svc.items[1].status, svc.items[1].percent = "converting", 0.5
        assert svc.snapshot()["batch"]["overall"] == 0.75


def test_hardware_는_한_번만_알아본다(store, convert):
    calls = []
    svc = Service(settings=store, convert=convert, detect=lambda: calls.append(1) or {"recommended_jobs": 1})
    svc.hardware()
    svc.hardware()
    assert calls == [1]
