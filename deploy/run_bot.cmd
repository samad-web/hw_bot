@echo off
rem Supervisor for the native (non-Docker) watcher: restart on any exit.
rem Registered as a Scheduled Task so it survives terminal/session close and reboot.
cd /d "%~dp0.."
:loop
echo [%date% %time%] starting watcher >> logs\native.log
python main.py >> logs\native.log 2>&1
echo [%date% %time%] watcher exited with %errorlevel%, restarting in 30s >> logs\native.log
timeout /t 30 /nobreak >nul
goto loop
