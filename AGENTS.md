# AGENTS.md

이 파일은 이 저장소에서 작업하는 모든 코딩 에이전트(Codex 등)를 위한 프로젝트 지침입니다.

## 언어 규칙 (필수)

- **모든 답변은 반드시 한글로 작성한다.** 사용자에게 보이는 설명·요약·질문·상태 보고는 한국어로 한다.
- 코드, 식별자, 파일 경로, 로그 원문, 명령어, 오류 메시지 원문 등 기술적 토큰은 원문 그대로 두되, 그에 대한 설명은 한글로 한다.

## 프로젝트 개요

- `video_converter`: Windows용 NVIDIA NVENC 기반 비디오 일괄 변환 GUI 데스크톱 앱.
- 핵심 파일: `gui_app.py`(GUI), `core_converter.py`(ffmpeg 변환 파이프라인), `tests/`(pytest).
- 테스트 실행: `.venv/Scripts/python.exe -m pytest -q`
