"""만들다 만 임시 결과 파일 기록과 다음 시작 때의 정리."""

import os

from fastapi.testclient import TestClient

from videoconverter.api.server import create_app
from videoconverter.core import leftovers

DEAD_PID = 4_000_000  # 이런 pid 의 프로세스는 없다


def part(tmp_path, pid=DEAD_PID, name="movie"):
    p = tmp_path / f"{name}.mp4.part-{pid}-0123abcd.mp4"
    p.write_bytes(b"half")
    return str(p)


def test_기록했다가_지우면_남는_것이_없다(tmp_path):
    p = part(tmp_path)
    leftovers.remember(p)
    assert leftovers._read() == [p]
    leftovers.forget(p)
    assert leftovers._read() == []
    assert not leftovers._file().exists()


def test_끝난_실행이_남긴_임시_파일을_지운다(tmp_path):
    p = part(tmp_path)
    leftovers.remember(p)
    assert leftovers.clean() == 1
    assert not os.path.exists(p)
    assert leftovers._read() == []


def test_살아_있는_실행의_임시_파일은_남긴다(tmp_path):
    p = part(tmp_path, pid=os.getpid())
    leftovers.remember(p)
    assert leftovers.clean() == 0
    assert os.path.exists(p) and leftovers._read() == [p]


def test_임시_파일_이름이_아니면_지우지_않는다(tmp_path):
    keep = tmp_path / "movie.mp4"
    keep.write_bytes(b"real")
    leftovers.remember(str(keep))
    assert leftovers.clean() == 0
    assert keep.exists() and leftovers._read() == []


def test_이미_없는_파일은_기록만_지운다(tmp_path):
    p = part(tmp_path)
    leftovers.remember(p)
    os.remove(p)
    assert leftovers.clean() == 0
    assert leftovers._read() == []


def test_기록_파일이_깨져_있어도_시작한다():
    leftovers._file().parent.mkdir(parents=True, exist_ok=True)
    leftovers._file().write_text("{not json", encoding="utf-8")
    assert leftovers.clean() == 0


def test_앱이_시작할_때_정리한다(tmp_path):
    p = part(tmp_path)
    leftovers.remember(p)
    with TestClient(create_app(token="t")):
        pass
    assert not os.path.exists(p)
