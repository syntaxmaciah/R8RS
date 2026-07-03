@echo off
echo [TEST] Tactical Command Deck Updater Test
echo.

if "%~1"=="" (
    echo [ERROR] Please provide a path to a ZIP file to test the update.
    echo Example: test_updater.bat TCD_Update.zip
    pause
    exit /b 1
)

set ZIP_PATH=%~f1
set TARGET_DIR=%CD%\dist\TacticalCommandDeck_Portable
set EXE_NAME=TacticalCommandDeck.exe

if not exist "dist\updater.exe" (
    echo [ERROR] updater.exe not found in dist\. Please run bump_version.bat first.
    pause
    exit /b 1
)

echo [INFO] Running updater with:
echo ZIP: %ZIP_PATH%
echo Target: %TARGET_DIR%
echo Restarting: %EXE_NAME%
echo.

start "" "dist\updater.exe" "%ZIP_PATH%" "%TARGET_DIR%" "%EXE_NAME%"
