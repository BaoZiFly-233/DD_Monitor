# -*- coding: utf-8 -*-
"""README 截图生成器 — 离屏渲染真实 UI 并保存到 docs/。

用法（项目根目录，需图形会话）：
    set PATH=%CD%;%PATH%   (Windows，保证 libmpv-2.dll 可加载)
    python scripts/make_screenshots.py

说明：
- 使用临时配置目录，不触碰用户真实 resources/config.json；
- 退出时走 MainWindow.closeEvent 的完整关闭路径（顺带冒烟测试退出崩溃修复）。
"""

import gc
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from PySide6.QtCore import QCoreApplication, QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget, QLabel, QProgressBar  # noqa: E402
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
    mw.MainWindow.updateChecker = lambda self: None  # 截图离线运行，不请求 GitHub


app = QApplication(sys.argv)
from app.ui.uikit_bridge import init_uikit, set_theme  # noqa: E402

init_uikit()
app.setFont(QFont("微软雅黑", 9))

from app.danmaku.events import DanmakuEvent  # noqa: E402
from app.ui.layout_config import layoutList  # noqa: E402
from app.ui.main_window import CheckDanmmuProvider, MainWindow  # noqa: E402
from app.core import log  # noqa: E402

log.init_log(_tmp_root)
_fake_application_path(_tmp_root)
CheckDanmmuProvider.start = lambda self: None

# 用轻量假闪屏控件
progressBar = QProgressBar()
progressText = QLabel("渲染中...")

mainWindow = MainWindow(_tmp_root + "/cache", progressBar, progressText)
mainWindow.resize(1600, 900)
mainWindow.show()

# 注入离线示例卡片，覆盖直播、离线、待录制和选中边框；仅用于视觉回归。
from app.ui.liver_select import CoverLabel  # noqa: E402

for room_id, name, live_state, record_state, top_token, selected in (
    ("10001", "示例主播 A", 1, 0, False, True),
    ("10002", "示例主播 B", 0, 0, False, False),
    ("10003", "示例主播 C", 0, 2, True, False),
    ("10004", "示例主播 D", 1, 0, False, False),
    ("10005", "示例主播 E", 0, 0, False, False),
    ("10006", "示例主播 F", 1, 0, False, False),
    ("10007", "示例主播 G", 0, 0, False, False),
    ("10008", "示例主播 H", 0, 2, False, False),
):
    card = CoverLabel(room_id, top_token)
    card._liverPanel = mainWindow.liverPanel
    card.firstUpdateToken = False
    card.title = name
    card._setTitleText(name)
    card.liveState = live_state
    card.recordState = record_state
    card.isPlaying = selected
    card.refreshStateLabel()
    mainWindow.liverPanel.coverList.append(card)
    mainWindow.liverPanel.layout.addWidget(card)
mainWindow.liverPanel.syncFlowHeight(mainWindow.scrollArea.viewport().width())

# 等待布局/延迟初始化（setPlayer 等）稳定
for _ in range(10):
    app.processEvents()
    import time

    time.sleep(0.15)
app.processEvents()


def _verify_player_layout(layout_number):
    expected_layout = layoutList[layout_number]
    mainWindow.changeLayout(expected_layout)
    app.processEvents()
    app.processEvents()

    assert mainWindow.mainLayout.count() == len(expected_layout)
    for index, expected_geometry in enumerate(expected_layout):
        video_widget = mainWindow.videoWidgetList[index]
        item_index = mainWindow.mainLayout.indexOf(video_widget)
        assert item_index >= 0
        assert mainWindow.mainLayout.getItemPosition(item_index) == tuple(expected_geometry)
        assert not video_widget.isHidden()
        assert video_widget.width() > 0 and video_widget.height() > 0

    for video_widget in mainWindow.videoWidgetList[len(expected_layout) :]:
        assert mainWindow.mainLayout.indexOf(video_widget) == -1
        assert video_widget.isHidden()


# 20 套播放器布局正向扩容、反向收缩各跑一次。空房间不能创建弹幕浮窗；
# 这会覆盖六宫格首次显示第 5/6 个播放器时曾触发的原生窗口事件回归。
for layout_number in range(len(layoutList)):
    _verify_player_layout(layout_number)
for layout_number in reversed(range(len(layoutList))):
    _verify_player_layout(layout_number)
assert all(video_widget.textBrowser is None for video_widget in mainWindow.videoWidgetList)
_verify_player_layout(7)
print(f"verified {len(layoutList)} player layouts in both directions")

# 鼠标可能停在某个播放窗口上；视觉回归截图统一隐藏悬停控制层。
for video_widget in mainWindow.videoWidgetList:
    video_widget.hoverToken = False
    video_widget.topLabel.hide()
    video_widget.frame.hide()
for dock in (mainWindow.controlDock, mainWindow.cardDock):
    assert dock.features() & QDockWidget.DockWidgetMovable
    assert dock.features() & QDockWidget.DockWidgetFloatable
app.processEvents()

docs_dir = os.path.join(ROOT, "docs")
os.makedirs(docs_dir, exist_ok=True)

pix = mainWindow.grab()
pix.save(os.path.join(docs_dir, "screenshot-main.png"))
print("saved screenshot-main.png")

# 复现用户常用的顶部停靠布局：导航必须仍位于两个 Dock 之上，
# 卡片超过可见高度时必须由滚动区接管，不能显示半张卡片。
mainWindow.addDockWidget(Qt.TopDockWidgetArea, mainWindow.controlDock)
mainWindow.splitDockWidget(mainWindow.controlDock, mainWindow.cardDock, Qt.Horizontal)
mainWindow.resizeDocks([mainWindow.controlDock, mainWindow.cardDock], [230, 1370], Qt.Horizontal)
mainWindow.resizeDocks([mainWindow.controlDock, mainWindow.cardDock], [175, 175], Qt.Vertical)
for _ in range(3):
    app.processEvents()
assert mainWindow.navigationInterface.geometry().bottom() < mainWindow.controlDock.geometry().top()
assert mainWindow.navigationInterface.geometry().bottom() < mainWindow.cardDock.geometry().top()
assert mainWindow.scrollArea.verticalScrollBar().maximum() > 0
mainWindow.grab().save(os.path.join(ROOT, "logs", "screenshot-top-dock.png"))
print("verified top-dock navigation and scrolling")

# 通过用户可用命令恢复默认左右停靠，再验证其余窗口入口。
mainWindow.resetDockLayout()
app.processEvents()
assert mainWindow.dockWidgetArea(mainWindow.controlDock) == Qt.LeftDockWidgetArea
assert mainWindow.dockWidgetArea(mainWindow.cardDock) == Qt.RightDockWidgetArea
assert mainWindow.controlDock.isVisible() and mainWindow.cardDock.isVisible()

# 保存/恢复必须真的覆盖后续移动，而不只是当前几何看起来正确。
mainWindow.addDockWidget(Qt.TopDockWidgetArea, mainWindow.controlDock)
mainWindow.addDockWidget(Qt.TopDockWidgetArea, mainWindow.cardDock)
app.processEvents()
mainWindow.loadDockLayout()
app.processEvents()
assert mainWindow.dockWidgetArea(mainWindow.controlDock) == Qt.LeftDockWidgetArea
assert mainWindow.dockWidgetArea(mainWindow.cardDock) == Qt.RightDockWidgetArea

# 全局画质/解码等旧菜单命令必须保留可达入口。
mainWindow.navigationInterface.widget("options").click()
app.processEvents()
assert mainWindow.optionMenu.isVisible()
mainWindow.optionMenu.close()

# 布局方式必须能从顶部导航直达，而不是依赖已经移除的隐藏菜单栏。
mainWindow.navigationInterface.widget("layout").click()
app.processEvents()
assert mainWindow.layoutSettingPanel.isVisible()
mainWindow.layoutSettingPanel.sendLayout(11)
app.processEvents()
assert mainWindow.mainLayout.count() == len(layoutList[11])
assert not mainWindow.layoutSettingPanel.isVisible()
mainWindow.changeLayout(layoutList[7])
app.processEvents()

# 点击顶部导航打开完整设置面板，并验证关闭后复用同一实例。
mainWindow.navigationInterface.widget("settings").click()
settings = mainWindow._settingsDialog
app.processEvents()
settings.grab().save(os.path.join(docs_dir, "screenshot-settings.png"))
print("saved screenshot-settings.png")
settings.close()
app.processEvents()
mainWindow.openSettingsDialog()
assert mainWindow._settingsDialog is settings
settings.close()

# 弹幕设置同样从顶部导航直达完整面板并复用实例。
mainWindow.navigationInterface.widget("danmaku").click()
global_danmu_panel = mainWindow._globalDanmuPanel
app.processEvents()
assert global_danmu_panel.isVisible()
global_danmu_panel.close()
mainWindow.openGlobalDanmuSetting()
assert mainWindow._globalDanmuPanel is global_danmu_panel
global_danmu_panel.close()

# 弹幕机工作台：通过播放器统一事件入口注入离线事件，覆盖分类、搜索、
# 礼物/上舰样式和模型批处理，不触发真实网络连接。
demo_video = mainWindow.videoWidgetList[0]
demo_video.roomID = "demo"
demo_video._activeDanmuConnectionId = 1
for event in (
    DanmakuEvent(room_id="demo", connection_id=1, text="今晚八点一起看比赛", uname="观众 A"),
    DanmakuEvent(
        room_id="demo",
        connection_id=1,
        text="[EN] Great play!",
        uname="同传组",
        is_translation=True,
        color="#38BDF8",
    ),
    DanmakuEvent(
        room_id="demo",
        connection_id=1,
        kind="gift",
        text="赠送 辣条 × 10",
        uname="观众 B",
        gift_name="辣条",
        quantity=10,
        price=1.0,
        color="#F59E0B",
    ),
    DanmakuEvent(
        room_id="demo",
        connection_id=1,
        kind="guard",
        text="开通 舰长",
        uname="守护者",
        gift_name="舰长",
        price=198.0,
        color="#F43F5E",
    ),
    DanmakuEvent(
        room_id="demo",
        connection_id=1,
        kind="enter",
        text="进入直播间",
        uname="新观众",
        color="#A78BFA",
    ),
):
    demo_video._onDanmakuEvent(event)
demo_video.danmakuModel.flush_pending()
demo_browser = demo_video.ensureTextBrowser()
demo_browser.resize(680, 620)
demo_browser.show()
for _ in range(3):
    app.processEvents()
demo_browser.grab().save(os.path.join(docs_dir, "screenshot-danmaku.png"))
print("saved screenshot-danmaku.png")
demo_browser.hide()
demo_video.danmakuModel.clear()
demo_video.roomID = "0"
demo_video._activeDanmuConnectionId = 0

# 添加直播间面板
addroom = mainWindow.liverPanel.addLiverRoomWidget
addroom.show()
app.processEvents()
addroom.resize(600, 900)
app.processEvents()
addroom.grab().save(os.path.join(docs_dir, "screenshot-addroom.png"))
print("saved screenshot-addroom.png")

# 用户常用浅色主题也走同一顶部 Dock 回归，诊断图写入忽略的 logs/。
addroom.hide()
set_theme(False)
mainWindow.addDockWidget(Qt.TopDockWidgetArea, mainWindow.controlDock)
mainWindow.splitDockWidget(mainWindow.controlDock, mainWindow.cardDock, Qt.Horizontal)
mainWindow.resizeDocks([mainWindow.controlDock, mainWindow.cardDock], [230, 1370], Qt.Horizontal)
mainWindow.resizeDocks([mainWindow.controlDock, mainWindow.cardDock], [175, 175], Qt.Vertical)
for _ in range(3):
    app.processEvents()
assert mainWindow.navigationInterface.geometry().bottom() < mainWindow.cardDock.geometry().top()
assert mainWindow.scrollArea.verticalScrollBar().maximum() > 0
mainWindow.grab().save(os.path.join(ROOT, "logs", "screenshot-top-dock-light.png"))
print("verified light-theme top-dock layout")
set_theme(True)

# 实际执行一次浮动/回停靠，验证功能不只是标志位存在。
mainWindow.cardDock.setFloating(True)
app.processEvents()
assert mainWindow.cardDock.isFloating()
mainWindow.cardDock.setFloating(False)
app.processEvents()
assert not mainWindow.cardDock.isFloating()

# 走完整退出路径（验证 shutdown 不崩溃）。OpenGL 窗口必须在 QApplication
# 仍存活时销毁，否则解释器收尾阶段释放原生上下文可能返回非零退出码。
mainWindow.close()
addroom.deleteLater()
settings.deleteLater()
mainWindow.deleteLater()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
app.processEvents()

# 在 QApplication 仍存活时释放卡片持有的非父子 QThread 包装对象。
card = None
addroom = None
settings = None
global_danmu_panel = None
mainWindow = None
gc.collect()
QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
app.processEvents()
app.quit()

shutil.rmtree(_tmp_root, ignore_errors=True)
print("done")
