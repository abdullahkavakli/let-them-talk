@echo off
rem Double-click to start Let Them Talk inside WSL and open it in the browser.
start "" /min cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:8765"
rem %~dp0 is this file's folder; the trailing "." keeps its "\" from escaping the quote.
wsl.exe --cd "%~dp0." -- bash -lc "python3 server.py"
