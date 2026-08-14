"""将弹幕机分离出来单独开发"""

from PySide6.QtWidgets import (
    QLabel,
    QToolButton,
    QWidget,
    QTextBrowser,
    QGridLayout,
    QVBoxLayout,
    QFrame,
)
from PySide6.QtGui import QFont, QPainterPath
from PySide6.QtCore import Qt, Signal, QPoint, QSize, QRectF
from app.ui.common_widget import Slider  # 保留：sliderValue 信号被主窗口/弹幕机连接
from app.ui.title_bar import FluentWindow
from qfluentwidgets_pro import (
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    Icon,
    LineEdit,
    Slider as FluentSlider,
    TabWidget,
)
from qfluentwidgets_pro.components.material.acrylic_widget import AcrylicWidget
from app.ui.uikit_bridge import is_dark, theme_changed

# 弹幕显示比例（定义在 constants.py，此处重导出兼容旧导入路径）
from app.core.constants import DISPLAY_RATIOS  # noqa: F401
# 弹幕配置数据类（独立模块，纯数据无 Qt 依赖；重导出兼容旧导入路径）
from app.danmaku.settings import DanmakuSettings  # noqa: F401

# 弹幕机标题栏图标映射（Fluent 矢量图标，颜色随主题自动适配）
_DANMU_ICONS = {"settings": FluentIcon.SETTING, "close": FluentIcon.CLOSE}


class Bar(QLabel):
    """自定义标题栏"""

    moveSignal = Signal(QPoint)

    def __init__(self, text):
        super(Bar, self).__init__()
        self.setText(text)
        self.setFixedHeight(25)
        self.startPos = self.pos()
        self.pressToken = False
        self._applyThemeColor()
        theme_changed().connect(self._applyThemeColor)

    def _applyThemeColor(self, dark=None):
        # 标题栏半透明底：暗色偏黑 / 亮色偏白，保证与图标文字对比清晰
        if is_dark():
            self.setStyleSheet("background: rgba(0,0,0,0.72)")
        else:
            self.setStyleSheet("background: rgba(255,255,255,0.82)")

    def mousePressEvent(self, event):
        self.startPos = event.pos()
        self.pressToken = True

    def mouseReleaseEvent(self, event):
        self.pressToken = False

    def mouseMoveEvent(self, event):
        if self.pressToken:
            self.moveSignal.emit(self.mapToParent(event.pos() - self.startPos))


class ToolButton(QToolButton):
    """标题栏按钮（Fluent 矢量图标，颜色随主题自动适配）

    注意：不能继承 qfluentwidgets 的 ToolButton——其构造用 singledispatch
    重载，子类里 super().__init__(icon=...) 会被转发回子类自身导致
    TypeError（弹幕机创建即崩）。用 QToolButton + Icon(QIcon) 同效。
    """

    def __init__(self, icon_name, size=18):
        super().__init__()
        self.setFixedSize(25, 25)
        self.setIconSize(QSize(size, size))
        self.setIcon(Icon(_DANMU_ICONS.get(icon_name, FluentIcon.INFO)))


class TextOption(FluentWindow):
    """弹幕机选项 - 弹出式窗口（SettingCard 卡片化）"""

    def __init__(self, setting=None):
        super(TextOption, self).__init__(title="弹幕窗设置")
        if setting is None:
            setting = [50, 1, 7, 0, "【 [ {", 10, 0]
        setting = list(setting)  # 防御：避免外部修改影响默认值
        self.resize(380, 460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)

        # ---- SettingCard 布局 ----
        from qfluentwidgets_pro.components.settings.setting_card import SettingCard
        from qfluentwidgets_pro.components.settings.setting_card_group import SettingCardGroup

        group = SettingCardGroup("弹幕窗", self)

        def _card(icon, title, content, widget):
            card = SettingCard(icon, title, content, self)
            card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(12)
            group.addSettingCard(card)

        # 字体大小
        self.fontSizeCombox = ComboBox()
        self.fontSizeCombox.addItems([str(i) for i in range(5, 26)])
        self.fontSizeCombox.setCurrentIndex(setting[5])
        _card(FluentIcon.FONT, "字体大小", "弹幕文字字号", self.fontSizeCombox)

        # 窗体透明度
        self.opacitySlider = Slider()
        self.opacitySlider.setValue(setting[0])
        _card(FluentIcon.ALBUM, "窗体透明度", "弹幕窗整体透明度", self.opacitySlider)

        # 窗体横向占比
        self.horizontalCombobox = ComboBox()
        self.horizontalCombobox.addItems(["%d" % x + "%" for x in range(10, 110, 10)])
        self.horizontalCombobox.setCurrentIndex(setting[1])
        _card(FluentIcon.ALIGNMENT, "窗体横向占比", "弹幕窗宽度占屏幕比例", self.horizontalCombobox)

        # 窗体纵向占比
        self.verticalCombobox = ComboBox()
        self.verticalCombobox.addItems(["%d" % x + "%" for x in range(10, 110, 10)])
        self.verticalCombobox.setCurrentIndex(setting[2])
        _card(FluentIcon.ALIGNMENT, "窗体纵向占比", "弹幕窗高度占屏幕比例", self.verticalCombobox)

        # 弹幕窗类型
        self.translateCombobox = ComboBox()
        self.translateCombobox.addItems(["弹幕和同传", "只显示弹幕", "只显示同传"])
        self.translateCombobox.setCurrentIndex(setting[3])
        _card(FluentIcon.CHAT, "弹幕窗类型", "弹幕与同传的显示方式", self.translateCombobox)

        # 同传过滤字符
        self.translateFitler = LineEdit()
        self.translateFitler.setText(setting[4])
        self.translateFitler.setFixedWidth(120)
        self.translateFitler.setPlaceholderText("空格分隔关键词")
        _card(FluentIcon.FILTER, "同传过滤字符", "命中关键词的同传将被过滤", self.translateFitler)

        # 礼物和进入信息
        self.showEnterRoom = ComboBox()
        self.showEnterRoom.addItems(["显示礼物和进入信息", "只显示礼物", "只显示进入信息", "隐藏窗口"])
        self.showEnterRoom.setCurrentIndex(setting[6])
        _card(FluentIcon.HEART, "礼物和进入信息", "信息区显示策略", self.showEnterRoom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(group)
        layout.addStretch()


class TextBrowser(AcrylicWidget, QWidget):
    """弹幕机 - 弹出式窗口（Fluent 毛玻璃 + 圆角）

    通过限制移动位置来模拟嵌入式窗口。背景用组件库 AcrylicWidget
    （半透明 tint + 噪点纹理，深浅主题自适应），圆角裁剪见
    acrylicClipPath。
    """

    closeSignal = Signal()
    moveSignal = Signal(QPoint)

    def __init__(self, parent):
        super(TextBrowser, self).__init__(parent)
        self.optionWidget = TextOption()
        self.setWindowTitle("弹幕机")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ---- 窗体布局（三区：弹幕 60% / 同传 25% / 信息 15%）----
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(6)

        # 标题栏（透明底，由毛玻璃背景透出）
        self.bar = Bar(" 弹幕机")
        self.bar.moveSignal.connect(self.moveWindow)
        layout.addWidget(self.bar, 0, 0, 1, 8)
        # 弹幕选项菜单
        self.optionButton = ToolButton("settings")
        self.optionButton.setToolTip("弹幕设置")
        self.optionButton.clicked.connect(self.optionWidget.show)  # 弹出设置菜单
        layout.addWidget(self.optionButton, 0, 8, 1, 1, alignment=Qt.AlignVCenter)
        # 关闭按钮
        self.closeButton = ToolButton("close")
        self.closeButton.setToolTip("关闭")
        self.closeButton.clicked.connect(self.userClose)
        layout.addWidget(self.closeButton, 0, 9, 1, 1, alignment=Qt.AlignVCenter)

        # 弹幕区域（主区 60%）
        self.textBrowser = self._create_zone(QFont("Microsoft JhengHei", 14, QFont.Bold))
        layout.addWidget(self.textBrowser, 1, 0, 3, 10)

        # 同传区域（25%）
        self.transBrowser = self._create_zone(QFont("Microsoft JhengHei", 13, QFont.Bold))
        layout.addWidget(self.transBrowser, 4, 0, 1, 10)

        # 信息区域（15%，单行紧凑）
        self.msgsBrowser = self._create_zone(QFont("Microsoft JhengHei", 12, QFont.Bold))
        self.msgsBrowser.setMaximumHeight(64)
        layout.addWidget(self.msgsBrowser, 5, 0, 1, 10)

        # 深浅主题刷新（文字/分区底色）
        self._apply_theme_colors()
        theme_changed().connect(self._apply_theme_colors)

    @staticmethod
    def _create_zone(font):
        """创建圆角半透明弹幕分区（背景半透明白/黑，文字主题色）"""
        zone = QTextBrowser()
        zone.setFont(font)
        # 限制文档最大行数，防止长时间运行内存无限增长（内存泄漏）
        zone.document().setMaximumBlockCount(500)
        zone.setFrameShape(QFrame.NoFrame)
        return zone

    def _apply_theme_colors(self, *args):
        if is_dark():
            bg, fg, border = "rgba(255,255,255,14)", "#F1F5F9", "rgba(255,255,255,26)"
        else:
            bg, fg, border = "rgba(255,255,255,120)", "#1C2330", "rgba(0,0,0,40)"
        for zone in (self.textBrowser, self.transBrowser, self.msgsBrowser):
            zone.setStyleSheet(
                f"QTextBrowser{{background-color:{bg};color:{fg};"
                f"border:1px solid {border};border-radius:8px;"
                f"padding:4px 8px;}}"
            )
        # 标题栏文字颜色
        self.bar.setStyleSheet(
            f"color:{fg};background:transparent;font-size:12px;font-weight:600;"
        )

    def acrylicClipPath(self):
        """毛玻璃圆角裁剪（12px 圆角）"""
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        return path

    def userClose(self):
        self.hide()
        self.closeSignal.emit()

    def moveWindow(self, moveDelta):
        self.moveSignal.emit(self.pos() + moveDelta)


class RollingOptionWidget(QWidget):
    """滚动弹幕设置面板（SettingCard 卡片化）"""

    def __init__(self, settings_dict=None):
        super().__init__()
        if settings_dict is None:
            settings_dict = {}

        from qfluentwidgets_pro.components.settings.setting_card import SettingCard
        from qfluentwidgets_pro.components.settings.setting_card_group import SettingCardGroup

        group = SettingCardGroup("滚动弹幕", self)

        def _card(icon, title, content, widget):
            card = SettingCard(icon, title, content, self)
            card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(12)
            group.addSettingCard(card)

        # 弹幕透明度
        self.opacitySlider = Slider()
        self.opacitySlider.setValue(int(settings_dict.get("opacity", 50)))
        _card(FluentIcon.ALBUM, "弹幕透明度", "滚动弹幕整体透明度", self.opacitySlider)

        # 显示区域
        self.displayAreaCombobox = ComboBox()
        self.displayAreaCombobox.addItems([f"{x}%" for x in range(10, 110, 10)])
        self.displayAreaCombobox.setCurrentIndex(int(settings_dict.get("display_area", 7)))
        _card(FluentIcon.ALIGNMENT, "显示区域", "滚动弹幕显示区域占比", self.displayAreaCombobox)

        # 字体大小
        self.fontSizeCombox = ComboBox()
        self.fontSizeCombox.addItems([str(i) for i in range(5, 26)])
        self.fontSizeCombox.setCurrentIndex(int(settings_dict.get("font_size", 10)))
        _card(FluentIcon.FONT, "字体大小", "滚动弹幕字体大小", self.fontSizeCombox)

        # 字体
        self.fontFamilyCombobox = EditableComboBox()
        self.fontFamilyCombobox.addItems(
            ["Microsoft YaHei", "SimHei", "Microsoft JhengHei", "Arial", "Noto Sans SC", "PingFang SC"]
        )
        current_family = str(settings_dict.get("font_family", "Microsoft YaHei"))
        idx = self.fontFamilyCombobox.findText(current_family)
        if idx >= 0:
            self.fontFamilyCombobox.setCurrentIndex(idx)
        self.fontFamilyCombobox.setText(current_family)
        _card(FluentIcon.FONT, "字体", "弹幕文字字体族", self.fontFamilyCombobox)

        # 弹幕速度
        self.speedSlider = FluentSlider(Qt.Horizontal)
        self.speedSlider.setRange(50, 200)
        self.speedSlider.setValue(int(settings_dict.get("speed_percent", 85)))
        _card(FluentIcon.PLAY, "弹幕速度", "滚动速度（50-200%）", self.speedSlider)

        # 描边粗细
        self.strokeWidthSlider = FluentSlider(Qt.Horizontal)
        self.strokeWidthSlider.setRange(0, 60)
        self.strokeWidthSlider.setValue(int(settings_dict.get("stroke_width", 30)))
        _card(FluentIcon.EDIT, "描边粗细", "文字描边宽度", self.strokeWidthSlider)

        # 阴影效果
        self.shadowEnabledCheckBox = CheckBox()
        self.shadowEnabledCheckBox.setChecked(bool(settings_dict.get("shadow_enabled", False)))
        _card(FluentIcon.COMPLETED, "阴影效果", "弹幕文字投影", self.shadowEnabledCheckBox)

        # 阴影强度
        self.shadowStrengthSlider = FluentSlider(Qt.Horizontal)
        self.shadowStrengthSlider.setRange(0, 100)
        self.shadowStrengthSlider.setValue(int(settings_dict.get("shadow_strength", 35)))
        _card(FluentIcon.EDIT, "阴影强度", "投影强度", self.shadowStrengthSlider)

        # 允许顶部弹幕
        self.topEnabledCheckBox = CheckBox()
        self.topEnabledCheckBox.setChecked(bool(settings_dict.get("top_enabled", True)))
        _card(FluentIcon.UP, "允许顶部弹幕", "顶部固定弹幕开关", self.topEnabledCheckBox)

        # 允许底部弹幕
        self.bottomEnabledCheckBox = CheckBox()
        self.bottomEnabledCheckBox.setChecked(bool(settings_dict.get("bottom_enabled", True)))
        _card(FluentIcon.DOWN, "允许底部弹幕", "底部固定弹幕开关", self.bottomEnabledCheckBox)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(group)
        layout.addStretch()

    def sync_from_dict(self, settings_dict):
        self.opacitySlider.setValue(int(settings_dict.get("opacity", 50)))
        self.displayAreaCombobox.setCurrentIndex(int(settings_dict.get("display_area", 7)))
        self.fontSizeCombox.setCurrentIndex(int(settings_dict.get("font_size", 10)))
        family = str(settings_dict.get("font_family", "Microsoft YaHei"))
        idx = self.fontFamilyCombobox.findText(family)
        if idx >= 0:
            self.fontFamilyCombobox.setCurrentIndex(idx)
        self.speedSlider.setValue(int(settings_dict.get("speed_percent", 85)))
        self.strokeWidthSlider.setValue(int(settings_dict.get("stroke_width", 30)))
        self.shadowEnabledCheckBox.setChecked(bool(settings_dict.get("shadow_enabled", False)))
        self.shadowStrengthSlider.setValue(int(settings_dict.get("shadow_strength", 35)))
        self.topEnabledCheckBox.setChecked(bool(settings_dict.get("top_enabled", True)))
        self.bottomEnabledCheckBox.setChecked(bool(settings_dict.get("bottom_enabled", True)))


class GlobalDanmuOption(FluentWindow):
    """全局弹幕设置面板 — 浏览器弹幕 + 滚动弹幕综合设置"""

    def __init__(self, danmu_config_list, rolling_config_dict):
        super().__init__(title="全局弹幕设置")
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.resize(400, 550)

        tabs = TabWidget()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)

        # config 弹幕格式为 9 项 [enabled, opacity, horiz, vert, translate, filter, font_size, show_enter, rolling]
        # TextOption 期望 7 项 [opacity, horiz, vert, translate, filter, font_size, show_enter]
        # 必须跳过 enabled(索引0) 取 [1:8]，否则错位导致 setCurrentIndex(str) TypeError 崩溃
        setting = list(danmu_config_list[1:8]) if isinstance(danmu_config_list, list) else [50, 1, 7, 0, "【 [ {", 10, 0]
        self.browserOptionWidget = TextOption(setting)
        tabs.addTab(self.browserOptionWidget, "弹幕窗")

        self.rollingOptionWidget = RollingOptionWidget(rolling_config_dict)
        tabs.addTab(self.rollingOptionWidget, "滚动弹幕")

    def syncBrowserSetting(self, danmu_config_list):
        if isinstance(danmu_config_list, list):
            cfg = list(danmu_config_list)
            self.browserOptionWidget.opacitySlider.setValue(cfg[1] if len(cfg) > 1 else 50)
            self.browserOptionWidget.horizontalCombobox.setCurrentIndex(cfg[2] if len(cfg) > 2 else 1)
            self.browserOptionWidget.verticalCombobox.setCurrentIndex(cfg[3] if len(cfg) > 3 else 7)
            self.browserOptionWidget.translateCombobox.setCurrentIndex(cfg[4] if len(cfg) > 4 else 0)
            self.browserOptionWidget.translateFitler.setText(cfg[5] if len(cfg) > 5 else "【 [ {")
            self.browserOptionWidget.fontSizeCombox.setCurrentIndex(cfg[6] if len(cfg) > 6 else 10)
            self.browserOptionWidget.showEnterRoom.setCurrentIndex(cfg[7] if len(cfg) > 7 else 0)

    def syncRollingSetting(self, settings_dict):
        self.rollingOptionWidget.sync_from_dict(settings_dict)
