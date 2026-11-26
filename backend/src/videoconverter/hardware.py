"""Windows 시스템 RAM과 NVIDIA GPU 정보 탐지."""

import ctypes
import subprocess
import sys

from .config import DEFAULT_PARALLEL_JOBS, VRAM_JOB_TIERS


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
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
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
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW
    try:
        res = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=True,
            creationflags=creation_flags,
        )
        output = res.stdout.strip()
        if output:
            parts = output.split(",")
            return parts[0].strip(), int(parts[1].strip())
    except Exception:
        pass
    return None, 0


def detect():
    """GPU·메모리와 권장 동시 작업 수. nvidia-smi를 부르므로 한 번만 불러 기억해 둔다(Service)."""
    gpu_name, vram_mb = get_nvidia_gpu_info()
    return {
        "gpu": gpu_name,
        "vram_mb": vram_mb,
        "ram_gb": get_system_ram_gb(),
        "recommended_jobs": recommend_parallel_jobs(gpu_name, vram_mb),
    }


def recommend_parallel_jobs(gpu_name, vram_mb):
    """GPU 존재 여부와 VRAM 경계값으로 기존 권장 병렬 작업 수를 계산한다."""
    if not gpu_name:
        return DEFAULT_PARALLEL_JOBS
    for max_vram_mb, jobs in VRAM_JOB_TIERS:
        if vram_mb <= max_vram_mb:
            return jobs
    return 4

