# -*- coding: utf-8 -*-
"""应用统一 Fluent 标题栏 — 经典 一 / 口 / X 窗口按钮，主题色自适应。

组件库 qfluentwidgets_pro 自带的 FluentTitleBar 存在两个问题：
1. 按钮顶对齐（48px 栏内按钮只有 32px 且 AlignTop），与垂直居中的标题不持平；
2. 最大化按钮使用 FluentIcon.ZOOM（放大镜图标），不是常规的"口"字形，
   且组件库编译资源中缺少 :/qframelesswindow/close.svg，CloseButton 无法渲染。

本模块用 QPainter 自绘经典窗口字形（一/口/X），颜色取自 UIKit 令牌并随
明暗主题刷新；按钮撑满标题栏高度保证与标题垂直居中。同时提供统一的无边框
对话框/窗口基类（FluentDialog / FluentWindow），让所有顶层窗口外观一致。
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel

from qfluentwidgets_pro.qframelesswindow import FramelessDialog, FramelessWindow
from qfluentwidgets_pro.qframelesswindow.titlebar import TitleBarBase
from qfluentwidgets_pro.qframelesswindow.titlebar.title_bar_buttons import (
    TitleBarButton as QtFramelessButton,
)

# 平台无关的无边框基类（mixin，用于 QFrame 等无法直接继承 FramelessWindow 的场景）
import sys as _sys

if _sys.platform == "win32":
    from qfluentwidgets_pro.qframelesswindow.windows import WindowsFramelessWindowBase as FramelessWindowBase  # noqa: F401
elif _sys.platform == "darwin":
    from qfluentwidgets_pro.qframelesswindow.mac import MacFramelessWindowBase as FramelessWindowBase  # noqa: F401
else:
    from qfluentwidgets_pro.qframelesswindow.linux import LinuxFramelessWindowBase as FramelessWindowBase  # noqa: F401

from app.ui.uikit_bridge import current_color, is_dark, theme_changed

TITLE_BAR_HEIGHT = 48
BUTTON_WIDTH = 46
BUTTON_HEIGHT = TITLE_BAR_HEIGHT
_CLOSE_HOVER = QColor(232, 17, 35)    # Windows 关闭键红
_CLOSE_PRESSED = QColor(241, 112, 122)


class AppTitleBarButton(QtFramelessButton):
    """经典窗口按钮基类：字形颜色随主题，悬停/按下背景反馈。

    继承组件库 TitleBarButton 以获得其状态机（enter/leave/press 事件、
    isPressed()），并参与标题栏拖拽区域的排除判断。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(BUTTON_WIDTH, BUTTON_HEIGHT)
        self._refreshColors()
        theme_changed().connect(self._refreshColors)

    def _refreshColors(self, *args):
        """字形/背景颜色取自 UIKit 令牌，随明暗主题与配色刷新。"""
        glyph = QColor(current_color("text.primary"))
        self.setNormalColor(glyph)
        self.setHoverColor(glyph)
        self.setPressedColor(glyph)
        if is_dark():
            self.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            self.setHoverBackgroundColor(QColor(255, 255, 255, 26))
            self.setPressedBackgroundColor(QColor(255, 255, 255, 51))
        else:
            self.setNormalBackgroundColor(QColor(0, 0, 0, 0))
            self.setHoverBackgroundColor(QColor(0, 0, 0, 16))
            self.setPressedBackgroundColor(QColor(0, 0, 0, 32))

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color, bgColor = self._getColors()
        painter.fillRect(self.rect(), bgColor)
        self._drawGlyph(painter, color)
        painter.end()

    def _drawGlyph(self, painter: QPainter, color: QColor):
        raise NotImplementedError


class MinButton(AppTitleBarButton):
    """最小化 — 一（水平线）"""

    def _drawGlyph(self, painter, color):
        pen = QPen(color, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        painter.drawLine(int(cx - 9), int(cy), int(cx + 9), int(cy))


class MaxButton(AppTitleBarButton):
    """最大化 / 还原 — 口（方框 / 双框）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._isMax = False

    def setMaxState(self, isMax):
        """切换最大化/还原字形（由 TitleBarBase 的 WindowStateChange 过滤联动）"""
        if self._isMax == bool(isMax):
            return
        self._isMax = bool(isMax)
        self.update()

    def _drawGlyph(self, painter, color):
        pen = QPen(color, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if not self._isMax:
            painter.drawRect(QRectF(cx - 7, cy - 7, 14, 14))
        else:
            # 还原：后框左上 + 前框右下
            painter.drawRect(QRectF(cx - 6.5, cy - 6.5, 10, 10))
            painter.drawRect(QRectF(cx - 1.5, cy + 0.5, 10, 10))


class CloseXButton(AppTitleBarButton):
    """关闭 — X（交叉线），悬停红底"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHoverBackgroundColor(_CLOSE_HOVER)
        self.setPressedBackgroundColor(_CLOSE_PRESSED)
        self.setHoverColor(Qt.white)
        self.setPressedColor(Qt.white)
        self.setNormalColor(QColor(current_color("text.primary")))
        theme_changed().connect(
            lambda *_: self.setNormalColor(QColor(current_color("text.primary")))
        )

    def _drawGlyph(self, painter, color):
        pen = QPen(color, 1.2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        cx, cy = self.width() / 2, self.height() / 2
        d = 9
        painter.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
        painter.drawLine(int(cx - d), int(cy + d), int(cx + d), int(cy - d))


class AppTitleBar(TitleBarBase):
    """应用统一标题栏：窗口图标 + 标题 + 经典三键，全部垂直居中。

    继承组件库 TitleBarBase 获得：窗口拖动（startSystemMove）、双击最大化、
    最大化状态联动（WindowStateChange 事件过滤器）。
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("appTitleBar")
        self.setFixedHeight(TITLE_BAR_HEIGHT)

        # 组件库默认按钮（SVG 资源缺失/风格不符），隐藏并替换为经典字形
        for old in (self.minBtn, self.maxBtn, self.closeBtn):
            old.hide()

        self.minBtn = MinButton(self)
        self.maxBtn = MaxButton(self)
        self.closeBtn = CloseXButton(self)
        self.minBtn.clicked.connect(self.window().showMinimized)
        self.maxBtn.clicked.connect(self._toggleMaxState)
        self.closeBtn.clicked.connect(self.window().close)

        # 窗口图标 + 标题
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(18, 18)
        self.titleLabel = QLabel(self)
        self.titleLabel.setObjectName("appTitleLabel")
        self._applyTitleColor()
        theme_changed().connect(self._applyTitleColor)
        self.window().windowTitleChanged.connect(self.setTitle)
        self.window().windowIconChanged.connect(self.setIcon)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.iconLabel, 0, Qt.AlignVCenter)
        layout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self.minBtn)
        layout.addWidget(self.maxBtn)
        layout.addWidget(self.closeBtn)

        self.setTitle(self.window().windowTitle())
        self.setIcon(self.window().windowIcon())

    def _applyTitleColor(self, *args):
        self.titleLabel.setStyleSheet(
            f"color: {current_color('text.primary')}; background: transparent;"
        )

    def setTitle(self, title):
        self.titleLabel.setText(title)
        self.titleLabel.adjustSize()

    def setIcon(self, icon):
        if icon and not icon.isNull():
            self.iconLabel.setPixmap(QIcon(icon).pixmap(18, 18))
            self.iconLabel.show()
        else:
            self.iconLabel.hide()

    def setMaximizeEnabled(self, enabled):
        """固定尺寸窗口（如扫码登录）可隐藏最大化按钮"""
        self.maxBtn.setVisible(bool(enabled))

    def _toggleMaxState(self):
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()


def _install_title_bar(window, title="", maximize_enabled=True):
    """给无边框窗口安装统一标题栏并让内容区避开标题栏。"""
    window.setTitleBar(AppTitleBar(window))
    window.setContentsMargins(0, window.titleBar.height(), 0, 0)
    window.titleBar.raise_()
    if title:
        window.setWindowTitle(title)
    if not maximize_enabled:
        window.titleBar.setMaximizeEnabled(False)


class FluentDialog(FramelessDialog):
    """统一无边框对话框：Fluent 标题栏 + DWM 阴影 + 内容区自动避开标题栏。"""

    def __init__(self, parent=None, title="", maximize_enabled=True):
        super().__init__(parent=parent)
        _install_title_bar(self, title=title, maximize_enabled=maximize_enabled)


class FluentWindow(FramelessWindow):
    """统一无边框顶层窗口（QWidget 版，用于非对话框弹窗）。"""

    def __init__(self, parent=None, title="", maximize_enabled=True):
        super().__init__(parent=parent)
        _install_title_bar(self, title=title, maximize_enabled=maximize_enabled)
