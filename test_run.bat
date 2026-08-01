@echo off
chcp 936 >nul
title DD监控室 快速测试
cd /d "%~dp0"

echo ==========================================
echo   DD监控室 快速测试模式
echo ==========================================
echo.

rem 检查 Python
where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

rem 检查 libmpv（缺失时视频无法播放，但 UI 可以启动）
if not exist "libmpv-2.dll" (
    echo [警告] 未找到 libmpv-2.dll，视频将无法播放
    echo        下载 mpv-dev-x86_64 包解压后，把 libmpv-2.dll 放到本目录
    echo.
)

echo [信息] 正在启动 DD监控室（源码直跑）...
echo        本窗口是调试终端，请保持打开；关闭窗口即退出程序
echo.

python DD监控室.py
set EXIT_CODE=%ERRORLEVEL%

echo.
if "%EXIT_CODE%"=="0" (
    echo [信息] 程序正常退出
) else (
    echo [错误] 程序异常退出，退出码: %EXIT_CODE%
    echo        崩溃日志: logs\crash-*.log
    echo        运行日志: logs\app.log
)
pause
