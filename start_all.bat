@echo off
title Insight Service Launcher
echo Starting Insight AI platform (backend serves frontend too)...
start "InsightBackend" /min cmd /c "D:\DJY\project\Insight\start_backend.bat"
echo.
echo Done. Now access:
echo   Local : http://localhost:8080
echo   LAN   : http://7.249.92.53:8080
echo   API doc: http://localhost:8080/docs
timeout /t 3 >nul
exit
