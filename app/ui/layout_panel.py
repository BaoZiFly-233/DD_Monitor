"""
选择布局方式的页面
"""

from PySide6.QtWidgets import QLabel, QGridLayout
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt, Signal
from app.ui.layout_config import layoutList
from app.ui.title_bar import FluentWindow
from app.ui.uikit_bridge import current_color, theme_changed


class Label(QLabel):
    """序号标签。用于布局的编号"""

    def __init__(self, text):
        super(Label, self).__init__()
        self.setText(text)
        self.setFont(QFont("微软雅黑", 13, QFont.Bold))
        self.setAlignment(Qt.AlignCenter)
        self._applyThemeColor()
        # 跟随全局明暗主题刷新色块（primary 令牌色 + 白字保证对比度）
        theme_changed().connect(self._applyThemeColor)

    def _applyThemeColor(self, dark=None):
        self.setStyleSheet(
            f"background-color:{current_color('primary')};color:{current_color('on.primary')}"
        )


class LayoutWidget(QLabel):
    """布局表示
    展示一种布局
    """

    clicked = Signal(int)

    def __init__(self, layout, number):
        super(LayoutWidget, self).__init__()
        self.number = number  # 布局编号
        mainLayout = QGridLayout(self)
        for index, rect in enumerate(layout):
            y, x, h, w = rect
            mainLayout.addWidget(Label(str(index + 1)), y, x, h, w)

    def mousePressEvent(self, QMouseEvent):
        self.clicked.emit(self.number)

    def enterEvent(self, QEvent):
        # hover 色取自主题令牌（primary.subtle），下次进入时随主题刷新
        self.setStyleSheet(f"background-color:{current_color('primary.subtle')}")

    def leaveEvent(self, QEvent):
        self.setStyleSheet("background-color:#00000000")


class LayoutSettingPanel(FluentWindow):
    """布局选择窗口"""

    layoutConfig = Signal(list)

    def __init__(self):
        super(LayoutSettingPanel, self).__init__(title="选择布局方式")
        self.resize(1280, 720)

        # 排列各种布局方式
        mainLayout = QGridLayout(self)
        mainLayout.setSpacing(15)
        mainLayout.setContentsMargins(15, 15, 15, 15)
        layoutWidgetList = []
        for index, layout in enumerate(layoutList):
            widget = LayoutWidget(layout, index)
            widget.clicked.connect(self.sendLayout)
            mainLayout.addWidget(widget, index // 4, index % 4)
            layoutWidgetList.append(widget)

    def sendLayout(self, number):
        self.layoutConfig.emit(layoutList[number])
        self.hide()
