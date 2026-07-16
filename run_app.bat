@echo off
echo ===================================================
echo   CUDA/NVENC Video Converter Launcher
echo ===================================================
echo.

echo [1/3] Checking python virtual environment...
if not exist .venv (
    echo [INFO] Creating virtual environment (.venv)...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        echo         Make sure Python is installed and added to PATH.
        pause
        exit /b 1
    )
)

echo [2/3] Installing/updating dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Please check internet connection.
    pause
    exit /b 1
)

echo [3/3] Launching CUDA/NVENC Video Converter...
python gui_app.py
if errorlevel 1 (
    echo [ERROR] Program terminated unexpectedly.
    pause
)
