@echo off
title AnnotoAI - Setup (Run this ONCE)
color 0A
echo.
echo ================================================
echo   AnnotoAI - Local Whisper Setup for Windows
echo   This will install everything you need FREE
echo ================================================
echo.
echo [1/4] Checking Python...
python --version
if errorlevel 1 (
    echo ERROR: Python not found! Please install from python.org
    pause
    exit
)
echo Python OK!
echo.

echo [2/4] Upgrading pip...
python -m pip install --upgrade pip
echo.

echo [3/4] Installing OpenAI Whisper (this may take 2-5 minutes)...
pip install openai-whisper
echo.

echo [4/4] Installing ffmpeg (needed for audio processing)...
pip install ffmpeg-python
echo.
echo Trying to install ffmpeg via winget...
winget install ffmpeg --accept-source-agreements --accept-package-agreements
if errorlevel 1 (
    echo.
    echo NOTE: winget ffmpeg failed. Please manually install ffmpeg:
    echo 1. Go to: https://ffmpeg.org/download.html
    echo 2. Download Windows build
    echo 3. Extract and add to PATH
    echo OR just run the transcriber - it may still work!
)

echo.
echo ================================================
echo   SETUP COMPLETE!
echo   Now run: 2_TRANSCRIBE.bat to transcribe audio
echo ================================================
echo.
pause
