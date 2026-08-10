# -*- coding: utf-8 -*-
"""
统一设置面板 — Fluent SettingCard 格式

以 qfluentwidgets 的 SettingCard / SettingCardGroup 组织所有配置项：
图标 + 标题 + 说明 + 右侧控件 的行卡片格式。
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFileDialog,
)
from qfluentwidgets_pro import (
    ComboBox,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SettingCard,
    SettingCardGroup,
    Slider,
    SmoothScrollArea,
    SwitchButton,
    TabWidget,
)
from uikit_bridge import ACCENT_NAMES, set_accent, set_menu_animation, set_theme
from config_manager import MAX_WINDOWS

#: 配色方案显示名（与 uikit_bridge.ACCENT_NAMES 一一对应）
_ACCENT_LABELS = {
    "blue": "默认蓝",
    "teal": "青绿",
    "purple": "紫罗兰",
    "orange": "暖橙",
    "green": "翠绿",
}

#: 滑条在设置卡片右侧的固定宽度（默认 sizeHint 过窄）
_SLIDER_W = 200
#: 输入框在设置卡片右侧的固定宽度
_EDIT_W = 220


def _setting_card(icon, title, content, widget, parent):
    """构建一行设置卡片：图标 + 标题 + 说明 + 右侧控件（留右间距）。"""
    card = SettingCard(icon, title, content, parent)
    card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(12)
    return card


def _scrollable_page(build_fn):
    """把标签页内容包进可滚动区域（内容超高时出现 Fluent 滚动条）。"""
    scroll = SmoothScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    build_fn(content)
    scroll.setWidget(content)
    return scroll


class SettingsDialog(QDialog):
    """统一设置对话框（Fluent SettingCard 格式，5 个标签页）"""

    def __init__(self, parent, config, config_manager, danmu_panel_fn, layout_panel_fn):
        super().__init__(parent)
        self.config = config
        self.configManager = config_manager
        self._danmu_panel_fn = danmu_panel_fn
        self._layout_panel_fn = layout_panel_fn
        self.setWindowTitle("设置")
        self.resize(560, 520)

        tabs = TabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(tabs)

        # 各标签页
        self._playback_tab = self._buildPlaybackTab()
        self._danmaku_tab = self._buildDanmakuTab()
        self._cache_tab = self._buildCacheTab()
        self._layout_tab = self._buildLayoutTab()
        self._general_tab = self._buildGeneralTab()

        tabs.addTab(self._playback_tab, "播放")
        tabs.addTab(self._danmaku_tab, "弹幕")
        tabs.addTab(self._cache_tab, "缓存")
        tabs.addTab(self._layout_tab, "布局")
        tabs.addTab(self._general_tab, "通用")

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        apply_btn = PrimaryPushButton("应用")
        apply_btn.clicked.connect(self._apply)
        btn_layout.addWidget(apply_btn)
        main_layout.addLayout(btn_layout)

    # ---- 播放标签页 ----

    def _buildPlaybackTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        group = SettingCardGroup("播放", w)

        self.qualityCombo = ComboBox()
        self.qualityCombo.addItems(["原画", "蓝光", "超清", "流畅", "仅音频"])
        quality_map = {10000: 0, 400: 1, 250: 2, 80: 3, -1: 4}
        current_q = self.config.get("quality", [80] * 16)[0]
        self.qualityCombo.setCurrentIndex(quality_map.get(current_q, 2))
        group.addSettingCard(_setting_card(FluentIcon.VIDEO, "全局画质", "所有窗口的默认画质", self.qualityCombo, w))

        self.decodeCombo = ComboBox()
        self.decodeCombo.addItems(["硬解", "软解"])
        self.decodeCombo.setCurrentIndex(0 if self.config.get("hardwareDecode", True) else 1)
        group.addSettingCard(_setting_card(FluentIcon.SETTING, "解码方案", "硬解优先使用显卡，软解兼容性更好", self.decodeCombo, w))

        self.audioCombo = ComboBox()
        self.audioCombo.addItems(["原始", "杜比"])
        current_audio = self.config.get("audioChannel", [0] * 16)[0]
        self.audioCombo.setCurrentIndex(0 if current_audio == 0 else 1)
        group.addSettingCard(_setting_card(FluentIcon.HEADPHONE, "全局音效", "默认音频通道", self.audioCombo, w))

        self.volumeSlider = Slider(Qt.Horizontal)
        self.volumeSlider.setFixedWidth(_SLIDER_W)
        self.volumeSlider.setValue(self.config.get("globalVolume", 30))
        group.addSettingCard(_setting_card(FluentIcon.VOLUME, "全局音量", "默认播放音量", self.volumeSlider, w))

        layout.addWidget(group)
        layout.addStretch()
        return w

    # ---- 弹幕标签页 ----

    def _buildDanmakuTab(self):
        # 弹幕页内容超高（15 项设置卡片），包进滚动区域
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.enableTransparentBackground()  # 去掉滚动区域四周的黑边框
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)

        danmu_cfg = self.config.get("danmu", [[True, 50, 1, 7, 0, "【 [ {", 10, 0, True]] * 16)[0]

        # 弹幕窗设置
        browser_group = SettingCardGroup("弹幕窗", content)

        self.browserOpacity = Slider(Qt.Horizontal)
        self.browserOpacity.setFixedWidth(_SLIDER_W)
        self.browserOpacity.setValue(danmu_cfg[1])
        browser_group.addSettingCard(_setting_card(FluentIcon.ALBUM, "透明度", "弹幕窗整体透明度", self.browserOpacity, content))

        self.browserHori = ComboBox()
        self.browserHori.addItems([f"{x}%" for x in range(10, 110, 10)])
        self.browserHori.setCurrentIndex(danmu_cfg[2])
        browser_group.addSettingCard(_setting_card(FluentIcon.ALIGNMENT, "横向占比", "弹幕窗宽度占屏幕比例", self.browserHori, content))

        self.browserVert = ComboBox()
        self.browserVert.addItems([f"{x}%" for x in range(10, 110, 10)])
        self.browserVert.setCurrentIndex(danmu_cfg[3])
        browser_group.addSettingCard(_setting_card(FluentIcon.ALIGNMENT, "纵向占比", "弹幕窗高度占屏幕比例", self.browserVert, content))

        self.browserFont = ComboBox()
        self.browserFont.addItems([str(i) for i in range(5, 26)])
        self.browserFont.setCurrentIndex(danmu_cfg[6])
        browser_group.addSettingCard(_setting_card(FluentIcon.FONT, "字体大小", "弹幕字体大小", self.browserFont, content))

        self.browserType = ComboBox()
        self.browserType.addItems(["弹幕和同传", "只显示弹幕", "只显示同传"])
        self.browserType.setCurrentIndex(danmu_cfg[4])
        browser_group.addSettingCard(_setting_card(FluentIcon.CHAT, "显示类型", "弹幕与同传的显示方式", self.browserType, content))

        self.browserMsgs = ComboBox()
        self.browserMsgs.addItems(["显示礼物和进入", "只显示礼物", "只显示进入", "隐藏"])
        self.browserMsgs.setCurrentIndex(danmu_cfg[7])
        browser_group.addSettingCard(_setting_card(FluentIcon.HEART, "礼物/进入", "礼物与进入信息显示策略", self.browserMsgs, content))

        self.browserFilter = LineEdit()
        self.browserFilter.setFixedWidth(_EDIT_W)
        self.browserFilter.setText(danmu_cfg[5])
        self.browserFilter.setPlaceholderText("空格分隔关键词")
        browser_group.addSettingCard(_setting_card(FluentIcon.FILTER, "同传过滤", "命中关键词的同传将被过滤", self.browserFilter, content))

        layout.addWidget(browser_group)

        # 滚动弹幕设置
        rd = self.config.get("rollingDanmu", {})
        rolling_group = SettingCardGroup("滚动弹幕", content)

        self.rollingOpacity = Slider(Qt.Horizontal)
        self.rollingOpacity.setFixedWidth(_SLIDER_W)
        self.rollingOpacity.setValue(rd.get("opacity", 50))
        rolling_group.addSettingCard(_setting_card(FluentIcon.ALBUM, "透明度", "滚动弹幕整体透明度", self.rollingOpacity, content))

        self.rollingArea = ComboBox()
        self.rollingArea.addItems([f"{x}%" for x in range(10, 110, 10)])
        self.rollingArea.setCurrentIndex(rd.get("display_area", 7))
        rolling_group.addSettingCard(_setting_card(FluentIcon.ALIGNMENT, "显示区域", "滚动弹幕显示区域占比", self.rollingArea, content))

        self.rollingFont = ComboBox()
        self.rollingFont.addItems([str(i) for i in range(5, 26)])
        self.rollingFont.setCurrentIndex(rd.get("font_size", 10))
        rolling_group.addSettingCard(_setting_card(FluentIcon.FONT, "字体大小", "滚动弹幕字体大小", self.rollingFont, content))

        self.rollingSpeed = Slider(Qt.Horizontal)
        self.rollingSpeed.setFixedWidth(_SLIDER_W)
        self.rollingSpeed.setValue(rd.get("speed_percent", 85))
        rolling_group.addSettingCard(_setting_card(FluentIcon.PLAY, "弹幕速度", "滚动速度（50-200%）", self.rollingSpeed, content))

        self.rollingStroke = Slider(Qt.Horizontal)
        self.rollingStroke.setFixedWidth(_SLIDER_W)
        self.rollingStroke.setValue(rd.get("stroke_width", 30))
        rolling_group.addSettingCard(_setting_card(FluentIcon.EDIT, "描边粗细", "文字描边宽度", self.rollingStroke, content))

        self.rollingShadow = SwitchButton()
        self.rollingShadow.setChecked(rd.get("shadow_enabled", False))
        rolling_group.addSettingCard(_setting_card(FluentIcon.COMPLETED, "阴影效果", "弹幕文字投影", self.rollingShadow, content))

        self.rollingTop = SwitchButton()
        self.rollingTop.setChecked(rd.get("top_enabled", True))
        rolling_group.addSettingCard(_setting_card(FluentIcon.UP, "顶部弹幕", "允许顶部弹幕", self.rollingTop, content))

        self.rollingBottom = SwitchButton()
        self.rollingBottom.setChecked(rd.get("bottom_enabled", True))
        rolling_group.addSettingCard(_setting_card(FluentIcon.DOWN, "底部弹幕", "允许底部弹幕", self.rollingBottom, content))

        self.rollingFps = ComboBox()
        self.rollingFps.addItems(["30", "60", "90", "120"])
        self.rollingFps.setCurrentText(str(rd.get("fps", 60)))
        rolling_group.addSettingCard(_setting_card(FluentIcon.VIDEO, "帧率上限", "渲染帧率上限", self.rollingFps, content))

        layout.addWidget(rolling_group)
        layout.addStretch()
        scroll.setWidget(content)
        return scroll

    # ---- 缓存标签页 ----

    def _buildCacheTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        group = SettingCardGroup("缓存", w)

        self.cacheSize = LineEdit()
        self.cacheSize.setFixedWidth(_EDIT_W)
        self.cacheSize.setPlaceholderText("1-9000")
        current_mb = max(1, self.config.get("maxCacheSize", 2048000) // 1024000)
        self.cacheSize.setText(str(current_mb))
        group.addSettingCard(_setting_card(FluentIcon.DOWNLOAD, "最大缓存(MB)", "缓存文件夹大小上限", self.cacheSize, w))

        path_box = QHBoxLayout()
        path_box.setContentsMargins(0, 0, 0, 0)
        path_box.setSpacing(6)
        self.cachePath = LineEdit()
        self.cachePath.setFixedWidth(_EDIT_W - 60)
        self.cachePath.setText(self.config.get("saveCachePath", ""))
        path_box.addWidget(self.cachePath)
        browse_btn = PushButton("浏览")
        browse_btn.clicked.connect(self._browseCachePath)
        path_box.addWidget(browse_btn)
        path_widget = QWidget(w)
        path_widget.setLayout(path_box)
        group.addSettingCard(_setting_card(FluentIcon.FOLDER, "备份路径", "留空则直接删除缓存", path_widget, w))

        layout.addWidget(group)
        layout.addStretch()
        return w

    def _browseCachePath(self):
        path = QFileDialog.getExistingDirectory(self, "选择缓存备份路径")
        if path:
            self.cachePath.setText(path)

    # ---- 布局标签页 ----

    def _buildLayoutTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        group = SettingCardGroup("布局", w)

        open_btn = PushButton("打开布局设置")
        open_btn.clicked.connect(self._layout_panel_fn)
        group.addSettingCard(_setting_card(FluentIcon.ALBUM, "布局方式", "打开布局面板，拖拽调整窗口排列", open_btn, w))

        layout.addWidget(group)
        layout.addStretch()
        return w

    # ---- 通用标签页 ----

    def _buildGeneralTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        behavior_group = SettingCardGroup("启动行为", w)

        self.startDanmu = SwitchButton()
        self.startDanmu.setChecked(self.config.get("startWithDanmu", True))
        behavior_group.addSettingCard(_setting_card(FluentIcon.PLAY, "启动时自动加载弹幕", "启动后自动打开弹幕机", self.startDanmu, w))

        self.startLive = SwitchButton()
        self.startLive.setChecked(self.config.get("showStartLive", True))
        behavior_group.addSettingCard(_setting_card(FluentIcon.INFO, "开播提醒", "关注主播开播时弹出提醒", self.startLive, w))

        self.checkUpdate = SwitchButton()
        self.checkUpdate.setChecked(self.config.get("checkUpdate", True))
        behavior_group.addSettingCard(_setting_card(FluentIcon.UPDATE, "启动时检查更新", "启动后自动检查新版本", self.checkUpdate, w))

        self.menuAnimation = SwitchButton()
        self.menuAnimation.setChecked(self.config.get("menuAnimation", True))
        behavior_group.addSettingCard(_setting_card(FluentIcon.MUSIC, "菜单动画", "菜单弹出时的展开动画", self.menuAnimation, w))

        layout.addWidget(behavior_group)

        appearance_group = SettingCardGroup("外观", w)

        self.themeCombo = ComboBox()
        self.themeCombo.addItems(["深色", "浅色"])
        self.themeCombo.setCurrentIndex(0 if self.config.get("theme", "dark") == "dark" else 1)
        appearance_group.addSettingCard(_setting_card(FluentIcon.BRIGHTNESS, "主题", "界面明暗主题", self.themeCombo, w))

        self.accentCombo = ComboBox()
        self.accentCombo.addItems([_ACCENT_LABELS.get(n, n) for n in ACCENT_NAMES])
        current_accent = self.config.get("accent", "blue")
        self.accentCombo.setCurrentIndex(ACCENT_NAMES.index(current_accent) if current_accent in ACCENT_NAMES else 0)
        # 选配色即实时预览（点"应用"才写入配置）
        self.accentCombo.currentIndexChanged.connect(self._previewAccent)
        appearance_group.addSettingCard(_setting_card(FluentIcon.BRUSH, "配色", "界面主题色", self.accentCombo, w))

        layout.addWidget(appearance_group)
        layout.addStretch()
        return w

    def _previewAccent(self, index):
        """切换配色下拉框时立即应用配色（预览），应用按钮负责保存配置。"""
        set_accent(ACCENT_NAMES[index])

    # ---- 应用 ----

    def _apply(self):
        """应用所有标签页的设置到 config 并保存"""
        cfg = self.config

        # 播放
        quality_map = [10000, 400, 250, 80, -1]
        quality = quality_map[self.qualityCombo.currentIndex()]
        cfg["quality"] = [quality] * MAX_WINDOWS
        cfg["hardwareDecode"] = self.decodeCombo.currentIndex() == 0
        cfg["audioChannel"] = [0 if self.audioCombo.currentIndex() == 0 else 5] * MAX_WINDOWS
        cfg["globalVolume"] = self.volumeSlider.value()

        # 弹幕窗
        for i in range(MAX_WINDOWS):
            danmu = cfg["danmu"][i]
            danmu[1] = self.browserOpacity.value()
            danmu[2] = self.browserHori.currentIndex()
            danmu[3] = self.browserVert.currentIndex()
            danmu[4] = self.browserType.currentIndex()
            danmu[5] = self.browserFilter.text()
            danmu[6] = self.browserFont.currentIndex()
            danmu[7] = self.browserMsgs.currentIndex()

        # 滚动弹幕
        rd = cfg["rollingDanmu"]
        rd["opacity"] = self.rollingOpacity.value()
        rd["display_area"] = self.rollingArea.currentIndex()
        rd["font_size"] = self.rollingFont.currentIndex()
        rd["speed_percent"] = self.rollingSpeed.value()
        rd["stroke_width"] = self.rollingStroke.value()
        rd["shadow_enabled"] = self.rollingShadow.isChecked()
        rd["top_enabled"] = self.rollingTop.isChecked()
        rd["bottom_enabled"] = self.rollingBottom.isChecked()
        rd["fps"] = int(self.rollingFps.currentText())

        # 缓存
        try:
            mb = int(self.cacheSize.text() or "2")
            cfg["maxCacheSize"] = max(1024000, min(mb * 1024000, 9216000000))
        except ValueError:
            pass
        cfg["saveCachePath"] = self.cachePath.text()

        # 通用
        cfg["startWithDanmu"] = self.startDanmu.isChecked()
        cfg["showStartLive"] = self.startLive.isChecked()
        cfg["checkUpdate"] = self.checkUpdate.isChecked()
        cfg["menuAnimation"] = self.menuAnimation.isChecked()
        set_menu_animation(cfg["menuAnimation"])

        # 主题 / 配色切换（全局生效，保存后立即生效）
        theme = "dark" if self.themeCombo.currentIndex() == 0 else "light"
        cfg["theme"] = theme
        cfg["accent"] = ACCENT_NAMES[self.accentCombo.currentIndex()]
        set_theme(theme == "dark")
        set_accent(cfg["accent"])

        self.configManager.save()
        self.accept()
