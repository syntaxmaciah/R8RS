@echo off
set DIST_EXE=dist\TacticalCommandDeck_Portable\TacticalCommandDeck.exe

if exist "%DIST_EXE%" (
    echo [INFO] Launching Tactical Command Deck Portable...
    start "" "%DIST_EXE%"
) else (
    echo [ERROR] Distribution not found. Please run bump_version.bat first to build the project.
    pause
)
