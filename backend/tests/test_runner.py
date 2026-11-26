"""run_ffmpeg_and_track 를 실제 하위 프로세스로 돌린다. ffmpeg 대신 진행 줄을 흉내 내는 파이썬 스크립트를 쓴다."""

import sys
import threading
import time

from videoconverter.core import runner

# 0.25초마다 ffmpeg 와 같은 모양의 진행 줄을 stderr 에 쓴다(\r 로 줄을 바꾸는 것도 같다)
PROGRESS = r"""
import sys, time
for n in range(int(sys.argv[1])):
    sys.stderr.write(f"frame={n} fps=30 time=00:00:{n:02d}.00 bitrate=1000k speed=2.5x\r")
    sys.stderr.flush()
    time.sleep(0.25)
sys.exit(int(sys.argv[2]))
"""
SILENT = "import time; time.sleep(30)"


def run(code, *args, cancel=None, stuck=None):
    seen = []
    start = time.monotonic()
    rc, err = runner.run_ffmpeg_and_track([sys.executable, "-c", code, *map(str, args)], 10.0,
                                          lambda pct, t, speed: seen.append((pct, t, speed)), cancel,
                                          stuck_timeout_sec=stuck)
    return rc, err, seen, time.monotonic() - start


def test_0_5초보다_긴_변환도_끝까지_기다린다():
    """9b32d1e 회귀: proc.wait(timeout=0.5) 의 TimeoutExpired 가 루프를 빠져나가 0.5초 만에 반환했다."""
    rc, err, seen, took = run(PROGRESS, 6, 0)
    assert rc == 0
    assert took > 1.2, "프로세스가 끝나기 전에 돌아왔다"
    assert len(seen) == 6 and seen[-1] == (50.0, "00:00:05.00", "2.5x")
    assert "frame=5" in err


def test_실패_반환코드를_그대로_돌려준다():
    rc, _err, _seen, _took = run(PROGRESS, 1, 3)
    assert rc == 3


def test_중단하면_곧바로_끊는다():
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    rc, err, _seen, took = run(SILENT, cancel=cancel)
    assert (rc, err) == (-1, "USER_CANCELLED")
    assert took < 5
    assert not runner._active_procs, "끝난 프로세스는 목록에서 빠진다"


def test_진행이_멈추면_강제로_끝낸다():
    rc, err, _seen, took = run(SILENT, stuck=1)
    assert err.startswith("STUCK_TIMEOUT")
    assert took < 5
