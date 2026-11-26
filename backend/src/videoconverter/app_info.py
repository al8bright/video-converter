"""앱마다 다른 값. 공통 파일(api/base.py, core/proc.py)은 이름과 포트를 여기서 읽는다. (docs/STRUCTURE.md)"""

NAME = "videoconverter"  # 패키지·명령 이름. 토큰 헤더는 X-Videoconverter-Token
ENV = "VIDEOCONVERTER"  # 환경 변수 접두사: VIDEOCONVERTER_TOKEN, VIDEOCONVERTER_HOME, 준비 신호 VIDEOCONVERTER_LISTENING
PORT = 8767  # `videoconverter serve` 기본 포트(개발용. 앱은 --port 0으로 빈 포트를 쓴다)
VITE_PORT = 5175  # 화면 개발 서버(pnpm dev)
