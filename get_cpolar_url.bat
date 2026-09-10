@echo off
chcp 65001 >nul
cd /d D:\DJY\project\Insight
echo ============================================
echo   AI Insight Platform - cpolar URLs
echo ============================================
powershell -NoProfile -Command "$m = Get-Content 'D:\DJY\project\Insight\cpolar.out.log' | Select-String 'Tunnel established at' | ForEach-Object { if ($_.Line -match 'https?://[^\" ]+') { $matches[0] } } | Select-Object -Last 3; $m"
echo.
echo Copy the https address above to access the platform.
echo (Address changes after each cpolar reconnect; rerun this to get the latest.)
pause

