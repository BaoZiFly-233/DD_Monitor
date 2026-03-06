@echo off
setlocal EnableExtensions EnableDelayedExpansion

for %%I in ("%~dp0..") do set "ROOT_DIR=%%~fI\"
pushd "%ROOT_DIR%"

set "TARGET_ARCH=%~1"
if "%TARGET_ARCH%"=="" set "TARGET_ARCH=x64"

if /I not "%TARGET_ARCH%"=="x64" if /I not "%TARGET_ARCH%"=="x86" (
echo Usage: scripts\build_win.bat [x64^|x86]
echo.
echo Optional env vars:
echo   APP_VERSION=2.27
echo   MPV_DLL=D:/path/to/libmpv-2.dll
echo   MPV_RUNTIME_DIR=D:/path/to/mpv-runtime-dir
exit /b 1
)

set "APP_VERSION=%APP_VERSION%"
if "%APP_VERSION%"=="" set "APP_VERSION=2.27"

set "DIST_NAME=DDMonitor"
set "DIST_DIR=%ROOT_DIR%dist\%DIST_NAME%"
set "BUILD_DIR=%ROOT_DIR%build"
set "RELEASE_DIR=%ROOT_DIR%release"
set "ARCHIVE_NAME=DDMonitor-%APP_VERSION%-windows-%TARGET_ARCH%"
set "ARCHIVE_PATH=%RELEASE_DIR%\%ARCHIVE_NAME%.zip"

set "MPV_DLL=%MPV_DLL%"
if "%MPV_DLL%"=="" set "MPV_DLL=%ROOT_DIR%libmpv-2.dll"
set "MPV_RUNTIME_DIR=%MPV_RUNTIME_DIR%"

if not exist "%MPV_DLL%" (
    echo [ERROR] libmpv DLL not found: "%MPV_DLL%"
    echo Please set MPV_DLL to the architecture-matched libmpv-2.dll path.
    exit /b 1
)

if exist "%DIST_DIR%" rmdir /S /Q "%DIST_DIR%"
if exist "%BUILD_DIR%" rmdir /S /Q "%BUILD_DIR%"
if exist "%ARCHIVE_PATH%" del /F /Q "%ARCHIVE_PATH%"
if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"

echo [INFO] Building DDMonitor %APP_VERSION% for Windows %TARGET_ARCH%...
python -m PyInstaller --clean --noconfirm "DDMonitor.spec"
if errorlevel 1 exit /b 1

if not exist "%DIST_DIR%" (
    echo [ERROR] Build output missing: "%DIST_DIR%"
    exit /b 1
)

if not exist "%DIST_DIR%\logs" mkdir "%DIST_DIR%\logs"
if not exist "%DIST_DIR%\utils" mkdir "%DIST_DIR%\utils"
if exist "%ROOT_DIR%utils\danmu.png" copy /Y "%ROOT_DIR%utils\danmu.png" "%DIST_DIR%\utils\danmu.png" >nul
if exist "%DIST_DIR%\utils\config.json" del /F /Q "%DIST_DIR%\utils\config.json"
if exist "%DIST_DIR%\utils\config_*.json" del /F /Q "%DIST_DIR%\utils\config_*.json"
copy /Y "%MPV_DLL%" "%DIST_DIR%\libmpv-2.dll" >nul

if not "%MPV_RUNTIME_DIR%"=="" (
    if exist "%MPV_RUNTIME_DIR%\d3dcompiler_43.dll" copy /Y "%MPV_RUNTIME_DIR%\d3dcompiler_43.dll" "%DIST_DIR%\d3dcompiler_43.dll" >nul
    if exist "%MPV_RUNTIME_DIR%\mpv" xcopy "%MPV_RUNTIME_DIR%\mpv" "%DIST_DIR%\mpv\" /E /I /Y >nul
)

powershell.exe -NoProfile -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ARCHIVE_PATH%' -Force"
if errorlevel 1 exit /b 1

echo [INFO] Build completed: "%ARCHIVE_PATH%"
popd
exit /b 0
