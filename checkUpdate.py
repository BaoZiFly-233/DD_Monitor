import requests
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import QDesktopServices


class checkUpdate(QThread):
    update = Signal(str, float, str)
    latest = Signal(float)

    def __init__(self, version):
        super(checkUpdate, self).__init__()
        self.version = version

    def run(self):
        token = False
        infos = ''
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36'
                                 '(KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 QIHU 360SE'}
        try:
            html = requests.get(r'https://gitee.com/zhimingshenjun/DD_Monitor_latest/releases', headers=headers, timeout=5)
        except requests.exceptions.RequestException:
            return
        for line in html.text.split('\n'):
            if 'DD监控室' in line and 'class="title"' in line:
                link, version = line.split('">')
                link = 'https://gitee.com/' + link.split('href="/')[1]
                version = float(version.split('室')[1].split('<')[0])
                print(version, self.version)
                if version > self.version:
                    print('检测到新版本')
                    token = True
            if '<p>' in line:
                l = line.split('>')
                for i in l:
                    if ';' in i:
                        i = i.split(';')[1]
                    if '<' in i:
                        i = i.split('<')[0]
                    i = i.strip()
                    if i:
                        infos += i + '\n'
            if 'committed-info' in line:
                break
        if token:
            self.update.emit(link, version, infos)
        else:
            self.latest.emit(version)


class updateReminder(QWidget):
    noMoreSignal = Signal()

    def __init__(self):
        super(updateReminder, self).__init__()
        self.link = ''
        self.resize(600, 400)
        self.setWindowTitle('检查版本')
        self.layout = QGridLayout()
        self.setLayout(self.layout)
        label = QLabel('检测到新版本 是否前往下载？')
        label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(label, 0, 0, 1, 3)

        self.updateInfo = QTextBrowser()
        self.layout.addWidget(self.updateInfo, 1, 0, 3, 3)

        noMoreButton = QPushButton('不再提示')
        noMoreButton.clicked.connect(self.noMoreSignal.emit)
        noMoreButton.clicked.connect(self.close)
        self.layout.addWidget(noMoreButton, 4, 0, 1, 1)
        noButton = QPushButton('否')
        noButton.clicked.connect(self.close)
        self.layout.addWidget(noButton, 4, 1, 1, 1)
        yesButton = QPushButton('是')
        yesButton.clicked.connect(self.openURL)
        yesButton.clicked.connect(self.close)
        # yesButton.setStyleSheet('background-color:#87CEFA')
        self.layout.addWidget(yesButton, 4, 2, 1, 1)

    def _show(self, link, version, infos):
        self.link = link
        self.updateInfo.setText(infos)
        self.show()

    def openURL(self):
        QDesktopServices.openUrl(QUrl(self.link))


class latestRemainder(QWidget):
    def __init__(self):
        super(latestRemainder, self).__init__()
        self.resize(480, 180)
        self.setWindowTitle('检查版本')
        self.layout = QGridLayout()
        self.setLayout(self.layout)
        self.label = QLabel()
        self.layout.addWidget(self.label)

    def _show(self, version):
        self.label.setText('已经是最新版本: v%.1f' % version)
        self.show()
