@echo off
rem Uruchamiane przez Harmonogram zadan Windows (zadanie "QA Job Finder").
rem Log ostatniego przebiegu: reports\logs\last_run.log
cd /d "%~dp0"
if not exist reports\logs mkdir reports\logs
set PYTHONIOENCODING=utf-8
"C:\Python312\python.exe" run_all.py --email > reports\logs\last_run.log 2>&1
