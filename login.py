# -*- coding: utf-8 -*-
"""
B站扫码登录模块
使用 B站 passport API 生成二维码，用户扫码后获取登录凭据
支持账号管理：登录/登出、用户信息展示

核心设计：不使用显式状态机，从数据推导 UI
  _user_info 非空 → 已登录，显示账号面板
  _sessdata 非空且 _user_info 为空 → 验证中
  都为空 → 未登录，显示扫码面板
"""

import logging
import time
from urllib.parse import urlparse, parse_qs
import http_utils
import qrcode  # requirements.txt 已强制依赖 qrcode[pil]
from PySide6.QtCore import Qt, Signal, QTimer, QThread, QUrl
from PySide6.QtGui import QPixmap, QImage, QFont, QPainter, QPainterPath, QDesktopServices
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout, QFrame, QMessageBox

# 集中管理面板样式 — 颜色统一在此定义，不散落各处
_PANEL_QSS = """
#loggedInPanel {
    background: #2b3138;
    border: 1px solid #3a4048;
    border-radius: 12px;
}
#loginInfoLabel {
    color: #9aa4b0;
    font-size: 12px;
    background: transparent;
}
#loginStatTitle {
    color: #6b7684;
    font-size: 10px;
    background: transparent;
}
#loginStatValue {
    color: #e8edf2;
    font-size: 18px;
    font-weight: bold;
    background: transparent;
}
#loginAvatar {
    border-radius: 40px;
    border: 2px solid #3daee9;
    background: #2b3138;
}
#loginQrFrame {
    border: 1px solid #555;
    border-radius: 8px;
    background: white;
}
#qrStatusOk {
    color: #00cc66;
}
#qrStatusScan {
    color: #3399ff;
}
#qrStatusExpired {
    color: #ff5555;
}
"""

HEADERS = {
    **http_utils.DEFAULT_HEADERS,
    "Referer": "https://www.bilibili.com",
}


class FetchUserInfo(QThread):
    """后台验证 session 并获取用户信息

    信号 userInfo 返回值约定：
    - {'uid':..., 'uname':..., ...}  → 验证成功
    - {'_expired': True}             → API 明确返回未登录
    - {'_error': True}               → 网络错误，session 可能仍有效
    """

    userInfo = Signal(dict)

    def __init__(self):
        super().__init__()
        self.sessdata = ""

    def run(self):
        try:
            cookies = {"SESSDATA": self.sessdata} if self.sessdata else {}
            resp = http_utils.get(
                "https://api.bilibili.com/x/web-interface/nav", headers=HEADERS, cookies=cookies, timeout=4
            )
            data = resp.json()
            if data["code"] == 0 and data["data"].get("isLogin"):
                info = data["data"]
                self.userInfo.emit(
                    {
                        "uid": info["mid"],
                        "uname": info["uname"],
                        "face": info.get("face", ""),
                        "level": info.get("level_info", {}).get("current_level", 0),
                        "coins": info.get("money", 0),
                        "bcoins": info.get("wallet", {}).get("bcoin_balance", 0),
                        "following": info.get("following", 0),
                        "vip": info.get("vip", {}),
                    }
                )
            else:
                logging.warning(f"session 验证失败: code={data['code']}")
                self.userInfo.emit({"_expired": True})
        except Exception:
            logging.exception("验证登录状态失败（网络错误）")
            self.userInfo.emit({"_error": True})


class FetchAvatar(QThread):
    """后台下载头像（线程安全：用 QImage 跨线程，主线程转 QPixmap）"""

    avatarReady = Signal(QImage)

    def __init__(self):
        super().__init__()
        self.url = ""

    def run(self):
        if not self.url:
            return
        try:
            r = http_utils.get(self.url, timeout=8, retries=2, retry_backoff=1.0)
            qimage = QImage.fromData(r.content)
            if not qimage.isNull():
                self.avatarReady.emit(qimage)
        except Exception:
            logging.exception("下载头像失败（网络超时，将在下次打开账号面板时重试）")


class FetchQRCode(QThread):
    """后台获取二维码（避免阻塞主线程）"""

    qrcodeReady = Signal(str, str)  # (qrcode_key, url)
    fetchError = Signal(str)  # 错误消息

    def run(self):
        try:
            resp = http_utils.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate", headers=HEADERS, timeout=4
            )
            data = resp.json()
            if data["code"] != 0:
                self.fetchError.emit(f"获取失败: {data['message']}")
                return
            self.qrcodeReady.emit(data["data"]["qrcode_key"], data["data"]["url"])
        except Exception:
            logging.exception("获取二维码失败")
            self.fetchError.emit("网络错误，请点击刷新")


class PollLoginStatus(QThread):
    """后台轮询登录状态（避免阻塞主线程）"""

    loginSuccess = Signal(object, dict)  # (response, result_data)
    qrExpired = Signal()
    qrScanned = Signal()
    pollError = Signal()

    def __init__(self):
        super().__init__()
        self.qrcode_key = ""

    def run(self):
        if not self.qrcode_key:
            return
        try:
            resp = http_utils.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": self.qrcode_key},
                headers=HEADERS,
                timeout=4,
            )
            result = resp.json()["data"]
            code = result["code"]

            if code == 0:
                self.loginSuccess.emit(resp, result)
            elif code == 86038:
                self.qrExpired.emit()
            elif code == 86090:
                self.qrScanned.emit()
        except Exception:
            logging.exception("轮询登录状态失败")
            self.pollError.emit()


# ---------------------------------------------------------------------------
# QRLoginWidget
# ---------------------------------------------------------------------------


class QRLoginWidget(QWidget):
    """扫码登录 / 账号管理窗口

    信号:
      sessionData(str)    登录/登出时发射 SESSDATA（空串=登出）
      login(bool)         登录状态变化
      credentialReady(dict) 完整凭据（SESSDATA, bili_jct 等）
      userInfoReady(dict) 用户信息就绪
    """

    sessionData = Signal(str)
    login = Signal(bool)
    credentialReady = Signal(dict)
    userInfoReady = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("B站账号")
        self.setFixedSize(400, 580)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        # ---- 核心数据（UI 从这些字段推导）----
        self._sessdata = ""  # 有值 = 有凭据
        self._user_info = {}  # 有值 = 已确认登录
        self._avatarPixmap = None
        self._qrcode_key = ""
        self._credential = {}
        self._destructiveGuardUntil = 0.0
        # 主窗口就绪门闩：启动早期下载的头像/等级图标先缓存，
        # 等主窗口 OpenGL 初始化完成后才应用（替代旧的 thread.wait 阻塞方案）
        self._paintSafe = False
        self._pendingAvatar = False
        self._pendingLevelIcon = False

        # ---- 后台线程 ----
        self._levelIconThread = None
        self._fetchUserInfo = FetchUserInfo()
        self._fetchUserInfo.userInfo.connect(self._onUserInfo)
        self._fetchAvatar = FetchAvatar()
        self._fetchAvatar.avatarReady.connect(self._onAvatarReady)
        self._fetchQRCodeThread = FetchQRCode()
        self._fetchQRCodeThread.qrcodeReady.connect(self._onQRCodeReady)
        self._fetchQRCodeThread.fetchError.connect(self._onQRCodeError)
        self._pollLoginThread = PollLoginStatus()
        self._pollLoginThread.loginSuccess.connect(self._onQRLoginSuccess)
        self._pollLoginThread.qrExpired.connect(self._onQRExpired)
        self._pollLoginThread.qrScanned.connect(self._onQRScanned)

        # ---- 布局 ----
        self._mainLayout = QVBoxLayout(self)
        self._mainLayout.setAlignment(Qt.AlignCenter)
        self._mainLayout.setSpacing(10)
        self._mainLayout.setContentsMargins(16, 16, 16, 16)
        self.setStyleSheet(_PANEL_QSS)

        self._buildLoggedInPanel()
        self._buildVerifyingPanel()
        self._buildQRPanel()

        # 轮询定时器（仅触发后台线程，不阻塞主线程）
        self._pollTimer = QTimer(self)
        self._pollTimer.timeout.connect(self._doPollLogin)
        self._pollTimer.setInterval(2000)

    # ================================================================
    # UI 构建（只在 __init__ 中调用一次）
    # ================================================================

    def _buildLoggedInPanel(self):
        self._loggedInPanel = QFrame()
        self._loggedInPanel.setObjectName("loggedInPanel")
        lay = QVBoxLayout(self._loggedInPanel)
        lay.setSpacing(12)
        lay.setContentsMargins(24, 24, 24, 24)

        # 头像
        self._avatarLabel = QLabel()
        self._avatarLabel.setFixedSize(80, 80)
        self._avatarLabel.setAlignment(Qt.AlignCenter)
        self._resetAvatarPlaceholder()
        lay.addWidget(self._avatarLabel, alignment=Qt.AlignCenter)

        # 用户名
        self._unameLabel = QLabel()
        self._unameLabel.setFont(QFont("微软雅黑", 16, QFont.Bold))
        self._unameLabel.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._unameLabel)

        # 等级图标 + UID/等级/大会员信息（同一行）
        self._levelIconLabel = QLabel()
        self._levelIconLabel.setFixedSize(30, 16)
        self._levelIconLabel.setAlignment(Qt.AlignCenter)
        self._infoLabel = QLabel()
        self._infoLabel.setObjectName("loginInfoLabel")
        self._infoLabel.setAlignment(Qt.AlignCenter)
        infoRow = QHBoxLayout()
        infoRow.setSpacing(6)
        infoRow.addStretch()
        infoRow.addWidget(self._levelIconLabel)
        infoRow.addWidget(self._infoLabel)
        infoRow.addStretch()
        lay.addLayout(infoRow)

        # 数据行（横排三列）
        stats = QHBoxLayout()
        stats.setSpacing(8)
        self._coinLabel = self._makeStatCell("硬币", stats)
        self._bcoinLabel = self._makeStatCell("B币", stats)
        self._followLabel = self._makeStatCell("关注", stats)
        lay.addLayout(stats)

        lay.addSpacing(8)

        # 操作按钮 — 全部走全局 qdark 主题，不再内联配色
        for text, slot in [
            ("打开 B站 个人空间", self._openUserSpace),
            ("切换账号", self._onSwitchAccount),
            ("退出登录", self._onLogout),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(36)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
            lay.addSpacing(2)

        self._loggedInPanel.hide()
        self._mainLayout.addWidget(self._loggedInPanel)

    @staticmethod
    def _makeStatCell(title, parent_layout):
        """横排统计单元格：上标题下数值"""
        cell = QVBoxLayout()
        cell.setSpacing(2)
        t = QLabel(title)
        t.setObjectName("loginStatTitle")
        t.setAlignment(Qt.AlignCenter)
        v = QLabel("--")
        v.setObjectName("loginStatValue")
        v.setAlignment(Qt.AlignCenter)
        cell.addWidget(t)
        cell.addWidget(v)
        parent_layout.addLayout(cell)
        return v

    def _buildVerifyingPanel(self):
        self._verifyingPanel = QWidget()
        lay = QVBoxLayout(self._verifyingPanel)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(16)

        self._verifyingLabel = QLabel("正在验证登录状态...")
        self._verifyingLabel.setFont(QFont("微软雅黑", 12))
        self._verifyingLabel.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._verifyingLabel)

        self._verifyingHint = QLabel("请稍候")
        self._verifyingHint.setFont(QFont("微软雅黑", 10))
        self._verifyingHint.setObjectName("loginInfoLabel")
        self._verifyingHint.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._verifyingHint)

        retryBtn = QPushButton("重试")
        retryBtn.setFixedHeight(36)
        retryBtn.setCursor(Qt.PointingHandCursor)
        retryBtn.clicked.connect(self._retryVerify)
        lay.addWidget(retryBtn)

        self._verifyingPanel.hide()
        self._mainLayout.addWidget(self._verifyingPanel)

    def _buildQRPanel(self):
        self._qrPanel = QWidget()
        lay = QVBoxLayout(self._qrPanel)
        lay.setAlignment(Qt.AlignCenter)
        lay.setSpacing(12)

        self._qrTitle = QLabel("请使用 Bilibili 客户端扫码登录")
        self._qrTitle.setFont(QFont("微软雅黑", 12, QFont.Bold))
        self._qrTitle.setAlignment(Qt.AlignCenter)
        self._qrTitle.setWordWrap(True)
        lay.addWidget(self._qrTitle)

        self._qrLabel = QLabel()
        self._qrLabel.setFixedSize(260, 260)
        self._qrLabel.setAlignment(Qt.AlignCenter)
        self._qrLabel.setObjectName("loginQrFrame")
        lay.addWidget(self._qrLabel, alignment=Qt.AlignCenter)

        self._qrStatus = QLabel()
        self._qrStatus.setFont(QFont("微软雅黑", 10))
        self._qrStatus.setAlignment(Qt.AlignCenter)
        self._qrStatus.setWordWrap(True)
        lay.addWidget(self._qrStatus)

        refreshBtn = QPushButton("刷新二维码")
        refreshBtn.setFixedHeight(36)
        refreshBtn.setCursor(Qt.PointingHandCursor)
        refreshBtn.clicked.connect(self._fetchQRCode)
        lay.addWidget(refreshBtn)

        self._qrPanel.hide()
        self._mainLayout.addWidget(self._qrPanel)

    # ================================================================
    # 唯一的 UI 同步入口 — 从数据推导该显示什么
    # ================================================================

    def _syncUI(self):
        """根据 _user_info / _sessdata 决定显示哪个面板。
        这是所有面板切换的唯一入口。"""
        logging.info(
            f"[LOGIN] _syncUI: _user_info={bool(self._user_info)}, "
            f"_sessdata={'有' if self._sessdata else '空'}(len={len(self._sessdata)})"
        )
        self._loggedInPanel.hide()
        self._verifyingPanel.hide()
        self._qrPanel.hide()
        self._pollTimer.stop()

        if self._user_info:
            uname = self._user_info.get("uname", "已登录")
            uid = self._user_info.get("uid", "")
            level = self._user_info.get("level", 0)
            coins = self._user_info.get("coins", 0)
            bcoins = float(self._user_info.get("bcoins", 0))
            following = self._user_info.get("following", 0)
            vip_info = self._user_info.get("vip", {})

            self._unameLabel.setText(uname)
            info_parts = [f"UID: {uid}", f"Lv.{level}"]
            if vip_info and vip_info.get("status") == 1:
                vt = "年度" if vip_info.get("type") == 2 else "月度"
                info_parts.append(f"大会员·{vt}")
            self._infoLabel.setText("  ·  ".join(info_parts))
            # 更新等级图标
            self._downloadLevelIcon(level)

            self._coinLabel.setText(str(coins))
            self._bcoinLabel.setText(f"{bcoins:.1f}" if bcoins == int(bcoins) else str(int(bcoins)))
            self._followLabel.setText(str(following))

            if self._avatarPixmap and not self._avatarPixmap.isNull():
                self._applyAvatar()
            else:
                self._resetAvatarPlaceholder()

            self.setWindowTitle(f"B站账号 - {uname}")
            self._loggedInPanel.show()

        elif self._sessdata:
            # ---- 有凭据，验证中 ----
            self.setWindowTitle("B站账号 - 验证中")
            self._verifyingLabel.setText("正在验证登录状态...")
            self._verifyingHint.setText("请稍候")
            self._verifyingPanel.show()
            # 如果线程不在跑，启动验证
            if not self._fetchUserInfo.isRunning():
                self._startVerify()

        else:
            # ---- 无凭据，扫码 ----
            self.setWindowTitle("B站账号")
            self._qrPanel.show()
            self._fetchQRCode()

    # ================================================================
    # 公开接口
    # ================================================================

    def show(self):
        self._destructiveGuardUntil = time.monotonic() + 0.35
        super().show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.ActiveWindowFocusReason)
        self._syncUI()

    def setSessionData(self, sessdata):
        """从外部（如配置恢复）设置 SESSDATA 并启动验证

        兼容旧版 config 中保存的 URL 编码值（%2C → , 等）
        """
        if not sessdata:
            return
        # 防御性 URL 解码：旧版本可能保存了 URL 编码的 SESSDATA
        if "%" in sessdata:
            from urllib.parse import unquote

            decoded = unquote(sessdata)
            logging.info(f"[LOGIN] setSessionData: URL 解码 {sessdata[:30]}... → {decoded[:30]}...")
            sessdata = decoded
        self._sessdata = sessdata
        self._startVerify()

    def isLoggedIn(self):
        return bool(self._user_info)

    # ================================================================
    # 内部：验证流程
    # ================================================================

    def _startVerify(self):
        """启动后台验证（如果未在运行）"""
        self._fetchUserInfo.sessdata = self._sessdata
        if not self._fetchUserInfo.isRunning():
            self._fetchUserInfo.start()

    def _retryVerify(self):
        """重试按钮"""
        if self._sessdata:
            self._verifyingLabel.setText("正在验证登录状态...")
            self._verifyingHint.setText("请稍候")
            self._startVerify()

    def _isGhostClick(self, action_name):
        if time.monotonic() < self._destructiveGuardUntil:
            logging.warning(f"[LOGIN] 忽略窗口刚打开后的误触动作: {action_name}")
            return True
        return False

    def _confirmAction(self, title, message):
        return (
            QMessageBox.question(
                self,
                title,
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            == QMessageBox.Yes
        )

    def _performLogout(self):
        self._sessdata = ""
        self._user_info = {}
        self._credential = {}
        self._avatarPixmap = None
        self._resetAvatarPlaceholder()
        self.sessionData.emit("")
        self.login.emit(False)
        self._syncUI()

    def _downloadLevelIcon(self, level):
        """后台下载 B站等级图标

        下载完成后不立即 setPixmap：若主窗口 OpenGL 初始化尚未完成，
        先挂起待主窗口就绪后再应用（替代旧方案的 thread.wait(5000) 阻塞）。
        """
        # 去重保护：重复调用时若上次下载仍在进行，直接复用，
        # 防止覆盖引用导致 running 状态的线程被 GC 析构（原生崩溃）
        if self._levelIconThread is not None and self._levelIconThread.isRunning():
            return

        class _FetchLevelIcon(QThread):
            iconReady = Signal(QPixmap)

            def __init__(self, level):
                super().__init__()
                self.level = level

            def run(self):
                try:
                    url = f"https://s1.hdslb.com/bfs/static/jinkela/long/images/lv_{self.level}.png"
                    r = http_utils.get(url, timeout=10)
                    img = QImage.fromData(r.content)
                    if not img.isNull():
                        pm = QPixmap.fromImage(img).scaled(30, 16, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        self.iconReady.emit(pm)
                except Exception:
                    logging.debug("等级图标下载失败", exc_info=True)

        thread = _FetchLevelIcon(level)
        thread.iconReady.connect(self._onLevelIconReady)
        # 保存为成员：防止函数返回后线程对象被 GC 析构（running 状态析构会原生崩溃）
        self._levelIconThread = thread
        thread.start()

    def _onLevelIconReady(self, pixmap):
        self._levelIconPixmap = pixmap
        if self._paintSafe:
            self._applyLevelIcon()
        else:
            self._pendingLevelIcon = True

    def _applyLevelIcon(self):
        if self._levelIconPixmap and not self._levelIconPixmap.isNull():
            self._levelIconLabel.setPixmap(self._levelIconPixmap)

    def _openUserSpace(self):
        uid = self._user_info.get("uid")
        if not uid:
            logging.warning("[LOGIN] 当前没有可打开的用户 UID")
            return
        QDesktopServices.openUrl(QUrl(f"https://space.bilibili.com/{uid}"))

    def _onSwitchAccount(self):
        if self._isGhostClick("switch-account"):
            return
        if not self._confirmAction("切换账号", "切换账号需要先退出当前登录，是否继续？"):
            return
        self._performLogout()

    def _onUserInfo(self, info):
        """FetchUserInfo 回调 — 区分成功/过期/网络错误"""
        logging.info(
            f"[LOGIN] _onUserInfo 回调: keys={list(info.keys())}, "
            f"_expired={info.get('_expired')}, _error={info.get('_error')}"
        )
        if info.get("_expired"):
            # API 明确说未登录 → 清除凭据
            logging.warning("session 已过期，需要重新登录")
            self._sessdata = ""
            self._user_info = {}
            self._avatarPixmap = None
            self.sessionData.emit("")
            self.login.emit(False)

        elif info.get("_error"):
            # 网络问题 → 保留 sessdata 不清除
            logging.warning("网络错误，保留现有凭据")
            if self.isVisible():
                self._verifyingLabel.setText("网络错误")
                self._verifyingHint.setText("请点击重试")

            # 不清除 _sessdata，不发信号，不切面板
            return

        else:
            # 验证成功
            self._user_info = info
            uname = info.get("uname", "")
            logging.info(f"登录用户: {uname} (UID: {info.get('uid', '?')})")
            self.userInfoReady.emit(info)

            # 下载头像
            face_url = info.get("face", "")
            if face_url:
                self._fetchAvatar.url = face_url
                if not self._fetchAvatar.isRunning():
                    self._fetchAvatar.start()
            # 等级图标由 _syncUI 统一触发（本函数末尾会调用），此处不重复下载

        # 成功和过期都需要刷新 UI
        if self.isVisible():
            self._syncUI()

    def _onAvatarReady(self, qimage):
        """头像下载完成 → 裁剪为圆形并缓存（主窗口就绪前挂起应用）"""
        pixmap = QPixmap.fromImage(qimage)
        scaled = pixmap.scaled(80, 80, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._avatarPixmap = self._makeCircularPixmap(scaled, 80)
        if self._paintSafe:
            self._applyAvatar()
        else:
            self._pendingAvatar = True

    # ================================================================
    # 内部：QR 登录流程
    # ================================================================

    def _fetchQRCode(self):
        """获取并显示二维码（后台线程执行，不阻塞 UI）"""
        self._qrStatus.setText("正在获取二维码...")
        self._qrStatus.setProperty("class", "")
        self._pollTimer.stop()
        if not self._fetchQRCodeThread.isRunning():
            self._fetchQRCodeThread.start()

    def _onQRCodeReady(self, qrcode_key, url):
        """二维码获取成功回调"""
        self._qrcode_key = qrcode_key
        self._renderQR(url)
        self._qrStatus.setText("请使用 Bilibili 客户端扫描二维码")
        self._pollTimer.start()

    def _onQRCodeError(self, msg):
        """二维码获取失败回调"""
        self._qrStatus.setText(msg)

    def _renderQR(self, url):
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        if hasattr(img, "convert"):
            # PIL 后端：直接转 RGB 取像素
            img = img.convert("RGB")
            raw = img.tobytes("raw", "RGB")
            qimg = QImage(raw, img.width, img.height, img.width * 3, QImage.Format_RGB888)
        else:
            # pypng 后端：经 BytesIO 中转
            import io

            buf = io.BytesIO()
            img.save(buf, "PNG")
            qimg = QImage.fromData(buf.getvalue())
        pm = QPixmap.fromImage(qimg)
        self._qrLabel.setPixmap(pm.scaled(self._qrLabel.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _doPollLogin(self):
        """定时器回调：启动后台轮询线程（不阻塞主线程）"""
        if not self._qrcode_key:
            return
        if self._pollLoginThread.isRunning():
            return  # 上一次轮询还没结束，跳过
        self._pollLoginThread.qrcode_key = self._qrcode_key
        self._pollLoginThread.start()

    def _onQRExpired(self):
        """二维码过期回调"""
        self._pollTimer.stop()
        self._qrStatus.setText("二维码已过期，请点击刷新")
        self._qrStatus.setObjectName("qrStatusExpired")

    def _onQRScanned(self):
        """已扫码回调"""
        self._qrStatus.setText("已扫码，请在手机上确认登录")
        self._qrStatus.setObjectName("qrStatusScan")

    def _onQRLoginSuccess(self, resp, result):
        """扫码登录成功处理"""
        self._pollTimer.stop()
        # 解析凭据（URL 解码）
        url = result.get("url", "")
        self._credential = self._parseCookiesFromURL(url)
        logging.info(f"[LOGIN] 登录成功 URL 参数: {list(self._credential.keys())}")

        # 提取 SESSDATA：优先 response cookies，其次 URL 参数
        sessdata = ""
        source = ""
        for cookie in resp.cookies:
            if cookie.name == "SESSDATA":
                sessdata = cookie.value
                source = "resp.cookies"
                break
        if not sessdata:
            sessdata = self._credential.get("SESSDATA", "")
            source = "URL参数"

        logging.info(f"[LOGIN] SESSDATA 来源={source}, 长度={len(sessdata)}, 前20字符={sessdata[:20]}")

        if not sessdata:
            self._qrStatus.setText("登录成功但获取凭据失败，请重试")
            logging.error("[LOGIN] 登录成功但 SESSDATA 为空!")
            return

        self._sessdata = sessdata
        logging.info(f"[LOGIN] 发射 sessionData 信号 (len={len(sessdata)})")
        self.sessionData.emit(sessdata)
        self.login.emit(True)
        self.credentialReady.emit(self._credential)

        self._qrStatus.setText("登录成功！正在获取用户信息...")
        self._qrStatus.setObjectName("qrStatusOk")

        # 启动用户信息验证
        self._startVerify()

    # ================================================================
    # 登出
    # ================================================================

    def _onLogout(self):
        if self._isGhostClick("logout"):
            return
        if not self._confirmAction("退出登录", "确定要退出当前 B站账号吗？"):
            return
        self._performLogout()

    # ================================================================
    # 工具方法
    # ================================================================

    def _resetAvatarPlaceholder(self):
        self._avatarLabel.setPixmap(QPixmap())
        self._avatarLabel.setText("")
        self._avatarLabel.setObjectName("loginAvatar")

    def _applyAvatar(self):
        """应用头像（主窗口就绪后调用）"""
        if self._avatarPixmap and not self._avatarPixmap.isNull():
            self._avatarLabel.setPixmap(self._avatarPixmap)
            self._avatarLabel.setObjectName("loginAvatar")

    def setMainWindowReady(self):
        """主窗口初始化完成回调 — 此后才安全执行 setPixmap 等重绘操作

        替代旧的 thread.wait(5000) 阻塞方案：启动早期到达的头像/等级图标
        先缓存，待 OpenGL 初始化窗口期结束后统一应用。
        """
        self._paintSafe = True
        if self._pendingAvatar:
            self._pendingAvatar = False
            self._applyAvatar()
        if self._pendingLevelIcon:
            self._pendingLevelIcon = False
            self._applyLevelIcon()

    @staticmethod
    def _makeCircularPixmap(src, size):
        target = QPixmap(size, size)
        target.fill(Qt.transparent)
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        painter.drawPixmap((size - src.width()) // 2, (size - src.height()) // 2, src)
        painter.end()
        return target

    @staticmethod
    def _parseCookiesFromURL(url):
        """从登录成功 URL 解析参数（自动 URL 解码）"""
        result = {}
        parsed = urlparse(url)
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items():
            result[key] = values[0] if values else ""
        return result

    def closeEvent(self, event):
        self._pollTimer.stop()
        # 等待所有后台线程退出后再关闭窗口
        # （线程在 running 状态下被析构会触发 STATUS_STACK_BUFFER_OVERRUN 原生崩溃）
        threads = [
            self._fetchUserInfo,
            self._fetchAvatar,
            self._fetchQRCodeThread,
            self._pollLoginThread,
        ]
        if self._levelIconThread is not None:
            threads.append(self._levelIconThread)
        for thread in threads:
            if thread.isRunning():
                thread.wait(6000)
        super().closeEvent(event)
