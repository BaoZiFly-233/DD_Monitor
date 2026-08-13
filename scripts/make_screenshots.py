# -*- coding: utf-8 -*-
"""README 截图生成器 — 离屏渲染真实 UI 并保存到 docs/。

用法（项目根目录，需图形会话）：
    set PATH=%CD%;%PATH%   (Windows，保证 libmpv-2.dll 可加载)
    python scripts/make_screenshots.py

说明：
- 使用临时配置目录，不触碰用户真实 resources/config.json；
- 退出时走 MainWindow.closeEvent 的完整关闭路径（顺带冒烟测试退出崩溃修复）。
"""

import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QLabel, QProgressBar  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402

# ---- 隔离配置：复制真实配置结构到临时目录，避免污染用户数据 ----
_tmp_root = tempfile.mkdtemp(prefix="ddmon_shot_")
_resources = os.path.join(_tmp_root, "resources")
os.makedirs(_resources, exist_ok=True)
os.makedirs(os.path.join(_tmp_root, "logs"), exist_ok=True)
os.makedirs(os.path.join(_tmp_root, "cache"), exist_ok=True)
for name in ("splash.jpg", "vtb.csv"):
    src = os.path.join(ROOT, "resources", name)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(_resources, name))


def _fake_application_path(tmp_root):
    """让 get_application_path() 指向临时目录：MainWindow 构造时以模块全局
    查找该函数，monkeypatch 后配置/资源读写全部落在临时目录，不碰真实数据。"""
    import app.ui.main_window as mw

    mw.get_application_path = lambda: tmp_root
    mw._hard_exit = lambda: None  # 截图脚本不走硬退出，保留正常收尾


app = QApplication(sys.argv)
from app.ui.uikit_bridge import init_uikit  # noqa: E402

init_uikit()
app.setFont(QFont("微软雅黑", 9))

from app.ui.main_window import MainWindow  # noqa: E402
from app.core import log  # noqa: E402

log.init_log(_tmp_root)
_fake_application_path(_tmp_root)

# 用轻量假闪屏控件
progressBar = QProgressBar()
progressText = QLabel("渲染中...")

mainWindow = MainWindow(_tmp_root + "/cache", progressBar, progressText)
mainWindow.resize(1600, 900)
mainWindow.show()

# 等待布局/延迟初始化（setPlayer 等）稳定
for _ in range(10):
    app.processEvents()
    import time

    time.sleep(0.15)
app.processEvents()

docs_dir = os.path.join(ROOT, "docs")
os.makedirs(docs_dir, exist_ok=True)

pix = mainWindow.grab()
pix.save(os.path.join(docs_dir, "screenshot-main.png"))
print("saved screenshot-main.png")

# 设置面板
from app.ui.settings_dialog import SettingsDialog  # noqa: E402

settings = SettingsDialog(
    mainWindow,
    mainWindow.config,
    mainWindow.configManager,
    danmu_panel_fn=lambda: mainWindow.openGlobalDanmuSetting(),
    layout_panel_fn=lambda: mainWindow.openLayoutSetting(),
)
settings.show()
app.processEvents()
settings.grab().save(os.path.join(docs_dir, "screenshot-settings.png"))
print("saved screenshot-settings.png")
settings.close()

# 添加直播间面板
addroom = mainWindow.liverPanel.addLiverRoomWidget
addroom.show()
app.processEvents()
addroom.resize(600, 900)
app.processEvents()
addroom.grab().save(os.path.join(docs_dir, "screenshot-addroom.png"))
print("saved screenshot-addroom.png")

# 走完整退出路径（验证 shutdown 不崩溃）
mainWindow.close()
app.processEvents()
app.quit()

shutil.rmtree(_tmp_root, ignore_errors=True)
print("done")
