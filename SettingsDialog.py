# -*- coding: utf-8 -*-
"""
统一设置面板 — Fluent SettingCard 现成卡片类

参考 Easy-FFmpeg（qfluentwidgets_pro 作者项目）的标准用法：
SwitchSettingCard / ComboBoxSettingCard / RangeSettingCard /
PushSettingCard 现成卡片类。配置项使用"假 ConfigItem"（未注册到
qconfig，仅作为卡片取值容器），读写仍走自研 config_manager。
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
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushSettingCard,
    RangeSettingCard,
    SettingCard,
    SettingCardGroup,
    SmoothScrollArea,
    SwitchSettingCard,
    TabWidget,
    ComboBoxSettingCard,
)
from qfluentwidgets_pro.common.config import (
    OptionsConfigItem,
    OptionsValidator,
    RangeConfigItem,
    RangeValidator,
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


def _setting_card(icon, title, content, widget, parent):
    """基础设置卡片：图标 + 标题 + 说明 + 右侧控件（无现成卡片类时用）。"""
    card = SettingCard(icon, title, content, parent)
    card.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
    card.hBoxLayout.addSpacing(12)
    return card


def _combo_card(icon, title, content, options, current_index, parent):
    """下拉设置卡片（假 OptionsConfigItem 仅作取值容器，不持久化）。"""
    item = OptionsConfigItem(
        "settings", title, options[current_index], OptionsValidator(options)
    )
    card = ComboBoxSettingCard(item, icon, title, content, texts=options, parent=parent)
    return card


def _switch_card(icon, title, content, checked, parent):
    """开关设置卡片（手动模式，不绑定 qconfig）。"""
    card = SwitchSettingCard(icon, title, content, None, parent)
    card.setChecked(checked)
    return card


def _range_card(icon, title, content, minimum, maximum, value, parent):
    """滑条设置卡片（假 RangeConfigItem 仅作取值容器）。"""
    item = RangeConfigItem("settings", title, value, RangeValidator(minimum, maximum))
    card = RangeSettingCard(item, icon, title, content, parent)
    card.setValue(value)
    return card


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

        quality_options = ["原画", "蓝光", "超清", "流畅", "仅音频"]
        quality_map = {10000: 0, 400: 1, 250: 2, 80: 3, -1: 4}
        current_q = self.config.get("quality", [80] * 16)[0]
        quality_card = _combo_card(
            FluentIcon.VIDEO, "全局画质", "所有窗口的默认画质",
            quality_options, quality_map.get(current_q, 2), w,
        )
        self.qualityCombo = quality_card.comboBox
        group.addSettingCard(quality_card)

        decode_card = _combo_card(
            FluentIcon.SETTING, "解码方案", "硬解优先使用显卡，软解兼容性更好",
            ["硬解", "软解"], 0 if self.config.get("hardwareDecode", True) else 1, w,
        )
        self.decodeCombo = decode_card.comboBox
        group.addSettingCard(decode_card)

        current_audio = self.config.get("audioChannel", [0] * 16)[0]
        audio_card = _combo_card(
            FluentIcon.HEADPHONE, "全局音效", "默认音频通道",
            ["原始", "杜比"], 0 if current_audio == 0 else 1, w,
        )
        self.audioCombo = audio_card.comboBox
        group.addSettingCard(audio_card)

        volume_card = _range_card(
            FluentIcon.VOLUME, "全局音量", "默认播放音量",
            0, 100, self.config.get("globalVolume", 30), w,
        )
        self.volumeSlider = volume_card.slider
        group.addSettingCard(volume_card)

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

        op_card = _range_card(
            FluentIcon.ALBUM, "透明度", "弹幕窗整体透明度",
            0, 100, danmu_cfg[1], content,
        )
        self.browserOpacity = op_card.slider
        browser_group.addSettingCard(op_card)

        hori_card = _combo_card(
            FluentIcon.ALIGNMENT, "横向占比", "弹幕窗宽度占屏幕比例",
            [f"{x}%" for x in range(10, 110, 10)], danmu_cfg[2], content,
        )
        self.browserHori = hori_card.comboBox
        browser_group.addSettingCard(hori_card)

        vert_card = _combo_card(
            FluentIcon.ALIGNMENT, "纵向占比", "弹幕窗高度占屏幕比例",
            [f"{x}%" for x in range(10, 110, 10)], danmu_cfg[3], content,
        )
        self.browserVert = vert_card.comboBox
        browser_group.addSettingCard(vert_card)

        font_card = _combo_card(
            FluentIcon.FONT, "字体大小", "弹幕字体大小",
            [str(i) for i in range(5, 26)], danmu_cfg[6], content,
        )
        self.browserFont = font_card.comboBox
        browser_group.addSettingCard(font_card)

        type_card = _combo_card(
            FluentIcon.CHAT, "显示类型", "弹幕与同传的显示方式",
            ["弹幕和同传", "只显示弹幕", "只显示同传"], danmu_cfg[4], content,
        )
        self.browserType = type_card.comboBox
        browser_group.addSettingCard(type_card)

        msgs_card = _combo_card(
            FluentIcon.HEART, "礼物/进入", "礼物与进入信息显示策略",
            ["显示礼物和进入", "只显示礼物", "只显示进入", "隐藏"], danmu_cfg[7], content,
        )
        self.browserMsgs = msgs_card.comboBox
        browser_group.addSettingCard(msgs_card)

        self.browserFilter = LineEdit()
        self.browserFilter.setText(danmu_cfg[5])
        self.browserFilter.setPlaceholderText("空格分隔关键词")
        browser_group.addSettingCard(_setting_card(
            FluentIcon.FILTER, "同传过滤", "命中关键词的同传将被过滤", self.browserFilter, content
        ))

        layout.addWidget(browser_group)

        # 滚动弹幕设置
        rd = self.config.get("rollingDanmu", {})
        rolling_group = SettingCardGroup("滚动弹幕", content)

        rop_card = _range_card(
            FluentIcon.ALBUM, "透明度", "滚动弹幕整体透明度",
            0, 100, rd.get("opacity", 50), content,
        )
        self.rollingOpacity = rop_card.slider
        rolling_group.addSettingCard(rop_card)

        area_card = _combo_card(
            FluentIcon.ALIGNMENT, "显示区域", "滚动弹幕显示区域占比",
            [f"{x}%" for x in range(10, 110, 10)], rd.get("display_area", 7), content,
        )
        self.rollingArea = area_card.comboBox
        rolling_group.addSettingCard(area_card)

        rfont_card = _combo_card(
            FluentIcon.FONT, "字体大小", "滚动弹幕字体大小",
            [str(i) for i in range(5, 26)], rd.get("font_size", 10), content,
        )
        self.rollingFont = rfont_card.comboBox
        rolling_group.addSettingCard(rfont_card)

        speed_card = _range_card(
            FluentIcon.PLAY, "弹幕速度", "滚动速度（50-200%）",
            50, 200, rd.get("speed_percent", 85), content,
        )
        self.rollingSpeed = speed_card.slider
        rolling_group.addSettingCard(speed_card)

        stroke_card = _range_card(
            FluentIcon.EDIT, "描边粗细", "文字描边宽度",
            0, 60, rd.get("stroke_width", 30), content,
        )
        self.rollingStroke = stroke_card.slider
        rolling_group.addSettingCard(stroke_card)

        self.rollingShadow = _switch_card(
            FluentIcon.COMPLETED, "阴影效果", "弹幕文字投影",
            rd.get("shadow_enabled", False), content,
        )
        rolling_group.addSettingCard(self.rollingShadow)

        self.rollingTop = _switch_card(
            FluentIcon.UP, "顶部弹幕", "允许顶部弹幕",
            rd.get("top_enabled", True), content,
        )
        rolling_group.addSettingCard(self.rollingTop)

        self.rollingBottom = _switch_card(
            FluentIcon.DOWN, "底部弹幕", "允许底部弹幕",
            rd.get("bottom_enabled", True), content,
        )
        rolling_group.addSettingCard(self.rollingBottom)

        fps_options = ["30", "60", "90", "120"]
        fps_current = str(rd.get("fps", 60))
        fps_index = fps_options.index(fps_current) if fps_current in fps_options else 1
        fps_card = _combo_card(
            FluentIcon.VIDEO, "帧率上限", "渲染帧率上限",
            fps_options, fps_index, content,
        )
        self.rollingFps = fps_card.comboBox
        rolling_group.addSettingCard(fps_card)

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
        self.cacheSize.setPlaceholderText("1-9000")
        current_mb = max(1, self.config.get("maxCacheSize", 2048000) // 1024000)
        self.cacheSize.setText(str(current_mb))
        group.addSettingCard(_setting_card(
            FluentIcon.DOWNLOAD, "最大缓存(MB)", "缓存文件夹大小上限", self.cacheSize, w
        ))

        self.cachePath = LineEdit()
        self.cachePath.setText(self.config.get("saveCachePath", ""))
        browse_card = PushSettingCard(
            "浏览", FluentIcon.FOLDER, "备份路径", "留空则直接删除缓存", w
        )
        self.cachePath.setFixedWidth(180)
        browse_card.hBoxLayout.insertWidget(2, self.cachePath, 0, Qt.AlignRight)
        browse_card.clicked.connect(self._browseCachePath)
        group.addSettingCard(browse_card)

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

        open_card = PushSettingCard(
            "打开布局设置", FluentIcon.ALBUM, "布局方式", "打开布局面板，拖拽调整窗口排列", w
        )
        open_card.clicked.connect(self._layout_panel_fn)
        group.addSettingCard(open_card)

        layout.addWidget(group)
        layout.addStretch()
        return w

    # ---- 通用标签页 ----

    def _buildGeneralTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)

        behavior_group = SettingCardGroup("启动行为", w)

        self.startDanmu = _switch_card(
            FluentIcon.PLAY, "启动时自动加载弹幕", "启动后自动打开弹幕机",
            self.config.get("startWithDanmu", True), w,
        )
        behavior_group.addSettingCard(self.startDanmu)

        self.startLive = _switch_card(
            FluentIcon.INFO, "开播提醒", "关注主播开播时弹出提醒",
            self.config.get("showStartLive", True), w,
        )
        behavior_group.addSettingCard(self.startLive)

        self.checkUpdate = _switch_card(
            FluentIcon.UPDATE, "启动时检查更新", "启动后自动检查新版本",
            self.config.get("checkUpdate", True), w,
        )
        behavior_group.addSettingCard(self.checkUpdate)

        self.menuAnimation = _switch_card(
            FluentIcon.MUSIC, "菜单动画", "菜单弹出时的展开动画",
            self.config.get("menuAnimation", True), w,
        )
        behavior_group.addSettingCard(self.menuAnimation)

        layout.addWidget(behavior_group)

        appearance_group = SettingCardGroup("外观", w)

        theme_card = _combo_card(
            FluentIcon.BRIGHTNESS, "主题", "界面明暗主题",
            ["深色", "浅色"], 0 if self.config.get("theme", "dark") == "dark" else 1, w,
        )
        self.themeCombo = theme_card.comboBox
        appearance_group.addSettingCard(theme_card)

        current_accent = self.config.get("accent", "blue")
        accent_card = _combo_card(
            FluentIcon.BRUSH, "配色", "界面主题色",
            [_ACCENT_LABELS.get(n, n) for n in ACCENT_NAMES],
            ACCENT_NAMES.index(current_accent) if current_accent in ACCENT_NAMES else 0,
            w,
        )
        self.accentCombo = accent_card.comboBox
        # 选配色即实时预览（点"应用"才写入配置）
        self.accentCombo.currentIndexChanged.connect(self._previewAccent)
        appearance_group.addSettingCard(accent_card)

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
