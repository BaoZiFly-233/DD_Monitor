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
echo   APP_VERSION=3.50
echo   MPV_DLL=D:/path/to/libmpv-2.dll
exit /b 1
)

rem MPV_RUNTIME_DIR 仅用于可选携带 d3dcompiler_43.dll，不再打包整个 mpv runtime 目录

set "APP_VERSION=%APP_VERSION%"
if "%APP_VERSION%"=="" set "APP_VERSION=3.51"

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
if exist "%ROOT_DIR%utils" xcopy "%ROOT_DIR%utils" "%DIST_DIR%\utils\" /E /I /Y >nul
if exist "%DIST_DIR%\utils\config.json" del /F /Q "%DIST_DIR%\utils\config.json"
if exist "%DIST_DIR%\utils\config_*.json" del /F /Q "%DIST_DIR%\utils\config_*.json"
if exist "%DIST_DIR%\utils\splash.psd" del /F /Q "%DIST_DIR%\utils\splash.psd"
if exist "%DIST_DIR%\utils\entitlements.plist" del /F /Q "%DIST_DIR%\utils\entitlements.plist"
copy /Y "%MPV_DLL%" "%DIST_DIR%\libmpv-2.dll" >nul

rem libmpv 嵌入只需要 DLL 本体；d3dcompiler_43.dll 可选（mpv gpu 输出需要），
rem 整个 mpv runtime 目录（mpv.exe/fonts/shaders）对嵌入场景无用，不再打包。
if not "%MPV_RUNTIME_DIR%"=="" (
    if exist "%MPV_RUNTIME_DIR%\d3dcompiler_43.dll" copy /Y "%MPV_RUNTIME_DIR%\d3dcompiler_43.dll" "%DIST_DIR%\d3dcompiler_43.dll" >nul
)

powershell.exe -NoProfile -Command "Compress-Archive -Path '%DIST_DIR%' -DestinationPath '%ARCHIVE_PATH%' -Force"
if errorlevel 1 exit /b 1

echo [INFO] Build completed: "%ARCHIVE_PATH%"
popd
exit /b 0
