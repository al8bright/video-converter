# 🎬 Video Converter (CUDA/NVENC)

NVIDIA 그래픽카드의 하드웨어 가속(**CUDA 디코딩** + **h264_nvenc 인코딩**)으로 큰 영상을 빠르게 H.264 mp4로 줄이는 Windows 데스크톱 앱입니다.
여러 파일을 동시에 변환하고, 파일마다 진행률과 배속을 보여 줍니다. GPU 가속이 안 되면 자동으로 CPU 변환으로 넘어갑니다.

> 2.0 전환 중입니다([PLAN.md](PLAN.md)). 화면은 React + Tauri로 바뀌었고, 옛 CustomTkinter 화면은 Phase 6에서 지웁니다.

---

## ✨ 주요 기능

- **NVIDIA 하드웨어 가속**: `-hwaccel cuda`로 GPU 디코딩, `h264_nvenc`(preset `p5`, VBR)로 인코딩합니다.
- **3단계 자동 폴백**: 실패하면 다음 단계로 넘어갑니다.
  1. CUDA 디코딩 + NVENC 인코딩 (기본)
  2. CPU 디코딩 + NVENC 인코딩 (CUDA 디코딩이 안 될 때)
  3. CPU 디코딩 + libx264 인코딩 (NVENC가 안 될 때)
- **필요할 때만 다시 인코딩**: 비트레이트가 4 Mbps 이하이고 줄일 필요가 없는 영상은 다시 인코딩하지 않고 mp4로 옮겨 담습니다. 오디오 트랙과 텍스트 자막도 함께 옮깁니다.
- **해상도 제한**: 제한(1080p 등)보다 큰 영상만 비율을 지켜 줄입니다.
- **할 일 미리 보기**: 대기열에서 파일마다 '줄여서 변환 · 변환 · 복사' 중 무엇을 할지 변환 전에 보여 줍니다.
- **끌어다 놓기와 폴더 검색**: 파일이나 폴더를 창에 끌어다 놓으면 하위 폴더까지 찾아 담습니다.
- **하드웨어 감지**: `nvidia-smi`로 GPU와 VRAM을 확인해 권장 동시 작업 수(1~4)를 정합니다.
- **안전한 저장**: 결과는 임시 파일에 먼저 쓰고, 다 만든 뒤 확인한 다음에 제 이름으로 바꿉니다. 원본 삭제도 그 뒤에만 합니다.
  중단하거나 앱이 강제로 끝나도 만들다 만 파일은 남지 않습니다(강제 종료 때는 다음 실행 때 지움).

넣을 수 있는 파일: `.mkv`, `.avi`, `.mov`, `.wmv`, `.mp4`, `.m4v`, `.ts`

---

## 📥 설치

설치 파일 `VideoConverter_<버전>_x64-setup.exe`를 실행합니다(아래 [설치 파일 만들기](#설치-파일-만들기)로 만듭니다).
관리자 권한이 필요 없고, FFmpeg가 함께 들어 있어 따로 설치하지 않아도 됩니다.

- **OS**: Windows 10/11
- **NVIDIA GPU + 최신 드라이버**: NVENC를 지원하는 GeForce/Quadro/RTX. GPU가 없거나 감지되지 않으면 CPU(libx264)로 변환합니다(훨씬 느림).

설정과 오류 기록은 `%APPDATA%\VideoConverter\`(`settings.json`, `conversion_errors.log`)에 남습니다.

---

## 🖱️ 사용법

1. 영상 파일이나 폴더를 창에 끌어다 놓거나 **파일 추가** · **폴더 추가**로 대기열에 담습니다.
2. 대기열에서 해상도 · 길이 · 크기와 **할 일**을 확인합니다.
3. 필요하면 **설정**에서 화질, 동시 변환 수, 저장 위치, 파일 이름 규칙을 바꿉니다. 바꾸면 바로 저장됩니다.
4. **변환 시작**을 누릅니다. 덮어쓰기나 원본 삭제를 켜 두었으면 한 번 더 묻습니다.
5. 변환 중에는 '지금 변환 중' 카드에 파일마다 진행률이 보이고, 끝나면 결과 요약(LAST RUN)이 남습니다.

| 설정 | 설명 | 기본값 / 선택지 |
| --- | --- | --- |
| **해상도 제한** | 이보다 큰 영상만 비율을 지켜 줄입니다. | 1080p (FHD) / 720p (HD) / 제한 없음 |
| **최대 비디오 비트레이트** | 낮출수록 파일이 작아지지만 움직임이 많은 장면이 뭉개질 수 있습니다. | 3.5 / 5.0 · 4.0 · 3.5 · 2.5 · 1.5 Mbps |
| **오디오 비트레이트** | AAC | 128k / 192k · 128k · 96k |
| **동시 변환** | 한 번에 변환할 파일 수. 권장값은 VRAM으로 정합니다(4GB 이하 1 · 8GB 이하 2 · 12GB 이하 3 · 그 이상 4). | 권장 / 1~8 |
| **저장 위치** | 원본과 같은 폴더 또는 지정 폴더 | 원본과 같은 폴더 |
| **파일 이름** | 접미사 붙이기(예: `_cuda`) 또는 같은 이름(덮어쓰기). 결과는 항상 mp4입니다. | 접미사 `_cuda` |
| **원본 삭제** | 결과 파일을 확인한 뒤 원본을 지웁니다(휴지통으로 가지 않음). | 끔 |

NVENC는 그래픽카드 안의 전용 칩이라 사용률을 직접 제한할 수 없습니다. 발열이나 부하를 줄이려면 동시 변환 수를 1~2로 낮추세요.

---

## 🛠️ 개발

필요한 것: [uv](https://docs.astral.sh/uv/), [pnpm](https://pnpm.io/), Rust(stable MSVC), 그리고 개발 실행용 FFmpeg·ffprobe(PATH, 예: `winget install Gyan.FFmpeg`).

```bat
cd app
pnpm install
pnpm tauri dev                   :: 창으로 실행(백엔드는 셸이 uv run 으로 띄움)
```

브라우저에서 화면만 볼 때는 터미널 두 개에서:

```bat
cd backend
uv run videoconverter serve      :: http://127.0.0.1:8767
uv run videoconverter doctor     :: FFmpeg·ffprobe·NVENC·libx264·GPU 확인
```

```bat
cd app
pnpm dev                         :: http://localhost:5175
```

브라우저에서는 끌어다 놓기와 선택 창이 없어 '경로로 추가'로 파일이나 폴더 경로를 넣습니다. 화면 규칙은 [DESIGN.md](DESIGN.md)에 있습니다.

검사:

```bat
cd backend
uv run pytest
uv run ruff check
cd ..\app
pnpm lint
pnpm build
cd ..
python scripts\check_structure.py
```

### 설치 파일 만들기

```bat
powershell -ExecutionPolicy Bypass -File scripts\build_app.ps1
```

1. 정해 둔 FFmpeg 빌드(gyan.dev 8.1 essentials: NVENC, CUDA 디코더, libx264 포함)를 한 번 내려받아
   SHA-256을 확인하고 `backend\.tools`에 둡니다. 빌드하는 PC에 깔린 FFmpeg는 쓰지 않습니다(이 빌드로 시험했으므로).
2. 백엔드를 PyInstaller로 묶고 옆에 `ffmpeg.exe` · `ffprobe.exe`와 라이선스를 넣은 뒤,
   `videoconverter-backend.exe doctor --bundled`로 FFmpeg · ffprobe · NVENC · libx264가 다 있는지 확인합니다.
3. Tauri로 설치 파일을 만듭니다: `app\src-tauri\target\release\bundle\nsis\VideoConverter_<버전>_x64-setup.exe`

FFmpeg를 올리려면 `build_app.ps1`의 `$FFmpegVersion`과 `$FFmpegSha256`을 함께 바꾸고 변환을 시험합니다.
`powershell -File`로 실행하세요. PowerShell 5.1 안에서 출력을 `*>&1`로 돌리면 uv가 stderr에 쓰는 안내를 오류로 여겨 멈춥니다.

---

## 🏗️ 프로젝트 구조

| 경로 | 역할 |
| --- | --- |
| `backend/src/videoconverter/config.py` | 변환 상수, 사용자 설정(`%APPDATA%\VideoConverter\settings.json`) |
| `backend/src/videoconverter/core/service.py` | 대기열·영상 분석·일괄 변환·중단 상태 |
| `backend/src/videoconverter/api/` | 화면이 쓰는 로컬 HTTP/WebSocket API (`base.py`는 네 앱 공통) |
| `backend/src/videoconverter/cli.py` | `serve`, `doctor` 명령 |
| `backend/src/videoconverter/core/` | FFmpeg 찾기, FFprobe, FFmpeg 명령, 실행 추적, 변환 파이프라인, 남은 임시 파일 정리 |
| `backend/src/videoconverter/gui/`, `theme.py`, `jobs/` | 옛 CustomTkinter 화면 (Phase 6에서 삭제) |
| `backend/src/videoconverter/assets/` | 아이콘 원본 |
| `backend/packaging/` | PyInstaller 설정 |
| `backend/tests/` | pytest |
| `app/src/` | 화면(React): 대기열 · 설정 · 도움말. `backend.ts`·`common.tsx`·`base.css`는 네 앱 공통 |
| `app/src-tauri/` | 데스크톱 셸(Tauri): 백엔드를 띄우고 끝냄. `lib.rs`는 네 앱 공통, 앱 값은 `app_info.rs` |
| `scripts/build_app.ps1` | 설치 파일 빌드 |
| `scripts/collect_licenses.py` | 설치 파일에 넣을 서드파티 라이선스 모으기 |
| `scripts/check_structure.py` | 네 앱(jamak_converter 등)의 공통 파일이 같은지 확인. 기준은 jamak_converter의 `docs/STRUCTURE.md` |
| `THIRD_PARTY_NOTICES.md` | 함께 배포하는 구성 요소의 라이선스 안내 |
| `.github/workflows/ci.yml` | 푸시·PR 검사 |

---

## 📄 라이선스

소스 코드는 [MIT](LICENSE)입니다. 설치 파일에 함께 들어 있는 FFmpeg(GPL-3.0) 등은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)를 보세요.
