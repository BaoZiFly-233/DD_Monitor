import re
import http_utils
from PySide6.QtCore import QThread, Signal, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QLabel, QTextBrowser, QWidget
from InstructionX_UIKit.components import Button
from uikit_bridge import apply_scoped_theme
from app_version import parse_version


class checkUpdate(QThread):
    update = Signal(str, tuple, str)

    def __init__(self, version):
        super(checkUpdate, self).__init__()
        self.version = version

    def run(self):
        """通过 GitHub API 检查最新版本

        旧实现解析 GitHub releases 网页 HTML，存在三个失效点：
        - release 标题实际是 "DDMonitor"（英文），"DD监控室" 条件永不命中，检查静默失效
        - 解析出的相对链接拼到 gitee.com 域名，点"是"打开的地址与实际发布页不符
        - 解析循环在 try 之外，异常直接抛出使更新检查无提示失败
        改用 releases/latest API（JSON），链接/版本/更新说明一次拿全。
        """
        try:
            resp = http_utils.get(
                r"https://api.github.com/repos/BaoZiFly-233/DD_Monitor/releases/latest",
                timeout=5,
            )
            data = resp.json()
            if not data or not isinstance(data, dict):
                return
            tag = data.get("tag_name", "")
            match = re.search(r"[\d.]+", tag)
            if not match:
                return
            new_version = parse_version(match.group())
            if new_version > self.version:
                self.update.emit(
                    data.get("html_url", ""),
                    new_version,
                    data.get("body", "") or "",
                )
        except Exception:
            return


class updateReminder(QWidget):
    noMoreSignal = Signal()

    def __init__(self):
        super(updateReminder, self).__init__()
        self.link = ""
        self.resize(600, 400)
        self.setWindowTitle("检查版本")
        self.layout = QGridLayout()
        self.setLayout(self.layout)
        label = QLabel("检测到新版本 是否前往下载？")
        label.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(label, 0, 0, 1, 3)

        self.updateInfo = QTextBrowser()
        self.layout.addWidget(self.updateInfo, 1, 0, 3, 3)

        noMoreButton = Button("不再提示", variant="default")
        noMoreButton.clicked.connect(self.noMoreSignal.emit)
        noMoreButton.clicked.connect(self.close)
        self.layout.addWidget(noMoreButton, 4, 0, 1, 1)
        noButton = Button("否", variant="default")
        noButton.clicked.connect(self.close)
        self.layout.addWidget(noButton, 4, 1, 1, 1)
        yesButton = Button("是", variant="primary")
        yesButton.clicked.connect(self.openURL)
        yesButton.clicked.connect(self.close)
        self.layout.addWidget(yesButton, 4, 2, 1, 1)

        # UIKit 局部主题：检查版本弹窗子树切换为暗色 UIKit 观感
        apply_scoped_theme(self)

    def _show(self, link, version, infos):
        self.link = link
        self.updateInfo.setText(infos)
        self.show()

    def openURL(self):
        QDesktopServices.openUrl(QUrl(self.link))
