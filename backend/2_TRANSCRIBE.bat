@echo off
title AnnotoAI - Transcribe Audio
color 0B
echo.
echo ================================================
echo   AnnotoAI - Whisper Transcriber
echo   Drag and drop your .wav file OR type path
echo ================================================
echo.

set /p AUDIO_FILE="Enter path to your .wav file (or drag and drop it here): "

if not exist "%AUDIO_FILE%" (
    echo.
    echo ERROR: File not found! Check the path and try again.
    pause
    exit
)

echo.
echo [*] Transcribing: %AUDIO_FILE%
echo [*] This may take 30-60 seconds for a 2 minute audio...
echo [*] Using Whisper 'base' model for speed. Change to 'small' for more accuracy.
echo.

python transcribe.py "%AUDIO_FILE%"

if errorlevel 1 (
    echo.
    echo ERROR during transcription. Make sure setup was completed.
    pause
    exit
)

echo.
echo ================================================
echo   DONE! Output saved to: transcript_output.json
echo   Now open: annotation_tool.html in your browser
echo   and paste the JSON there!
echo ================================================
echo.
pause
