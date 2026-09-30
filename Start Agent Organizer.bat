@echo off
rem Double-click to start the organizer inside WSL and open it in the browser.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8765"
wsl.exe --cd "%~dp0." -- bash -lc "python3 server.py"
