@echo off
if "%~1"=="" (
    echo [INFO] No version number provided. Auto-incrementing current version...
    python set_version.py
) else (
    echo [INFO] Setting version to %1...
    python set_version.py %1
)

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Version bump failed.
    pause
    exit /b 1
)

echo [SUCCESS] Project files updated.
echo.
echo Starting the distribution build (Windows EXE, Updater, and Android APK)...
pause

call build_dist.bat
