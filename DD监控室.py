"""
DD监控室主界面进程 包含对所有子页面的初始化、排版管理
同时卡片和播放窗口的交互需要通过主界面线程通信
以及软件启动和退出后的一些操作
新增全局鼠标坐标跟踪 用于刷新鼠标交互效果
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
from PySide6.QtWidgets import (
    QApplication,
    QDockWidget,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSplashScreen,
    QWidget,
)
from PySide6.QtGui import (
    QAction,
    QCursor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QHideEvent,
    QIntValidator,
    QPixmap,
    QShowEvent,
)
from PySide6.QtCore import QByteArray, QPoint, QSize, QThread, QTimer, QUrl, Qt, Signal
from LayoutPanel import LayoutSettingPanel
from VideoWidget_mpv import VideoWidget, load_mpv_module
from LiverSelect import LiverPanel
from config_manager import ConfigManager, MAX_WINDOWS, WINDOW_CARD_WIDTH, DISPLAY_RATIOS
from bili_credential import normalize_credential_data, build_credential, credential_to_dict
import log  # 本地日志模块（faulthandler 块之后才安全）
from qfluentwidgets_pro import (
    FluentIcon,
    FluentTitleBar,
    Icon,
    LineEdit,
    PushButton as FPushButton,
    PrimaryPushButton as FPrimaryPushButton,
    RoundMenu,
    Slider as FluentSlider,
    SmoothScrollArea,
    ToolButton,
    TransparentToolButton,
)
from qfluentwidgets_pro.qframelesswindow.windows import WindowsFramelessMainWindow
from uikit_bridge import confirm, info, current_color, theme_changed
from bilibili_api import sync
from bilibili_api.exceptions import CredentialNoBiliJctException
from danmu import GlobalDanmuOption
from SettingsDialog import SettingsDialog
from login import LoginDialog
from app_version import APP_NAME, DISPLAY_VERSION, VERSION, RELEASE_DATE, parse_version

# 程序所在路径
application_path = ""


def _translate(context, text, disambig):
    return QApplication.translate(context, text, disambig)


class CredentialRefreshWorker(QThread):
    refreshed = Signal(dict)
    failed = Signal(str)
    skipped = Signal(str)

    def __init__(self, credential_data, sessionData):
        super().__init__()
        self.credential_data = normalize_credential_data(credential_data, sessdata=sessionData)
        self.sessionData = sessionData

    def run(self):
        credential = build_credential(self.credential_data, sessdata=self.sessionData)
        if credential is None:
            self.failed.emit("凭据无效，无法刷新")
            return
        try:
            if sync(credential.check_refresh()):
                sync(credential.refresh())
                self.refreshed.emit(credential_to_dict(credential))
        except CredentialNoBiliJctException:
            # 旧凭据缺 bili_jct 无法续期：不是登录失效，观看/关注列表等读操作不受影响，
            # 重新扫码登录可补齐 bili_jct（login.py 已从 Set-Cookie 捕获完整凭据）。
            self.skipped.emit("凭据缺少 bili_jct，本次跳过续期（不影响观看与关注列表等读操作）")
        except Exception as e:
            logging.exception("[LOGIN] 验证登录异常")
            self.failed.emit(str(e))


class ControlWidget(QWidget):
    heightValue = Signal(int)

    def __init__(self):
        super(ControlWidget, self).__init__()

    def resizeEvent(self, QResizeEvent):
        self.heightValue.emit(self.height())


class ScrollArea(SmoothScrollArea):
    multipleTimes = Signal(int)
    addLiver = Signal()
    clearAll = Signal()

    def __init__(self):
        super(ScrollArea, self).__init__()
        self.multiple = self.width() // WINDOW_CARD_WIDTH
        self.horizontalScrollBar().setVisible(False)

    def sizeHint(self):
        return QSize(100, 90)

    def mouseReleaseEvent(self, QMouseEvent):
        if QMouseEvent.button() == Qt.RightButton:
            # RoundMenu.exec 非阻塞，菜单项用 triggered 信号处理
            menu = RoundMenu()
            addLiver = menu.addAction("添加直播间")
            addLiver.triggered.connect(lambda: self.addLiver.emit())
            menu.addSeparator()  # 添加分割线，防止误操作
            clearAll = menu.addAction("清空")
            clearAll.triggered.connect(lambda: self.clearAll.emit())
            menu.exec(self.mapToGlobal(QMouseEvent.position().toPoint()))

    def wheelEvent(self, QEvent):
        if QEvent.angleDelta().y() < 0:
            value = self.verticalScrollBar().value()
            self.verticalScrollBar().setValue(value + 80)
        elif QEvent.angleDelta().y() > 0:
            value = self.verticalScrollBar().value()
            self.verticalScrollBar().setValue(value - 80)

    def resizeEvent(self, QResizeEvent):
        multiple = self.width() // WINDOW_CARD_WIDTH
        if multiple and multiple != self.multiple:  # 按卡片长度的倍数调整且不为0
            self.multiple = multiple
            self.multipleTimes.emit(multiple)


class DockWidget(QDockWidget):
    def __init__(self, title):
        super(DockWidget, self).__init__()
        self.setWindowTitle(title)
        self.setObjectName(f"dock-{title}")
        self.setFloating(False)
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea | Qt.TopDockWidgetArea)


class StartLiveWindow(QWidget):
    """开播提醒弹窗"""

    def __init__(self):
        super(StartLiveWindow, self).__init__()
        self.setWindowTitle("开播提醒")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.resize(240, 70)
        self.tipLabel = QLabel()
        # 提醒横幅背景/文字取自主题令牌，随明暗主题变化
        self.tipLabel.setStyleSheet(
            f"background-color:{current_color('primary.subtle')};color:{current_color('primary')}"
        )
        self.tipLabel.setFont(QFont("微软雅黑", 15, QFont.Bold))
        layout = QGridLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.addWidget(self.tipLabel)

        self.hideTimer = QTimer(self)
        self.hideTimer.setInterval(10000)
        self.hideTimer.timeout.connect(self.hide)  # 10秒倒计时结束隐藏

    def mousePressEvent(self, QMouseEvent):  # 点击的话就停止倒计时
        self.hideTimer.stop()


class CacheSetting(QWidget):
    """缓存设置窗口"""

    setting = Signal(list)

    def __init__(self):
        super(CacheSetting, self).__init__()
        self.resize(400, 200)
        self.setWindowTitle("缓存设置")
        layout = QGridLayout(self)
        layout.addWidget(QLabel("最大缓存(GB)"), 0, 0, 1, 1)
        self.maxCacheEdit = LineEdit()
        self.maxCacheEdit.setValidator(QIntValidator(1, 9))
        layout.addWidget(self.maxCacheEdit, 0, 1, 1, 3)
        layout.addWidget(QLabel("缓存自动备份至以上路径 (若不填则默认删除)"), 2, 0, 1, 3)
        selectButton = FPushButton("备份路径")
        selectButton.clicked.connect(self.selectCopyPath)
        layout.addWidget(selectButton, 1, 0, 1, 1)
        self.savePathEdit = LineEdit()
        layout.addWidget(self.savePathEdit, 1, 1, 1, 3)
        okButton = FPrimaryPushButton("OK")
        okButton.clicked.connect(self.sendSetting)
        layout.addWidget(okButton, 2, 3, 1, 1)

    def selectCopyPath(self):
        savePath = QFileDialog.getExistingDirectory(self, "选择备份缓存路径", None, QFileDialog.ShowDirsOnly)
        if savePath:
            self.savePathEdit.setText(savePath)

    def sendSetting(self):
        self.setting.emit([self.maxCacheEdit.text(), self.savePathEdit.text()])
        self.hide()


class Version(QWidget):
    """版本说明窗口"""

    def __init__(self):
        super(Version, self).__init__()
        self.resize(350, 220)
        self.setWindowTitle("当前版本")
        layout = QGridLayout(self)
        layout.addWidget(QLabel(f"{APP_NAME} v{DISPLAY_VERSION} ({RELEASE_DATE})"), 0, 0, 1, 2)
        layout.addWidget(QLabel("原作者：神君Channel"), 1, 0, 1, 2)
        layout.addWidget(QLabel("魔改维护：BaoZi_Fly"), 2, 0, 1, 2)
        layout.addWidget(QLabel("特别鸣谢：大锅饭 美东矿业 inkydragon 聪_哥 PR"), 3, 0, 1, 2)
        releases_url = QLabel("")
        releases_url.setOpenExternalLinks(True)
        releases_url.setText(
            _translate(
                "MainWindow",
                '<html><head/><body><p><a href="https://space.bilibili.com/637783">\
<span style=" text-decoration: underline; color:#cccccc;">原作者：https://space.bilibili.com/637783</span></a></p></body></html>',
                None,
            )
        )
        layout.addWidget(releases_url, 1, 1, 1, 2, Qt.AlignRight)
        fork_url = QLabel("")
        fork_url.setOpenExternalLinks(True)
        fork_url.setText(
            _translate(
                "MainWindow",
                '<html><head/><body><p><a href="https://space.bilibili.com/34094740">\
<span style=" text-decoration: underline; color:#cccccc;">魔改：https://space.bilibili.com/34094740</span></a></p></body></html>',
                None,
            )
        )
        layout.addWidget(fork_url, 2, 1, 1, 2, Qt.AlignRight)

        checkButton = FPushButton("检查更新")
        checkButton.setFixedHeight(40)
        checkButton.clicked.connect(self.checkUpdate)
        layout.addWidget(checkButton, 0, 2, 1, 1)

    def checkUpdate(self):
        QDesktopServices.openUrl(QUrl(r"https://gitee.com/zhimingshenjun/DD_Monitor_latest/releases"))


class HotKey(QWidget):
    """热键说明窗口"""

    def __init__(self):
        super(HotKey, self).__init__()
        self.resize(350, 200)
        self.setWindowTitle("快捷键")
        layout = QGridLayout(self)
        layout.addWidget(QLabel("F、f —— 全屏"), 0, 0)
        layout.addWidget(QLabel("H、h —— 隐藏控制条"), 1, 0)
        layout.addWidget(QLabel("M、m、S、s —— 除当前鼠标悬停窗口外全部静音"), 2, 0)
        layout.addWidget(QLabel("1 - 9 —— 聚焦对应窗口"), 3, 0)
        layout.addWidget(QLabel("Ctrl + 1 - 9 —— 加载房间到对应窗口"), 4, 0)
        layout.addWidget(QLabel("Esc —— 退出全屏"), 5, 0)


class CheckDanmmuProvider(QThread):
    """检查弹幕服务器域名解析状态"""

    def __init__(self):
        super(CheckDanmmuProvider, self).__init__()

    def run(self):
        try:
            import dns.resolver

            anwsers = dns.resolver.resolve("broadcastlv.chat.bilibili.com", "A")
            danmu_ip = anwsers[0].to_text()
            logging.info("弹幕IP: %s" % danmu_ip)
        except Exception as e:
            logging.error("解析弹幕域名失败: %s", e)


class MainWindow(WindowsFramelessMainWindow):
    """主窗口（无边框 + Fluent 自绘标题栏）"""

    def __init__(self, cacheFolder, progressBar, progressText):
        super(MainWindow, self).__init__()
        self.versionNumber = parse_version(VERSION)  # tuple 比较，兼容 x.y.z
        self.versionDisplay = DISPLAY_VERSION
        # Fluent 自绘标题栏（图标 + 标题 + 最小化/最大化/关闭），
        # qframelesswindow 提供边缘缩放与拖动；先装标题栏再设标题/图标，
        # 让 FluentTitleBar 的 windowTitleChanged/windowIconChanged 信号生效
        self.setTitleBar(FluentTitleBar(self))
        self.setWindowTitle(f"DD监控室{self.versionDisplay}")
        self.setWindowIcon(Icon(FluentIcon.ROBOT))
        # QMainWindow 的 menuBar 从窗口顶部开始，会盖住 Fluent 标题栏
        # （48px，含窗口控制按钮）；把 QMainWindow 内容区（menuBar/
        # dock/central）整体下移标题栏高度。菜单栏已改为顶部导航按钮
        # （_initNavBar 挂载到 menuWidget 区），无 QMenuBar 悬停问题
        self.setContentsMargins(0, self.titleBar.height(), 0, 0)
        self._initThemeButton()
        self.resize(1600, 900)
        self.maximumToken = True
        self.soloToken = False  # 记录静音除鼠标悬停窗口以外的其他所有窗口的标志位 True就是恢复所有房间声音
        self.cacheFolder = cacheFolder

        # ---- json 配置文件加载 ----
        self.configManager = ConfigManager(application_path, parent=self)
        self.config = self.configManager.load()
        # 应用配置的主题（明/暗）与配色，主界面全局 QSS 由 UIKit 主题驱动
        from uikit_bridge import set_theme, set_accent, set_menu_animation

        set_theme(self.config.get("theme", "dark") == "dark")
        set_accent(self.config.get("accent", "blue"))
        set_menu_animation(self.config.get("menuAnimation", True))
        self.credential = normalize_credential_data(
            self.config.get("credential", {}), sessdata=self.config["sessionData"]
        )
        self.sessionData = self.credential.get("sessdata", "")
        self.config["credential"] = self.credential
        self.config["sessionData"] = self.sessionData
        self.danmuSettingPanel = None

        # ---- 主窗体控件 ----
        mainWidget = QWidget()
        self.setCentralWidget(mainWidget)
        # Grid 布局
        self.mainLayout = QGridLayout(mainWidget)
        self.mainLayout.setSpacing(0)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.layoutSettingPanel = LayoutSettingPanel()
        self.layoutSettingPanel.layoutConfig.connect(self.changeLayout)
        self.version = None
        self.cacheSetting = None
        self.hotKey = None
        self._pay = None  # 延迟创建
        self.startLiveWindow = None
        self.loginDialog = LoginDialog(self)
        # 先连接信号，再触发验证（确保回调到达时信号已就绪）
        self.loginDialog.sessionData.connect(self.updateSessionData)
        self.loginDialog.credentialReady.connect(self.updateCredential)
        self.loginDialog.login.connect(self.updateLogin)
        self.loginDialog.userInfoReady.connect(self.onUserInfoReady)
        # 启动时如果有已保存的 sessionData，静默验证登录状态（不弹窗）
        if any(self.credential.values()):
            self.loginDialog.setSessionData(self.credential.get("sessdata", ""))
        elif self.config["sessionData"]:
            self.loginDialog.setSessionData(self.config["sessionData"])
        self.credentialRefreshTimer = QTimer(self)
        self.credentialRefreshTimer.timeout.connect(self.refreshCredentialIfNeeded)
        self.credentialRefreshTimer.setInterval(6 * 60 * 60 * 1000)
        self.credentialRefreshWorker = None
        if any(self.credential.values()):
            QTimer.singleShot(0, self.refreshCredentialIfNeeded)
            self.credentialRefreshTimer.start()

        # ---- 内嵌/弹出播放器初始化 ----
        self.videoWidgetList = []
        self.popVideoWidgetList = [None] * 16
        progressCounter = 1
        for i in range(16):
            volume = self.config["volume"][i]
            progressText.setText("设置第%s个主层播放器..." % str(i + 1))
            self.videoWidgetList.append(
                VideoWidget(
                    i,
                    volume,
                    cacheFolder,
                    textSetting=self.config["danmu"][i],
                    rollingSetting=self.config["rollingDanmu"],
                    maxCacheSize=self.config["maxCacheSize"],
                    saveCachePath=self.config["saveCachePath"],
                    startWithDanmu=self.config["startWithDanmu"],
                    hardwareDecode=self.config["hardwareDecode"],
                    sessionData=self.config["sessionData"],
                    credential=self.config["credential"],
                )
            )
            progressCounter += 1
            progressBar.setValue(progressCounter)
            self._connectVideoWidget(self.videoWidgetList[i])
            # 不在循环内调 processEvents — 见 login.py thread.wait 注释
            logging.info(f"播放器设置完毕 {i + 1} / 16")
        QApplication.instance().processEvents()  # 刷新启动画面进度（勿用模块级 app 变量）
        # 延迟创建 OpenGL 上下文，避免 16 个同时初始化导致栈溢出
        QTimer.singleShot(0, self.setPlayer)

        self.controlDock = DockWidget("控制条")
        self.controlDock.setFixedWidth(178)
        self.addDockWidget(Qt.TopDockWidgetArea, self.controlDock)
        self.controlWidget = ControlWidget()
        self.controlWidget.heightValue.connect(self.showAddButton)
        self.controlDock.setWidget(self.controlWidget)
        self.controlBarLayout = QGridLayout(self.controlWidget)
        self.globalPlayToken = True
        self.play = ToolButton(FluentIcon.PAUSE, self)
        self.play.setFixedSize(30, 30)
        self.play.setIconSize(QSize(16, 16))
        self.play.setToolTip("全局暂停/播放")
        self.play.clicked.connect(self.globalMediaPlay)
        self.controlBarLayout.addWidget(self.play, 0, 0, 1, 1)
        self.reload = ToolButton(FluentIcon.SYNC, self)
        self.reload.setFixedSize(30, 30)
        self.reload.setIconSize(QSize(16, 16))
        self.reload.setToolTip("全局刷新")
        self.reload.clicked.connect(self.globalMediaReload)
        self.controlBarLayout.addWidget(self.reload, 0, 1, 1, 1)
        self.stop = ToolButton(FluentIcon.CANCEL, self)
        self.stop.setFixedSize(30, 30)
        self.stop.setIconSize(QSize(16, 16))
        self.stop.setToolTip("全局停止")
        self.stop.clicked.connect(self.globalMediaStop)
        self.controlBarLayout.addWidget(self.stop, 0, 2, 1, 1)

        # 全局弹幕设置（Fluent 齿轮图标）
        self.danmuButton = ToolButton(FluentIcon.SETTING, self)
        self.danmuButton.setFixedSize(30, 30)
        self.danmuButton.setIconSize(QSize(16, 16))
        self.danmuButton.setToolTip("弹幕设置")
        self.danmuButton.clicked.connect(self.openGlobalDanmuSetting)
        theme_changed().connect(self._applyDanmuIconTheme)
        self.controlBarLayout.addWidget(self.danmuButton, 0, 3, 1, 1)

        # 全局静音
        self.globalMuteToken = False
        self.volumeButton = ToolButton(FluentIcon.VOLUME, self)
        self.volumeButton.setFixedSize(30, 30)
        self.volumeButton.setIconSize(QSize(16, 16))
        self.volumeButton.setToolTip("全局静音")
        self.volumeButton.clicked.connect(self.globalMediaMute)
        self.controlBarLayout.addWidget(self.volumeButton, 1, 0, 1, 1)
        # 全局音量滑条
        self.slider = FluentSlider(Qt.Horizontal)
        self.slider.setValue(self.config["globalVolume"])
        self.slider.valueChanged.connect(self.globalSetVolume)
        self.controlBarLayout.addWidget(self.slider, 1, 1, 1, 3)
        progressText.setText("设置播放器控制...")

        # 添加主播按钮
        # UIKit 虚线按钮；内联 QSS 覆盖 UIKit 默认的 md 高度（32px），
        # 保持 160x90 的拖放区尺寸与虚线描边
        self.addButton = FPushButton("+")
        self.addButton.setFixedSize(160, 90)
        self._applyAddButtonTheme()
        theme_changed().connect(self._applyAddButtonTheme)
        self.addButton.setFont(QFont("Arial", 24, QFont.Bold))
        progressText.setText("设置添加控制...")
        self.controlBarLayout.addWidget(self.addButton, 2, 0, 1, 4)
        progressText.setText("设置全局控制...")

        self.scrollArea = ScrollArea()
        self.scrollArea.setStyleSheet("border-width:0px")
        # 关键：让卡片面板宽度跟随视口宽度，FlowLayout 才能按行横排
        # （widgetResizable=False 时面板塌缩为最小宽度，卡片竖排）
        self.scrollArea.setWidgetResizable(True)
        # self.scrollArea.setMinimumHeight(111)
        self.cardDock = DockWidget("卡片槽")
        self.cardDock.setWidget(self.scrollArea)
        self.addDockWidget(Qt.TopDockWidgetArea, self.cardDock)

        # self.controlBarLayout.addWidget(self.scrollArea, 3, 0, 1, 5)

        # 主播添加窗口
        self.liverPanel = LiverPanel(self.config["roomid"], application_path)
        self.liverPanel.setSessionData(self.sessionData)
        if any(self.credential.values()):
            self.liverPanel.setCredential(self.credential)
        # self.liverPanel.addLiverRoomWidget.getHotLiver.start()
        self.liverPanel.addToWindow.connect(self.addCoverToPlayer)
        self.liverPanel.dumpConfig.connect(self._onDumpRoomConfig)  # 保存房间配置
        self.liverPanel.refreshIDList.connect(self.refreshPlayerStatus)  # 刷新播放器
        self.liverPanel.startLiveList.connect(self.startLiveTip)  # 开播提醒
        self.scrollArea.setWidget(self.liverPanel)
        self.scrollArea.multipleTimes.connect(self.changeLiverPanelLayout)
        self.scrollArea.addLiver.connect(self.liverPanel.openLiverRoomPanel)
        self.scrollArea.clearAll.connect(self.clearLiverPanel)
        self.addButton.clicked.connect(self.liverPanel.openLiverRoomPanel)
        self.liverPanel.updatePlayingStatus(self.config["player"])
        progressText.setText("设置主播选择控制...")

        # ---- 菜单设置（RoundMenu 独立构建，导航按钮在 _initNavBar 挂载）----
        self.optionMenu = RoundMenu("设置", self)
        self.controlBarLayoutToken = self.config["control"]
        settingsAction = QAction("打开设置面板...", self, triggered=self.openSettingsDialog)
        self.optionMenu.addAction(settingsAction)
        self.optionMenu.addSeparator()
        layoutConfigAction = QAction("布局方式", self, triggered=self.openLayoutSetting)
        self.optionMenu.addAction(layoutConfigAction)
        globalQualityMenu = self.optionMenu.addMenu("全局画质 ►")
        originQualityAction = QAction("原画", self, triggered=lambda: self.globalQuality(10000))
        globalQualityMenu.addAction(originQualityAction)
        bluerayQualityAction = QAction("蓝光", self, triggered=lambda: self.globalQuality(400))
        globalQualityMenu.addAction(bluerayQualityAction)
        highQualityAction = QAction("超清", self, triggered=lambda: self.globalQuality(250))
        globalQualityMenu.addAction(highQualityAction)
        lowQualityAction = QAction("流畅", self, triggered=lambda: self.globalQuality(80))
        globalQualityMenu.addAction(lowQualityAction)
        onlyAudio = QAction("仅播声音", self, triggered=lambda: self.globalQuality(-1))
        globalQualityMenu.addAction(onlyAudio)
        globalAudioMenu = self.optionMenu.addMenu("全局音效 ►")
        audioOriginAction = QAction("原始音效", self, triggered=lambda: self.globalAudioChannel(0))
        globalAudioMenu.addAction(audioOriginAction)
        audioDolbysAction = QAction("杜比音效", self, triggered=lambda: self.globalAudioChannel(5))
        globalAudioMenu.addAction(audioDolbysAction)
        hardDecodeMenu = self.optionMenu.addMenu("解码方案 ►")
        hardDecodeAction = QAction("硬解", self, triggered=lambda: self.setDecode(True))
        hardDecodeMenu.addAction(hardDecodeAction)
        softDecodeAction = QAction("软解", self, triggered=lambda: self.setDecode(False))
        hardDecodeMenu.addAction(softDecodeAction)
        startLiveSetting = self.optionMenu.addMenu("开播提醒 ►")
        enableStartLive = QAction("打开", self, triggered=lambda: self.setStartLive(True))
        startLiveSetting.addAction(enableStartLive)
        disableStartLive = QAction("关闭", self, triggered=lambda: self.setStartLive(False))
        startLiveSetting.addAction(disableStartLive)
        cacheSizeSetting = QAction("缓存设置", self, triggered=self.openCacheSetting)
        self.optionMenu.addAction(cacheSizeSetting)
        danmuSettingAction = QAction("弹幕设置", self, triggered=self.openGlobalDanmuSetting)
        self.optionMenu.addAction(danmuSettingAction)
        controlPanelAction = QAction("显示 / 隐藏控制条(H)", self, triggered=self.openControlPanel)
        self.optionMenu.addAction(controlPanelAction)
        self.fullScreenAction = QAction("全屏(F) / 退出(Esc)", self, triggered=self.fullScreen)
        self.optionMenu.addAction(self.fullScreenAction)
        exportConfig = QAction("导出预设", self, triggered=self.exportConfig)
        self.optionMenu.addAction(exportConfig)
        importConfig = QAction("导入预设", self, triggered=self.importConfig)
        self.optionMenu.addAction(importConfig)
        progressText.setText("设置选项菜单...")

        self.versionMenu = RoundMenu("帮助", self)
        bilibiliAction = QAction("B站视频", self, triggered=self.openBilibili)
        self.versionMenu.addAction(bilibiliAction)
        hotKeyAction = QAction("快捷键", self, triggered=self.openHotKey)
        self.versionMenu.addAction(hotKeyAction)
        versionAction = QAction("检查版本", self, triggered=self.openVersion)
        self.versionMenu.addAction(versionAction)
        otherDDMenu = self.versionMenu.addMenu("其他DD系列工具 ►")
        DDSubtitleAction = QAction("DD烤肉机", self, triggered=self.openDDSubtitle)
        otherDDMenu.addAction(DDSubtitleAction)
        DDThanksAction = QAction("DD答谢机", self, triggered=self.openDDThanks)
        otherDDMenu.addAction(DDThanksAction)
        progressText.setText("设置帮助菜单...")

        self.payMenu = RoundMenu("开源和投喂", self)
        githubAction = QAction("GitHub", self, triggered=self.openGithub)
        self.payMenu.addAction(githubAction)
        feedAction = QAction("投喂作者", self, triggered=self.openFeed)
        self.payMenu.addAction(feedAction)
        progressText.setText("设置关于菜单...")

        self.loginMenu = RoundMenu("B站账号", self)
        self._rebuildLoginMenu()
        self._initNavBar()

        # 鼠标和计时器
        self.oldMousePos = QPoint(0, 0)  # 初始化鼠标坐标
        self.hideMouseCnt = 90
        self.mouseTrackTimer = QTimer(self)
        self.mouseTrackTimer.timeout.connect(self.checkMousePos)
        self.mouseTrackTimer.start(200)  # 0.2s检测一次（降低开销）
        # moveEvent 防抖：停止移动后 200ms 再更新弹幕基准视口
        self._viewport_debounce = QTimer(self)
        self._viewport_debounce.setSingleShot(True)
        self._viewport_debounce.setInterval(200)
        self._viewport_debounce.timeout.connect(self._onViewportDebounced)
        progressText.setText("设置UI...")
        self.checkDanmmuProvider = CheckDanmmuProvider()
        self.checkDanmmuProvider.start()
        self.loadDockLayout()
        logging.info("UI构造完毕")

        if self.config["checkUpdate"]:
            self.updateChecker()

    def setPlayer(self):
        for index, layoutConfig in enumerate(self.config["layout"]):
            roomID = self.config["player"][index]
            videoWidget = self.videoWidgetList[index]
            videoWidget.roomID = str(roomID)  # 转一下防止格式出错
            y, x, h, w = layoutConfig
            self.mainLayout.addWidget(videoWidget, y, x, h, w)
            self.videoWidgetList[index].show()
        self.videoIndex = 0
        # 并行启动所有已配置房间的信息获取，替代串行 100ms timer
        for vw in self.videoWidgetList:
            if vw.roomID != "0":
                vw.mediaReload()
            else:
                vw.playerRestart()

    def _connectVideoWidget(self, videoWidget):
        videoWidget.mutedChanged.connect(self.mutedChanged)
        videoWidget.volumeChanged.connect(self.volumeChanged)
        videoWidget.addMedia.connect(self.addMedia)
        videoWidget.deleteMedia.connect(self.deleteMedia)
        videoWidget.exchangeMedia.connect(self.exchangeMedia)
        videoWidget.changeQuality.connect(self.setQuality)
        videoWidget.setDanmu.connect(self.setDanmu)
        videoWidget.popWindow.connect(self.popWindow)
        videoWidget.hideBarKey.connect(self.openControlPanel)
        videoWidget.fullScreenKey.connect(self.fullScreen)
        videoWidget.muteExceptKey.connect(self.muteExcept)
        videoWidget.mediaMute(self.config["muted"][videoWidget.id % 16], emit=False)
        videoWidget.slider.setValue(self.config["volume"][videoWidget.id % 16])
        videoWidget.quality = self.config["quality"][videoWidget.id % 16]
        videoWidget.audioChannel = self.config["audioChannel"][videoWidget.id % 16]
        videoWidget.setDanmakuBaseViewport(self._resolveDanmakuBaseViewport())
        if videoWidget.top:
            videoWidget.closePopWindow.connect(self.closePopWindow)

    def _iterVideoWidgets(self, include_popups=False):
        for videoWidget in self.videoWidgetList:
            yield videoWidget
        if include_popups:
            for videoWidget in self.popVideoWidgetList:
                if videoWidget is not None:
                    yield videoWidget

    def _getOrCreatePopVideoWidget(self, index):
        videoWidget = self.popVideoWidgetList[index]
        if videoWidget is not None:
            return videoWidget

        volume = self.config["volume"][index]
        videoWidget = VideoWidget(
            index + 16,
            volume,
            self.cacheFolder,
            True,
            "悬浮窗",
            [1280, 720],
            textSetting=self.config["danmu"][index],
            rollingSetting=self.config["rollingDanmu"],
            maxCacheSize=self.config["maxCacheSize"],
            saveCachePath=self.config["saveCachePath"],
            startWithDanmu=self.config["startWithDanmu"],
            hardwareDecode=self.config["hardwareDecode"],
            sessionData=self.config["sessionData"],
            credential=self.config["credential"],
        )
        self._connectVideoWidget(videoWidget)
        self.popVideoWidgetList[index] = videoWidget
        return videoWidget

    def _getCacheSetting(self):
        if self.cacheSetting is None:
            self.cacheSetting = CacheSetting()
            self.cacheSetting.maxCacheEdit.setText(str(self.config["maxCacheSize"] // 1024000))
            self.cacheSetting.savePathEdit.setText(self.config["saveCachePath"])
            self.cacheSetting.setting.connect(self.setCache)
        return self.cacheSetting

    def _getVersionWindow(self):
        if self.version is None:
            self.version = Version()
        return self.version

    def _getHotKeyWindow(self):
        if self.hotKey is None:
            self.hotKey = HotKey()
        return self.hotKey

    def _getStartLiveWindow(self):
        if self.startLiveWindow is None:
            self.startLiveWindow = StartLiveWindow()
        return self.startLiveWindow

    def addMedia(self, info):  # 窗口 房号
        id, roomID = info
        if not (0 <= id < MAX_WINDOWS):  # 防御：悬浮窗(id=16..31)的播放记录不写入主窗口 config
            return
        self.config["player"][id] = roomID
        self.liverPanel.updatePlayingStatus(self.config["player"])
        self.configManager.save()

    def deleteMedia(self, id):
        if not (0 <= id < MAX_WINDOWS):  # 防御：悬浮窗 id 越界时直接忽略
            return
        self.config["player"][id] = 0
        self.liverPanel.updatePlayingStatus(self.config["player"])
        self.configManager.save()

    def exchangeMedia(self, info):  # 交换播放窗口的函数
        fromID, fromRoomID, toID, toRoomID = info  # 交换数据
        # 防御：悬浮窗(id=16..31)的拖放交换不涉及主窗口列表，直接忽略
        if not (0 <= fromID < MAX_WINDOWS) or not (0 <= toID < MAX_WINDOWS):
            logging.warning("exchangeMedia 忽略越界 id: from=%s to=%s", fromID, toID)
            return
        # 待交换的两个控件
        fromVideo, toVideo = self.videoWidgetList[fromID], self.videoWidgetList[toID]
        fromVideo.id, toVideo.id = toID, fromID  # 交换id
        fromVideo.topLabel.setText(fromVideo.topLabel.text().replace("窗口%s" % (fromID + 1), "窗口%s" % (toID + 1)))
        toVideo.topLabel.setText(toVideo.topLabel.text().replace("窗口%s" % (toID + 1), "窗口%s" % (fromID + 1)))

        fromWidth, fromHeight = fromVideo.width(), fromVideo.height()
        toWidth, toHeight = toVideo.width(), toVideo.height()
        if 3 < abs(fromWidth - toWidth) or 3 < abs(
            fromHeight - toHeight
        ):  # 有主次关系的播放窗交换同时交换音量和弹幕设置
            fromMuted = 2 if fromVideo.get_mute() else 1
            toMuted = 2 if toVideo.get_mute() else 1
            fromVolume, toVolume = fromVideo.get_volume(), toVideo.get_volume()
            fromVideo.mediaMute(toMuted)  # 交换静音设置
            fromVideo.setVolume(toVolume)  # 交换音量
            toVideo.mediaMute(fromMuted)
            toVideo.setVolume(fromVolume)

            fromVideo.textSetting, toVideo.textSetting = toVideo.textSetting, fromVideo.textSetting  # 交换弹幕设置
            for videoWidget in [fromVideo, toVideo]:
                videoWidget.horiPercent = DISPLAY_RATIOS[videoWidget.textSetting[2]]
                videoWidget.vertPercent = DISPLAY_RATIOS[videoWidget.textSetting[3]]
                videoWidget.filters = videoWidget.textSetting[5].split(" ")
                videoWidget.applyDanmuSettings()

        # 交换控件列表
        self.videoWidgetList[fromID], self.videoWidgetList[toID] = toVideo, fromVideo
        self.config["player"][toID] = fromRoomID  # 记录config
        self.config["player"][fromID] = toRoomID
        self.configManager.save()
        # self.changeLayout(self.config['layout'])  # 刷新layout
        # 交换前保存弹幕机归一化坐标（基于旧窗口尺寸；addWidget 触发的 resizeEvent 会用旧绝对偏移重算比例，故必须提前捕获）
        danmuRatios = {}
        for videoWidget in (fromVideo, toVideo):
            if videoWidget.textBrowser is not None:
                danmuRatios[id(videoWidget)] = (videoWidget.deltaX, videoWidget.deltaY)

        # 用新的方法直接交换两个窗口
        fromLayout, toLayout = self.config["layout"][fromID], self.config["layout"][toID]
        y, x, h, w = fromLayout
        self.mainLayout.addWidget(toVideo, y, x, h, w)
        y, x, h, w = toLayout
        self.mainLayout.addWidget(fromVideo, y, x, h, w)

        # 强制同步重新布局，确保下面按比例重算时读到交换后的新窗口尺寸
        self.mainLayout.activate()

        # 弹幕机坐标按比例重算：窗口交换后尺寸可能不同，保持弹幕机相对视频区域的位置不变
        for videoWidget in (fromVideo, toVideo):
            savedRatio = danmuRatios.get(id(videoWidget))
            if savedRatio is None:
                continue
            videoPos = videoWidget.mapToGlobal(videoWidget.videoFrame.pos())
            target = QPoint(
                videoPos.x() + round(savedRatio[0] * videoWidget.width()),
                videoPos.y() + round(savedRatio[1] * videoWidget.height()),
            )
            videoWidget.moveTextBrowser(target)  # 重定位 + 边界钳制 + 刷新 textPosDelta/deltaX/deltaY

    def clearLiverPanel(self):  # 清空卡片槽
        confirm(
            self, "清空卡片槽", "注意：是否要清空卡片槽？",
            on_result=lambda ok: self.liverPanel.deleteAll() if ok else None,
            ok_text="是", cancel_text="否",
        )

    def setDanmu(self):
        self.configManager.save()

    def _resolveDanmakuBaseViewport(self):
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return QSize(1920, 1080)
        geometry = screen.geometry()
        return QSize(max(geometry.width(), 1), max(geometry.height(), 1))

    def _applyDanmakuBaseViewport(self):
        viewport = self._resolveDanmakuBaseViewport()
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setDanmakuBaseViewport(viewport)

    def openGlobalDanmuSetting(self):
        """打开全局弹幕设置（缓存复用，避免反复创建/销毁顶层窗口）"""
        if not hasattr(self, "_globalDanmuPanel") or self._globalDanmuPanel is None:
            panel = GlobalDanmuOption(self.config["danmu"][0], self.config["rollingDanmu"])
            panel.setAttribute(Qt.WA_DeleteOnClose)
            panel.syncBrowserSetting(self.config["danmu"][0])
            panel.syncRollingSetting(self.config["rollingDanmu"])
            # 连接信号
            browser = panel.browserOptionWidget
            rolling = panel.rollingOptionWidget
            browser.opacitySlider.sliderValue.connect(self.setGlobalDanmuOpacity)
            browser.horizontalCombobox.currentIndexChanged.connect(self.setGlobalHorizontalPercent)
            browser.verticalCombobox.currentIndexChanged.connect(self.setGlobalVerticalPercent)
            browser.translateCombobox.currentIndexChanged.connect(self.setGlobalTranslateBrowser)
            browser.showEnterRoom.currentIndexChanged.connect(self.setGlobalShowEnterRoom)
            browser.translateFitler.textChanged.connect(self.setGlobalTranslateFilter)
            browser.fontSizeCombox.currentIndexChanged.connect(self.setGlobalFontSize)
            rolling.opacitySlider.sliderValue.connect(self.setGlobalRollingDanmuOpacity)
            rolling.displayAreaCombobox.currentIndexChanged.connect(self.setGlobalRollingDanmuDisplayArea)
            rolling.fontSizeCombox.currentIndexChanged.connect(self.setGlobalRollingDanmuFontSize)
            rolling.fontFamilyCombobox.currentTextChanged.connect(self.setGlobalRollingDanmuFontFamily)
            rolling.speedSlider.valueChanged.connect(self.setGlobalRollingDanmuSpeed)
            rolling.strokeWidthSlider.valueChanged.connect(self.setGlobalRollingDanmuStrokeWidth)
            rolling.shadowEnabledCheckBox.toggled.connect(self.setGlobalRollingDanmuShadowEnabled)
            rolling.shadowStrengthSlider.valueChanged.connect(self.setGlobalRollingDanmuShadowStrength)
            rolling.topEnabledCheckBox.toggled.connect(self.setGlobalRollingDanmuTopEnabled)
            rolling.bottomEnabledCheckBox.toggled.connect(self.setGlobalRollingDanmuBottomEnabled)
            panel.destroyed.connect(lambda: setattr(self, "_globalDanmuPanel", None))
            self._globalDanmuPanel = panel
        self._globalDanmuPanel.show()
        self._globalDanmuPanel.raise_()
        self._globalDanmuPanel.activateWindow()

    def _applyDanmuIconTheme(self, dark=None):
        """"弹幕设置" 按钮图标用 Fluent 设置图标，随全局明暗主题自动适配。"""
        self.danmuButton.setIcon(Icon(FluentIcon.SETTING))

    def _applyAddButtonTheme(self, dark=None):
        """"+" 添加主播按钮：虚线描边取主题令牌，随全局明暗主题刷新。"""
        border = current_color("text.tertiary")
        hover = current_color("primary")
        self.addButton.setStyleSheet(
            f'background-color:transparent;'
            f'border:3px dotted {border};border-radius:8px;color:{border};'
            f'min-height:84px;max-height:84px;'
            f'QPushButton:hover{{border-color:{hover};color:{hover};}}'
        )

    def showAddButton(self, height):
        # 阈值 165：控制条内容（两行按钮 + 90px 添加按钮 + 边距 ≈ 160）
        # 高度不足时才隐藏；原阈值 181 太敏感，布局微调（±1px）就误藏
        if height < 165:
            self.addButton.hide()
        else:
            self.addButton.show()

    def setTranslator(self, info):
        id, token = info  # 窗口 同传显示布尔值
        if not (0 <= id < MAX_WINDOWS):  # 防御：悬浮窗(id=16..31)设置不写入主窗口 config
            return
        self.config["translator"][id] = token
        self.configManager.save()

    def setQuality(self, info):
        id, quality = info  # 窗口 画质
        if not (0 <= id < MAX_WINDOWS):
            return
        self.config["quality"][id] = quality
        self.configManager.save()

    def setAudioChannel(self, info):
        id, audioChannel = info  # 窗口 音效
        if not (0 <= id < MAX_WINDOWS):
            return
        self.config["audioChannel"][id] = audioChannel
        self.configManager.save()

    def popWindow(self, info):  # 悬浮窗播放
        id, roomID, quality, showMax, startWithDanmu = info
        logging.info("%s 进入悬浮窗模式, 弹幕?: %s" % (roomID, startWithDanmu))
        pop_video_widget = self._getOrCreatePopVideoWidget(id)
        pop_video_widget.roomID = roomID
        pop_video_widget.quality = quality
        pop_video_widget.resize(1280, 720)
        pop_video_widget.show()
        pop_video_widget.setDanmakuBaseViewport(self._resolveDanmakuBaseViewport())
        if startWithDanmu:
            pop_video_widget.showDanmu()
        if showMax:
            pop_video_widget.showMaximized()
        pop_video_widget.mediaReload()

    def mutedChanged(self, mutedInfo):
        id, muted = mutedInfo
        if not (0 <= id < MAX_WINDOWS):  # 防御：悬浮窗音量操作不写入主窗口 config
            return
        token = 2 if muted else 1
        self.config["muted"][id] = token

    def volumeChanged(self, volumeInfo):
        id, value = volumeInfo
        if not (0 <= id < MAX_WINDOWS):
            return
        self.config["volume"][id] = value

    def globalMediaPlay(self):
        if self.globalPlayToken:
            force = 1
            self.play.setIcon(Icon(FluentIcon.PLAY))
        else:
            force = 2
            self.play.setIcon(Icon(FluentIcon.PAUSE))
        self.globalPlayToken = not self.globalPlayToken
        for videoWidget in self.videoWidgetList:
            videoWidget.mediaPlay(force, setUserPause=True)

    def globalMediaReload(self):
        for videoWidget in self.videoWidgetList:
            if not videoWidget.isHidden():
                videoWidget.mediaReload()

    def globalMediaMute(self):
        if self.globalMuteToken:
            force = 1
            self.volumeButton.setIcon(Icon(FluentIcon.VOLUME))
        else:
            force = 2
            self.volumeButton.setIcon(Icon(FluentIcon.MUTE))
        self.globalMuteToken = not self.globalMuteToken
        for videoWidget in self.videoWidgetList:
            videoWidget.mediaMute(force)
        self.config["muted"] = [force] * 16

    def globalSetVolume(self, value):
        for videoWidget in self.videoWidgetList:
            videoWidget.set_volume_direct(int(value * videoWidget.volumeAmplify))
            videoWidget.volume = value
            videoWidget.slider.setValue(value)
        self.config["volume"] = [value] * 16
        self.config["globalVolume"] = value

    def globalMediaStop(self):
        for videoWidget in self.videoWidgetList:
            videoWidget.mediaStop()

    def setGlobalDanmuOpacity(self, value):
        if value < 7:
            value = 7  # 最小透明度
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setDanmuOpacity(value)
        self.configManager.save()

    def setGlobalHorizontalPercent(self, index):  # 设置弹幕框水平宽度
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setHorizontalPercent(index)
        self.configManager.save()

    def setGlobalVerticalPercent(self, index):  # 设置弹幕框垂直高度
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setVerticalPercent(index)
        self.configManager.save()

    def setGlobalTranslateBrowser(self, index):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setTranslateBrowser(index)
        self.configManager.save()

    def setGlobalShowEnterRoom(self, index):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setMsgsBrowser(index)
        self.configManager.save()

    def setGlobalTranslateFilter(self, filterWords):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setTranslateFilter(filterWords)
        self.configManager.save()

    def setGlobalFontSize(self, index):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setFontSize(index)
        self.configManager.save()

    def setGlobalRollingDanmuOpacity(self, value):
        self.config["rollingDanmu"]["opacity"] = max(7, int(value))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuOpacity(value, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuDisplayArea(self, index):
        self.config["rollingDanmu"]["display_area"] = max(0, min(int(index), 9))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuDisplayArea(index, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuFontSize(self, index):
        self.config["rollingDanmu"]["font_size"] = max(0, min(int(index), 20))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuFontSize(index, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuFontFamily(self, family):
        family = str(family).strip() or "Microsoft YaHei"
        self.config["rollingDanmu"]["font_family"] = family
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuFontFamily(family, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuSpeed(self, value):
        self.config["rollingDanmu"]["speed_percent"] = max(50, min(int(value), 200))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuSpeed(value, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuStrokeWidth(self, value):
        self.config["rollingDanmu"]["stroke_width"] = max(0, min(int(value), 60))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuStrokeWidth(value, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuShadowEnabled(self, enabled):
        self.config["rollingDanmu"]["shadow_enabled"] = bool(enabled)
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuShadowEnabled(enabled, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuShadowStrength(self, value):
        self.config["rollingDanmu"]["shadow_strength"] = max(0, min(int(value), 100))
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuShadowStrength(value, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuTopEnabled(self, enabled):
        self.config["rollingDanmu"]["top_enabled"] = bool(enabled)
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuTopEnabled(enabled, emit_signal=False)
        self.configManager.save()

    def setGlobalRollingDanmuBottomEnabled(self, enabled):
        self.config["rollingDanmu"]["bottom_enabled"] = bool(enabled)
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.setRollingDanmuBottomEnabled(enabled, emit_signal=False)
        self.configManager.save()

    def globalQuality(self, quality):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            if not videoWidget.isHidden():  # 窗口没有被隐藏
                videoWidget.quality = quality
                videoWidget.mediaReload()
        self.config["quality"] = [quality] * 16
        self.configManager.save()

    def globalAudioChannel(self, audioChannel):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.set_audio_channel(audioChannel)
        self.config["audioChannel"] = [audioChannel] * 16
        self.configManager.save()

    def setDecode(self, hardwareDecodeToken):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.hardwareDecode = hardwareDecodeToken
        self.globalMediaReload()
        self.config["hardwareDecode"] = hardwareDecodeToken
        self.configManager.save()

    def setStartLive(self, token):
        self.config["showStartLive"] = token
        self.configManager.save()

    def openControlPanel(self):
        if self.controlDock.isHidden() and self.cardDock.isHidden():
            self.controlDock.show()
            self.cardDock.show()
            self.optionMenu.menuAction().setVisible(True)
            self.versionMenu.menuAction().setVisible(True)
            self.payMenu.menuAction().setVisible(True)
        else:
            self.controlDock.hide()
            self.cardDock.hide()
            self.optionMenu.menuAction().setVisible(False)
            self.versionMenu.menuAction().setVisible(False)
            self.payMenu.menuAction().setVisible(False)
        self.controlBarLayoutToken = self.controlDock.isHidden()

    def openVersion(self):
        version_window = self._getVersionWindow()
        version_window.hide()
        version_window.show()

    def openSettingsDialog(self):
        """打开统一设置面板（非模态，缓存复用）"""
        if not hasattr(self, "_settingsDialog") or self._settingsDialog is None:
            self._settingsDialog = SettingsDialog(
                self,
                self.config,
                self.configManager,
                danmu_panel_fn=self.openGlobalDanmuSetting,
                layout_panel_fn=self.openLayoutSetting,
            )
            self._settingsDialog.setAttribute(Qt.WA_DeleteOnClose)
            self._settingsDialog.destroyed.connect(lambda: setattr(self, "_settingsDialog", None))
        self._settingsDialog.show()
        self._settingsDialog.raise_()
        self._settingsDialog.activateWindow()

    def openGithub(self):
        QDesktopServices.openUrl(QUrl(r"https://github.com/BaoZiFly-233/DD_Monitor"))

    def openBilibili(self):
        QDesktopServices.openUrl(QUrl(r"https://www.bilibili.com/video/BV14v411s7WE"))

    def openDDSubtitle(self):
        QDesktopServices.openUrl(QUrl(r"https://www.bilibili.com/video/BV1p5411b7o7"))

    def openDDThanks(self):
        QDesktopServices.openUrl(QUrl(r"https://www.bilibili.com/video/BV1Di4y1L7T2"))

    def openCacheSetting(self):
        cache_setting = self._getCacheSetting()
        cache_setting.hide()
        cache_setting.show()

    def openLoginPage(self):
        self.loginDialog.show()

    def updateSessionData(self, sessionData):
        logging.info(f"[LOGIN] updateSessionData: len={len(sessionData)}")
        if not sessionData:
            import traceback

            logging.warning("[LOGIN] *** sessionData 被清空！调用栈: ***\n" + "".join(traceback.format_stack()))
        self.sessionData = sessionData
        self.config["sessionData"] = sessionData
        self.credential = normalize_credential_data(self.config.get("credential", {}), sessdata=sessionData)
        self.config["credential"] = self.credential
        if not sessionData:
            self.config["loginUserInfo"] = {}
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            if hasattr(videoWidget, "applyCredentialContext"):
                videoWidget.applyCredentialContext(sessionData=sessionData)
            else:
                videoWidget.sessionData = sessionData
        self.liverPanel.setSessionData(sessionData)
        self.configManager.save()
        if sessionData:
            self.globalMediaReload()

    def updateCredential(self, credential):
        self.credential = normalize_credential_data(credential)
        self.config["credential"] = self.credential
        # 防御：传入的 credential 若未携带 sessdata（如扫码 URL 无 SESSDATA 参数），
        # 保留现有 sessionData，避免覆盖清空导致菜单退回"扫码登录"、播放失效
        sessdata = self.credential.get("sessdata", "") or self.sessionData or self.config.get("sessionData", "")
        self.sessionData = sessdata
        self.config["sessionData"] = sessdata
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            if hasattr(videoWidget, "applyCredentialContext"):
                videoWidget.applyCredentialContext(
                    sessionData=self.sessionData,
                    credential=self.credential,
                )
            else:
                if hasattr(videoWidget, "credential"):
                    videoWidget.credential = self.credential
                videoWidget.sessionData = self.sessionData
        if hasattr(self.liverPanel, "setCredential"):
            self.liverPanel.setCredential(self.credential)
        if any(self.credential.values()):
            self.credentialRefreshTimer.start()
        else:
            self.credentialRefreshTimer.stop()
        self.configManager.save()

    def refreshCredentialIfNeeded(self):
        if self.credentialRefreshWorker is not None and self.credentialRefreshWorker.isRunning():
            logging.info("[LOGIN] 凭据刷新任务已在运行，跳过")
            return
        self.credentialRefreshWorker = CredentialRefreshWorker(self.credential, self.sessionData)
        self.credentialRefreshWorker.refreshed.connect(self._onCredentialRefreshed)
        self.credentialRefreshWorker.failed.connect(self._onCredentialRefreshFailed)
        self.credentialRefreshWorker.skipped.connect(self._onCredentialRefreshSkipped)
        self.credentialRefreshWorker.finished.connect(self._onCredentialRefreshFinished)
        self.credentialRefreshWorker.start()

    def _onCredentialRefreshed(self, refreshed):
        logging.info("[LOGIN] 凭据刷新成功")
        self.updateCredential(refreshed)
        self.loginDialog.setSessionData(refreshed.get("sessdata", ""))

    def _onCredentialRefreshFailed(self, error):
        logging.warning(f"[LOGIN] 凭据刷新失败: {error}")

    def _onCredentialRefreshSkipped(self, reason):
        # 仅缺 bili_jct 时跳过续期，属正常情况而非错误：读操作不受影响
        logging.info("[LOGIN] 凭据续期跳过（非错误）: %s", reason)

    def _onCredentialRefreshFinished(self):
        if self.credentialRefreshWorker is not None:
            self.credentialRefreshWorker.deleteLater()
            self.credentialRefreshWorker = None

    def updateLogin(self, login):
        if not login:
            self.setWindowTitle(f"DD监控室{self.versionDisplay} - 未登录")
            # 登出：清除 sessionData 与缓存的用户信息
            self.config["sessionData"] = ""
            self.config["credential"] = {}
            self.config["loginUserInfo"] = {}
            for videoWidget in self._iterVideoWidgets(include_popups=True):
                if hasattr(videoWidget, "applyCredentialContext"):
                    videoWidget.applyCredentialContext(sessionData="", credential={})
                else:
                    videoWidget.sessionData = ""
                    if hasattr(videoWidget, "credential"):
                        videoWidget.credential = {}
            self.configManager.save()
            self._rebuildLoginMenu()
        else:
            self.setWindowTitle(f"DD监控室{self.versionDisplay} - 已登录")
            self._rebuildLoginMenu()

    # ================================================================
    # 「B站账号」菜单 — 登录入口完全收敛到菜单栏
    # ================================================================

    def _addLoginInfoAction(self, text):
        """以不可交互的菜单项展示登录信息（UID/账号名）

        RoundMenu 是自绘菜单（QListWidget），QWidgetAction 不会渲染；
        用 addWidget(selectable=False)：不可点击、颜色保持正常
        （disabled 的 QAction 会呈灰色，用户误以为登录异常）。
        """
        label = QLabel(text)
        label.setContentsMargins(8, 2, 8, 2)
        label.setFixedHeight(24)  # 紧凑行高，避免信息项撑高整个菜单
        # 信息项撑满标准菜单宽度（登录信息是整行展示，文字宽会让菜单
        # 显得窄、右侧大片空白）
        label.setMinimumWidth(160)
        label.setStyleSheet("background: transparent;")
        self.loginMenu.addWidget(label, selectable=False)

    def _rebuildLoginMenu(self):
        """根据登录状态重建「B站账号」菜单

        未登录：扫码登录…
        已登录（验证中）：占位提示 + 退出登录
        已登录：账号名 / UID / 打开个人空间 / 切换账号 / 退出登录
        """
        self.loginMenu.clear()
        info = self.config.get("loginUserInfo", {})
        uname = info.get("uname", "")
        uid = info.get("uid", "")
        if uname and self.config.get("sessionData"):
            self._addLoginInfoAction(f"{uname}")
            self._addLoginInfoAction(f"UID: {uid}")
            self.loginMenu.addSeparator()
            self.loginMenu.addAction(QAction("打开个人空间", self, triggered=self.openUserSpace))
            self.loginMenu.addAction(QAction("切换账号", self, triggered=self.switchAccount))
            self.loginMenu.addAction(QAction("退出登录", self, triggered=self.logoutAccount))
        elif self.config.get("sessionData"):
            # 已登录但用户信息未就绪（网络验证中或失败）— 保留退出入口
            pending = QAction("已登录（验证中…）", self)
            pending.setEnabled(False)
            self.loginMenu.addAction(pending)
            self.loginMenu.addSeparator()
            self.loginMenu.addAction(QAction("退出登录", self, triggered=self.logoutAccount))
        else:
            self.loginMenu.addAction(QAction("扫码登录…", self, triggered=self.openLoginPage))

    def openUserSpace(self):
        """打开当前账号的 B站个人空间"""
        uid = self.config.get("loginUserInfo", {}).get("uid", "")
        if not uid:
            logging.warning("[LOGIN] 当前没有可打开的用户 UID")
            return
        QDesktopServices.openUrl(QUrl(f"https://space.bilibili.com/{uid}"))

    def switchAccount(self):
        """切换账号：退出当前登录并弹出扫码窗"""
        confirm(
            self, "切换账号", "切换账号需要先退出当前登录，是否继续？",
            on_result=lambda ok: self._doSwitchAccount() if ok else None,
            ok_text="是", cancel_text="否",
        )

    def _doSwitchAccount(self):
        self.updateLogin(False)
        self.openLoginPage()

    def logoutAccount(self):
        """退出登录"""
        confirm(
            self, "退出登录", "确定要退出当前 B站账号吗？",
            on_result=lambda ok: self.updateLogin(False) if ok else None,
            ok_text="是", cancel_text="否",
        )

    def _onDumpRoomConfig(self):
        """回写房间列表到 config 并保存 — 否则 roomid 永不持久化"""
        self.config["roomid"] = dict(self.liverPanel.roomIDDict)
        self.configManager.save()

    def onUserInfoReady(self, info):
        """登录成功后收到用户信息，更新标题并自动获取关注列表"""
        uname = info.get("uname", "")
        uid = info.get("uid", 0)
        self.config["loginUserInfo"] = {
            "uid": uid,
            "uname": uname,
            "face": info.get("face", ""),
            "level": info.get("level", 0),
        }
        self.configManager.save()
        self.setWindowTitle(f"DD监控室{self.versionDisplay} - {uname}")
        self._rebuildLoginMenu()
        # 确保 liverPanel 已持有 sessionData（启动恢复 session 时不会触发 updateSessionData）
        sessdata = getattr(self, "sessionData", "") or self.config.get("sessionData", "")
        if sessdata:
            self.liverPanel.setSessionData(sessdata)
        if self.credential and hasattr(self.liverPanel, "setCredential"):
            self.liverPanel.setCredential(self.credential)
        # 自动填入 UID 并获取关注列表
        if uid:
            self.liverPanel.autoFetchFollows(str(uid))

    def setCache(self, setting):
        maxCache, savePath = setting
        try:
            intergerMaxCache = int(maxCache or "0")
        except (TypeError, ValueError):  # 空输入/非法字符：按 0 处理并提示
            intergerMaxCache = 0
        if intergerMaxCache <= 0:
            info(self, "大小错误", "缓存大小不能小于为0GB!")
            return
        self.config["maxCacheSize"] = intergerMaxCache * 1024000
        self.config["saveCachePath"] = savePath
        self.configManager.save()
        info(self, "缓存设置更改", "设置成功 重启监控室后生效")

    def openHotKey(self):
        hotkey_window = self._getHotKeyWindow()
        hotkey_window.hide()
        hotkey_window.show()

    def openFeed(self):
        if self._pay is None:
            from pay import pay

            self._pay = pay()
        self._pay.hide()
        self._pay.show()
        # 线程未运行才启动，避免重复 start 警告
        if not self._pay.thankToBoss.isRunning():
            self._pay.thankToBoss.start()

    def checkMousePos(self):
        newMousePos = QCursor.pos()
        if newMousePos != self.oldMousePos:
            self.setCursor(Qt.ArrowCursor)  # 鼠标动起来就显示
            self.oldMousePos = newMousePos
            self.hideMouseCnt = 10  # 刷新隐藏鼠标的间隔（200ms * 10 = 2s）
        if self.hideMouseCnt > 0:
            self.hideMouseCnt -= 1
        elif self.hideMouseCnt == 0:
            self.hideMouseCnt = -1  # 标记已隐藏，避免重复操作
            self.setCursor(Qt.BlankCursor)  # 计数归零隐藏鼠标
            # 一次性遍历（含悬浮窗），隐藏所有控制条
            for videoWidget in self._iterVideoWidgets(include_popups=True):
                videoWidget.topLabel.hide()  # 隐藏播放窗口的控制条
                videoWidget.frame.hide()

    def _initThemeButton(self):
        """标题栏最小化按钮左侧的主题切换按钮（参考 Easy-FFmpeg 实现）。

        深色模式显示太阳（点它切浅色），浅色模式显示月亮（点它切深色），
        图标随主题自动更新；切换同时写入自研 config 持久化。
        """

        self.themeButton = TransparentToolButton(self.titleBar)
        self.themeButton.setFixedSize(self.titleBar.minBtn.size())
        self.themeButton.setToolTip("切换明暗主题")
        self.themeButton.clicked.connect(self._toggleThemeFromTitleBar)
        self._updateThemeButtonIcon()
        theme_changed().connect(self._updateThemeButtonIcon)
        # 插入到最小化按钮左侧（buttonLayout: themeBtn, minBtn, maxBtn, closeBtn）
        self.titleBar.buttonLayout.insertWidget(0, self.themeButton, 0, Qt.AlignTop)

    def _updateThemeButtonIcon(self, dark=None):
        """深色显示太阳（切浅色），浅色显示月亮（切深色）"""
        from uikit_bridge import is_dark as bridge_is_dark

        self.themeButton.setIcon(
            Icon(FluentIcon.BRIGHTNESS if bridge_is_dark() else FluentIcon.QUIET_HOURS)
        )

    def _toggleThemeFromTitleBar(self):
        """标题栏主题按钮：切换明暗并持久化到自研 config"""
        from uikit_bridge import is_dark as bridge_is_dark, set_theme

        dark = not bridge_is_dark()
        self.config["theme"] = "dark" if dark else "light"
        self.configManager.save()
        set_theme(dark)

    def _initNavBar(self):
        """顶部导航按钮行（替代原 QMenuBar 菜单栏，参考 Easy-FFmpeg 导航）。

        点击导航按钮在按钮下方弹出对应 RoundMenu——无 hover 弹出，
        不存在 Popup 截获鼠标事件导致菜单"锁住"的问题。
        """
        nav_bar = QWidget()
        nav_bar.setStyleSheet("background: transparent;")
        nav_layout = QHBoxLayout(nav_bar)
        nav_layout.setContentsMargins(10, 2, 10, 2)
        nav_layout.setSpacing(6)
        for text, menu in (
            ("设置", self.optionMenu),
            ("帮助", self.versionMenu),
            ("开源和投喂", self.payMenu),
            ("B站账号", self.loginMenu),
        ):
            btn = FPushButton(text)
            btn.setFixedHeight(24)
            btn.clicked.connect(lambda checked=False, m=menu, b=btn: self._popupTopMenu(m, b))
            nav_layout.addWidget(btn)
        nav_layout.addStretch(1)
        self.setMenuWidget(nav_bar)

    def _popupTopMenu(self, menu, btn):
        """在导航按钮正下方弹出菜单（exec 动画路径）。"""
        pos = btn.mapToGlobal(QPoint(0, btn.height()))
        menu.exec(pos)

    def moveEvent(self, event):  # 捕获主窗口moveEvent来实时同步弹幕机位置
        # 无边框窗口初始化（super().__init__）期间 moveEvent 会提前触发，
        # 此时 _viewport_debounce 尚未创建，直接跳过
        if not hasattr(self, "_viewport_debounce"):
            return
        # 防抖：moveEvent 高频触发，_applyDanmakuBaseViewport 会遍历所有窗口并
        # 触发 applyDanmuSettings（重操作），合并为停止移动后 200ms 执行一次
        if not self._viewport_debounce.isActive():
            self._viewport_debounce.start()
        for videoWidget in self.videoWidgetList:
            if videoWidget.textBrowser is None:
                continue
            videoPos = videoWidget.mapToGlobal(videoWidget.videoFrame.pos())  # videoFrame的坐标要转成globalPos
            videoWidget.textBrowser.move(videoPos + videoWidget.textPosDelta)
            videoWidget.textPosDelta = videoWidget.textBrowser.pos() - videoPos

    def _onViewportDebounced(self):
        self._applyDanmakuBaseViewport()

    def hideEvent(self, e: QHideEvent) -> None:
        """主窗口隐藏：关闭、最小化
        隐藏所有弹幕机
        """
        logging.debug("主窗口已隐藏")
        if not hasattr(self, "videoWidgetList"):  # 无边框初始化期间可能提前触发
            return
        for videoWidget in self.videoWidgetList:
            videoWidget.hideTextBrowser()

    def showEvent(self, e: QShowEvent) -> None:
        """主窗口显示：打开、最大化
        显示开启的弹幕机
        """
        logging.debug("主窗口已显示")
        if not hasattr(self, "videoWidgetList"):  # 无边框初始化期间可能提前触发
            return
        self._applyDanmakuBaseViewport()
        for index, videoWidget in enumerate(self.videoWidgetList):
            if self.config["danmu"][index][0] and not videoWidget.isHidden():
                videoWidget.showTextBrowser()

    def closeEvent(self, event):
        self.hide()
        self.layoutSettingPanel.close()
        self.liverPanel.addLiverRoomWidget.close()
        # 等待轮询线程退出后再继续 — 否则进程退出时线程阻塞在 HTTP 请求中
        # 会被强杀，触发原生 access violation 崩溃（FlClash 代理下尤为常见）
        self.liverPanel.collectLiverInfo.stop()
        self.liverPanel.collectLiverInfo.wait(5000)
        self.loginDialog.close()
        # 先停止所有窗口的取流线程（发停止信号），再并行等待退出，
        # 避免串行 wait(3000) × N 窗口导致最长 48s 的退出延迟
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.getMediaURL.recordToken = False
            videoWidget.checkPlaying.stop()
            videoWidget.mediaStop(deleteMedia=False)  # 不要清除播放窗记录
        _wait_threads = [vw.getMediaURL for vw in self._iterVideoWidgets(include_popups=True) if vw.getMediaURL.isRunning()]
        if _wait_threads:
            _waiter = threading.Thread(target=lambda: [t.wait(3000) for t in _wait_threads], daemon=True)
            _waiter.start()
            _waiter.join(4000)
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.close()
        self.saveDockLayout()
        self.configManager.save_now()
        event.accept()

    def openLayoutSetting(self):
        self.layoutSettingPanel.show()
        self.layoutSettingPanel.raise_()
        self.layoutSettingPanel.activateWindow()

    def changeLayout(self, layoutConfig):
        for videoWidget in self.videoWidgetList:
            videoWidget.mediaPlay(1)  # 全部暂停
        for index, _ in enumerate(self.config["layout"]):
            self.videoWidgetList[index].hideTextBrowser()
            item = self.mainLayout.itemAt(0)
            if item is not None and item.widget() is not None:
                item.widget().hide()
                self.mainLayout.removeWidget(item.widget())
        for index, layout in enumerate(layoutConfig):
            y, x, h, w = layout
            videoWidget = self.videoWidgetList[index]
            videoWidget.show()
            if videoWidget.textSetting[0]:  # 显示弹幕
                videoWidget.showTextBrowser()
            self.mainLayout.addWidget(videoWidget, y, x, h, w)
            if videoWidget.roomID != "0":
                videoWidget.mediaPlay(2)  # 显示的窗口播放
        # 隐藏布局之外的窗口（按布局数量而非循环变量，避免空布局时未绑定）
        for videoWidget in self.videoWidgetList[len(layoutConfig) :]:
            videoWidget.getMediaURL.recordToken = False
            videoWidget.checkPlaying.stop()
        self.config["layout"] = layoutConfig
        self._applyDanmakuBaseViewport()
        self.configManager.save()

    def changeLiverPanelLayout(self, multiple):
        # FlowLayout 卡片随容器宽度自动流式换行，无需按宽度手动重排
        pass

    def fullScreen(self):
        if self.isFullScreen():  # 退出全屏
            if self.maximumToken:
                self.showMaximized()
            else:
                self.showNormal()
            self.optionMenu.menuAction().setVisible(True)
            self.versionMenu.menuAction().setVisible(True)
            self.payMenu.menuAction().setVisible(True)
            if self.controlBarLayoutToken:
                self.controlDock.show()
                self.cardDock.show()
        else:  # 全屏
            for videoWidget in self.videoWidgetList:
                videoWidget.fullScreen = True
            self.maximumToken = self.isMaximized()
            self.optionMenu.menuAction().setVisible(False)
            self.versionMenu.menuAction().setVisible(False)
            self.payMenu.menuAction().setVisible(False)
            if self.controlBarLayoutToken:
                self.controlDock.hide()
                self.cardDock.hide()
            for videoWidget in self.videoWidgetList:
                videoWidget.fullScreen = True
            self.showFullScreen()

    def saveDockLayout(self):
        self.config["geometry"] = str(self.saveGeometry().toBase64(), "ASCII")
        self.config["windowState"] = str(self.saveState().toBase64(), "ASCII")
        logging.info("save Window layout.")

    def loadDockLayout(self):
        if "geometry" in self.config:
            geometry = QByteArray().fromBase64(self.config["geometry"].encode("ASCII"))
            self.restoreGeometry(geometry)
        if "windowState" in self.config:
            windowState = QByteArray().fromBase64(self.config["windowState"].encode("ASCII"))
            self.restoreState(windowState)
        logging.info("restore Window layout.")

    def exportConfig(self):
        savePath = QFileDialog.getSaveFileName(self, "选择保存路径", "DD监控室预设", "*.json")[0]
        if savePath:
            try:
                self.configManager.export_to(savePath)
                info(self, "导出预设", "导出完成")
            except Exception:
                logging.exception("json 配置导出失败")

    def importConfig(self):
        jsonPath = QFileDialog.getOpenFileName(self, "选择预设", None, "*.json")[0]
        if jsonPath:
            if self.configManager.import_from(jsonPath, self.config["layout"]):
                self.config = self.configManager.config
                self.liverPanel.addLiverRoomList(self.config["roomid"])
                info(self, "导入预设", "导入完成")

    def muteExcept(self):
        if not self.soloToken:
            for videoWidget in self.videoWidgetList:
                if not videoWidget.isHidden() and videoWidget.hoverToken:
                    videoWidget.mediaMute(1)  # 取消静音
                else:
                    videoWidget.mediaMute(2)  # 静音
        else:  # 恢复所有直播间声音
            for videoWidget in self.videoWidgetList:
                if not videoWidget.isHidden():
                    videoWidget.mediaMute(1)  # 取消静音
        self.soloToken = not self.soloToken

    def closePopWindow(self, info):
        id, roomID = info
        # 房间号有效
        if not self.videoWidgetList[id - 16].isHidden() and roomID != "0" and roomID:
            self.videoWidgetList[id - 16].roomID = roomID
            self.videoWidgetList[id - 16].mediaReload()
            self.config["player"][id - 16] = roomID
            self.liverPanel.updatePlayingStatus(self.config["player"])
            self.configManager.save()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape or event.key() == Qt.Key_F:
            self.fullScreen()
        elif event.key() == Qt.Key_H:
            self.openControlPanel()
        elif event.key() == Qt.Key_M or event.key() == Qt.Key_S:
            self.muteExcept()
        elif Qt.Key_1 <= event.key() <= Qt.Key_9:
            idx = event.key() - Qt.Key_1
            if idx < len(self.videoWidgetList):
                if event.modifiers() & Qt.ControlModifier:
                    # Ctrl+数字: 加载卡片面板第一个房间到该窗口
                    first_room = self.liverPanel.getFirstRoomID()
                    if first_room:
                        self.videoWidgetList[idx].roomID = first_room
                        self.videoWidgetList[idx].mediaReload()
                        self.config["player"][idx] = first_room
                        self.liverPanel.updatePlayingStatus(self.config["player"])
                        self.configManager.save()
                else:
                    # 数字键: 聚焦对应窗口
                    self.videoWidgetList[idx].setFocus()
                    self.videoWidgetList[idx].raise_()

    def addCoverToPlayer(self, info):  # 窗口 房号
        self.addMedia(info)
        self.videoWidgetList[info[0]].roomID = info[1]  # 修改房号
        self.videoWidgetList[info[0]].mediaReload()  # 重载视频

    def refreshPlayerStatus(self, refreshIDList):  # 刷新直播状态发生变化的播放器
        for videoWidget in self.videoWidgetList:
            for roomID in refreshIDList:
                if roomID == videoWidget.roomID:
                    videoWidget.mediaReload()
                    break

    def startLiveTip(self, startLiveList):  # 开播提醒
        if self.config["showStartLive"]:
            start_live_window = self._getStartLiveWindow()
            start_live_window.resize(240, 70)
            start_live_window.move(self.pos() + QPoint(50, 50))
            startLivers = ""
            for liver in startLiveList:
                startLivers += "  %s 开播啦!~  \n" % liver
            start_live_window.tipLabel.setText(startLivers)
            start_live_window.show()
            start_live_window.hideTimer.start()

    def setNoMore(self):
        self.config["checkUpdate"] = False
        self.configManager.save()  # 持久化"不再提示"，否则重启后失效

    def updateChecker(self):
        from checkUpdate import updateReminder, checkUpdate

        self.updateReminder = updateReminder()
        self.updateReminder.noMoreSignal.connect(self.setNoMore)
        # 属性名避开类名 checkUpdate，防止遮蔽模块符号
        self._updateCheckerThread = checkUpdate(self.versionNumber)
        self._updateCheckerThread.update.connect(self.updateReminder._show)
        self._updateCheckerThread.start()


# 程序入口点
if __name__ == "__main__":
    # 平台相关 patch
    import ctypes

    if platform.system() == "Windows":
        ctypes.windll.kernel32.SetDllDirectoryW(None)
    if getattr(sys, "frozen", False):
        application_path = os.path.dirname(sys.executable)
    elif __file__:
        application_path = os.path.dirname(__file__)

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

    # 应用全局样式：qfluentwidgets_pro Fluent 暗色主题（替换原 qdark.qss）
    # mpv 播放器 / 弹幕机 / 布局面板等自绘或带实例级内联样式的控件不受影响
    # Qt6 默认启用高 DPI，无需手动设置 AA_EnableHighDpiScaling
    app = QApplication(sys.argv)
    from uikit_bridge import init_uikit

    # faulthandler：任何原生崩溃（segfault）都把 Python 栈写进 crash.log，
    # 用于定位"打开即闪退"类问题
    import faulthandler

    try:
        faulthandler.enable(open(os.path.join(application_path, "crash.log"), "w"))
    except Exception:
        pass

    init_uikit()
    app.setFont(QFont("微软雅黑", 9))

    # 日志采集初始化
    log.init_log(application_path)
    from ReportException import (
        threadingExceptionHandler,
        uncaughtExceptionHandler,
        unraisableExceptionHandler,
        loggingSystemInfo,
    )

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
    splash = QSplashScreen(QPixmap(os.path.join(application_path, "utils/splash.jpg")))
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
    sys.exit(app.exec())
