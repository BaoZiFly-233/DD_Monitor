# -*- coding: utf-8 -*-
"""MPV render API + QOpenGLWidget 集成。"""

import logging

from PySide6.QtCore import QByteArray, QMetaObject, QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QOpenGLContext, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication


class MpvGLWidget(QOpenGLWidget):
    rightClicked = Signal(object)
    leftClicked = Signal()
    doubleClicked = Signal()

    def __init__(self, danmaku_renderer=None, parent=None):
        super().__init__(parent)
        self._mpv = None
        self._render_context = None
        self._proc_addr_cb = None
        self._danmaku_renderer = danmaku_renderer
        self._update_scheduled = False
        self._render_init_failed = False
        self._playback_active = False
        self._left_press_pos = QPoint()
        self._left_pressed = False
        self._left_drag_emitted = False
        self._danmaku_timer = QTimer(self)
        self._danmaku_timer.setInterval(16)
        self._danmaku_timer.timeout.connect(self._on_danmaku_tick)
        self.frameSwapped.connect(self._on_frame_swapped)
        self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.setUpdateCallback(self._schedule_danmaku_updates)

    def setDanmakuRenderer(self, renderer):
        self._danmaku_renderer = renderer
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.setUpdateCallback(self._schedule_danmaku_updates)
        self.update()

    def setPlayer(self, mpv_instance):
        if self._mpv is mpv_instance:
            return
        self.makeCurrent()
        self._free_render_context()
        self._mpv = mpv_instance
        self._render_init_failed = False
        if mpv_instance is None:
            self._playback_active = False
        self._ensure_render_context()
        self.doneCurrent()
        self.update()

    def setPlaybackActive(self, active):
        active = bool(active)
        if self._playback_active == active:
            return
        self._playback_active = active
        self.update()

    def initializeGL(self):
        self._ensure_render_context()
        current_context = QOpenGLContext.currentContext()
        if current_context is not None:
            surface_format = current_context.format()
            logging.info(
                'MpvGLWidget OpenGL 上下文: isGLES=%s version=%s.%s profile=%s dpr=%.2f',
                current_context.isOpenGLES(),
                surface_format.majorVersion(),
                surface_format.minorVersion(),
                surface_format.profile(),
                self.devicePixelRatioF(),
            )
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.initialize_gl()

    def resizeGL(self, width, height):
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.setViewportSize(width, height)

    def paintGL(self):
        self._update_scheduled = False
        self._ensure_render_context()
        dpr = max(float(self.devicePixelRatioF()), 1.0)
        pixel_width = max(1, int(round(self.width() * dpr)))
        pixel_height = max(1, int(round(self.height() * dpr)))
        current_context = QOpenGLContext.currentContext()
        if current_context is not None:
            funcs = current_context.functions()
            if self._render_context is None or not self._playback_active:
                funcs.glClearColor(0.3529, 0.3882, 0.4274, 1.0)  # #5a636d
            else:
                funcs.glClearColor(0.0, 0.0, 0.0, 1.0)
            funcs.glClear(0x00004000)
        if self._render_context is not None and self._playback_active:
            self._render_context.render(
                opengl_fbo={
                    'w': pixel_width,
                    'h': pixel_height,
                    'fbo': int(self.defaultFramebufferObject()),
                    'internal_format': 0,
                },
                flip_y=True,
            )
        if self._danmaku_renderer is not None:
            painter = QPainter(self)
            try:
                self._danmaku_renderer.paint(painter, self.width(), self.height())
            finally:
                painter.end()
            self._schedule_danmaku_updates()

    def _ensure_render_context(self):
        if self._render_context is not None or self._mpv is None or self._render_init_failed:
            return
        current_context = QOpenGLContext.currentContext() or self.context()
        if current_context is None:
            return
        import mpv
        if self._proc_addr_cb is None:
            self._proc_addr_cb = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
        try:
            self._render_context = mpv.MpvRenderContext(
                self._mpv,
                'opengl',
                opengl_init_params={'get_proc_address': self._proc_addr_cb},
                advanced_control=False,
            )
            self._render_context.update_cb = self._on_mpv_update
        except Exception:
            self._render_init_failed = True
            raise

    def _free_render_context(self):
        if self._render_context is not None:
            try:
                self._render_context.free()
            except Exception:
                pass
            self._render_context = None

    def _get_proc_address(self, _, name):
        if not name:
            return 0
        current_context = QOpenGLContext.currentContext() or self.context()
        if current_context is None:
            return 0
        proc = current_context.getProcAddress(QByteArray(name))
        if proc is None:
            return 0
        try:
            return int(proc)
        except TypeError:
            try:
                return proc.__int__()
            except Exception:
                return 0

    def _on_mpv_update(self):
        if self._update_scheduled:
            return
        self._update_scheduled = True
        QMetaObject.invokeMethod(self, '_triggerUpdate', Qt.QueuedConnection)

    @Slot()
    def _on_frame_swapped(self):
        if self._render_context is None:
            return
        try:
            self._render_context.report_swap()
        except Exception:
            logging.debug('MpvGLWidget report_swap 调用失败', exc_info=True)

    def _schedule_danmaku_updates(self):
        if self._danmaku_renderer is not None and self._danmaku_renderer.hasActiveDanmaku():
            if not self._danmaku_timer.isActive():
                self._danmaku_timer.start()
        else:
            self._danmaku_timer.stop()

    @Slot()
    def _on_danmaku_tick(self):
        if self._danmaku_renderer is None or not self._danmaku_renderer.hasActiveDanmaku():
            self._danmaku_timer.stop()
            return
        self.update()

    @Slot()
    def _triggerUpdate(self):
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit(event)
        elif event.button() == Qt.LeftButton:
            self._left_pressed = True
            self._left_press_pos = event.position().toPoint()
            self._left_drag_emitted = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._left_pressed and not (event.buttons() & Qt.LeftButton):
            self._left_pressed = False
            self._left_drag_emitted = False
        if self._left_pressed and (event.buttons() & Qt.LeftButton) and not self._left_drag_emitted:
            current_pos = event.position().toPoint()
            if (current_pos - self._left_press_pos).manhattanLength() >= QApplication.startDragDistance():
                self._left_drag_emitted = True
                self.leftClicked.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._left_pressed = False
            self._left_drag_emitted = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def closeEvent(self, event):
        self._danmaku_timer.stop()
        self.makeCurrent()
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.cleanup_gl()
        self._free_render_context()
        self.doneCurrent()
        super().closeEvent(event)
