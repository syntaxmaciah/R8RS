@echo off
set VERSION=1.2
echo [BUILD] Starting Tactical Command Deck v%VERSION% Build Sequence...

REM 1. Build EXE
echo [BUILD] Packaging Windows EXE...
pyinstaller --noconfirm tcd_package.spec

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] PyInstaller build failed.
    exit /b %ERRORLEVEL%
)

REM 1.5 Build Updater
echo [BUILD] Packaging Updater...
pyinstaller --noconfirm --onefile --console updater.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Updater build failed.
    exit /b %ERRORLEVEL%
)

REM 2. Prepare Distribution Folder
echo [BUILD] Preparing portable distribution...
set DIST_DIR=dist\TacticalCommandDeck_Portable

REM Copy PyInstaller output to portable folder
if not exist "%DIST_DIR%" mkdir "%DIST_DIR%"
xcopy /E /I /Y "dist\TacticalCommandDeck\*" "%DIST_DIR%\"

REM Copy Updater
copy /Y "dist\updater.exe" "%DIST_DIR%\"

REM Clean up the non-portable dist folder created by PyInstaller
rmdir /S /Q "dist\TacticalCommandDeck"
del /Q "dist\updater.exe"

REM Create necessary external folders if they don't exist in dist
if not exist "%DIST_DIR%\server" mkdir "%DIST_DIR%\server"
if not exist "%DIST_DIR%\server\templates" mkdir "%DIST_DIR%\server\templates"
if not exist "%DIST_DIR%\server\assets" mkdir "%DIST_DIR%\server\assets"

REM Copy user-editable files to the dist folder
copy /Y "server\layout.json" "%DIST_DIR%\server\"
copy /Y "server\editor_settings.json" "%DIST_DIR%\server\"
copy /Y "server\about.txt" "%DIST_DIR%\server\"
copy /Y "server\Bug_fixes.txt" "%DIST_DIR%\server\"
copy /Y "server\Bug_fixes_joke.txt" "%DIST_DIR%\server\"
copy /Y "server\update_locations.txt" "%DIST_DIR%\server\"
copy /Y "server\*_default_keys.json" "%DIST_DIR%\server\"

REM Copy assets content
xcopy /E /I /Y "server\assets\*" "%DIST_DIR%\server\assets\"

REM 3. Handle Android APK
echo [BUILD] Building Android APK...
pushd android_app
if exist gradlew.bat (
    call gradlew.bat assembleDebug
) else (
    echo [WARNING] gradlew.bat not found in android_app. Skipping automated APK build.
    echo [INFO] Please run Android Studio or 'gradle wrapper' in the android_app folder to enable this.
)
popd

set APK_SOURCE=android_app\app\build\outputs\apk\debug\app-debug.apk
if exist "%APK_SOURCE%" (
    echo [BUILD] Including Android APK v%VERSION%...
    copy /Y "%APK_SOURCE%" "%DIST_DIR%\TCD_v%VERSION%.apk"
) else (
    echo [WARNING] app-debug.apk not found. Build it in Android Studio first to include it.
)

echo [SUCCESS] Build complete! 
echo [INFO] Windows distribution is ready in: %DIST_DIR%

REM 4. Create Update ZIP
echo [BUILD] Creating update ZIP...
powershell -Command "Compress-Archive -Path '%DIST_DIR%\*' -DestinationPath 'dist\TCD_Update.zip' -Force"
echo [SUCCESS] Update ZIP created: dist\TCD_Update.zip
echo.
set /p DO_RELEASE="Would you like to publish this update to GitHub now? (y/n): "
if /i "%DO_RELEASE%"=="y" (
    python github_release.py
)
pause
