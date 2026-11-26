# 🎬 CUDA/NVENC Video Converter

NVIDIA GPU의 하드웨어 가속(**CUDA 디코딩** + **h264_nvenc 인코딩**)을 활용해 대용량 비디오를 초고속으로 변환·압축하는 Windows 데스크톱 GUI 프로그램입니다. 여러 파일을 병렬로 인코딩하며, 각 작업의 진행률과 배속을 실시간 대시보드로 보여줍니다.

세련된 다크 테마 UI(CustomTkinter)와 드래그 앤 드롭 일괄 추가를 지원하며, GPU 가속에 실패하더라도 자동 폴백을 통해 어떤 비디오든 변환이 끊기지 않도록 설계되었습니다.

---

## ✨ 주요 기능

- **NVIDIA 하드웨어 가속** — `-hwaccel cuda`로 GPU 디코딩, `h264_nvenc`(preset `p5`, VBR)로 저CPU 고속 H.264 인코딩.
- **3단계 자동 폴백** — 실패 시 다음 단계로 자동 전환하여 변환 실패를 방지합니다.
  1. `CUDA 디코딩 + NVENC 인코딩` (기본)
  2. `CPU 디코딩 + NVENC 인코딩` (CUDA 디코드 실패 시)
  3. `CPU 디코딩 + libx264 인코딩` (NVENC 자체 실패 시)
- **지능적 단순 복사(Remux)** — 원본 비디오 비트레이트가 임계값(4 Mbps) 이하이면 재인코딩 없이 컨테이너만 복사하고 `-movflags +faststart`만 적용해 화질 손실 없이 빠르게 저장.
- **자동 다운스케일링** — 원본 해상도가 설정 제한(예: 1080p)보다 클 때만 원본 비율을 유지하며 축소합니다.
- **병렬 인코딩** — `ThreadPoolExecutor`로 1~8개의 파일을 동시에 변환. 각 작업의 진행률·경과 시간·배속(speed)을 개별 진행바로 실시간 표시.
- **드래그 앤 드롭 & 폴더 스캔** — 파일이나 폴더를 끌어다 놓으면 하위 폴더까지 재귀적으로 스캔해 지원 확장자를 일괄 추가.
- **하드웨어 자동 감지** — `nvidia-smi`로 GPU/VRAM, Windows API로 시스템 RAM을 감지하고 VRAM 용량에 맞춰 권장 동시 작업 수를 자동 설정.
- **원본 자동 삭제 옵션** — 변환 성공 및 출력 파일 유효성 검증 후 원본을 삭제하여 저장 공간 확보(원본과 출력 경로가 같을 때는 삭제하지 않음).

지원 입력 확장자: `.mkv`, `.avi`, `.mov`, `.wmv`, `.mp4`, `.m4v`, `.ts`

---

## 📋 요구사항

- **OS**: Windows 10/11 (RAM 감지에 Windows API `GlobalMemoryStatusEx`, `nvidia-smi` 사용)
- **[uv](https://docs.astral.sh/uv/)**: Python과 의존성을 맞춰 설치합니다(Python 3.13).
- **FFmpeg / ffprobe**: `ffmpeg`와 `ffprobe`가 시스템 `PATH`에 등록되어 있어야 합니다. NVENC 가속을 쓰려면 **NVENC가 활성화된 FFmpeg 빌드**가 필요합니다 (예: [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) full 빌드).
- **NVIDIA GPU + 드라이버**: `h264_nvenc` / CUDA 하드웨어 가속을 위해 NVENC를 지원하는 GeForce/Quadro/RTX GPU와 최신 NVIDIA 드라이버(포함된 `nvidia-smi`). GPU가 없거나 감지되지 않으면 자동으로 CPU(libx264) 모드로 동작합니다.
- **Python 패키지** (`backend/pyproject.toml`, `uv.lock`으로 고정):
  - `customtkinter` — GUI 프레임워크
  - `tkinterdnd2` — 드래그 앤 드롭 (없어도 파일/폴더 추가 버튼으로 동작)

---

## 🚀 설치 및 실행

> 2.0 전환 중입니다([PLAN.md](PLAN.md)). 새 화면이 들어오기 전까지는 옛 화면(CustomTkinter)을 씁니다.

```bat
cd backend
uv run python -m videoconverter.gui
```

새 화면(React)은 데스크톱 셸(Tauri)이 들어오기 전까지 브라우저에서 띄웁니다. 터미널 두 개에서:

```bat
cd backend
uv run videoconverter serve      :: http://127.0.0.1:8767
uv run videoconverter doctor     :: FFmpeg·ffprobe·NVENC·GPU 확인
```

```bat
cd app
pnpm install
pnpm dev                         :: http://localhost:5175
```

브라우저에서는 끌어다 놓기와 선택 창이 없어 '경로로 추가'로 파일이나 폴더 경로를 넣습니다. 화면 규칙은 [DESIGN.md](DESIGN.md)에 있습니다.

처음 실행할 때 uv가 Python과 의존성을 설치합니다. 테스트와 린트:

```bat
cd backend
uv run pytest
uv run ruff check
```

### FFmpeg 확인

```bat
ffmpeg -version
ffprobe -version
```

두 명령이 정상 출력되지 않으면 FFmpeg를 설치하고 `PATH`에 추가하세요.

---

## 🖱️ 사용법

1. 앱을 실행합니다. 상단 정보 바에서 감지된 GPU/VRAM 및 시스템 RAM을 확인할 수 있습니다.
2. 변환할 **파일 또는 폴더를 드래그 앤 드롭**하거나 `파일 추가...` / `폴더 추가...` 버튼으로 대기열에 추가합니다. (폴더는 하위 파일까지 스캔)
3. 설정 패널에서 동시 작업 수, 비트레이트, 해상도, 저장 위치, 파일명 규칙 등을 조정합니다.
4. `변환 시작`을 누르면 실시간 대시보드에 진행 중인 작업이 표시됩니다.
5. 완료되면 완료 알림이 뜨고, 대기열 각 항목의 상태(`완료`, `완료(삭제)`, `복사완료`, `실패` 등)가 갱신됩니다.

> 필요 시 `설정 도움말 & 성능 팁` 버튼으로 GPU 가속·성능 관련 안내 팝업을 볼 수 있습니다.

---

## ⚙️ GUI 설정 설명

| 설정 | 설명 | 기본값 / 선택지 |
| --- | --- | --- |
| **동시 변환 작업 수** | 병렬로 실행할 인코딩 개수. VRAM 용량에 따라 권장값이 자동 설정됩니다 (4GB↓:1, 8GB↓:2, 12GB↓:3, 12GB↑:4 / GPU 미감지 시 2). | 1 ~ 8 (슬라이더) |
| **최대 비디오 대역폭** | VBR 최대 비트레이트(Mbps). 낮출수록 용량이 작아지지만 격렬한 장면에서 화질 저하가 있을 수 있습니다. | 3.5 / 5.0·4.0·3.5·2.5·1.5 |
| **오디오 비트레이트** | AAC 오디오 비트레이트. | 128k / 192k·128k·96k |
| **해상도 제한** | 이 값보다 큰 원본만 비율 유지 다운스케일. | 1080p (FHD) / 720p (HD) / 제한 없음 |
| **변환 완료 후 원본 자동 삭제** | 성공·유효성 검증 후 원본 삭제(원본=출력 경로일 땐 미삭제). | OFF |
| **저장 위치** | `원본과 동일한 폴더` 또는 `지정 폴더`. | 원본 폴더 |
| **파일명 규칙** | `덮어쓰기` 또는 `접미사 추가`(예: `_cuda`). 덮어쓰기 선택 시 확인 경고가 표시됩니다. | 접미사 `_cuda` |

### 동작 참고

- **Remux 임계값 4 Mbps** 및 **NVENC preset `p5`**는 내부 고정값입니다.
- NVENC는 하드웨어 ASIC 특성상 사용률을 직접 % 캡으로 제어할 수 없습니다. 발열/부하를 낮추려면 **동시 작업 수를 줄이는 방식**으로 간접 조절하는 것이 권장됩니다.

---

## 🏗️ 프로젝트 구조

| 경로 | 역할 |
| --- | --- |
| `backend/src/videoconverter/config.py` | 변환 상수, 사용자 설정(`%APPDATA%\VideoConverter\settings.json`) |
| `backend/src/videoconverter/core/service.py` | 대기열·영상 분석·일괄 변환·중단 상태 |
| `backend/src/videoconverter/api/` | 화면이 쓰는 로컬 HTTP/WebSocket API (`base.py`는 네 앱 공통) |
| `backend/src/videoconverter/cli.py` | `serve`, `doctor` 명령 |
| `backend/src/videoconverter/core/` | FFmpeg 찾기, FFprobe, FFmpeg 명령, 실행 추적, 변환 파이프라인 |
| `backend/src/videoconverter/gui/`, `theme.py` | 옛 CustomTkinter 화면 (2.0에서 React로 바뀜) |
| `backend/src/videoconverter/jobs/` | 병렬 작업 실행과 슬롯 상태 관리 |
| `backend/src/videoconverter/assets/` | 창·실행 파일 아이콘 |
| `app/src/` | 새 화면(React): 대기열 · 설정 · 도움말. `backend.ts`·`common.tsx`·`base.css`는 네 앱 공통 |
| `scripts/check_structure.py` | 네 앱 공통 파일이 같은지 확인 |
| `backend/tests/` | pytest |
| `backend/pyproject.toml`, `uv.lock` | 의존성과 ruff·pytest 설정 |

---

## 📦 설치 파일

2.0에서 Tauri 설치 파일(FFmpeg 포함)로 바뀝니다([PLAN.md](PLAN.md) Phase 5). 옛 단일 실행 파일 빌드(`build_exe.bat`)는 지웠습니다.
