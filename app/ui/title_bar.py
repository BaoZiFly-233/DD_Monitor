# -*- coding: utf-8 -*-
"""应用统一 Fluent 标题栏 — 参照组件库官方原版（zhiyiYo/PySide6-Fluent-Widgets）观感。

官方 FluentTitleBar 的按钮是 qframelesswindow 的经典 QPainter 字形
（MinimizeButton 一横 / MaximizeButton 方框与还原双框 / CloseButton 交叉线，
1px 细线、小尺寸），标题为 13px 级标签。本模块按同样比例绘制，并修正官方
实现的两处缺陷：
1. 官方 48px 栏中按钮 32px 顶对齐（与垂直居中的标题不持平）→ 本实现按钮
   垂直居中，字形中心与标题中心严格对齐；
2. 官方 close.svg 资源缺失导致 CloseButton 渲染为空 → 本实现 QPainter 自绘。

同时提供统一的无边框对话框/窗口基类（FluentDialog / FluentWindow），
让所有顶层窗口外观一致。
"""

import sys as _sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel

from qfluentwidgets_pro.qframelesswindow import FramelessDialog, FramelessWindow
from qfluentwidgets_pro.qframelesswindow.titlebar import TitleBarBase
from qfluentwidgets_pro.qframelesswindow.titlebar.title_bar_buttons import (
    TitleBarButton as QtFramelessButton,
)

# 平台无关的无边框基类（mixin，用于 QFrame 等无法直接继承 FramelessWindow 的场景）
if _sys.platform == "win32":
    from qfluentwidgets_pro.qframelesswindow.windows import WindowsFramelessWindowBase as FramelessWindowBase  # noqa: F401
elif _sys.platform == "darwin":
    from qfluentwidgets_pro.qframelesswindow.mac import MacFramelessWindowBase as FramelessWindowBase  # noqa: F401
else:
    from qfluentwidgets_pro.qframelesswindow.linux import LinuxFramelessWindowBase as FramelessWindowBase  # noqa: F401

from app.ui.uikit_bridge import current_color, is_dark, theme_changed

TITLE_BAR_HEIGHT = 48
BUTTON_WIDTH = 46
# 官方按钮为 46x32；在 48px 栏中垂直居中，既与标题持平又保持官方轻盈比例
BUTTON_HEIGHT = 32
# 官方字形比例（46x32 按钮内约 10px 字形），48px 栏内略放大至 12px
_GLYPH = 12
_CLOSE_HOVER = QColor(232, 17, 35)      # Windows 关闭键红
_CLOSE_PRESSED = QColor(241, 112, 122)


class AppTitleBarButton(QtFramelessButton):
    """经典窗口按钮基类：字形颜色随主题，悬停/按下背景反馈。

    继承组件库 TitleBarButton 获得状态机（enter/leave/press、isPressed()），
    并参与标题栏拖拽区域的排除判断。
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

    @staticmethod
    def _pen(color):
        pen = QPen(color, 1.2)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.RoundCap)
        return pen

    def _drawGlyph(self, painter: QPainter, color: QColor):
        raise NotImplementedError


class MinButton(AppTitleBarButton):
    """最小化 — 一（水平线，圆角线帽）"""

    def _drawGlyph(self, painter, color):
        painter.setPen(self._pen(color))
        cx, cy = self.width() / 2, self.height() / 2
        half = _GLYPH
        painter.drawLine(int(cx - half), int(cy), int(cx + half), int(cy))


class MaxButton(AppTitleBarButton):
    """最大化 / 还原 — 口（方框 / 官方双框）"""

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
        painter.setPen(self._pen(color))
        painter.setBrush(Qt.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if not self._isMax:
            painter.drawRect(QRectF(cx - _GLYPH / 2, cy - _GLYPH / 2, _GLYPH, _GLYPH))
        else:
            # 官方还原双框：后框左上、前框右下
            s = _GLYPH - 3
            painter.drawRect(QRectF(cx - s / 2 - 2, cy - s / 2 - 2, s, s))
            painter.drawRect(QRectF(cx - s / 2 + 1, cy - s / 2 + 1, s, s))


class CloseXButton(AppTitleBarButton):
    """关闭 — X（交叉线，圆角线帽），悬停 Windows 红底"""

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
        painter.setPen(self._pen(color))
        cx, cy = self.width() / 2, self.height() / 2
        d = _GLYPH
        painter.drawLine(int(cx - d), int(cy - d), int(cx + d), int(cy + d))
        painter.drawLine(int(cx - d), int(cy + d), int(cx + d), int(cy - d))


class AppTitleBar(TitleBarBase):
    """应用统一标题栏：窗口图标 + 标题（13px）+ 经典三键，全部垂直居中。

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

        # 窗口图标 + 标题（13px，与官方 CaptionLabel 同级）
        self.iconLabel = QLabel(self)
        self.iconLabel.setFixedSize(18, 18)
        self.titleLabel = QLabel(self)
        self.titleLabel.setObjectName("appTitleLabel")
        self._applyTitleStyle()
        theme_changed().connect(self._applyTitleStyle)
        self.window().windowTitleChanged.connect(self.setTitle)
        self.window().windowIconChanged.connect(self.setIcon)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self.iconLabel, 0, Qt.AlignVCenter)
        layout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self.minBtn, 0, Qt.AlignVCenter)
        layout.addWidget(self.maxBtn, 0, Qt.AlignVCenter)
        layout.addWidget(self.closeBtn, 0, Qt.AlignVCenter)

        self.setTitle(self.window().windowTitle())
        self.setIcon(self.window().windowIcon())

    def _applyTitleStyle(self, *args):
        self.titleLabel.setStyleSheet(
            f"color: {current_color('text.primary')}; background: transparent;"
            f" font-size: 13px;"
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
