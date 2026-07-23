import os
import re
import sys
import uuid
import shutil
import subprocess
import threading
import ctypes

# ffmpeg/ffprobe 텍스트 디코딩 셋팅
SUBPROC_TEXT = {"encoding": "utf-8", "errors": "replace"}

# 재인코딩 시 mp4 컨테이너로 옮길 수 있는 "텍스트 기반" 자막 코덱 (mov_text 변환 대상).
# 이미지 기반(hdmv_pgs_subtitle, dvd_subtitle, dvb_subtitle 등)은 mp4에서 드롭한다.
_TEXT_SUB_CODECS = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}

# faststart(+movflags)를 적용할 수 있는 출력 컨테이너 확장자.
_FASTSTART_EXTS = (".mp4", ".mov", ".m4v")

def get_system_ram_gb():
    """ctypes를 이용해 Windows 시스템 RAM 크기(GB) 조회"""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(stat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        return 0.0

def get_nvidia_gpu_info():
    """nvidia-smi를 실행해 NVIDIA 그래픽카드 이름 및 VRAM(MB) 조회"""
    creation_flags = 0
    if sys.platform == 'win32':
        creation_flags = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=creation_flags
        )
        output = res.stdout.strip()
        if output:
            parts = output.split(",")
            gpu_name = parts[0].strip()
            vram_mb = int(parts[1].strip())
            return gpu_name, vram_mb
    except Exception:
        pass
    return None, 0


def get_video_info(file_path):
    """
    ffprobe를 사용하여 비디오 정보(duration_sec, bit_rate, width, height)를 추출.
    실패 시 None 반환.
    """
    # Windows에서 subprocess 창 팝업 방지
    creation_flags = 0
    if sys.platform == 'win32':
        creation_flags = subprocess.CREATE_NO_WINDOW

    info = {
        'duration_sec': 0.0,
        'bit_rate': 0,
        'width': 0,
        'height': 0,
        'sub_codecs': []  # 자막 스트림 코덱명 목록 (0:s:i 순서)
    }
    try:
        # 1. 해상도(width, height) 조회
        cmd_res = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", file_path
        ]
        result = subprocess.run(cmd_res, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=creation_flags, timeout=15)
        line = result.stdout.strip()
        if line:
            w, h = line.split(",")
            info['width'] = int(w)
            info['height'] = int(h)

        # 2. 재생시간(duration) 조회
        cmd_dur = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", file_path
        ]
        result = subprocess.run(cmd_dur, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=creation_flags, timeout=15)
        line = result.stdout.strip()
        if line and line != "N/A":
            info['duration_sec'] = float(line)

        # 3. 비트레이트(bit_rate) 조회 (스트림 우선, 없을 시 포맷 메타데이터에서 조회)
        cmd_br = [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=bit_rate", "-of", "csv=p=0", file_path
        ]
        result = subprocess.run(cmd_br, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=creation_flags, timeout=15)
        line = result.stdout.strip()
        if line and line != "N/A":
            info['bit_rate'] = int(line)
        else:
            cmd_br_fmt = [
                "ffprobe", "-v", "error", "-show_entries", "format=bit_rate",
                "-of", "csv=p=0", file_path
            ]
            result = subprocess.run(cmd_br_fmt, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=creation_flags, timeout=15)
            line = result.stdout.strip()
            if line and line != "N/A":
                info['bit_rate'] = int(line)

        # 4. 자막 스트림 코덱 조회 (best-effort, 실패해도 무시)
        try:
            cmd_sub = [
                "ffprobe", "-v", "error", "-select_streams", "s",
                "-show_entries", "stream=codec_name", "-of", "csv=p=0", file_path
            ]
            res_sub = subprocess.run(cmd_sub, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False, creationflags=creation_flags, timeout=15)
            for ln in res_sub.stdout.splitlines():
                ln = ln.strip()
                if ln and ln != "N/A":
                    info['sub_codecs'].append(ln)
        except Exception:
            pass

        return info
    except Exception as e:
        print(f"ffprobe 에러 ({file_path}): {e}", file=sys.stderr)
    return None

def _time_str_to_seconds(t_str):
    try:
        parts = t_str.strip().split(":")
        if len(parts) != 3:
            return None
        h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None

def _stderr_suggests_nvenc_fail(stderr_text):
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return any(p in low for p in [
        "h264_nvenc", "hevc_nvenc", "no capable devices",
        "10 bit encode not supported", "could not open encoder",
        "error while opening encoder"
    ])

def _stderr_suggests_fatal_input_error(stderr_text):
    """재시도해도 소용없는 입력/출력/경로성 치명 오류를 감지한다.
    이런 경우 NVENC->CPU 폴백 체인을 반복해도 동일 실패이므로 조기 중단한다."""
    if not stderr_text:
        return False
    low = stderr_text.lower()
    return any(p in low for p in [
        "no such file or directory",
        "same as input",
        "permission denied",
        "invalid data found when processing input",
    ])

def _output_wants_faststart(output_path):
    """출력 컨테이너가 faststart(+movflags)를 지원하는 mp4/mov 계열인지."""
    return os.path.splitext(output_path)[1].lower() in _FASTSTART_EXTS

def _estimate_bps(bit_rate, duration_sec, size_bytes):
    """스트림/포맷 비트레이트가 N/A(0)일 때 파일크기*8/duration 으로 평균 비트레이트 추정."""
    if bit_rate and bit_rate > 0:
        return int(bit_rate)
    if duration_sec and duration_sec > 0 and size_bytes and size_bytes > 0:
        return int(size_bytes * 8 / duration_sec)
    return 0

def should_remux(bit_rate, duration_sec, size_bytes, threshold_mbps, need_scale):
    """Remux(무손실 복사) 여부 판정.
    - 다운스케일이 필요하면(need_scale) 절대 remux 하지 않는다(해상도 제한 위반 방지).
    - 비트레이트가 임계 이하일 때만 remux. N/A(0)면 크기/길이로 추정해 보조 판정.
    """
    if need_scale:
        return False
    bps = _estimate_bps(bit_rate, duration_sec, size_bytes)
    return 0 < bps <= threshold_mbps * 1_000_000

def _force_mp4_ext(path):
    """재인코딩 경로 출력 확장자를 .mp4로 강제."""
    root, _ = os.path.splitext(path)
    return root + ".mp4"

def _tmp_output_path(dest_path):
    """dest와 같은 폴더에, dest와 동일 확장자를 가진 유니크한 임시 출력 경로 생성."""
    ext = os.path.splitext(dest_path)[1] or ".mp4"
    return f"{dest_path}.part-{os.getpid()}-{uuid.uuid4().hex[:8]}{ext}"

def _tmp_is_valid(path, min_bytes=1024):
    """임시 산출물 무결성 최소 검증: 존재 + 크기 임계 초과."""
    try:
        return os.path.exists(path) and os.path.getsize(path) > min_bytes
    except OSError:
        return False

def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass

def _build_ffmpeg_cmd(input_path, output_path, remux_only, vf, faststart, mode, settings, text_sub_indices=None):
    """
    변환 모드와 사용자 설정에 따라 ffmpeg 인자 구성.
    mode: 'cuda' (GPU 디코딩+인코딩), 'cpu_decode' (CPU 디코딩+GPU 인코딩), 'cpu' (완전 CPU 처리)
    text_sub_indices: mp4/mov 출력 시 mov_text 로 보존할 텍스트 자막 스트림의 0:s:i 인덱스 목록.
    faststart(+movflags)는 출력이 mp4/mov 계열일 때만 부여한다(L-1).
    """
    add_faststart = bool(faststart) and _output_wants_faststart(output_path)

    # 단순 복사(Remux) 모드: 모든 스트림 그대로 복사, 원본 컨테이너 유지
    if remux_only:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy"]
        if add_faststart:
            cmd += ["-movflags", "+faststart"]
        cmd += [output_path]
        return cmd

    video_maxrate = f"{settings.get('video_maxrate_mbps', 3.5)}M"
    video_bufsize = f"{float(settings.get('video_maxrate_mbps', 3.5)) * 2}M"
    audio_bitrate = settings.get('audio_bitrate', '128k')
    nvenc_preset = settings.get('nvenc_preset', 'p5')

    cmd = ["ffmpeg", "-y"]
    # 1차 기본 가속 모드만 CUDA 하드웨어 디코딩 사용
    if mode == 'cuda':
        cmd += ["-hwaccel", "cuda"]
    cmd += ["-i", input_path]

    # 스트림 매핑: 비디오 1개 + 모든 오디오 트랙 보존(H-2). 데이터/첨부는 미매핑 → 드롭.
    cmd += ["-map", "0:v:0", "-map", "0:a?"]

    # 텍스트 자막 best-effort 보존 (mp4/mov 출력 한정). 이미지 자막은 애초에 목록에서 제외됨.
    sub_codec_args = []
    if text_sub_indices and _output_wants_faststart(output_path):
        for i in text_sub_indices:
            cmd += ["-map", f"0:s:{i}?"]
        sub_codec_args = ["-c:s", "mov_text"]

    # 비디오 코덱 선택
    if mode == 'cpu':
        # 3차 최종 폴백 (완전 CPU x264 인코딩)
        cmd += ["-c:v", "libx264", "-preset", "medium"]
    else:
        # cuda / cpu_decode: NVENC 인코딩
        cmd += ["-c:v", "h264_nvenc", "-preset", nvenc_preset, "-rc", "vbr"]

    cmd += [
        "-b:v", video_maxrate,
        "-maxrate", video_maxrate,
        "-bufsize", video_bufsize,
        "-vf", vf,
        "-c:a", "aac", "-b:a", audio_bitrate,
    ]
    cmd += sub_codec_args
    cmd += [output_path]

    if add_faststart:
        cmd.insert(-1, "-movflags")
        cmd.insert(-1, "+faststart")

    return cmd

def resolve_output_path(file_path, output_dir, name_option, value=""):
    """
    출력 위치 및 파일명 옵션을 결합해 최종 경로 생성.
    """
    src_dir = os.path.dirname(os.path.abspath(file_path))
    if not output_dir:
        dest_dir = src_dir
    else:
        dest_dir = os.path.abspath(output_dir)

    filename = os.path.basename(file_path)
    name, ext = os.path.splitext(filename)

    if name_option == 'suffix':
        new_filename = f"{name}{value}{ext}"
    elif name_option == 'prefix':
        new_filename = f"{value}{name}{ext}"
    else: # 'overwrite'
        new_filename = filename

    return os.path.join(dest_dir, new_filename)

def run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event, output_path=None):
    """
    ffmpeg 명령어를 실행하고 stderr에서 진행 정보를 실시간 파싱해 콜백 전송.
    취소 시 프로세스를 kill 하고 부분 생성된 출력 파일(output_path)을 정리한다(H-4).
    """
    creation_flags = 0
    if sys.platform == 'win32':
        creation_flags = subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        creationflags=creation_flags,
        **SUBPROC_TEXT
    )

    stderr_lines = []

    def read_stderr():
        buf = ""
        while True:
            c = proc.stderr.read(1)
            if not c:
                break
            buf += c
            if c in ("\r", "\n"):
                line = buf.strip()
                buf = ""
                if line:
                    stderr_lines.append(line)
                    # ffmpeg 출력 파싱
                    if "time=" in line:
                        mt = re.search(r"time=(\S+)", line)
                        ms = re.search(r"speed=\s*(\S+)", line)
                        cur_t = mt.group(1) if mt else "?"
                        speed = ms.group(1) if ms else "?"
                        pct = 0.0
                        if cur_t != "?" and total_sec and total_sec > 0:
                            cur_sec = _time_str_to_seconds(cur_t)
                            if cur_sec is not None:
                                pct = min(100.0, (cur_sec / total_sec) * 100)
                        
                        # UI로 실시간 상태 피드백 전송
                        if progress_callback:
                            progress_callback(pct, cur_t, speed)

        if buf.strip():
            stderr_lines.append(buf.strip())

    # stderr 비동기 리더 구동
    t_reader = threading.Thread(target=read_stderr, daemon=True)
    t_reader.start()

    # 프로세스 완료 또는 취소 이벤트 폴링 대기
    try:
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                proc.kill()
                try:
                    proc.wait(timeout=2.0)
                except Exception:
                    pass
                _safe_remove(output_path)
                return -1, "USER_CANCELLED"
            proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        proc.kill()
        _safe_remove(output_path)
        return -1, f"Error: {e}"

    t_reader.join(timeout=2.0)
    stderr_full = "\n".join(stderr_lines)
    return proc.returncode, stderr_full

def process_video(file_path, output_dir, name_option, value, settings, progress_callback=None, cancel_event=None):
    """
    비디오 변환 핵심 파이프라인.
    """
    if not os.path.exists(file_path):
        return 'FAIL', "파일이 존재하지 않습니다."

    # 1. 정보 분석
    info = get_video_info(file_path)
    if not info:
        return 'FAIL', "비디오 메타데이터 분석 실패."

    def _cancelled():
        return bool(cancel_event and cancel_event.is_set())

    # 입력 경로 동일 규칙 정규화 (C-1: ffmpeg same-file 가드가 확실히 동작하도록)
    src_path = os.path.abspath(os.path.normpath(file_path))

    # 2. 해상도 다운스케일 필요 여부
    max_w = settings.get('max_width', 1920)
    max_h = settings.get('max_height', 1080)
    need_scale = info['width'] > max_w or info['height'] > max_h

    # 3. Remux(무손실 복사) 판단 (H-1: 다운스케일 필요 시 절대 remux 안 함, N/A 비트레이트는 추정)
    remux_threshold = settings.get('remux_threshold_mbps', 4.0)
    try:
        size_bytes = os.path.getsize(file_path)
    except OSError:
        size_bytes = 0
    remux_only = should_remux(
        info['bit_rate'], info['duration_sec'], size_bytes, remux_threshold, need_scale
    )

    # 4. 출력 경로 결정 (core 소유). 재인코딩 경로는 .mp4 강제(H-3), remux는 원본 확장자 유지.
    dest_path = os.path.abspath(os.path.normpath(
        resolve_output_path(file_path, output_dir, name_option, value)
    ))
    if not remux_only:
        dest_path = _force_mp4_ext(dest_path)
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    is_same_file = (src_path == dest_path)

    # 5. 다운스케일 필터 생성
    scale_filter = f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    base_vf = scale_filter if need_scale else "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    vf = f"{base_vf},format=yuv420p"  # NVENC 용 pix format

    total_sec = info['duration_sec']
    faststart = settings.get('faststart', True)

    # 텍스트 자막(mov_text 보존 대상) 인덱스 산출 — 이미지 자막은 제외되어 자연 드롭(H-2)
    text_sub_indices = [
        i for i, c in enumerate(info.get('sub_codecs', []))
        if str(c).lower() in _TEXT_SUB_CODECS
    ]

    # C-1: 항상 임시 파일에 쓴 뒤 os.replace 로 원자 교체 → 인플레이스 원본 손상 방지
    tmp_path = _tmp_output_path(dest_path)

    def _finalize_success(mode_label, copy=False):
        """tmp 무결성 검증 후 dest로 원자 교체하고 상태 반환."""
        if not _tmp_is_valid(tmp_path):
            _safe_remove(tmp_path)
            return 'FAIL', "산출물 무결성 검증 실패(빈 파일/손상)"
        try:
            os.replace(tmp_path, dest_path)
        except OSError as e:
            _safe_remove(tmp_path)
            return 'FAIL', f"결과 파일 교체 실패: {e}"
        if copy:
            # remux는 원본 삭제 옵션을 (다른 파일일 때만) 적용
            if settings.get('delete_source', False) and not is_same_file:
                _safe_remove(file_path)
                return 'SUCCESS_DEL', f"Remux 완료 및 원본 삭제됨"
            return 'COPY', "Remux 완료 (비트레이트 기준 미달, 재인코딩 없이 복사)"
        if settings.get('delete_source', False) and not is_same_file:
            try:
                os.remove(file_path)
                return 'SUCCESS_DEL', f"변환 완료 및 원본 삭제됨 (모드: {mode_label})"
            except OSError as e:
                return 'SUCCESS', f"변환 완료 (원본 삭제 실패: {e})"
        return 'SUCCESS', f"변환 완료 (모드: {mode_label})"

    try:
        # ---- Remux 경로 ----
        if remux_only:
            cmd = _build_ffmpeg_cmd(src_path, tmp_path, True, "", faststart, 'cpu', settings)
            rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event, tmp_path)
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return 'CANCELLED', "사용자 취소됨"
            if rc == 0:
                return _finalize_success('remux', copy=True)
            _safe_remove(tmp_path)
            return 'FAIL', f"Remux 실패 (코드: {rc})"

        # ---- 재인코딩 경로 (단계별 폴백) ----
        # Step 1: CUDA 가속 시도
        mode = 'cuda'
        cmd = _build_ffmpeg_cmd(src_path, tmp_path, False, vf, faststart, mode, settings, text_sub_indices)
        rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event, tmp_path)
        if _cancelled() or stderr_full == "USER_CANCELLED":
            _safe_remove(tmp_path)
            return 'CANCELLED', "사용자 취소됨"

        # 재시도 무의미한 입력/경로 오류는 조기 중단(폴백 3회 낭비 방지)
        if rc != 0 and _stderr_suggests_fatal_input_error(stderr_full):
            _safe_remove(tmp_path)
            return 'FAIL', "입력/출력 경로 오류로 변환 중단"

        # Step 2: CUDA 디코드 실패 정황이면 CPU 디코딩 + NVENC 인코딩
        if rc != 0 and _stderr_suggests_nvenc_fail(stderr_full):
            print(f"CUDA 하드웨어 디코드 실패 -> CPU 디코딩 + GPU 인코딩 폴백 시도 ({file_path})")
            mode = 'cpu_decode'
            cmd = _build_ffmpeg_cmd(src_path, tmp_path, False, vf, faststart, mode, settings, text_sub_indices)
            rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event, tmp_path)
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return 'CANCELLED', "사용자 취소됨"

        # Step 3: NVENC 자체 실패 시 완전 CPU 인코딩(libx264)
        if rc != 0:
            print(f"NVENC 가속 실패 -> 완전 CPU 인코딩(libx264) 최종 폴백 시도 ({file_path})")
            mode = 'cpu'
            cmd = _build_ffmpeg_cmd(src_path, tmp_path, False, vf, faststart, mode, settings, text_sub_indices)
            rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event, tmp_path)
            if _cancelled() or stderr_full == "USER_CANCELLED":
                _safe_remove(tmp_path)
                return 'CANCELLED', "사용자 취소됨"

        if rc == 0:
            return _finalize_success(mode, copy=False)
        _safe_remove(tmp_path)
        return 'FAIL', f"인코딩 오류 (반환코드: {rc})"
    except Exception as e:
        _safe_remove(tmp_path)
        return 'FAIL', f"변환 예외: {e}"

if __name__ == '__main__':
    # 간단한 CLI 테스트 모드
    if len(sys.argv) < 3:
        print("사용법: python core_converter.py <input_video_file> <output_dir> [delete_source: true/false]")
        sys.exit(1)
        
    in_file = sys.argv[1]
    out_dir = sys.argv[2]
    del_src = sys.argv[3].lower() == 'true' if len(sys.argv) > 3 else False
    
    settings = {
        'video_maxrate_mbps': 3.5,
        'audio_bitrate': '128k',
        'max_width': 1920,
        'max_height': 1080,
        'remux_threshold_mbps': 0.001,
        'faststart': True,
        'delete_source': del_src,
        'nvenc_preset': 'p5'
    }
    
    print(f"인풋 비디오: {in_file}")
    print(f"아웃풋 폴더: {out_dir}")
    
    def test_cb(pct, time_str, speed):
        print(f"진행 상황: {pct:.1f}% | 시간: {time_str} | 속도: {speed}")
        
    from threading import Event
    cancel_ev = Event()
    
    status, msg = process_video(in_file, out_dir, "suffix", "_converted", settings, test_cb, cancel_ev)
    print(f"결과: [{status}] {msg}")

