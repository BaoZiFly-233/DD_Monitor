# -*- coding: utf-8 -*-
"""
B站扫码登录模块 - 轻量级实现
使用 B站 passport API 生成二维码，用户扫码后获取登录凭据
替代原有的 QWebEngineView 浏览器登录方式
"""
import logging
import requests
from PySide6.QtCore import Qt, Signal, QTimer, QThread
from PySide6.QtGui import QPixmap, QImage, QFont
from PySide6.QtWidgets import QWidget, QLabel, QPushButton, QVBoxLayout, QHBoxLayout

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com',
}


class FetchUserInfo(QThread):
    """后台获取用户信息"""
    userInfo = Signal(dict)  # {'uid': int, 'uname': str, 'face': str}

    def __init__(self, sessdata=''):
        super().__init__()
        self.sessdata = sessdata

    def run(self):
        try:
            cookies = {'SESSDATA': self.sessdata} if self.sessdata else {}
            resp = requests.get(
                'https://api.bilibili.com/x/web-interface/nav',
                headers=HEADERS, cookies=cookies, timeout=10
            )
            data = resp.json()
            if data['code'] == 0 and data['data'].get('isLogin'):
                info = data['data']
                self.userInfo.emit({
                    'uid': info['mid'],
                    'uname': info['uname'],
                    'face': info.get('face', ''),
                })
            else:
                logging.warning(f'获取用户信息失败: code={data["code"]}')
        except Exception:
            logging.exception('获取用户信息失败')


class QRLoginWidget(QWidget):
    """扫码登录窗口

    信号:
    - sessionData(str): 登录成功后发射 SESSDATA
    - login(bool): 登录状态变化
    - userInfoReady(dict): 用户信息就绪 {'uid': int, 'uname': str, 'face': str}
    """
    sessionData = Signal(str)
    login = Signal(bool)
    credentialReady = Signal(dict)
    userInfoReady = Signal(dict)

    def __init__(self):
        super().__init__()
        self.setWindowTitle('扫码登录 Bilibili')
        self.setFixedSize(320, 480)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        self._qrcode_key = ''
        self._credential = {}
        self._logged_in = False
        self._sessdata = ''
        self._user_info = {}

        self._fetchUserInfo = FetchUserInfo()
        self._fetchUserInfo.userInfo.connect(self._onUserInfo)

        # 布局
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(10)

        self.titleLabel = QLabel('请使用 Bilibili 客户端扫码登录')
        self.titleLabel.setFont(QFont('微软雅黑', 11))
        self.titleLabel.setAlignment(Qt.AlignCenter)
        self.titleLabel.setWordWrap(True)
        layout.addWidget(self.titleLabel)

        # 用户信息面板（登录后显示）
        self.userPanel = QWidget()
        userLayout = QHBoxLayout(self.userPanel)
        userLayout.setContentsMargins(10, 5, 10, 5)
        self.avatarLabel = QLabel()
        self.avatarLabel.setFixedSize(48, 48)
        self.avatarLabel.setStyleSheet('border-radius: 24px; border: 2px solid #3daee9;')
        self.avatarLabel.setAlignment(Qt.AlignCenter)
        userLayout.addWidget(self.avatarLabel)
        self.unameLabel = QLabel('')
        self.unameLabel.setFont(QFont('微软雅黑', 12, QFont.Bold))
        userLayout.addWidget(self.unameLabel)
        self.userPanel.hide()
        layout.addWidget(self.userPanel)

        # 二维码区域
        self.qrLabel = QLabel()
        self.qrLabel.setFixedSize(260, 260)
        self.qrLabel.setAlignment(Qt.AlignCenter)
        self.qrLabel.setStyleSheet('border: 1px solid #555; background: white;')
        layout.addWidget(self.qrLabel, alignment=Qt.AlignCenter)

        self.statusLabel = QLabel('')
        self.statusLabel.setFont(QFont('微软雅黑', 10))
        self.statusLabel.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.statusLabel)

        self.refreshBtn = QPushButton('刷新二维码')
        self.refreshBtn.setFixedHeight(36)
        self.refreshBtn.setStyleSheet('background-color:#3daee9;border-width:1px')
        self.refreshBtn.clicked.connect(self._onRefreshClick)
        layout.addWidget(self.refreshBtn)

        # 轮询定时器
        self._pollTimer = QTimer(self)
        self._pollTimer.timeout.connect(self._pollLoginStatus)
        self._pollTimer.setInterval(2000)

    def show(self):
        super().show()
        if self._logged_in:
            self._showLoggedInState()
        else:
            self.fetchQRCode()

    def setSessionData(self, sessdata):
        """从外部（如配置恢复）设置 SESSDATA 并验证登录状态"""
        if sessdata:
            self._sessdata = sessdata
            self._fetchUserInfo.sessdata = sessdata
            if not self._fetchUserInfo.isRunning():
                self._fetchUserInfo.start()

    def fetchQRCode(self):
        """获取登录二维码"""
        self.userPanel.hide()
        self.qrLabel.show()
        self.statusLabel.setText('正在获取二维码...')
        self.statusLabel.setStyleSheet('')
        self.refreshBtn.setText('刷新二维码')
        self._pollTimer.stop()
        try:
            resp = requests.get(
                'https://passport.bilibili.com/x/passport-login/web/qrcode/generate',
                headers=HEADERS, timeout=10
            )
            data = resp.json()
            if data['code'] != 0:
                self.statusLabel.setText(f'获取失败: {data["message"]}')
                return
            qr_url = data['data']['url']
            self._qrcode_key = data['data']['qrcode_key']
            self._renderQRCode(qr_url)
            self.statusLabel.setText('请使用 Bilibili 客户端扫描二维码')
            self._pollTimer.start()
        except Exception:
            logging.exception('获取二维码失败')
            self.statusLabel.setText('网络错误，请点击刷新')

    def _renderQRCode(self, url):
        """将 URL 渲染为二维码图片"""
        if HAS_QRCODE:
            qr = qrcode.QRCode(version=1, box_size=8, border=2)
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color='black', back_color='white')
            img = img.convert('RGB')
            data = img.tobytes('raw', 'RGB')
            qimage = QImage(data, img.width, img.height, img.width * 3, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)
            self.qrLabel.setPixmap(pixmap.scaled(
                self.qrLabel.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.qrLabel.setText('请先安装 qrcode 库:\npip install qrcode[pil]')

    def _pollLoginStatus(self):
        """轮询扫码登录状态"""
        if not self._qrcode_key:
            return
        try:
            resp = requests.get(
                'https://passport.bilibili.com/x/passport-login/web/qrcode/poll',
                params={'qrcode_key': self._qrcode_key},
                headers=HEADERS, timeout=10
            )
            data = resp.json()['data']
            code = data['code']

            if code == 0:  # 登录成功
                self._pollTimer.stop()
                self._logged_in = True

                # 从 URL 参数中提取凭据
                url = data.get('url', '')
                self._credential = self._parseCookiesFromURL(url)

                # 从 response cookies 或 URL 参数中提取 SESSDATA
                sessdata = self._credential.get('SESSDATA', '')
                if not sessdata:
                    for cookie in resp.cookies:
                        if cookie.name == 'SESSDATA':
                            sessdata = cookie.value
                            break

                if sessdata:
                    self._sessdata = sessdata
                    self.sessionData.emit(sessdata)
                    self.login.emit(True)
                    self.credentialReady.emit(self._credential)

                    # 获取用户信息
                    self._fetchUserInfo.sessdata = sessdata
                    self._fetchUserInfo.start()

                    self.statusLabel.setText('登录成功！正在获取用户信息...')
                    self.statusLabel.setStyleSheet('color: #00CC00;')
                else:
                    self.statusLabel.setText('登录成功但获取凭据失败，请重试')
                    self._logged_in = False

            elif code == 86038:  # 二维码已失效
                self._pollTimer.stop()
                self.statusLabel.setText('二维码已过期，请点击刷新')
                self.statusLabel.setStyleSheet('color: #CC0000;')

            elif code == 86090:  # 已扫码未确认
                self.statusLabel.setText('已扫码，请在手机上确认登录')
                self.statusLabel.setStyleSheet('color: #3399FF;')

            elif code == 86101:  # 未扫码
                pass

        except Exception:
            logging.exception('轮询登录状态失败')

    def _onUserInfo(self, info):
        """用户信息获取成功"""
        self._user_info = info
        logging.info(f'登录用户: {info["uname"]} (UID: {info["uid"]})')
        self.userInfoReady.emit(info)
        self._showLoggedInState()
        QTimer.singleShot(2000, self.hide)

    def _showLoggedInState(self):
        """显示已登录状态"""
        self.qrLabel.hide()
        self.userPanel.show()
        uname = self._user_info.get('uname', '已登录')
        uid = self._user_info.get('uid', '')
        self.unameLabel.setText(f'{uname}\nUID: {uid}')
        self.avatarLabel.setText(uname[:1] if uname else '?')
        self.avatarLabel.setStyleSheet(
            'border-radius: 24px; border: 2px solid #00CC00; '
            'background-color: #3daee9; color: white; font-size: 20px;'
        )
        self.statusLabel.setText('已登录')
        self.statusLabel.setStyleSheet('color: #00CC00;')
        self.refreshBtn.setText('切换账号')
        self.titleLabel.setText('Bilibili 账号管理')

    def _onRefreshClick(self):
        """刷新按钮点击"""
        if self._logged_in:
            # 已登录状态下点击 = 切换账号
            self._logged_in = False
            self._user_info = {}
            self.userPanel.hide()
            self.qrLabel.show()
            self.titleLabel.setText('请使用 Bilibili 客户端扫码登录')
        self.fetchQRCode()

    @staticmethod
    def _parseCookiesFromURL(url: str) -> dict:
        """从登录成功的 redirect URL 中解析 cookie 参数"""
        result = {}
        if '?' not in url:
            return result
        query = url.split('?', 1)[1]
        for param in query.split('&'):
            if '=' in param:
                key, value = param.split('=', 1)
                result[key] = value
        return result

    def closeEvent(self, event):
        self._pollTimer.stop()
        super().closeEvent(event)
