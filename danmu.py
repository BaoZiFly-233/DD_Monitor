"""将弹幕机分离出来单独开发
"""
import os
import time
import logging
import tempfile

from PySide6.QtWidgets import QLabel, QToolButton, QWidget, QComboBox, QLineEdit, QTextBrowser, QGridLayout, QStyle
from PySide6.QtGui import QFont, QColor, QPainter, QPen, QBrush, QFontMetrics, QPainterPath
from PySide6.QtCore import Qt, Signal, QPoint, QTimer
from CommonWidget import Slider


class Bar(QLabel):
    """自定义标题栏"""
    moveSignal = Signal(QPoint)

    def __init__(self, text):
        super(Bar, self).__init__()
        self.setText(text)
        self.setFixedHeight(25)
        self.startPos = self.pos()
        self.pressToken = False

    def mousePressEvent(self, event):
        self.startPos = event.pos()
        self.pressToken = True

    def mouseReleaseEvent(self, event):
        self.pressToken = False

    def mouseMoveEvent(self, event):
        if self.pressToken:
            self.moveSignal.emit(self.mapToParent(event.pos() - self.startPos))


class ToolButton(QToolButton):
    """标题栏按钮"""

    def __init__(self, icon):
        super(ToolButton, self).__init__()
        self.setStyleSheet('border-color:#CCCCCC')
        self.setFixedSize(25, 25)
        self.setIcon(icon)


class TextOpation(QWidget):
    """弹幕机选项 - 弹出式窗口"""

    def __init__(self, setting=[50, 1, 7, 0, '【 [ {', 10, 0]):
        super(TextOpation, self).__init__()
        self.resize(300, 300)
        self.setWindowTitle('弹幕窗设置')
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        # ---- 窗体布局 ----
        layout = QGridLayout(self)
        layout.addWidget(QLabel('字体大小'), 0, 0, 1, 1)
        self.fontSizeCombox = QComboBox()
        self.fontSizeCombox.addItems([str(i) for i in range(5, 26)])
        self.fontSizeCombox.setCurrentIndex(setting[5])
        layout.addWidget(self.fontSizeCombox, 0, 1, 1, 1)

        layout.addWidget(QLabel('窗体透明度'), 1, 0, 1, 1)
        self.opacitySlider = Slider()
        self.opacitySlider.setValue(setting[0])
        layout.addWidget(self.opacitySlider, 1, 1, 1, 1)

        layout.addWidget(QLabel('窗体横向占比'), 2, 0, 1, 1)
        self.horizontalCombobox = QComboBox()
        self.horizontalCombobox.addItems(
            ['%d' % x + '%' for x in range(10, 110, 10)])
        self.horizontalCombobox.setCurrentIndex(setting[1])
        layout.addWidget(self.horizontalCombobox, 2, 1, 1, 1)

        layout.addWidget(QLabel('窗体纵向占比'), 3, 0, 1, 1)
        self.verticalCombobox = QComboBox()
        self.verticalCombobox.addItems(
            ['%d' % x + '%' for x in range(10, 110, 10)])
        self.verticalCombobox.setCurrentIndex(setting[2])
        layout.addWidget(self.verticalCombobox, 3, 1, 1, 1)

        layout.addWidget(QLabel('弹幕窗类型'), 4, 0, 1, 1)
        self.translateCombobox = QComboBox()
        self.translateCombobox.addItems(['弹幕和同传', '只显示弹幕', '只显示同传'])
        self.translateCombobox.setCurrentIndex(setting[3])
        layout.addWidget(self.translateCombobox, 4, 1, 1, 1)

        layout.addWidget(QLabel('同传过滤字符 (空格隔开)'), 5, 0, 1, 1)
        self.translateFitler = QLineEdit('')
        self.translateFitler.setText(setting[4])
        self.translateFitler.setFixedWidth(100)
        layout.addWidget(self.translateFitler, 5, 1, 1, 1)

        layout.addWidget(QLabel('礼物和进入信息'), 6, 0, 1, 1)
        self.showEnterRoom = QComboBox()
        self.showEnterRoom.addItems(['显示礼物和进入信息', '只显示礼物', '只显示进入信息', '隐藏窗口'])
        self.showEnterRoom.setCurrentIndex(setting[6])
        layout.addWidget(self.showEnterRoom, 6, 1, 1, 1)


class TextBrowser(QWidget):
    """弹幕机 - 弹出式窗口
    通过限制移动位置来模拟嵌入式窗口
    """
    closeSignal = Signal()
    moveSignal = Signal(QPoint)

    def __init__(self, parent):
        super(TextBrowser, self).__init__(parent)
        self.optionWidget = TextOpation()
        self.setWindowTitle('弹幕机')
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ---- 窗体布局 ----
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题栏
        self.bar = Bar(' 弹幕机')
        self.bar.setStyleSheet('background:#AAAAAAAA')
        self.bar.moveSignal.connect(self.moveWindow)
        layout.addWidget(self.bar, 0, 0, 1, 10)
        # 弹幕选项菜单
        self.optionButton = ToolButton(
            self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.optionButton.clicked.connect(self.optionWidget.show)  # 弹出设置菜单
        layout.addWidget(self.optionButton, 0, 8, 1, 1)
        # 关闭按钮
        self.closeButton = ToolButton(
            self.style().standardIcon(QStyle.SP_TitleBarCloseButton))
        self.closeButton.clicked.connect(self.userClose)
        layout.addWidget(self.closeButton, 0, 9, 1, 1)

        # 弹幕区域
        self.textBrowser = QTextBrowser()
        self.textBrowser.setFont(QFont('Microsoft JhengHei', 14, QFont.Bold))
        self.textBrowser.setStyleSheet('border-width:1')
        # textCursor = self.textBrowser.textCursor()
        # textBlockFormat = QTextBlockFormat()
        # textBlockFormat.setLineHeight(17, QTextBlockFormat.FixedHeight)  # 弹幕框行距
        # textCursor.setBlockFormat(textBlockFormat)
        # self.textBrowser.setTextCursor(textCursor)
        layout.addWidget(self.textBrowser, 1, 0, 1, 10)

        # 同传区域
        self.transBrowser = QTextBrowser()
        self.transBrowser.setFont(QFont('Microsoft JhengHei', 14, QFont.Bold))
        self.transBrowser.setStyleSheet('border-width:1')
        layout.addWidget(self.transBrowser, 2, 0, 1, 10)

        # 信息区域
        self.msgsBrowser = QTextBrowser()
        self.msgsBrowser.setFont(QFont('Microsoft JhengHei', 14, QFont.Bold))
        self.msgsBrowser.setStyleSheet('border-width:1')
        # self.msgsBrowser.setMaximumHeight(100)
        layout.addWidget(self.msgsBrowser, 3, 0, 1, 10)

    def userClose(self):
        self.hide()
        self.closeSignal.emit()

    def moveWindow(self, moveDelta):
        self.moveSignal.emit(self.pos() + moveDelta)


class MpvDanmakuRenderer:
    """MPV 弹幕渲染器 — ASS 字幕轨道方案

    通过动态生成 ASS 字幕文件并加载为 MPV 字幕轨道实现滚动弹幕。
    使用 ASS 的 \\move() 标签让 libass 以视频原生帧率插值动画，
    比手动 25fps 更新位置更流畅，接近 B站 原生弹幕效果。

    工作流程：
    1. 创建临时 .ass 文件，包含 ASS 头部和样式定义
    2. 通过 sub-add 加载为字幕轨道（仅在媒体播放后）
    3. 新弹幕到达时：追加 Dialogue 行（带 \\move 动画），重写文件，sub-reload 刷新
    4. 定时清理过期弹幕条目
    """

    PLAY_RES_X = 1920
    PLAY_RES_Y = 1080

    # ASS 文件头模板
    _ASS_HEADER = (
        '[Script Info]\n'
        'ScriptType: v4.00+\n'
        'PlayResX: {w}\n'
        'PlayResY: {h}\n'
        'WrapStyle: 2\n'
        'ScaledBorderAndShadow: yes\n'
        '\n'
        '[V4+ Styles]\n'
        'Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,'
        'OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,'
        'ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,'
        'Alignment,MarginL,MarginR,MarginV,Encoding\n'
        'Style: Default,微软雅黑,{fs},&H00FFFFFF,&H000000FF,'
        '&H00000000,&H40000000,1,0,0,0,'
        '100,100,0,0,1,2,0,7,0,0,0,1\n'
        '\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )

    def __init__(self):
        self._mpv = None
        self._dialogues = []      # 活跃的 Dialogue 条目
        self._lane_end_time = {}  # lane -> 该轨道解除占用的 time_pos
        self._font_size = 40
        self._duration = 12.0     # 弹幕滚过屏幕的时长（秒）
        self._enabled = True
        self._opacity = 200       # 0-255
        self._max_lane_ratio = 0.55

        # 临时 ASS 文件
        fd, self._ass_path = tempfile.mkstemp(suffix='.ass', prefix='dd_danmaku_')
        os.close(fd)
        self._sub_loaded = False

        # 批量刷新定时器（避免每条弹幕都写文件+reload）
        self._flush_timer = QTimer()
        self._flush_timer.timeout.connect(self._flush)
        self._flush_timer.setInterval(150)  # 150ms 批量刷新
        self._dirty = False

        # 定期清理过期弹幕
        self._cleanup_timer = QTimer()
        self._cleanup_timer.timeout.connect(self._cleanup)
        self._cleanup_timer.setInterval(5000)

    def setMpv(self, mpv_instance):
        """绑定 MPV 播放器实例"""
        self._mpv = mpv_instance
        # 写入初始空 ASS 文件
        self._writeAss()

    def setEnabled(self, enabled):
        self._enabled = enabled
        if not enabled:
            self._dialogues.clear()
            self._lane_end_time.clear()
            self._flush_timer.stop()
            self._cleanup_timer.stop()
            self._writeAss()
            self._reloadSub()

    def setFontSize(self, size):
        self._font_size = max(20, min(size, 60))

    def setDuration(self, seconds):
        """设置弹幕滚过屏幕的时长"""
        self._duration = max(5.0, min(seconds, 20.0))

    def setOpacity(self, value):
        """设置弹幕透明度 (0-255)"""
        self._opacity = max(0, min(value, 255))

    def addDanmaku(self, text, color='#FFFFFF'):
        """添加一条滚动弹幕"""
        if not self._enabled or not self._mpv or not text.strip():
            return

        # 获取当前播放时间
        time_pos = self._getTimePos()
        if time_pos is None:
            return

        lane = self._findLane(time_pos)
        if lane < 0:
            return  # 轨道全满，丢弃

        lane_height = self._font_size + 10
        y = lane * lane_height + self._font_size + 8

        # 估算文字宽度
        cjk_count = sum(1 for c in text if ord(c) > 0x2E80)
        ascii_count = len(text) - cjk_count
        width = int(cjk_count * self._font_size + ascii_count * self._font_size * 0.55 + 30)

        start_t = time_pos
        end_t = time_pos + self._duration

        # 标记轨道占用（后续弹幕需等右边缘过了安全阈值才能使用同一轨道）
        # 安全阈值：弹幕右边缘离开屏幕右侧 ~35% 的时刻
        self._lane_end_time[lane] = start_t + self._duration * 0.35

        # ASS 颜色和透明度
        ass_color = self._rgbToAss(color)
        alpha = format(255 - self._opacity, '02X')

        # 转义 ASS 特殊字符
        safe = text.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')

        # 构建 \\move 动画：从屏幕右侧移动到左侧外
        tags = (
            '{' +
            f'\\move({self.PLAY_RES_X},{y},{-width},{y})'
            f'\\fs{self._font_size}'
            f'\\1c{ass_color}\\1a&H{alpha}&'
            f'\\b1\\bord2\\3c&H000000&\\3a&H40&\\shad0'
            f'\\fn微软雅黑'
            '}'
        )
        line = f'Dialogue: 0,{self._fmtTime(start_t)},{self._fmtTime(end_t)},Default,,0,0,0,,{tags}{safe}'

        self._dialogues.append({
            'line': line,
            'end_time': end_t,
        })

        # 标记需要刷新
        self._dirty = True
        if not self._flush_timer.isActive():
            self._flush_timer.start()
        if not self._cleanup_timer.isActive():
            self._cleanup_timer.start()

    def stop(self):
        """停止渲染并清除画面"""
        self._flush_timer.stop()
        self._cleanup_timer.stop()
        self._dialogues.clear()
        self._lane_end_time.clear()
        self._writeAss()
        self._reloadSub()

    def cleanup_file(self):
        """清理临时文件（程序退出时调用）"""
        try:
            if os.path.exists(self._ass_path):
                os.unlink(self._ass_path)
        except OSError:
            pass

    # ---- 内部方法 ----

    def _getTimePos(self):
        """安全获取播放时间"""
        try:
            pos = self._mpv.time_pos
            return pos if pos is not None else None
        except Exception:
            return None

    def _findLane(self, current_time):
        """寻找可用弹道"""
        max_y = self.PLAY_RES_Y * self._max_lane_ratio
        lane_height = self._font_size + 10
        max_lanes = max(1, int(max_y / lane_height))

        for lane in range(max_lanes):
            if lane not in self._lane_end_time:
                return lane
            if current_time >= self._lane_end_time[lane]:
                return lane
        return -1

    def _flush(self):
        """批量写入文件并刷新字幕"""
        if not self._dirty:
            self._flush_timer.stop()
            return
        self._dirty = False
        self._writeAss()
        self._reloadSub()

    def _cleanup(self):
        """清理过期弹幕"""
        time_pos = self._getTimePos()
        if time_pos is None:
            return

        before = len(self._dialogues)
        self._dialogues = [d for d in self._dialogues if d['end_time'] > time_pos]

        # 清理过期轨道占用
        expired_lanes = [
            lane for lane, t in self._lane_end_time.items()
            if t <= time_pos
        ]
        for lane in expired_lanes:
            del self._lane_end_time[lane]

        if len(self._dialogues) < before:
            self._writeAss()
            self._reloadSub()

        if not self._dialogues:
            self._cleanup_timer.stop()

    def _writeAss(self):
        """生成并写入 ASS 字幕文件"""
        header = self._ASS_HEADER.format(
            w=self.PLAY_RES_X, h=self.PLAY_RES_Y, fs=self._font_size
        )
        lines = '\n'.join(d['line'] for d in self._dialogues)
        content = header + lines + '\n'
        try:
            with open(self._ass_path, 'w', encoding='utf-8-sig') as f:
                f.write(content)
        except OSError:
            logging.exception('写入 ASS 弹幕文件失败')

    def _reloadSub(self):
        """加载或刷新字幕轨道"""
        if not self._mpv:
            return
        try:
            if not self._sub_loaded:
                self._mpv.command('sub-add', self._ass_path)
                self._sub_loaded = True
                logging.info(f'弹幕字幕轨道已加载: {self._ass_path}')
            else:
                self._mpv.command('sub-reload')
        except Exception:
            # sub-add 在无媒体时会失败，标记为未加载以便下次重试
            self._sub_loaded = False

    @staticmethod
    def _fmtTime(seconds):
        """秒 -> ASS 时间格式 H:MM:SS.CC"""
        if seconds < 0:
            seconds = 0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f'{h}:{m:02d}:{s:05.2f}'

    @staticmethod
    def _rgbToAss(color_str):
        """#RRGGBB -> &HBBGGRR& (ASS 使用 BGR 字节序)"""
        c = color_str.lstrip('#')
        if len(c) != 6:
            return '&HFFFFFF&'
        return f'&H{c[4:6]}{c[2:4]}{c[0:2]}&'
