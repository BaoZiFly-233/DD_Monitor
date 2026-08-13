"""
DD监控室 — 程序入口

业务代码全部位于 app/ 包内（app.ui / app.core / app.danmaku / app.media），
本文件仅负责：
- 原生崩溃诊断（faulthandler 必须在任何业务 import 之前启用）
- 平台 patch 与缓存 / 日志目录初始化
- 启动闪屏与 MainWindow
"""

import os
import sys
import time

# 原生崩溃诊断 — 在全部 import 之前启用
import faulthandler

_logs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_logs_dir, exist_ok=True)
# 清理 7 天前的旧崩溃日志（faulthandler 每次启动都会建文件，正常退出时为空）
try:
    _cutoff = time.time() - 7 * 86400
    for _old in os.listdir(_logs_dir):
        if _old.startswith("crash-") and _old.endswith(".log"):
            _p = os.path.join(_logs_dir, _old)
            if os.path.getmtime(_p) < _cutoff:
                os.remove(_p)
except OSError:
    pass  # 清理失败不影响启动

_crash_log = os.path.join(_logs_dir, f"crash-{time.strftime('%Y%m%d-%H%M%S')}.log")
# faulthandler 需要长期持有该文件句柄，不能用 with 上下文
faulthandler.enable(file=open(_crash_log, "w"), all_threads=True)
if sys.platform == "win32":
    import ctypes

    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002)

import shutil
import logging
import platform
import threading
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QSplashScreen
from PySide6.QtGui import QFont, QPixmap

from app.ui.main_window import MainWindow, get_application_path
from app.ui.video_widget import load_mpv_module
from app.core.app_version import DISPLAY_VERSION
from app.core import log
from app.core.exception_handlers import (
    threadingExceptionHandler,
    uncaughtExceptionHandler,
    unraisableExceptionHandler,
    loggingSystemInfo,
)

if __name__ == "__main__":
    # 平台相关 patch
    import ctypes

    if platform.system() == "Windows":
        ctypes.windll.kernel32.SetDllDirectoryW(None)

    application_path = get_application_path()

    # 缓存、日志文件夹初始化
    cachePath = os.path.join(application_path, "cache")
    logsPath = os.path.join(application_path, "logs")
    if not os.path.exists(cachePath):  # 启动前初始化cache文件夹
        os.mkdir(cachePath)
    if not os.path.exists(logsPath):  # 启动前初始化logs文件夹
        os.mkdir(logsPath)
    try:  # 尝试清除上次缓存 如果失败则跳过（cache/ 内可能混有截图等文件，只删目录）
        for cacheFolder in os.listdir(cachePath):
            _cacheDir = os.path.join(cachePath, cacheFolder)
            if os.path.isdir(_cacheDir):
                shutil.rmtree(_cacheDir, ignore_errors=True)
    except Exception:
        logging.exception("清除缓存失败")
    cacheFolder = os.path.join(application_path, "cache/%d" % time.time())  # 初始化缓存文件夹
    os.mkdir(cacheFolder)

    # 应用全局样式：qfluentwidgets_pro Fluent 暗色主题
    # Qt6 默认启用高 DPI，无需手动设置 AA_EnableHighDpiScaling
    app = QApplication(sys.argv)
    from app.ui.uikit_bridge import init_uikit

    init_uikit()
    app.setFont(QFont("微软雅黑", 9))

    # 日志采集初始化
    log.init_log(application_path)
    sys.excepthook = uncaughtExceptionHandler
    sys.unraisablehook = unraisableExceptionHandler
    threading.excepthook = threadingExceptionHandler
    # 系统信息收集延迟到后台线程
    _sysInfoThread = threading.Thread(target=loggingSystemInfo, daemon=True)
    _sysInfoThread.start()
    # MPV 信息log
    try:
        if load_mpv_module() is not None:
            logging.info("python-mpv 已就绪（惰性加载）")
        else:
            logging.warning("python-mpv 未安装或 libmpv 未找到")
    except Exception as e:
        logging.warning(f"python-mpv 预检查失败: {e}")

    # 欢迎页面
    splash = QSplashScreen(QPixmap(os.path.join(application_path, "resources/splash.jpg")))
    progressBar = QProgressBar(splash)
    progressBar.setMaximum(16)  # 仅在启动时初始化 16 个主层播放器
    progressBar.setGeometry(0, splash.height() - 20, splash.width(), 20)
    # 版本号动态叠加 — 不再烧在背景图里，发版无需改 PSD
    versionLabel = QLabel(splash)
    versionLabel.setText(f"v{DISPLAY_VERSION}")
    versionLabel.setFont(QFont("微软雅黑", 11))
    versionLabel.setStyleSheet("color: rgba(255,255,255,0.75); background: transparent;")
    versionLabel.adjustSize()
    versionLabel.move(splash.width() - versionLabel.width() - 18, splash.height() - 40 - versionLabel.height())
    progressText = QLabel(splash)
    progressText.setText("加载中...")
    progressText.setGeometry(0, 0, 170, 20)
    splash.show()

    # 主页面入口
    mainWindow = MainWindow(cacheFolder, progressBar, progressText)
    mainWindow.showMaximized()
    mainWindow.show()
    splash.hide()
    exit_code = app.exec()
    if sys.platform == "win32":
        # libmpv-2.dll 的退出清理（DllMain/atexit）与 Qt GL 上下文销毁存在
        # 已知冲突（0xe24c4a02 / segfault），且 mpv_render_context_free /
        # mpv_terminate_destroy 在 Windows 上也有已知崩溃（mpv#8509/iina#5031）。
        # 所有业务清理（配置保存/线程停止/MPV 释放）已在 closeEvent 内完成，
        # 此处用 TerminateProcess 硬终止，跳过 DLL 清理，保证退出不崩溃。
        import ctypes

        ctypes.windll.kernel32.TerminateProcess(
            ctypes.windll.kernel32.GetCurrentProcess(), exit_code
        )
    sys.exit(exit_code)
