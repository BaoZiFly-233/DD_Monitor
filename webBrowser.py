import sys
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWidgets import QApplication, QWidget, QPushButton, QLineEdit, QGridLayout
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkCookieJar


class Browser(QWidget):
    sessionData = Signal(str)
    login = Signal(bool)
    def __init__(self):
        super().__init__()
        self.resize(1000, 600)
        self.setWindowTitle('扫码登录Bilibili')
        self.browser = QWebEngineView()
        profile = QWebEngineProfile('storage', self.browser)
        self.cookie_store = profile.cookieStore()
        self.cookie_store.cookieAdded.connect(self.onCookieAdd)
        webpage = QWebEnginePage(profile, self.browser)
        self.browser.setPage(webpage)
        self.browser.load(QUrl(r'https://account.bilibili.com/account/home'))
        self.layout = QGridLayout()
        self.layout.addWidget(self.browser)
        self.setLayout(self.layout)
        self.browser.loadFinished.connect(self.onLoadFinished)
        self.loginToken = False

    def onLoadFinished(self):
        if self.browser.page().title() == '账号登录':
            self.login.emit(False)
        else:
            self.login.emit(True)

    def onCookieAdd(self, cookie):
        name = cookie.name().data().decode('utf-8')  # 先获取cookie的名字，再把编码处理一下
        value = cookie.value().data().decode('utf-8')  # 先获取cookie值，再把编码处理一下
        if name == 'SESSDATA' and not self.loginToken:
            self.sessionData.emit(value)
            self.loginToken = True


if __name__ == '__main__':
    app = QApplication(sys.argv)
    browser = Browser()
    browser.show()
    sys.exit(app.exec_())