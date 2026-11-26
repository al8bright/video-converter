# CLAUDE.md

이 파일은 이 저장소에서 작업하는 Claude(및 Claude Code 에이전트)를 위한 프로젝트 지침입니다.

## 언어 규칙 (필수)

- **모든 답변은 반드시 한글로 작성한다.** 사용자에게 보이는 설명·요약·질문·상태 보고는 한국어로 한다.
- 코드, 식별자, 파일 경로, 로그 원문, 명령어, 오류 메시지 원문 등 기술적 토큰은 원문 그대로 두되, 그에 대한 설명은 한글로 한다.

## 프로젝트 개요

- `video_converter`: Windows용 NVIDIA NVENC 기반 비디오 일괄 변환 GUI 데스크톱 앱.
- 2.0 전환 중: 계획은 `PLAN.md`, 네 앱(jamak_converter 등) 공통 구조는 jamak_converter의 `docs/STRUCTURE.md`.
- 코드: `backend/src/videoconverter/` — `core/service.py`(대기열·변환 상태), `api/server.py`(로컬 API), `core/`(ffprobe·ffmpeg 명령·실행·변환 파이프라인), `gui/`·`jobs/`(옛 CustomTkinter 화면, Phase 6에서 삭제).
- 공통 파일(`api/base.py`, `core/proc.py`, `tests/test_common.py` 등)은 네 앱이 같은 내용을 쓴다. 고치면 다른 앱에도 옮기고 `python scripts/check_structure.py`로 확인한다.
- 테스트·린트: `cd backend; uv run pytest; uv run ruff check`
