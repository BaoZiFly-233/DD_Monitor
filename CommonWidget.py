# -*- coding: utf-8 -*-
"""一些公用的组件
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QSlider


class Slider(QSlider):
    """通用的滚动条"""
    value = Signal(int)

    def __init__(self, value=100):
        super(Slider, self).__init__()
        self.setOrientation(Qt.Horizontal)
        self.setFixedWidth(100)
        self.setValue(value)
        self.pressToken = False

    def mousePressEvent(self, event):
        # self.updateValue(event.pos())
        self.pressToken = True

    def mouseReleaseEvent(self, event):
        self.pressToken = False

    def mouseMoveEvent(self, event):
        if self.pressToken:
            self.updateValue(event.pos())

    def wheelEvent(self, event):  # 把进度条的滚轮事件去了 用啥子滚轮
        pass

    def updateValue(self, QPoint):
        # 按滑块实际宽度比例映射值
        slider_width = max(self.width(), 1)
        value = int(QPoint.x() / slider_width * self.maximum())
        if value > self.maximum():
            value = self.maximum()
        elif value < 0:
            value = 0
        self.setValue(value)
        self.value.emit(value)
