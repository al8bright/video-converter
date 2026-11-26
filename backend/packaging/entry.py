"""PyInstaller 진입점: `uv run videoconverter`과 같은 명령줄(앱은 `videoconverter-backend serve ...`로 띄운다). (공통 파일)"""

import sys

from videoconverter import main

if __name__ == "__main__":
    sys.exit(main())
