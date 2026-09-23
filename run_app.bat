@echo off
cd /d "%~dp0"
title Tapnotic

rem Prefer the py launcher; fall back to python on PATH.
set "PY=python"
where py >nul 2>nul && set "PY=py"

rem Install requirements the first time, or after new ones were added.
%PY% -c "import flask, requests, qrcode" >nul 2>nul
if errorlevel 1 (
    echo Installing Tapnotic requirements...
    %PY% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Could not install requirements. Check the internet connection
        echo and that Python is installed from python.org.
        pause
        exit /b 1
    )
)

%PY% app.py

rem Keep the window open if Tapnotic crashed, so the error can be read.
if errorlevel 1 pause
