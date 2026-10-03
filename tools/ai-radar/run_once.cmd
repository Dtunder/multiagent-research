@echo off
setlocal
set HERE=%~dp0
"%HERE%.venv\Scripts\python.exe" "%HERE%ai_radar.py" collect --config "G:\Meine Ablage\Antigravity\AI_Intel\CONFIG\config.yaml"
exit /b %ERRORLEVEL%
