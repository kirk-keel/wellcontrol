@echo off
REM ---------------------------------------------------------------------
REM  Well Control Kill Planner
REM
REM  Double-click this file to start the app. It opens in your browser at
REM  http://localhost:8501 and keeps running until you close this window.
REM
REM  First run takes a minute while it builds the environment. After that
REM  it starts in a few seconds.
REM ---------------------------------------------------------------------

cd /d "%~dp0"
title Well Control Kill Planner

echo.
echo   Well Control Kill Planner
echo   =========================
echo.

REM -- Find a Python to build the environment with ----------------------
set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not exist "%PY%" (
    where py >nul 2>&1 && set "PY=py"
)
if not exist "%PY%" if not "%PY%"=="py" (
    echo   Python was not found.
    echo.
    echo   Install it with this command, then run this file again:
    echo       winget install Python.Python.3.13 --scope user
    echo.
    pause
    exit /b 1
)

REM -- Build the virtual environment on first run ------------------------
if not exist ".venv\Scripts\python.exe" (
    echo   First run - setting up. This takes a minute...
    echo.
    "%PY%" -m venv .venv
    if errorlevel 1 goto failed
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -e ".[app]"
    if errorlevel 1 goto failed
    echo   Setup complete.
    echo.
)

REM -- Skip Streamlit's first-run "Email:" prompt -----------------------
REM  Without this, the very first launch stops and waits for input with
REM  no explanation, and the app never starts.
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

echo   Starting... your browser will open at http://localhost:8501
echo   Close this window to stop the app.
echo.

".venv\Scripts\python.exe" -m streamlit run "app\streamlit_app.py" ^
    --server.address localhost ^
    --browser.gatherUsageStats false

goto :eof

:failed
echo.
echo   Setup failed. See the messages above.
echo.
pause
exit /b 1
