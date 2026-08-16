"""将弹幕机分离出来单独开发"""

from PySide6.QtWidgets import (
    QLabel,
    QWidget,
    QGridLayout,
    QVBoxLayout,
    QFrame,
)
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtCore import Qt, Signal, QPoint, QRectF
from app.ui.common_widget import Slider  # 保留：sliderValue 信号被主窗口/弹幕机连接
from app.ui.title_bar import FluentWindow
from qfluentwidgets_pro import (
    CheckBox,
    ComboBox,
    EditableComboBox,
    FluentIcon,
    LineEdit,
    Slider as FluentSlider,
    SmoothScrollArea,
    TabWidget,
)
from qfluentwidgets_pro.components.material.acrylic_widget import AcrylicWidget
from qfluentwidgets_pro.components.widgets.button import TransparentToolButton
from app.ui.uikit_bridge import is_dark, theme_changed
from app.ui.danmaku_workbench import DanmakuWorkbench

# 弹幕显示比例（定义在 constants.py，此处重导出兼容旧导入路径）
from app.core.constants import DISPLAY_RATIOS  # noqa: F401
# 弹幕配置数据类（独立模块，纯数据无 Qt 依赖；重导出兼容旧导入路径）
from app.danmaku.settings import DanmakuSettings  # noqa: F401

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


class BrowserOptionWidget(QWidget):
    """浏览器弹幕设置页，可嵌入全局设置或独立弹窗。"""

    CONTROL_NAMES = (
        "fontSizeCombox",
        "opacitySlider",
        "horizontalCombobox",
        "verticalCombobox",
        "translateCombobox",
        "translateFitler",
        "showEnterRoom",
    )

    def __init__(self, setting=None, parent=None):
        super().__init__(parent)
        if setting is None:
            setting = [50, 1, 7, 0, "【 [ {", 10, 0]
        setting = list(setting)

        from qfluentwidgets_pro.components.settings.setting_card import SettingCard
        from qfluentwidgets_pro.components.settings.setting_card_group import SettingCardGroup

        group = SettingCardGroup("弹幕窗", self)

        def _card(icon, title, content, widget):
            card = SettingCard(icon, title, content, self)
            card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
            card.hBoxLayout.addSpacing(12)
            group.addSettingCard(card)

        self.fontSizeCombox = ComboBox()
        self.fontSizeCombox.addItems([str(i) for i in range(5, 26)])
        self.fontSizeCombox.setCurrentIndex(setting[5])
        _card(FluentIcon.FONT, "字体大小", "弹幕文字字号", self.fontSizeCombox)

        self.opacitySlider = Slider()
        self.opacitySlider.setValue(setting[0])
        _card(FluentIcon.ALBUM, "窗体透明度", "弹幕窗整体透明度", self.opacitySlider)

        self.horizontalCombobox = ComboBox()
        self.horizontalCombobox.addItems(["%d" % x + "%" for x in range(10, 110, 10)])
        self.horizontalCombobox.setCurrentIndex(setting[1])
        _card(FluentIcon.ALIGNMENT, "窗体横向占比", "弹幕窗宽度占屏幕比例", self.horizontalCombobox)

        self.verticalCombobox = ComboBox()
        self.verticalCombobox.addItems(["%d" % x + "%" for x in range(10, 110, 10)])
        self.verticalCombobox.setCurrentIndex(setting[2])
        _card(FluentIcon.ALIGNMENT, "窗体纵向占比", "弹幕窗高度占屏幕比例", self.verticalCombobox)

        self.translateCombobox = ComboBox()
        self.translateCombobox.addItems(["弹幕和同传", "只显示弹幕", "只显示同传"])
        self.translateCombobox.setCurrentIndex(setting[3])
        _card(FluentIcon.CHAT, "弹幕窗类型", "弹幕与同传的显示方式", self.translateCombobox)

        self.translateFitler = LineEdit()
        self.translateFitler.setText(setting[4])
        self.translateFitler.setFixedWidth(120)
        self.translateFitler.setPlaceholderText("空格分隔关键词")
        _card(FluentIcon.FILTER, "同传过滤字符", "命中关键词的同传将被过滤", self.translateFitler)

        self.showEnterRoom = ComboBox()
        self.showEnterRoom.addItems(["显示礼物和进入信息", "只显示礼物", "只显示进入信息", "隐藏窗口"])
        self.showEnterRoom.setCurrentIndex(setting[6])
        _card(FluentIcon.HEART, "礼物和进入信息", "信息区显示策略", self.showEnterRoom)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(group)
        layout.addStretch()


class TextOption(FluentWindow):
    """弹幕机选项独立窗口。"""

    def __init__(self, setting=None, parent=None):
        super().__init__(parent=parent, title="弹幕窗设置")
        self.resize(380, 460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.optionPage = BrowserOptionWidget(setting, self)
        for name in BrowserOptionWidget.CONTROL_NAMES:
            setattr(self, name, getattr(self.optionPage, name))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.optionPage)


class TextBrowser(AcrylicWidget, QWidget):
    """弹幕机 - 弹出式窗口（Fluent 毛玻璃 + 圆角）

    通过限制移动位置来模拟嵌入式窗口。背景用组件库 AcrylicWidget
    （半透明 tint + 噪点纹理，深浅主题自适应），圆角裁剪见
    acrylicClipPath。
    """

    closeSignal = Signal()
    moveSignal = Signal(QPoint)
    optionWidgetCreated = Signal(object)

    def __init__(self, parent, event_model=None):
        super().__init__(parent)
        self.optionWidget = None
        self.setWindowTitle("弹幕机")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ---- 窗体布局：统一事件工作台 ----
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 0, 10, 10)
        layout.setSpacing(6)

        # 标题栏（透明底，由毛玻璃背景透出）
        self.bar = Bar(" 弹幕机")
        self.bar.moveSignal.connect(self.moveWindow)
        layout.addWidget(self.bar, 0, 0, 1, 8)
        # 弹幕选项菜单
        self.optionButton = TransparentToolButton(FluentIcon.SETTING, self)
        self.optionButton.setFixedSize(30, 30)
        self.optionButton.setToolTip("弹幕设置")
        self.optionButton.clicked.connect(self.showOptionWidget)
        layout.addWidget(self.optionButton, 0, 8, 1, 1, alignment=Qt.AlignVCenter)
        # 关闭按钮
        self.closeButton = TransparentToolButton(FluentIcon.CLOSE, self)
        self.closeButton.setFixedSize(30, 30)
        self.closeButton.setToolTip("关闭弹幕机")
        self.closeButton.clicked.connect(self.userClose)
        layout.addWidget(self.closeButton, 0, 9, 1, 1, alignment=Qt.AlignVCenter)

        self.workbench = DanmakuWorkbench(self, max_events=500, event_model=event_model)
        layout.addWidget(self.workbench, 1, 0, 1, 10)

        self._panel_opacity = 0.55
        self._apply_theme_colors()
        theme_changed().connect(self._apply_theme_colors)

    def _apply_theme_colors(self, *args):
        fg = "#F1F5F9" if is_dark() else "#1C2330"
        self.bar.setStyleSheet(
            f"color:{fg};background:transparent;font-size:12px;font-weight:600;"
        )
        self.update()

    def _updateAcrylicColor(self):
        AcrylicWidget._updateAcrylicColor(self)
        alpha = max(20, min(235, int(round(self._panel_opacity * 235))))
        tint = QColor(20, 23, 29, alpha) if is_dark() else QColor(250, 251, 253, alpha)
        self.acrylicBrush.tintColor = tint

    def setPanelOpacity(self, opacity):
        self._panel_opacity = max(0.07, min(float(opacity), 1.0))
        self.update()

    def appendEvent(self, event):
        return self.workbench.appendEvent(event)

    def clearEvents(self):
        self.workbench.clear()

    def setDisplayFilters(self, translation_mode=0, interaction_mode=0):
        self.workbench.setDisplayFilters(translation_mode, interaction_mode)

    def setTranslationRules(self, words):
        self.workbench.setTranslationRules(words)

    def setFontSize(self, size):
        self.workbench.setFontSize(size)

    def acrylicClipPath(self):
        """毛玻璃圆角裁剪（12px 圆角）"""
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        return path

    def ensureOptionWidget(self):
        if self.optionWidget is None:
            self.optionWidget = TextOption(parent=self)
            self.optionWidgetCreated.emit(self.optionWidget)
        return self.optionWidget

    def showOptionWidget(self):
        option_widget = self.ensureOptionWidget()
        option_widget.show()
        option_widget.raise_()
        option_widget.activateWindow()

    def userClose(self):
        self.hide()
        self.closeSignal.emit()

    def hideEvent(self, event):
        if self.optionWidget is not None:
            self.optionWidget.hide()
        super().hideEvent(event)

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
        self.resize(560, 640)

        tabs = TabWidget()
        tabs.setMovable(False)
        tabs.tabBar.setTabsClosable(False)
        tabs.tabBar.setAddButtonVisible(False)
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)

        # config 弹幕格式为 9 项 [enabled, opacity, horiz, vert, translate, filter, font_size, show_enter, rolling]
        # TextOption 期望 7 项 [opacity, horiz, vert, translate, filter, font_size, show_enter]
        # 必须跳过 enabled(索引0) 取 [1:8]，否则错位导致 setCurrentIndex(str) TypeError 崩溃
        setting = list(danmu_config_list[1:8]) if isinstance(danmu_config_list, list) else [50, 1, 7, 0, "【 [ {", 10, 0]
        self.browserOptionWidget = BrowserOptionWidget(setting)
        tabs.addTab(self._scrollPage(self.browserOptionWidget), "弹幕窗")

        self.rollingOptionWidget = RollingOptionWidget(rolling_config_dict)
        tabs.addTab(self._scrollPage(self.rollingOptionWidget), "滚动弹幕")

    @staticmethod
    def _scrollPage(page):
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background:transparent;border:none;")
        page.setStyleSheet("background:transparent;")
        scroll.setWidget(page)
        return scroll

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
