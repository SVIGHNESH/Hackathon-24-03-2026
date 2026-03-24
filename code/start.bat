@echo off
setlocal

cd /d "%~dp0"

echo Starting OurPlan backend and frontend...

set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    set "PYTHON_EXE=python"
)

start "OurPlan Backend" /D "%~dp0ourplan-backend" cmd /k ""%PYTHON_EXE%" -m uvicorn main:app --host 127.0.0.1 --port 8000"
start "OurPlan Frontend" /D "%~dp0ourplan-frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port 3000"

echo Backend: http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:3000
echo.
echo Both servers were started in separate terminal windows.
