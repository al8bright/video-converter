# PLAN — VideoConverter 2.0 (Tauri · React · FastAPI 전환)

CustomTkinter 앱을 jamak_converter와 같은 구조로 옮기는 계획입니다.
공통 구조의 기준 문서: [jamak_converter/docs/STRUCTURE.md](https://github.com/al8bright/jamak_converter/blob/main/docs/STRUCTURE.md)

- 작성: 2026-11-26
- 본보기: youtube_down 2.0 (대기열 하나를 메모리에 두고 WebSocket으로 알리는 방식이 같음)

---

## 목표

- 화면을 React로 다시 만들고, 변환 로직은 Python 백엔드로 남깁니다.
- FFmpeg를 설치 파일에 넣어, PATH에 FFmpeg가 없어도 동작하게 합니다.
- 지금 있는 기능과 변환 결과는 그대로 유지합니다.

## 하지 않는 것

- 새 변환 기능(HEVC·AV1, 자막 굽기, 프리셋 편집)은 넣지 않습니다.
- Mac 지원은 하지 않습니다. NVENC 전용이라 VideoToolbox를 따로 써야 합니다.
- audio_converter와 합치지 않습니다.

---

## 지금 있는 것과 갈 곳

| 지금 | 줄 | 2.0에서 |
|---|---|---|
| `core/probe.py` | 133 | `backend/src/videoconverter/core/probe.py` 그대로 |
| `core/ffmpeg_cmd.py` | 217 | 그대로 |
| `core/runner.py` | 193 | 그대로. 프로세스 묶기는 공통 `proc.py`로 |
| `core/pipeline.py` | 248 | 그대로 (3단계 폴백, 멈춤 감지, 임시 출력 → 검증 → 교체) |
| `core/errorlog.py` | 51 | 그대로. 로그 위치는 데이터 폴더로 |
| `hardware.py` | 69 | `core/hardware.py` |
| `jobs/executor.py` | 281 | `core/service.py`로 다시 씀. 순수 함수(상태 요약 등)는 가져감 |
| `config.py` | 63 | 상수는 `config.py`, 화면 문구("1080p (FHD)", "제한 없음")는 화면으로 |
| `gui/`, `theme.py`, `resources.py` | 1,150 | 삭제 (React로 대체) |
| `tests/test_core_converter.py` | 747 | `backend/tests/`로 옮기고 import만 고침 |
| `tests/test_gui_helpers.py` | 401 | 끌어다 놓기 문자열 해석은 삭제, VRAM 규칙·상태 요약은 남김 |

테스트는 지금 144개가 통과합니다. 옮긴 뒤에도 변환 로직 테스트는 전부 통과해야 합니다.

---

## 구조

```
Tauri 창 (React) ──HTTP / WebSocket (127.0.0.1, 실행마다 바뀌는 토큰)──▶ videoconverter-backend.exe ──▶ ffmpeg.exe / ffprobe.exe
```

### 백엔드

- `core/service.py`의 `Service`가 대기열·설정·진행 상태를 들고 있습니다. 바뀔 때마다 버전을 올리고, `/events`가 바뀐 스냅숏만 보냅니다.
- 변환은 `ThreadPoolExecutor`로 1~8개를 동시에 돌립니다(지금과 같음). 각 작업의 진행률·경과 시간·배속을 스냅숏에 담습니다.
- FFmpeg·ffprobe는 백엔드 실행 파일 옆의 것을 먼저 쓰고, 없으면 PATH에서 찾습니다. 지금은 이름만 넘겨 PATH에 의존합니다.
- 설정은 `%APPDATA%\VideoConverter\settings.json`에 저장합니다. 지금은 실행할 때마다 기본값으로 돌아갑니다.

### API

| 경로 | 하는 일 |
|---|---|
| `GET /health`, `GET /system` | 버전, GPU·VRAM·RAM, FFmpeg 위치와 인코더(h264_nvenc, libx264), 권장 동시 작업 수 |
| `GET /state`, `WS /events` | 대기열·진행·설정 스냅숏 |
| `POST /queue/paths` | 파일·폴더 추가(폴더는 하위까지 훑음). 추가하면 백그라운드에서 ffprobe |
| `DELETE /queue/{id}`, `POST /queue/clear`, `POST /queue/clear-finished` | 대기열 정리 |
| `POST /batch/start`, `POST /batch/stop` | 변환 시작·중단 |
| `PUT /settings` | 동시 작업 수, 최대 대역폭, 오디오 비트레이트, 해상도 제한, 저장 위치, 파일명 규칙, 원본 삭제 |
| `POST /open/file`, `POST /open/folder` | 결과 열기 |

### 화면

| 화면 | 내용 |
|---|---|
| 대기열 | 끌어다 놓기, 파일·폴더 추가, 목록(원본 해상도·비트레이트, 예정 동작: 변환/복사, 상태), 진행 중인 작업 카드(진행률·배속), 전체 진행 |
| 설정 | 변환 옵션, 저장 위치, 파일명 규칙, 원본 자동 삭제 |
| 도움말 | 지금의 "설정 도움말 & 성능 팁" |
| 하단 상태 줄 | GPU·VRAM·RAM, FFmpeg 상태 |

- 끌어다 놓기는 Tauri의 `onDragDropEvent`로 경로를 받습니다. `tkinterdnd2`는 더 필요 없습니다.
- 덮어쓰기와 원본 삭제의 확인은 앱 안 `Modal`로 합니다.

### 종료

- 변환 중에 창을 닫으면 확인 창을 띄웁니다.
- 앱이 어떻게 끝나든 FFmpeg는 Job Object로 함께 끝납니다. 지금은 `terminate_all_processes`가 정상 종료 때만 정리합니다.
- 만들다 만 임시 출력은 다음 시작 때 지웁니다. 원본 자동 삭제는 지금처럼 출력 검증이 끝난 뒤에만 합니다.

---

## 단계

### Phase 1 — 백엔드 폴더로 옮기기 (동작 그대로)

- [x] `src/videoconverter` → `backend/src/videoconverter`, `tests` → `backend/tests`
- [x] `pyproject.toml`을 uv 기준으로(의존성 고정, ruff 설정), `requirements.txt`·`run_app.bat` 정리. 경로가 바뀌어 동작하지 않게 된 옛 실행 파일 빌드(`run.py`, `VideoConverter.spec`, `build_exe.bat`)도 이때 지움
- [x] ruff 통과, 변환 로직 테스트 통과 (144개)

완료 기준: `cd backend; uv run pytest`가 통과하고, 옛 화면이 `uv run videoconverter`로 그대로 뜹니다. (Phase 2부터 옛 화면은 `uv run python -m videoconverter.gui`)

### Phase 2 — Service와 API

- [x] `core/service.py`: 대기열 상태 기계(분석 중 → 대기 → 변환 중 → 완료/복사 완료/실패/중단), 동시 작업, 중단
- [x] `config.py`: 화면 문구를 코드 값으로 바꾸고 설정 저장
- [x] FFmpeg 찾기(옆 → PATH), `doctor [--bundled]` (`core/tools.py`)
- [x] `api/server.py`, `cli.py`, 공통 `proc.py`·`api/base.py`
- [x] 테스트: FFmpeg를 가짜로 바꾼 Service·API 테스트, 실제 하위 프로세스로 돌리는 runner 테스트(9b32d1e 회귀 포함)

확인(2026-11-26, RTX 4080, FFmpeg 8.1): API만으로 1440p 고비트레이트 → 1080p NVENC 변환, 저비트레이트 → mp4 복사,
변환 중 중단(Chocolatey shim 아래 진짜 ffmpeg까지 종료, 임시 파일 없음, 시작 전 항목은 대기로 남음),
CUDA를 숨긴 실행에서 NVENC 실패 → CPU(libx264) 폴백.

고침: 저비트레이트라 mp4로 복사할 때 ASS 같은 텍스트 자막과 두 번째 이후 오디오 트랙이 조용히 빠졌다
(ffmpeg 기본 스트림 선택). 이제 재인코딩과 같게 비디오 첫 트랙 + 오디오 전부 + 텍스트 자막(`mov_text`)을 담는다.
그림 자막(PGS 등)은 mp4에 담을 수 없어 두 경로 모두 뺀다.

완료 기준: 브라우저 없이 API만으로 실제 영상을 넣어 변환·중단·폴백이 됩니다.

### Phase 3 — 화면

- [ ] 공통 파일(`api.ts` 연결부, `ui.tsx`, `index.css` 토큰)을 넣고 틀(사이드바·상태 줄)을 만듦
- [ ] 대기열, 설정, 도움말 화면
- [ ] `DESIGN.md`

완료 기준: `pnpm dev` + `videoconverter serve`로 브라우저에서 전체 흐름이 됩니다.

### Phase 4 — Tauri 셸

- [ ] 공통 `lib.rs`, 끌어다 놓기, 폴더 선택 창, 닫기 확인
- [ ] 아이콘(`assets/video_icon.png`에서 다시 만듦)

완료 기준: `pnpm tauri dev`로 앱이 뜨고, 변환 중 강제 종료 뒤 FFmpeg가 남지 않습니다.

### Phase 5 — 설치 파일, CI, 문서

- [ ] `backend/packaging`, `scripts/build_app.ps1`: 정해 둔 FFmpeg 빌드(ffmpeg + ffprobe, NVENC·libx264 포함)를 SHA-256으로 확인해 넣음
- [ ] `THIRD_PARTY_NOTICES.md`, `LICENSE`(MIT)
- [ ] `.github/workflows/ci.yml`
- [ ] README, `CLAUDE.md`·`AGENTS.md` 갱신(지금은 없어진 `gui_app.py`를 가리킴)

완료 기준: FFmpeg가 없는 PC에 설치해 변환이 됩니다.

### Phase 6 — 옛 화면 제거, 2.0.0

- [ ] `gui/`, `theme.py`, `resources.py` 삭제 (`run.py`·`VideoConverter.spec`·`build_exe.bat`·`run_app.bat`은 Phase 1에서 지움)
- [ ] 버전 2.0.0

---

## 확인할 것 (실제 영상)

- CUDA 디코딩 + NVENC, CPU 디코딩 + NVENC, libx264 세 경로가 각각 도는지
- 4Mbps 이하 원본이 복사(remux)로 가는지, 해상도 제한이 큰 원본에만 걸리는지
- 동시 작업 1개와 4개에서 진행률·배속 표시
- 중단, 변환 중 창 닫기, 작업 관리자로 강제 종료
- 원본 자동 삭제: 성공했을 때만, 출력과 원본이 같은 경로면 지우지 않는지

## 위험

| 위험 | 대응 |
|---|---|
| 설치 파일이 커짐. ffmpeg와 ffprobe 각각 80MB 안팎 | NSIS 압축 후 크기를 재고, 크면 ffprobe 호출을 `ffmpeg -i` 출력 해석으로 바꾸는 것을 검토 |
| libx264가 든 FFmpeg는 GPL 빌드 | 별도 실행 파일로 배포하고 출처와 소스 위치를 `THIRD_PARTY_NOTICES.md`에 적음(youtube_down과 같은 방식) |
| 넣은 FFmpeg와 사용자의 드라이버가 맞지 않아 NVENC 실패 | 지금의 폴백이 그대로 처리. `/system`에 실제로 쓸 수 있는 인코더를 표시 |
| `executor.py`를 다시 쓰다 조기 종료·남는 프로세스 버그가 되살아남 | 그 버그를 잡은 테스트(9b32d1e)를 Service 테스트로 옮김 |
