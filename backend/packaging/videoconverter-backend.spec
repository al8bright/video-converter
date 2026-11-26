# PyInstaller spec (onedir). 빌드:  uv run pyinstaller packaging/videoconverter-backend.spec
# ffmpeg.exe·ffprobe.exe 는 여기서 넣지 않는다. scripts/build_app.ps1 이 결과 폴더(dist/videoconverter-backend/)에 복사한다.
from PyInstaller.utils.hooks import collect_submodules

hidden = (
    collect_submodules("videoconverter")
    + collect_submodules("uvicorn")
    + ["websockets", "websockets.legacy", "httptools", "h11"]
)

a = Analysis(
    ["entry.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "ruff", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
# console=True: Tauri 가 표준 출력으로 주소를 받는다. 창은 Tauri 가 CREATE_NO_WINDOW 로 숨긴다
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="videoconverter-backend", console=True, upx=False,
          icon="../../app/src-tauri/icons/icon.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="videoconverter-backend", upx=False)
