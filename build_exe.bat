@echo off
echo ===================================================
echo   CUDA/NVENC Video Converter PyInstaller Builder
echo ===================================================
echo.

:: 기존 빌드 결과물 삭제하여 충돌 방지
echo [1/3] Cleaning previous build files...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [2/3] Packing single EXE file from VideoConverter.spec...
call .venv\Scripts\activate.bat
pyinstaller --noconfirm VideoConverter.spec

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
