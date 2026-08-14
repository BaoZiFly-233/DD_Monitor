"""DD监控室主界面 — 主窗口与全局控制逻辑。

包含对所有子页面的初始化、排版管理，卡片和播放窗口的交互通过主界面线程通信，
以及软件启动和退出后的一些操作。程序入口见项目根目录 DD监控室.py。
"""

import os
import sys
import threading
import logging
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
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
    QShowEvent,
)
from PySide6.QtCore import QByteArray, QEvent, QPoint, QSize, QThread, QTimer, QUrl, Qt, Signal
from app.ui.layout_panel import LayoutSettingPanel
from app.ui.title_bar import AppTitleBar, FluentWindow, apply_fullscreen_style
from app.ui.video_widget import VideoWidget
from app.ui.liver_select import LiverPanel
from app.core.config_manager import ConfigManager, MAX_WINDOWS, WINDOW_CARD_WIDTH, DISPLAY_RATIOS
from app.core.bili_credential import normalize_credential_data, build_credential, credential_to_dict

from qfluentwidgets_pro import (
    FluentIcon,
    Icon,
    LineEdit,
    PushButton as FPushButton,
    PrimaryPushButton as FPrimaryPushButton,
    RoundMenu,
    Slider as FluentSlider,
    SmoothScrollArea,
)
from qfluentwidgets_pro.qframelesswindow.windows import WindowsFramelessMainWindow
from app.ui.uikit_bridge import confirm, info, current_color, theme_changed
from bilibili_api import sync
from bilibili_api.exceptions import CredentialNoBiliJctException
from app.ui.danmu import GlobalDanmuOption
from app.ui.settings_dialog import SettingsDialog
from app.ui.login import LoginDialog
from app.core.app_version import APP_NAME, DISPLAY_VERSION, VERSION, RELEASE_DATE, parse_version

def _hard_exit():
    """退出竞态窗口防护：checkUpdate/凭据刷新/热门列表等后台线程仍在运行，
    其 bilibili_api sync() 的 futures 线程在进程收尾时可能触发 0xe24c4a02
    （LuaJIT panic）崩溃。所有业务清理已完成，直接硬终止进程，跳过
    DLL/线程收尾的竞态窗口。测试/截图脚本可 monkeypatch 本函数跳过。"""
    if sys.platform == "win32":
        import ctypes

        # 64 位 Windows 上 HANDLE 是 8 字节，ctypes 默认按 c_int 截断会导致
        # TerminateProcess 静默失败（进程继续收尾，触发 0xe24c4a02 竞态崩溃）
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        _kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        _kernel32.TerminateProcess(_kernel32.GetCurrentProcess(), 0)


def get_application_path() -> str:
    """返回程序根目录（frozen 打包后为可执行文件所在目录）。

    资源（resources/）与运行时配置均以它为基准定位。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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


class StartLiveWindow(QWidget):
    """开播提醒弹窗 — 无边框横幅（无标题栏，拖动移动）"""

    def __init__(self):
        super(StartLiveWindow, self).__init__()
        self.setWindowTitle("开播提醒")
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(240, 70)
        self._drag_pos = None
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

    def mousePressEvent(self, event):  # 点击的话就停止倒计时
        self.hideTimer.stop()
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)


class CacheSetting(FluentWindow):
    """缓存设置窗口"""

    setting = Signal(list)

    def __init__(self):
        super(CacheSetting, self).__init__(title="缓存设置")
        self.resize(400, 230)
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


class Version(FluentWindow):
    """版本说明窗口"""

    def __init__(self):
        super(Version, self).__init__(title="当前版本")
        self.resize(350, 260)
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


class HotKey(FluentWindow):
    """热键说明窗口"""

    def __init__(self):
        super(HotKey, self).__init__(title="快捷键")
        self.resize(350, 240)
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

            # 限制解析超时（默认 lifetime 可达 30s+），避免退出时线程
            # 阻塞在 DNS 查询导致 join 等待与异常退出码（实测 127）
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3
            resolver.lifetime = 3
            anwsers = resolver.resolve("broadcastlv.chat.bilibili.com", "A")
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
        # 统一 Fluent 标题栏（经典 一/口/X 按钮，主题色自适应），
        # qframelesswindow 提供边缘缩放与拖动；先装标题栏再设标题/图标
        self.setTitleBar(AppTitleBar(self))
        self.setWindowTitle(f"DD监控室{self.versionDisplay}")
        self.setWindowIcon(Icon(FluentIcon.ROBOT))
        # QMainWindow 的 menuBar 从窗口顶部开始，会盖住 Fluent 标题栏
        # （48px，含窗口控制按钮）；把 QMainWindow 内容区（menuBar/
        # dock/central）整体下移标题栏高度，menuBar 保持在 menuBar 区
        self.setContentsMargins(0, self.titleBar.height(), 0, 0)
        # 顶栏菜单悬停即弹：菜单（Qt.Popup）打开后鼠标事件被 popup
        # 截获，menuBar 的 hovered 信号不再触发，必须用 app 级事件
        # 过滤器监听全局鼠标移动来驱动菜单切换
        QApplication.instance().installEventFilter(self)
        self.resize(1600, 900)
        # 最小尺寸：防止无边框窗口被拖到极小导致布局错乱/控件不可见
        self.setMinimumSize(640, 480)
        self.maximumToken = True
        self.soloToken = False  # 记录静音除鼠标悬停窗口以外的其他所有窗口的标志位 True就是恢复所有房间声音
        self.cacheFolder = cacheFolder

        # ---- json 配置文件加载 ----
        self.configManager = ConfigManager(get_application_path(), parent=self)
        self.config = self.configManager.load()
        # 应用配置的主题（明/暗）与配色，主界面全局 QSS 由 UIKit 主题驱动
        from app.ui.uikit_bridge import set_theme, set_accent, set_menu_animation, ACCENT_NAMES

        set_theme(self.config.get("theme", "dark") == "dark")
        accent = self.config.get("accent", "blue")
        if accent not in ACCENT_NAMES:
            # config.json 被手改/损坏/旧版本遗留非法配色时回退 blue，
            # 否则 set_accent 抛 ValueError 导致启动崩溃
            logging.warning("config 中的配色非法: %r，回退 blue", accent)
            accent = "blue"
            self.config["accent"] = accent
        set_accent(accent)
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
        # Grid 布局（16 宫格内容区，控制条/卡片面板迁入子页面后仍由 mainLayout 管理）
        self.mainLayout = QGridLayout(mainWidget)
        self.mainLayout.setSpacing(0)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)

        # ---- 标准 Fluent 结构：顶部导航 + StackedWidget 内容区 ----
        from qfluentwidgets_pro.components.navigation import (
            TopNavigationInterface,
            TopNavigationItemPosition,
        )
        from qfluentwidgets_pro.components.widgets.stacked_widget import PopUpAniStackedWidget as StackedWidget

        self.navigationInterface = TopNavigationInterface(self)
        self.contentStack = StackedWidget(self)

        # 页面0：直播监控（控制条 + 16 宫格）
        self.monitorPage = QWidget()
        self.monitorPageLayout = QHBoxLayout(self.monitorPage)
        self.monitorPageLayout.setContentsMargins(0, 0, 0, 0)
        self.monitorPageLayout.setSpacing(0)
        # 控制条容器（原 controlDock 178px 宽度，H 键可显示/隐藏）
        self.controlContainer = QWidget()
        self.controlContainer.setFixedWidth(178)
        self.monitorPageLayout.addWidget(self.controlContainer)
        self.monitorPageLayout.addWidget(mainWidget, 1)

        # 页面1：弹幕机（控制台，Batch5 深化）
        self.danmakuPage = QWidget()
        self.danmakuPageLayout = QVBoxLayout(self.danmakuPage)
        self.danmakuPageLayout.setContentsMargins(24, 24, 24, 24)
        self.danmakuPageLayout.setSpacing(12)
        _danmu_tip = QLabel("弹幕机控制台\n\n每个播放窗口的弹幕机是独立悬浮窗，可拖动位置、设置透明度/字体/过滤词。")
        _danmu_tip.setWordWrap(True)
        self.danmakuPageLayout.addWidget(_danmu_tip)
        _danmu_btn_row = QHBoxLayout()
        _open_all = FPrimaryPushButton("打开全部弹幕机")
        _open_all.clicked.connect(self._openAllDanmakuMachines)
        _danmu_btn_row.addWidget(_open_all)
        _global_danmu = FPushButton("全局弹幕设置")
        _global_danmu.clicked.connect(self.openGlobalDanmuSetting)
        _danmu_btn_row.addWidget(_global_danmu)
        _danmu_btn_row.addStretch()
        self.danmakuPageLayout.addLayout(_danmu_btn_row)
        self.danmakuPageLayout.addStretch()

        # 页面2：卡片面板（原 cardDock 内容迁入）
        self.cardPage = QWidget()
        self.cardPageLayout = QVBoxLayout(self.cardPage)
        self.cardPageLayout.setContentsMargins(0, 0, 0, 0)
        self.cardPageLayout.setSpacing(0)
        self.scrollArea = ScrollArea()
        self.scrollArea.setStyleSheet("border-width:0px")
        self.scrollArea.setWidgetResizable(True)
        self.cardPageLayout.addWidget(self.scrollArea)

        # 页面3：设置（Batch5 内嵌 SettingCard 页，先用引导页）
        self.settingsPage = QWidget()
        self.settingsPageLayout = QVBoxLayout(self.settingsPage)
        self.settingsPageLayout.setContentsMargins(24, 24, 24, 24)
        self.settingsPageLayout.setSpacing(12)
        _settings_tip = QLabel("设置\n\n所有设置项已整合到统一设置面板（播放/弹幕/缓存/布局/通用）。")
        _settings_tip.setWordWrap(True)
        self.settingsPageLayout.addWidget(_settings_tip)
        _settings_btn = FPrimaryPushButton("打开设置面板")
        _settings_btn.clicked.connect(self.openSettingsDialog)
        self.settingsPageLayout.addWidget(_settings_btn, alignment=Qt.AlignLeft)
        self.settingsPageLayout.addStretch()

        # 组装内容区 + 导航
        self.contentStack.addWidget(self.monitorPage)
        self.contentStack.addWidget(self.danmakuPage)
        self.contentStack.addWidget(self.cardPage)
        self.contentStack.addWidget(self.settingsPage)
        self.contentStack.setCurrentWidget(self.monitorPage)  # 启动默认直播监控页

        rootWidget = QWidget()
        self.setCentralWidget(rootWidget)
        self.rootLayout = QVBoxLayout(rootWidget)
        self.rootLayout.setContentsMargins(0, 0, 0, 0)
        self.rootLayout.setSpacing(0)
        self.rootLayout.addWidget(self.navigationInterface)
        self.rootLayout.addWidget(self.contentStack, 1)

        # 导航项（图标+文字，主题自适应，点击切换页面）
        self.navigationInterface.addItem(
            routeKey="monitor", icon=FluentIcon.VIDEO, text="直播监控",
            onClick=lambda: self.contentStack.setCurrentWidget(self.monitorPage),
        )
        self.navigationInterface.addItem(
            routeKey="danmaku", icon=FluentIcon.CHAT, text="弹幕机",
            onClick=lambda: self.contentStack.setCurrentWidget(self.danmakuPage),
        )
        self.navigationInterface.addItem(
            routeKey="cards", icon=FluentIcon.ALBUM, text="卡片面板",
            onClick=lambda: self.contentStack.setCurrentWidget(self.cardPage),
        )
        self.navigationInterface.addItem(
            routeKey="settings", icon=FluentIcon.SETTING, text="设置",
            onClick=lambda: self.contentStack.setCurrentWidget(self.settingsPage),
        )
        # 导航右侧：账号/帮助/投喂（弹出保留的菜单对象）
        self.navigationInterface.addItem(
            routeKey="account", icon=FluentIcon.PEOPLE, text="账号",
            onClick=lambda: self.loginMenu.popup(QCursor.pos()),
            selectable=False, position=TopNavigationItemPosition.RIGHT,
        )
        self.navigationInterface.addItem(
            routeKey="help", icon=FluentIcon.HELP, text="帮助",
            onClick=lambda: self.versionMenu.popup(QCursor.pos()),
            selectable=False, position=TopNavigationItemPosition.RIGHT,
        )
        self.navigationInterface.addItem(
            routeKey="donate", icon=FluentIcon.HEART, text="投喂",
            onClick=lambda: self.payMenu.popup(QCursor.pos()),
            selectable=False, position=TopNavigationItemPosition.RIGHT,
        )
        # 原生 menuBar 隐藏（菜单对象保留，由导航按钮弹出）
        self.menuBar().hide()
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
        self.popVideoWidgetList = [None] * MAX_WINDOWS
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
            self.videoWidgetList[i].volumeAmplify = float(self.config["volumeAmplify"][i] or 1.0)
            # 不在循环内调 processEvents — 见 login.py thread.wait 注释
            logging.info(f"播放器设置完毕 {i + 1} / 16")
        QApplication.instance().processEvents()  # 刷新启动画面进度（勿用模块级 app 变量）
        # 延迟创建 OpenGL 上下文，避免 16 个同时初始化导致栈溢出
        QTimer.singleShot(0, self.setPlayer)

        # 控制条（原 controlDock 迁入直播监控页左侧容器，CommandBar 化）
        self.controlWidget = ControlWidget()
        self.controlWidget.heightValue.connect(self.showAddButton)
        self.controlContainerLayout = QVBoxLayout(self.controlContainer)
        self.controlContainerLayout.setContentsMargins(0, 0, 0, 0)
        self.controlContainerLayout.setSpacing(0)
        self.controlContainerLayout.addWidget(self.controlWidget)
        self.controlBarLayout = QVBoxLayout(self.controlWidget)
        self.controlBarLayout.setContentsMargins(4, 4, 4, 4)
        self.controlBarLayout.setSpacing(6)

        # CommandBar：播放/刷新/停止/弹幕设置/静音（Fluent 命令栏）
        from qfluentwidgets_pro.components.widgets.command_bar import CommandBar

        self.commandBar = CommandBar(self.controlWidget)
        self.commandBar.setIconSize(QSize(16, 16))
        self.globalPlayToken = True
        self.play = QAction(Icon(FluentIcon.PAUSE), "播放/暂停", self)
        self.play.setToolTip("全局暂停/播放")
        self.play.triggered.connect(self.globalMediaPlay)
        self.commandBar.addAction(self.play)
        self.reload = QAction(Icon(FluentIcon.SYNC), "刷新", self)
        self.reload.setToolTip("全局刷新")
        self.reload.triggered.connect(self.globalMediaReload)
        self.commandBar.addAction(self.reload)
        self.stop = QAction(Icon(FluentIcon.CANCEL), "停止", self)
        self.stop.setToolTip("全局停止")
        self.stop.triggered.connect(self.globalMediaStop)
        self.commandBar.addAction(self.stop)
        # 全局弹幕设置（Fluent 齿轮图标）
        self.danmuAction = QAction(Icon(FluentIcon.SETTING), "弹幕设置", self)
        self.danmuAction.setToolTip("全局弹幕设置")
        self.danmuAction.triggered.connect(self.openGlobalDanmuSetting)
        self.commandBar.addAction(self.danmuAction)
        # 全局静音
        self.globalMuteToken = False
        self.volumeButton = QAction(Icon(FluentIcon.VOLUME), "静音", self)
        self.volumeButton.setToolTip("全局静音")
        self.volumeButton.triggered.connect(self.globalMediaMute)
        self.commandBar.addAction(self.volumeButton)
        self.controlBarLayout.addWidget(self.commandBar)

        # 全局音量滑条
        self.slider = FluentSlider(Qt.Horizontal)
        self.slider.setValue(self.config["globalVolume"])
        self.slider.valueChanged.connect(self.globalSetVolume)
        self.controlBarLayout.addWidget(self.slider)
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
        self.controlBarLayout.addWidget(self.addButton)
        self.controlBarLayout.addStretch()
        progressText.setText("设置全局控制...")

        # 卡片面板（原 cardDock 迁入卡片面板页）
        self.cardPageLayout.addWidget(self.scrollArea)

        # 主播添加窗口
        self.liverPanel = LiverPanel(self.config["roomid"], get_application_path())
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

        # ---- 菜单设置 ----
        self.optionMenu = RoundMenu("设置", self)
        self.menuBar().addMenu(self.optionMenu)
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
        self.menuBar().addMenu(self.versionMenu)
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
        self.menuBar().addMenu(self.payMenu)
        githubAction = QAction("GitHub", self, triggered=self.openGithub)
        self.payMenu.addAction(githubAction)
        feedAction = QAction("投喂作者", self, triggered=self.openFeed)
        self.payMenu.addAction(feedAction)
        progressText.setText("设置关于菜单...")

        self.loginMenu = RoundMenu("B站账号", self)
        self.menuBar().addMenu(self.loginMenu)
        self._rebuildLoginMenu()

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
        videoWidget.amplifyChanged.connect(self.amplifyChanged)
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
        self.danmuAction.setIcon(Icon(FluentIcon.SETTING))

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

    def _openAllDanmakuMachines(self):
        """弹幕机控制台：打开所有窗口的弹幕机"""
        for video_widget in self.videoWidgetList:
            video_widget.showTextBrowser()
        info(self, "弹幕机", "已打开全部弹幕机（可在各窗口右键/H 键控制）")

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
        # 恢复上次的悬浮窗位置（分辨率变化时 clamp 到可见区域），
        # 否则每次都在默认位置弹出，用户拖到别处后下次又回默认
        try:
            from PySide6.QtCore import QByteArray

            geom = QByteArray().fromBase64(self.config.get("popupGeometry", "").encode("ASCII"))
            restored = pop_video_widget.restoreGeometry(geom)
            if not restored:
                pop_video_widget.resize(1280, 720)
            # 确保窗口主体落在可见屏幕内（上次所在屏幕已断开/分辨率变化）
            screen = QApplication.screenAt(pop_video_widget.frameGeometry().center())
            if screen is None:
                pop_video_widget.resize(1280, 720)
                pop_video_widget.move(100, 100)
        except Exception:
            pop_video_widget.resize(1280, 720)
        pop_video_widget.show()
        pop_video_widget.setDanmakuBaseViewport(self._resolveDanmakuBaseViewport())
        if startWithDanmu:
            pop_video_widget.showDanmu()
        if showMax:
            pop_video_widget.showMaximized()
        pop_video_widget.mediaReload()

    def amplifyChanged(self, info):
        id, amp = info
        if not (0 <= id < MAX_WINDOWS):
            return
        self.config["volumeAmplify"][id] = amp
        self.configManager.save()

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
        self.config["muted"] = [force] * MAX_WINDOWS

    def globalSetVolume(self, value):
        for videoWidget in self.videoWidgetList:
            videoWidget.set_volume_direct(int(value * videoWidget.volumeAmplify))
            videoWidget.volume = value
            videoWidget.slider.setValue(value)
        self.config["volume"] = [value] * MAX_WINDOWS
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
        self.config["quality"] = [quality] * MAX_WINDOWS
        self.configManager.save()

    def globalAudioChannel(self, audioChannel):
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.set_audio_channel(audioChannel)
        self.config["audioChannel"] = [audioChannel] * MAX_WINDOWS
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
        # 控制条已迁入直播监控页左侧容器（H 键显示/隐藏）
        if self.controlContainer.isHidden():
            self.controlContainer.show()
        else:
            self.controlContainer.hide()
        self.controlBarLayoutToken = self.controlContainer.isHidden()
        self.configManager.save()

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
            self._settingsDialog.applied.connect(self._applySettingsToWindows)
        self._settingsDialog.show()
        self._settingsDialog.raise_()
        self._settingsDialog.activateWindow()

    def _applySettingsToWindows(self):
        """设置应用后：把新配置同步到所有播放窗口（音量/弹幕/滚动弹幕）

        VideoWidget 的 textSetting/rollingSetting 是 config 对象的引用，
        设置对话框修改后 applyDanmuSettings() 重读即可生效。"""
        try:
            volume = self.config.get("globalVolume", 30)
            for video_widget in self._iterVideoWidgets(include_popups=True):
                video_widget.setVolume(volume)
                video_widget.applyDanmuSettings()
        except Exception:
            logging.exception("应用设置到播放窗口失败")

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
            info(self, "大小错误", "缓存大小不能小于 1GB!", level="error")
            return
        self.config["maxCacheSize"] = intergerMaxCache * 1024000
        self.config["saveCachePath"] = savePath
        self.configManager.save()
        info(self, "缓存设置更改", "设置成功 重启监控室后生效", level="success")

    def openHotKey(self):
        hotkey_window = self._getHotKeyWindow()
        hotkey_window.hide()
        hotkey_window.show()

    def openFeed(self):
        if self._pay is None:
            from app.ui.pay import pay

            self._pay = pay()
        self._pay.hide()
        self._pay.show()
        # 线程未运行才启动，避免重复 start 警告
        if not self._pay.thankToBoss.isRunning():
            self._pay.thankToBoss.start()

    def checkMousePos(self):
        newMousePos = QCursor.pos()
        if newMousePos != self.oldMousePos:
            # 仅在光标形状不同时才设置，避免鼠标持续移动时每 200ms 重复
            # setCursor 造成光标抖动/子控件光标被反复覆盖
            if self.cursor().shape() != Qt.ArrowCursor:
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

    def eventFilter(self, obj, event):
        """全局鼠标移动 → 顶栏菜单悬停切换。

        菜单（Qt.Popup）打开后鼠标事件被 popup 截获，menuBar 的
        hovered 信号不再触发；在 app 级监听 MouseMove，光标位于
        菜单栏菜单项上且该菜单未打开时执行切换（exec 动画路径）。
        """
        if event.type() == QEvent.MouseMove:
            self._onGlobalMouseMove(event.globalPosition().toPoint())
        return super().eventFilter(obj, event)

    def _onGlobalMouseMove(self, gpos):
        """光标在菜单栏菜单项上时，关闭其他菜单并弹出目标菜单。"""
        mb = self.menuBar()
        if mb is None or not mb.isVisible():
            return
        local = mb.mapFromGlobal(gpos)
        if not mb.rect().contains(local):
            return
        for action in mb.actions():
            if mb.actionGeometry(action).contains(local):
                menu = action.menu()
                if menu is not None and not menu.isVisible():
                    self._openTopMenu(action)
                return

    def _openTopMenu(self, action):
        """关闭其他顶层菜单并弹出目标菜单（exec：动画由菜单动画开关控制）"""
        menu = action.menu()
        for m in (self.optionMenu, self.versionMenu, self.payMenu, self.loginMenu):
            if m is not menu and m.isVisible():
                m.close()
        pos = self.menuBar().mapToGlobal(self.menuBar().actionGeometry(action).bottomLeft())
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
        # DNS 解析线程：解释器退出时若仍在运行（dnspython 阻塞中）会导致
        # 非零退出码（实测 127）；等待其退出，超时由末尾硬退出兜底
        if self.checkDanmmuProvider.isRunning():
            self.checkDanmmuProvider.wait(3000)
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
        # 停止所有窗口的播放与周边线程（跳过 MPV free/terminate：
        # libmpv 销毁在播放中有已知死锁/崩溃，入口 TerminateProcess 硬退出保底）
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.shutdown(skip_mpv=True)
        for videoWidget in self._iterVideoWidgets(include_popups=True):
            videoWidget.close()
        self.saveDockLayout()
        self.configManager.save_now()
        event.accept()
        _hard_exit()

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
            # 恢复阴影与原生样式（内部轮询，等待 Qt 异步状态应用完成）
            apply_fullscreen_style(self, False)
            self.optionMenu.menuAction().setVisible(True)
            self.versionMenu.menuAction().setVisible(True)
            self.payMenu.menuAction().setVisible(True)
            if self.controlBarLayoutToken:
                self.controlContainer.show()
        else:  # 全屏
            apply_fullscreen_style(self, True)  # 移除阴影与 WS_CAPTION，防 DWM 幽灵标题栏
            for videoWidget in self.videoWidgetList:
                videoWidget.fullScreen = True
            self.maximumToken = self.isMaximized()
            self.optionMenu.menuAction().setVisible(False)
            self.versionMenu.menuAction().setVisible(False)
            self.payMenu.menuAction().setVisible(False)
            if self.controlBarLayoutToken:
                self.controlContainer.hide()
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
                info(self, "导出预设", "导出完成", level="success")
            except Exception:
                logging.exception("json 配置导出失败")

    def importConfig(self):
        jsonPath = QFileDialog.getOpenFileName(self, "选择预设", None, "*.json")[0]
        if jsonPath:
            if self.configManager.import_from(jsonPath, self.config["layout"]):
                self.config = self.configManager.config
                self.liverPanel.addLiverRoomList(self.config["roomid"])
                info(self, "导入预设", "导入完成", level="success")

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
        # 保存悬浮窗位置（关闭时），下次弹出恢复到同一位置
        try:
            pop = self.popVideoWidgetList[id - 16] if 16 <= id < 16 + len(self.popVideoWidgetList) else None
            if pop is not None and pop.isVisible():
                self.config["popupGeometry"] = str(pop.saveGeometry().toBase64(), "ASCII")
        except Exception:
            pass
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
        from app.ui.check_update import updateReminder, checkUpdate

        self.updateReminder = updateReminder()
        self.updateReminder.noMoreSignal.connect(self.setNoMore)
        # 属性名避开类名 checkUpdate，防止遮蔽模块符号
        self._updateCheckerThread = checkUpdate(self.versionNumber)
        self._updateCheckerThread.update.connect(self.updateReminder._show)
        self._updateCheckerThread.start()


# 程序入口点
