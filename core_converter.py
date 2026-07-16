import os
import re
import sys
import shutil
import subprocess
import threading
import ctypes

# ffmpeg/ffprobe 텍스트 디코딩 셋팅
SUBPROC_TEXT = {"encoding": "utf-8", "errors": "replace"}

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
        'height': 0
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

def _build_ffmpeg_cmd(input_path, output_path, remux_only, vf, faststart, mode, settings):
    """
    변환 모드와 사용자 설정에 따라 ffmpeg 인자 구성.
    mode: 'cuda' (GPU 디코딩+인코딩), 'cpu_decode' (CPU 디코딩+GPU 인코딩), 'cpu' (완전 CPU 처리)
    """
    # 단순 복사(Remux) 모드
    if remux_only:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy"]
        if faststart:
            cmd += ["-movflags", "+faststart"]
        cmd += [output_path]
        return cmd

    video_maxrate = f"{settings.get('video_maxrate_mbps', 3.5)}M"
    video_bufsize = f"{float(settings.get('video_maxrate_mbps', 3.5)) * 2}M"
    audio_bitrate = settings.get('audio_bitrate', '128k')
    nvenc_preset = settings.get('nvenc_preset', 'p5')

    # 1차 기본 가속 모드 (CUDA 하드웨어 디코딩 + NVENC 인코딩)
    if mode == 'cuda':
        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "cuda",
            "-i", input_path,
            "-c:v", "h264_nvenc",
            "-preset", nvenc_preset,
            "-rc", "vbr",
            "-b:v", video_maxrate,
            "-maxrate", video_maxrate,
            "-bufsize", video_bufsize,
            "-vf", vf,
            "-c:a", "aac", "-b:a", audio_bitrate,
            output_path
        ]
    # 2차 가속 모드 (CPU 디코딩 + NVENC 인코딩)
    elif mode == 'cpu_decode':
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "h264_nvenc",
            "-preset", nvenc_preset,
            "-rc", "vbr",
            "-b:v", video_maxrate,
            "-maxrate", video_maxrate,
            "-bufsize", video_bufsize,
            "-vf", vf,
            "-c:a", "aac", "-b:a", audio_bitrate,
            output_path
        ]
    # 3차 최종 폴백 모드 (CPU 디코딩 + CPU x264 인코딩)
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "medium",
            "-b:v", video_maxrate,
            "-maxrate", video_maxrate,
            "-bufsize", video_bufsize,
            "-vf", vf,
            "-c:a", "aac", "-b:a", audio_bitrate,
            output_path
        ]

    if faststart:
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

def run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event):
    """
    ffmpeg 명령어를 실행하고 stderr에서 진행 정보를 실시간 파싱해 콜백 전송.
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
                return -1, "USER_CANCELLED"
            proc.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        pass
    except Exception as e:
        proc.kill()
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

    dest_path = resolve_output_path(file_path, output_dir, name_option, value)
    dest_dir = os.path.dirname(dest_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    is_same_file = (os.path.abspath(file_path) == os.path.abspath(dest_path))

    # 2. 단순 복사(Remux) 판단
    remux_threshold = settings.get('remux_threshold_mbps', 4.0)
    src_bps = info['bit_rate']
    remux_only = (src_bps > 0 and src_bps <= remux_threshold * 1_000_000)

    # 3. 해상도 다운스케일 필터 생성
    max_w = settings.get('max_width', 1920)
    max_h = settings.get('max_height', 1080)
    need_scale = info['width'] > max_w or info['height'] > max_h
    
    scale_filter = f"scale={max_w}:{max_h}:force_original_aspect_ratio=decrease,pad=ceil(iw/2)*2:ceil(ih/2)*2"
    base_vf = scale_filter if need_scale else "pad=ceil(iw/2)*2:ceil(ih/2)*2"
    vf = f"{base_vf},format=yuv420p"  # NVENC 용 pix format

    total_sec = info['duration_sec']
    faststart = settings.get('faststart', True)

    # 4. 인코딩 실행 및 단계별 폴백 프로세스
    if remux_only:
        # Remux 모드는 굳이 가속이나 스케일링이 필요 없음
        cmd = _build_ffmpeg_cmd(file_path, dest_path, True, "", faststart, 'cpu', settings)
        rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event)
        if rc == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) >= 1024:
            return 'COPY', "Remux 완료 (비트레이트 기준 미달, 화질/오디오 유지)"
        else:
            return 'FAIL', f"Remux 실패 (코드: {rc})"

    # 인코딩 변환 시도
    # Step 1: CUDA 가속 시도
    mode = 'cuda'
    cmd = _build_ffmpeg_cmd(file_path, dest_path, False, vf, faststart, mode, settings)
    rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event)

    # Step 2: CUDA 실패 시 CPU 디코딩 + NVENC 인코딩 시도
    if rc != 0 and _stderr_suggests_nvenc_fail(stderr_full):
        if cancel_event and cancel_event.is_set():
            return 'FAIL', "사용자 취소됨"
        print(f"CUDA 하드웨어 디코드 실패 -> CPU 디코딩 + GPU 인코딩 폴백 시도 ({file_path})")
        mode = 'cpu_decode'
        cmd = _build_ffmpeg_cmd(file_path, dest_path, False, vf, faststart, mode, settings)
        rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event)

    # Step 3: NVENC 자체 실패 시 완전 CPU 인코딩(libx264) 시도
    if rc != 0:
        if cancel_event and cancel_event.is_set():
            return 'FAIL', "사용자 취소됨"
        print(f"NVENC 가속 실패 -> 완전 CPU 인코딩(libx264) 최종 폴백 시도 ({file_path})")
        mode = 'cpu'
        cmd = _build_ffmpeg_cmd(file_path, dest_path, False, vf, faststart, mode, settings)
        rc, stderr_full = run_ffmpeg_and_track(cmd, total_sec, progress_callback, cancel_event)

    # 결과 검토
    if rc == 0 and os.path.exists(dest_path) and os.path.getsize(dest_path) >= 1024:
        # 성공 시 원본 삭제 옵션 적용
        if settings.get('delete_source', False) and not is_same_file:
            try:
                os.remove(file_path)
                return 'SUCCESS_DEL', f"변환 완료 및 원본 삭제됨 (모드: {mode})"
            except Exception as e:
                return 'SUCCESS', f"변환 완료 (원본 삭제 실패: {e})"
        return 'SUCCESS', f"변환 완료 (모드: {mode})"
    else:
        if cancel_event and cancel_event.is_set():
            return 'FAIL', "사용자 취소됨"
        return 'FAIL', f"인코딩 오류 (반환코드: {rc})"

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

