# -*- coding: utf-8 -*-
"""MPV render API + QOpenGLWidget 集成。"""

import logging

from PySide6.QtCore import QByteArray, QMetaObject, QPoint, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QOpenGLContext, QPainter
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication
from app.ui.uikit_bridge import current_color, theme_changed


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
        # 关闭标记：一旦置位，mpv 线程回调与延迟刷新全部失效，避免退出时
        # 对已销毁的 GL 上下文调用 mpv_render_context_render 导致崩溃
        self._closing = False
        self._danmaku_timer = QTimer(self)
        self._danmaku_timer.setInterval(16)  # 默认 60fps, setDanmakuInterval 可调
        self._danmaku_timer.timeout.connect(self._on_danmaku_tick)
        self._render_suspended = False  # 窗口隐藏（页面切换）时挂起渲染
        self.frameSwapped.connect(self._on_frame_swapped)
        self.setUpdateBehavior(QOpenGLWidget.NoPartialUpdate)
        # 明暗/配色切换后重绘 GL 面，使无视频占位色及时更新
        theme_changed().connect(lambda *_: self.update())
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.setUpdateCallback(self._schedule_danmaku_updates)

    def setDanmakuRenderer(self, renderer):
        self._danmaku_renderer = renderer
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.setUpdateCallback(self._schedule_danmaku_updates)
        self.update()

    def setDanmakuInterval(self, fps):
        """设置弹幕刷新帧率（fps: 30/60/90/120）"""
        interval = max(8, int(1000 / max(1, int(fps))))
        self._danmaku_timer.setInterval(interval)

    def setPlayer(self, mpv_instance):
        if self._mpv is mpv_instance:
            return
        if self._closing:
            return
        # mpv_render_context_free 要求调用线程持有有效 GL 上下文；
        # makeCurrent 失败（窗口隐藏/上下文失效）时跳过 C 层释放，
        # 避免 libmpv 内部 GL 调用触发原生访问冲突。
        gl_ok = False
        try:
            gl_ok = self.makeCurrent()
        except Exception:
            gl_ok = False
        if gl_ok:
            self._free_render_context()
        else:
            self._render_context = None
        self._mpv = mpv_instance
        self._render_init_failed = False
        if mpv_instance is None:
            self._playback_active = False
        if gl_ok:
            self._ensure_render_context()
        try:
            self.doneCurrent()
        except Exception:
            pass
        self.update()

    def hideEvent(self, event):
        """窗口隐藏（如导航切换离开直播监控页）：挂起 mpv 渲染与弹幕刷新，
        避免 Qt 销毁 WGL surface 后 mpv 仍在失效表面上做 GL 操作（access violation）。"""
        self._render_suspended = True
        self._danmaku_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        """窗口重新可见：恢复渲染"""
        self._render_suspended = False
        if self._danmaku_renderer is not None and self._danmaku_renderer.hasActiveDanmaku():
            self._danmaku_timer.start()
        super().showEvent(event)

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
                "MpvGLWidget OpenGL 上下文: isGLES=%s version=%s.%s profile=%s dpr=%.2f",
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
        if self._closing:
            # 退出流程中不再触碰 GL/mpv
            return
        self._ensure_render_context()
        dpr = max(float(self.devicePixelRatioF()), 1.0)
        pixel_width = max(1, int(round(self.width() * dpr)))
        pixel_height = max(1, int(round(self.height() * dpr)))
        current_context = QOpenGLContext.currentContext()
        if current_context is not None:
            funcs = current_context.functions()
            if self._render_context is None or not self._playback_active:
                # 空播放器使用中性背景令牌，主题色只用于可操作控件和状态强调。
                color = QColor(current_color("bg.muted"))
                funcs.glClearColor(color.redF(), color.greenF(), color.blueF(), 1.0)
            else:
                funcs.glClearColor(0.0, 0.0, 0.0, 1.0)
            funcs.glClear(0x00004000)
        if self._render_context is not None and self._playback_active:
            try:
                self._render_context.render(
                    opengl_fbo={
                        "w": pixel_width,
                        "h": pixel_height,
                        "fbo": int(self.defaultFramebufferObject()),
                        "internal_format": 0,
                    },
                    flip_y=True,
                )
            except Exception:
                logging.debug("MpvGLWidget render 失败", exc_info=True)
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
                "opengl",
                opengl_init_params={"get_proc_address": self._proc_addr_cb},
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
        # mpv 渲染线程回调：关闭中、上下文已释放或窗口隐藏（页面切换）时
        # 直接忽略，绝不触碰已销毁/失效的 render context
        # （退出期与页面切换期的 access violation 源头）
        if self._closing or self._render_context is None or self._render_suspended:
            return
        if self._update_scheduled:
            return
        self._update_scheduled = True
        try:
            QMetaObject.invokeMethod(self, "_triggerUpdate", Qt.QueuedConnection)
        except RuntimeError:
            pass  # C++ 对象已销毁（关闭竞态），忽略

    @Slot()
    def _on_frame_swapped(self):
        if self._closing or self._render_context is None:
            return
        try:
            self._render_context.report_swap()
        except Exception:
            logging.debug("MpvGLWidget report_swap 调用失败", exc_info=True)

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
        if not self._closing and not self._render_suspended:
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
        # 置位关闭标记：mpv 线程回调与排队刷新全部失效，
        # 防止退出期对已销毁的 GL 上下文执行 render/report_swap
        self._closing = True
        self._danmaku_timer.stop()
        try:
            self.frameSwapped.disconnect(self._on_frame_swapped)
        except (RuntimeError, TypeError):
            pass
        try:
            self.makeCurrent()
        except Exception:
            pass
        if self._danmaku_renderer is not None:
            self._danmaku_renderer.cleanup_gl()
        self._free_render_context()
        try:
            self.doneCurrent()
        except Exception:
            pass
        super().closeEvent(event)
