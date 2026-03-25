@echo off
title AnnotoAI - Local Server
color 0A
echo.
echo ================================================
echo   AnnotoAI - Starting Local Server
echo   DO NOT CLOSE THIS WINDOW!
echo ================================================
echo.
echo [*] Starting server and opening browser...
echo [*] If browser doesn't open, go to:
echo     http://localhost:7842
echo.
python server.py
pause
