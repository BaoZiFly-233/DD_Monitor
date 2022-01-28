# -*- coding: utf-8 -*-
"""一些公用的组件
"""
from PySide2.QtCore import Qt, Signal
from PySide2.QtWidgets import QSlider


class Slider(QSlider):
    """通用的滚动条"""
    value = Signal(int)

    def __init__(self, value=100):
        super(Slider, self).__init__()
        self.setOrientation(Qt.Horizontal)
        self.setFixedWidth(100)
        self.setValue(value)

    def mousePressEvent(self, event):
        self.updateValue(event.pos())

    def mouseMoveEvent(self, event):
        self.updateValue(event.pos())

    def wheelEvent(self, event):  # 把进度条的滚轮事件去了 用啥子滚轮
        pass

    def updateValue(self, QPoint):
        value = QPoint.x()
        if value > 100: value = 100
        elif value < 0: value = 0
        self.setValue(value)
        self.value.emit(value)
