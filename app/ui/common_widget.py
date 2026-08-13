# -*- coding: utf-8 -*-
"""一些公用的组件"""

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QSlider

from app.core import http_utils


class Slider(QSlider):
    """通用的滚动条

    注意：自定义信号命名为 sliderValue，避免遮蔽 QSlider.value() 方法
    （原先命名为 value 会导致 settingsDialog 中 slider.value() 调用失败）
    """

    sliderValue = Signal(int)

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
        self.sliderValue.emit(value)


class DownloadImage(QThread):
    """下载图片（线程安全：QImage 在线程内构造，主线程转 QPixmap）

    用法：
        downloader = DownloadImage(60, 60)
        downloader.setUrl(url)
        downloader.img.connect(callback)      # 缩放后的图片
        downloader.img_origin.connect(callback)  # 原图（可选）
        downloader.start()
    """

    img = Signal(QPixmap)
    img_origin = Signal(QPixmap)
    _imgReady = Signal(QImage, int, int, bool)  # image, w, h, hasOrigin

    def __init__(self, scaleW=60, scaleH=60, keyFrame=False):
        super(DownloadImage, self).__init__()
        self.W = scaleW
        self.H = scaleH
        self.keyFrame = keyFrame
        self.url = ""
        self._imgReady.connect(self._onImageReady)

    def setUrl(self, url):
        self.url = str(url or "").strip()

    def run(self):
        if not self.url:
            return
        try:
            if self.W == 60:
                r = http_utils.get(self.url + "@100w_100h.jpg", headers=http_utils.DEFAULT_HEADERS)
            else:
                r = http_utils.get(self.url, headers=http_utils.DEFAULT_HEADERS)
            # QImage 是线程安全的，QPixmap 不是
            qimage = QImage.fromData(r.content)
            if not qimage.isNull():
                self._imgReady.emit(qimage, self.W, self.H, self.keyFrame)
        except Exception as e:
            import logging

            logging.error(str(e))

    def _onImageReady(self, qimage, w, h, hasOrigin):
        """主线程回调：将 QImage 转换为 QPixmap"""
        pixmap = QPixmap.fromImage(qimage)
        if w > 0 and h > 0:
            self.img.emit(pixmap.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        else:
            self.img.emit(pixmap)
        if hasOrigin:
            self.img_origin.emit(pixmap)
