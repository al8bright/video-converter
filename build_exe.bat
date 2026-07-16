@echo off
echo ===================================================
echo   CUDA/NVENC Video Converter PyInstaller Builder
echo ===================================================
echo.

:: 기존 빌드 결과물 삭제하여 충돌 방지
echo [1/3] Cleaning previous build files...
rmdir /s /q build
rmdir /s /q dist
del /q VideoConverter.spec

echo [2/3] Packing single EXE file...
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --onefile --windowed --name="VideoConverter" --add-data ".venv\Lib\site-packages\customtkinter;customtkinter" --collect-all tkinterdnd2 gui_app.py

if errorlevel 1 (
    echo.
    echo [ERROR] Build failed! Please check error logs above.
    pause
    exit /b 1
)

echo.
echo [3/3] Build completed successfully!
echo       Output binary: dist/VideoConverter.exe
echo.
pause
