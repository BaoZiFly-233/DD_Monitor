# -*- coding: utf-8 -*-
"""
B站扫码登录模块 — 极简版
使用 B站 passport API 生成二维码，用户扫码后获取登录凭据

设计：登录入口收敛到主窗口菜单栏「B站账号」，
本模块只提供两种能力：
  1. LoginDialog — 极简扫码小窗（二维码 + 状态 + 刷新/关闭）
  2. 后台验证链路（setSessionData → FetchUserInfo），
     供启动时静默验证 session 是否有效
"""

import logging
from urllib.parse import urlparse, parse_qs

from app.core import http_utils
import qrcode  # requirements.txt 已强制依赖 qrcode[pil]
from app.ui.title_bar import FluentDialog
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout
from qfluentwidgets_pro import PushButton, PrimaryPushButton

HEADERS = {
    **http_utils.DEFAULT_HEADERS,
    "Referer": "https://www.bilibili.com",
}

#: 登录成功响应里需要落盘保存的 cookie 名。扫码登录的跳转 URL 参数并不齐全
#: （bili_jct / DedeUserID / buvid 等通常在 Set-Cookie 里），只解析 URL 会导致
#: 保存的凭据缺 bili_jct，后续 check_refresh() 因缺少 CSRF 令牌而永远跳过续期。
_CREDENTIAL_COOKIES = (
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "buvid3",
    "buvid4",
    "ac_time_value",
)


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
                "https://api.bilibili.com/x/web-interface/nav",
                headers=HEADERS,
                cookies=cookies,
                timeout=4,
                retries=2,
                retry_backoff=1.0,
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
                        "vip": info.get("vip", {}),
                    }
                )
            else:
                logging.warning(f"session 验证失败: code={data['code']}")
                self.userInfo.emit({"_expired": True})
        except Exception:
            logging.exception("验证登录状态失败（网络错误）")
            self.userInfo.emit({"_error": True})


class FetchQRCode(QThread):
    """后台获取二维码（避免阻塞主线程）"""

    qrcodeReady = Signal(str, str)  # (qrcode_key, url)
    fetchError = Signal(str)  # 错误消息

    def run(self):
        try:
            resp = http_utils.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                headers=HEADERS,
                timeout=4,
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


class LoginDialog(FluentDialog):
    """极简扫码登录窗口

    信号（与主窗口对接）：
      sessionData(str)    登录/登出时发射 SESSDATA（空串=登出）
      login(bool)         登录状态变化
      credentialReady(dict) 完整凭据（SESSDATA, bili_jct 等）
      userInfoReady(dict) 用户信息就绪
    """

    sessionData = Signal(str)
    login = Signal(bool)
    credentialReady = Signal(dict)
    userInfoReady = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent=parent, title="扫码登录", maximize_enabled=False)
        self.setFixedSize(320, 420)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        # ---- 核心数据 ----
        self._sessdata = ""  # 有值 = 有凭据（用于启动时静默验证）
        self._qrcode_key = ""
        self._credential = {}
        self._justLoggedIn = False  # 刚扫码成功：验证失败不登出（凭据是新拿到的）

        # ---- 后台线程（全部保存为成员，防止 running 状态被 GC 析构崩溃）----
        self._fetchUserInfo = FetchUserInfo()
        self._fetchUserInfo.userInfo.connect(self._onUserInfo)
        self._fetchQRCodeThread = FetchQRCode()
        self._fetchQRCodeThread.qrcodeReady.connect(self._onQRCodeReady)
        self._fetchQRCodeThread.fetchError.connect(self._onQRCodeError)
        self._pollLoginThread = PollLoginStatus()
        self._pollLoginThread.loginSuccess.connect(self._onQRLoginSuccess)
        self._pollLoginThread.qrExpired.connect(self._onQRExpired)
        self._pollLoginThread.qrScanned.connect(self._onQRScanned)

        # 轮询定时器
        self._pollTimer = QTimer(self)
        self._pollTimer.timeout.connect(self._doPollLogin)
        self._pollTimer.setInterval(2000)

        # ---- 布局（最基本：标题 + 二维码 + 状态 + 按钮）----
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.setContentsMargins(24, 24, 24, 24)

        tip = QLabel("使用 Bilibili 客户端扫码登录")
        tip.setFont(QFont("微软雅黑", 11, QFont.Bold))
        tip.setAlignment(Qt.AlignCenter)
        lay.addWidget(tip)

        self._qrLabel = QLabel()
        self._qrLabel.setFixedSize(240, 240)
        self._qrLabel.setAlignment(Qt.AlignCenter)
        self._qrLabel.setStyleSheet("border: 1px solid #555; border-radius: 8px; background: white;")
        lay.addWidget(self._qrLabel, alignment=Qt.AlignCenter)

        self._qrStatus = QLabel("正在获取二维码...")
        self._qrStatus.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._qrStatus)

        btnRow = QHBoxLayout()
        btnRow.setSpacing(8)
        refreshBtn = PrimaryPushButton("刷新二维码")
        refreshBtn.clicked.connect(self._fetchQRCode)
        closeBtn = PushButton("关闭")
        closeBtn.clicked.connect(self.close)
        btnRow.addWidget(refreshBtn)
        btnRow.addWidget(closeBtn)
        lay.addLayout(btnRow)

    # ================================================================
    # 公开接口
    # ================================================================

    def showEvent(self, event):
        super().showEvent(event)
        self._fetchQRCode()

    def setSessionData(self, sessdata):
        """启动时静默验证已保存的 session（不弹窗）"""
        if not sessdata:
            return
        # 防御性 URL 解码：旧版本可能保存了 URL 编码的 SESSDATA
        if "%" in sessdata:
            from urllib.parse import unquote

            sessdata = unquote(sessdata)
        self._sessdata = sessdata
        self._startVerify()

    def _startVerify(self):
        self._fetchUserInfo.sessdata = self._sessdata
        if not self._fetchUserInfo.isRunning():
            self._fetchUserInfo.start()

    def _onUserInfo(self, info):
        """验证回调：成功发 userInfoReady；过期清凭据发登出信号

        刚扫码成功后的验证失败不登出（凭据是新拿到的，可能只是网络抖动），
        保留凭据等下次启动重新验证。
        """
        if info.get("_expired"):
            if self._justLoggedIn:
                logging.warning("登录后验证返回未登录，保留凭据待下次启动重试")
            else:
                logging.warning("session 已过期，需要重新登录")
                self._sessdata = ""
                self.sessionData.emit("")
                self.login.emit(False)
        elif info.get("_error"):
            logging.warning("网络错误，保留现有凭据")
        else:
            logging.info(f"登录用户: {info.get('uname', '?')} (UID: {info.get('uid', '?')})")
            self.userInfoReady.emit(info)
        # 验证流程已结束，"刚扫码登录"保护期到此为止
        # 否则 _justLoggedIn 永不复位，session 过期后永远走"保留凭据"分支，永不登出
        self._justLoggedIn = False

    # ================================================================
    # QR 登录流程
    # ================================================================

    def _fetchQRCode(self):
        """获取并显示二维码（后台线程执行，不阻塞 UI）"""
        self._qrStatus.setText("正在获取二维码...")
        self._qrStatus.setStyleSheet("")
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
        self._qrStatus.setStyleSheet("color: #CC0000;")

    def _onQRScanned(self):
        """已扫码回调"""
        self._qrStatus.setText("已扫码，请在手机上确认登录")
        self._qrStatus.setStyleSheet("color: #3399FF;")

    def _onQRLoginSuccess(self, resp, result):
        """扫码登录成功处理 — 提取凭据、发信号、自动关闭"""
        self._pollTimer.stop()
        # 解析凭据（URL 解码）
        url = result.get("url", "")
        self._credential = self._parseCookiesFromURL(url)

        # 提取 SESSDATA：优先 response cookies，其次 URL 参数
        sessdata = ""
        for cookie in resp.cookies:
            if cookie.name == "SESSDATA":
                sessdata = cookie.value
                break
        if not sessdata:
            sessdata = self._credential.get("SESSDATA", "")

        if not sessdata:
            self._qrStatus.setText("登录成功但获取凭据失败，请重试")
            logging.error("[LOGIN] 登录成功但 SESSDATA 为空!")
            return

        # 把实际取到的 SESSDATA 写回 credential（URL 参数里可能没有），
        # 否则 credentialReady 发出的凭据不含 sessdata，主窗口 updateCredential
        # 会用空值覆盖 config["sessionData"]，导致菜单退回"扫码登录"
        self._credential["SESSDATA"] = sessdata

        # 从 Set-Cookie 补齐其余凭据：bili_jct 等通常只在响应 cookie 里，
        # 缺了会导致保存的凭据无法续期（check_refresh 永远因缺 bili_jct 跳过）。
        # URL 参数已有的值优先保留，不覆盖。
        for cookie in resp.cookies:
            if cookie.name in _CREDENTIAL_COOKIES and not self._credential.get(cookie.name):
                self._credential[cookie.name] = cookie.value

        self._sessdata = sessdata
        logging.info(f"[LOGIN] 发射 sessionData 信号 (len={len(sessdata)})")
        self._justLoggedIn = True
        self.sessionData.emit(sessdata)
        self.login.emit(True)
        self.credentialReady.emit(self._credential)
        # 启动用户信息验证（驱动主窗口更新标题/关注列表）
        self._startVerify()
        # 登录成功自动关闭扫码窗
        self.close()

    # ================================================================
    # 工具方法
    # ================================================================

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
        # 并行等待三个线程，避免串行 wait 造成最长 18s 的关闭延迟
        _threads = [t for t in (self._fetchUserInfo, self._fetchQRCodeThread, self._pollLoginThread) if t.isRunning()]
        if _threads:
            import threading

            _waiter = threading.Thread(
                target=lambda: [t.wait(6000) for t in _threads],
                daemon=True,
            )
            _waiter.start()
            _waiter.join(7000)
        super().closeEvent(event)
