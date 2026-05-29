@echo off
echo ========================================
echo   Slayer RPG Bot - Push to GitHub
echo ========================================
echo.

:: Add Git to PATH if it isn't already there
where git >nul 2>nul
if %errorlevel% neq 0 (
    set "PATH=%PATH%;C:\Program Files\Git\cmd"
)

cd /d "%~dp0"


git add -A

set /p msg="Enter commit message (or press Enter for auto): "
if "%msg%"=="" set msg=Auto update: %date% %time%

git commit -m "%msg%"

git remote set-url origin https://github.com/nikhilgurjar7605-collab/slayer.git

git push origin main

echo.
echo ========================================
if %errorlevel%==0 (
    echo   SUCCESS - Pushed to GitHub!
) else (
    echo   ERROR - Push failed. Check your credentials.
)
echo ========================================
pause
