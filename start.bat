@echo off
chcp 65001 >nul 2>nul
setlocal EnableDelayedExpansion

title KARDS Server

:: --- Check Python ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Install Python 3.7+ first.
    pause
    exit /b 1
)

:: --- Find available port ---
set PORT=8000
:findport
netstat -ano 2>nul | findstr /R /C:":%PORT% " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    set /a PORT+=1
    if !PORT! gtr 8010 (
        echo [ERROR] No available port between 8000-8010.
        pause
        exit /b 1
    )
    goto findport
)

:: --- Print info ---
echo.
echo ========================================
echo   KARDS Frontend Server
echo ========================================
echo.
echo   URL  : http://localhost:%PORT%/account.html
echo   Admin: admin / admin123
echo   Stop : Ctrl+C
echo.
echo ========================================
echo.

:: --- Open browser after 2s delay ---
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:%PORT%/account.html"

:: --- Start server ---
python serve.py --port %PORT%

echo.
echo Server stopped.
pause
