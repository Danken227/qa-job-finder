@echo off
rem Uruchomienie recznie (z oknem konsoli). Harmonogram zadan uruchamia skrypt
rem przez pythonw.exe bez okna: run_all.py --email --log reports\logs\last_run.log
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\Python312\python.exe" run_all.py --email --log reports\logs\last_run.log
