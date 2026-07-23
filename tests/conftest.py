"""pytest 공용 설정: 프로젝트 루트를 import 경로에 추가한다.

tests/ 하위에서 `import core_converter`, `import gui_app` 가 동작하도록
프로젝트 루트(tests의 상위 디렉터리)를 sys.path 맨 앞에 삽입한다.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
