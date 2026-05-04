"""将弹幕机分离出来单独开发
"""
import logging
from dataclasses import dataclass

from PySide6.QtWidgets import QLabel, QToolButton, QWidget, QComboBox, QLineEdit, QTextBrowser, QGridLayout, QStyle, QCheckBox, QSlider, QTabWidget
from PySide6.QtGui import QFont, QColor
from PySide6.QtCore import Qt, Signal, QPoint
from CommonWidget import Slider

# 全局显示比例选项
DISPLAY_RATIOS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


@dataclass
class DanmakuSettings:
    """弹幕配置 — 替代旧版 textSetting list 魔法索引。

    旧版索引: [0=enabled, 1=opacity, 2=horiz_idx, 3=vert_idx, 4=translate_mode,
                5=filters, 6=font_size, 7=enter_room, 8=rolling_enabled]
    """
    enabled: bool = True
    opacity: int = 50
    horizontal_index: int = 1
    vertical_index: int = 7
    translate_mode: int = 0
    translate_filters: str = '【 [ {'
    font_size: int = 10
    show_enter_room: int = 0
    rolling_enabled: bool = True

    def to_config_list(self):
        """导出为兼容旧 config.json 的列表格式"""
        return [self.enabled, self.opacity, self.horizontal_index,
                self.vertical_index, self.translate_mode,
                self.translate_filters, self.font_size,
                self.show_enter_room, self.rolling_enabled]

    @classmethod
    def from_config_list(cls, data):
        """从 config.json 列表格式恢复"""
        defaults = [True, 50, 1, 7, 0, '【 [ {', 10, 0, True]
        if isinstance(data, bool):
            data = [data, 20, 1, 7, 0, '【 [ {', 10, 0, data]
        lst = list(data)
        while len(lst) < 9:
            lst.append(defaults[len(lst)])
        lst = lst[:9]
        return cls(
            enabled=bool(lst[0]),
            opacity=max(7, int(lst[1])),
            horizontal_index=max(0, min(int(lst[2]), 9)),
            vertical_index=max(0, min(int(lst[3]), 9)),
            translate_mode=max(0, min(int(lst[4]), 2)),
            translate_filters=str(lst[5]),
            font_size=max(0, min(int(lst[6]), 25)),
            show_enter_room=max(0, min(int(lst[7]), 3)),
            rolling_enabled=bool(lst[8]),
        )

    # 兼容旧代码的列表索引访问
    _INDEX_MAP = {
        0: 'enabled', 1: 'opacity', 2: 'horizontal_index',
        3: 'vertical_index', 4: 'translate_mode', 5: 'translate_filters',
        6: 'font_size', 7: 'show_enter_room', 8: 'rolling_enabled',
    }

    def __getitem__(self, index):
        if index in self._INDEX_MAP:
            return getattr(self, self._INDEX_MAP[index])
        raise IndexError(f'DanmakuSettings index out of range: {index}')

    def __setitem__(self, index, value):
        if index in self._INDEX_MAP:
            setattr(self, self._INDEX_MAP[index], value)
            return
        raise IndexError(f'DanmakuSettings index out of range: {index}')


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


class TextOption(QWidget):
    """弹幕机选项 - 弹出式窗口"""

    def __init__(self, setting=[50, 1, 7, 0, '【 [ {', 10, 0]):
        super(TextOption, self).__init__()
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
        self.optionWidget = TextOption()
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




class RollingOptionWidget(QWidget):
    """滚动弹幕设置面板"""

    def __init__(self, settings_dict=None):
        super().__init__()
        if settings_dict is None:
            settings_dict = {}
        layout = QGridLayout(self)

        layout.addWidget(QLabel('弹幕透明度'), 0, 0, 1, 1)
        self.opacitySlider = Slider()
        self.opacitySlider.setValue(int(settings_dict.get('opacity', 50)))
        layout.addWidget(self.opacitySlider, 0, 1, 1, 1)

        layout.addWidget(QLabel('显示区域'), 1, 0, 1, 1)
        self.displayAreaCombobox = QComboBox()
        self.displayAreaCombobox.addItems([f'{x}%' for x in range(10, 110, 10)])
        self.displayAreaCombobox.setCurrentIndex(int(settings_dict.get('display_area', 7)))
        layout.addWidget(self.displayAreaCombobox, 1, 1, 1, 1)

        layout.addWidget(QLabel('字体大小'), 2, 0, 1, 1)
        self.fontSizeCombox = QComboBox()
        self.fontSizeCombox.addItems([str(i) for i in range(5, 26)])
        self.fontSizeCombox.setCurrentIndex(int(settings_dict.get('font_size', 10)))
        layout.addWidget(self.fontSizeCombox, 2, 1, 1, 1)

        layout.addWidget(QLabel('字体'), 3, 0, 1, 1)
        self.fontFamilyCombobox = QComboBox()
        self.fontFamilyCombobox.addItems(['Microsoft YaHei', 'SimHei', 'Microsoft JhengHei',
                                           'Arial', 'Noto Sans SC', 'PingFang SC'])
        current_family = str(settings_dict.get('font_family', 'Microsoft YaHei'))
        idx = self.fontFamilyCombobox.findText(current_family)
        if idx >= 0:
            self.fontFamilyCombobox.setCurrentIndex(idx)
        self.fontFamilyCombobox.setEditable(True)
        layout.addWidget(self.fontFamilyCombobox, 3, 1, 1, 1)

        layout.addWidget(QLabel('弹幕速度'), 4, 0, 1, 1)
        self.speedSlider = QSlider(Qt.Horizontal)
        self.speedSlider.setRange(50, 200)
        self.speedSlider.setValue(int(settings_dict.get('speed_percent', 85)))
        layout.addWidget(self.speedSlider, 4, 1, 1, 1)

        layout.addWidget(QLabel('描边粗细'), 5, 0, 1, 1)
        self.strokeWidthSlider = QSlider(Qt.Horizontal)
        self.strokeWidthSlider.setRange(0, 60)
        self.strokeWidthSlider.setValue(int(settings_dict.get('stroke_width', 30)))
        layout.addWidget(self.strokeWidthSlider, 5, 1, 1, 1)

        from PySide6.QtWidgets import QCheckBox
        layout.addWidget(QLabel('阴影效果'), 6, 0, 1, 1)
        self.shadowEnabledCheckBox = QCheckBox()
        self.shadowEnabledCheckBox.setChecked(bool(settings_dict.get('shadow_enabled', False)))
        layout.addWidget(self.shadowEnabledCheckBox, 6, 1, 1, 1)

        layout.addWidget(QLabel('阴影强度'), 7, 0, 1, 1)
        self.shadowStrengthSlider = QSlider(Qt.Horizontal)
        self.shadowStrengthSlider.setRange(0, 100)
        self.shadowStrengthSlider.setValue(int(settings_dict.get('shadow_strength', 35)))
        layout.addWidget(self.shadowStrengthSlider, 7, 1, 1, 1)

        layout.addWidget(QLabel('允许顶部弹幕'), 8, 0, 1, 1)
        self.topEnabledCheckBox = QCheckBox()
        self.topEnabledCheckBox.setChecked(bool(settings_dict.get('top_enabled', True)))
        layout.addWidget(self.topEnabledCheckBox, 8, 1, 1, 1)

        layout.addWidget(QLabel('允许底部弹幕'), 9, 0, 1, 1)
        self.bottomEnabledCheckBox = QCheckBox()
        self.bottomEnabledCheckBox.setChecked(bool(settings_dict.get('bottom_enabled', True)))
        layout.addWidget(self.bottomEnabledCheckBox, 9, 1, 1, 1)

    def sync_from_dict(self, settings_dict):
        self.opacitySlider.setValue(int(settings_dict.get('opacity', 50)))
        self.displayAreaCombobox.setCurrentIndex(int(settings_dict.get('display_area', 7)))
        self.fontSizeCombox.setCurrentIndex(int(settings_dict.get('font_size', 10)))
        family = str(settings_dict.get('font_family', 'Microsoft YaHei'))
        idx = self.fontFamilyCombobox.findText(family)
        if idx >= 0:
            self.fontFamilyCombobox.setCurrentIndex(idx)
        self.speedSlider.setValue(int(settings_dict.get('speed_percent', 85)))
        self.strokeWidthSlider.setValue(int(settings_dict.get('stroke_width', 30)))
        self.shadowEnabledCheckBox.setChecked(bool(settings_dict.get('shadow_enabled', False)))
        self.shadowStrengthSlider.setValue(int(settings_dict.get('shadow_strength', 35)))
        self.topEnabledCheckBox.setChecked(bool(settings_dict.get('top_enabled', True)))
        self.bottomEnabledCheckBox.setChecked(bool(settings_dict.get('bottom_enabled', True)))


class GlobalDanmuOption(QWidget):
    """全局弹幕设置面板 — 浏览器弹幕 + 滚动弹幕综合设置"""

    def __init__(self, danmu_config_list, rolling_config_dict):
        super().__init__()
        self.setWindowTitle('全局弹幕设置')
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.resize(400, 550)

        from PySide6.QtWidgets import QTabWidget
        tabs = QTabWidget()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)

        setting = list(danmu_config_list[:7]) if isinstance(danmu_config_list, list) else [50, 1, 7, 0, '【 [ {', 10, 0]
        self.browserOptionWidget = TextOption(setting)
        tabs.addTab(self.browserOptionWidget, '弹幕窗')

        self.rollingOptionWidget = RollingOptionWidget(rolling_config_dict)
        tabs.addTab(self.rollingOptionWidget, '滚动弹幕')

    def syncBrowserSetting(self, danmu_config_list):
        if isinstance(danmu_config_list, list):
            cfg = list(danmu_config_list)
            self.browserOptionWidget.opacitySlider.setValue(cfg[1] if len(cfg) > 1 else 50)
            self.browserOptionWidget.horizontalCombobox.setCurrentIndex(cfg[2] if len(cfg) > 2 else 1)
            self.browserOptionWidget.verticalCombobox.setCurrentIndex(cfg[3] if len(cfg) > 3 else 7)
            self.browserOptionWidget.translateCombobox.setCurrentIndex(cfg[4] if len(cfg) > 4 else 0)
            self.browserOptionWidget.translateFitler.setText(cfg[5] if len(cfg) > 5 else '【 [ {')
            self.browserOptionWidget.fontSizeCombox.setCurrentIndex(cfg[6] if len(cfg) > 6 else 10)
            self.browserOptionWidget.showEnterRoom.setCurrentIndex(cfg[7] if len(cfg) > 7 else 0)

    def syncRollingSetting(self, settings_dict):
        self.rollingOptionWidget.sync_from_dict(settings_dict)
