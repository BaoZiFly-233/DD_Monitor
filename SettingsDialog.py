# -*- coding: utf-8 -*-
"""
统一设置面板 — 标签页集中管理所有配置项

替代散落在菜单和多处独立弹窗中的设置界面。
"""
from PySide6.QtWidgets import (
    QDialog, QTabWidget, QWidget, QGridLayout, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QCheckBox, QPushButton, QLineEdit, QFileDialog,
    QGroupBox, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from CommonWidget import Slider


class SettingsDialog(QDialog):
    """统一设置对话框"""

    def __init__(self, parent, config, config_manager, danmu_panel_fn, layout_panel_fn):
        super().__init__(parent)
        self.config = config
        self.configManager = config_manager
        self._danmu_panel_fn = danmu_panel_fn
        self._layout_panel_fn = layout_panel_fn
        self.setWindowTitle('设置')
        self.resize(520, 480)
        self.setModal(True)

        tabs = QTabWidget()
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(tabs)

        # 各标签页
        self._playback_tab = self._buildPlaybackTab()
        self._danmaku_tab = self._buildDanmakuTab()
        self._cache_tab = self._buildCacheTab()
        self._layout_tab = self._buildLayoutTab()
        self._general_tab = self._buildGeneralTab()

        tabs.addTab(self._playback_tab, '播放')
        tabs.addTab(self._danmaku_tab, '弹幕')
        tabs.addTab(self._cache_tab, '缓存')
        tabs.addTab(self._layout_tab, '布局')
        tabs.addTab(self._general_tab, '通用')

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        apply_btn = QPushButton('应用')
        apply_btn.clicked.connect(self._apply)
        apply_btn.setStyleSheet('background-color:#3daee9;color:white;padding:6px 20px;border-radius:3px')
        btn_layout.addWidget(apply_btn)
        main_layout.addLayout(btn_layout)

    # ---- 播放标签页 ----

    def _buildPlaybackTab(self):
        w = QWidget()
        layout = QGridLayout(w)
        layout.setVerticalSpacing(12)

        layout.addWidget(QLabel('全局画质'), 0, 0)
        self.qualityCombo = QComboBox()
        self.qualityCombo.addItems(['原画', '蓝光', '超清', '流畅', '仅音频'])
        quality_map = {10000: 0, 400: 1, 250: 2, 80: 3, -1: 4}
        current_q = self.config.get('quality', [80] * 16)[0]
        self.qualityCombo.setCurrentIndex(quality_map.get(current_q, 2))
        layout.addWidget(self.qualityCombo, 0, 1)

        layout.addWidget(QLabel('解码方案'), 1, 0)
        self.decodeCombo = QComboBox()
        self.decodeCombo.addItems(['硬解', '软解'])
        self.decodeCombo.setCurrentIndex(0 if self.config.get('hardwareDecode', True) else 1)
        layout.addWidget(self.decodeCombo, 1, 1)

        layout.addWidget(QLabel('全局音效'), 2, 0)
        self.audioCombo = QComboBox()
        self.audioCombo.addItems(['原始', '杜比'])
        current_audio = self.config.get('audioChannel', [0] * 16)[0]
        self.audioCombo.setCurrentIndex(0 if current_audio == 0 else 1)
        layout.addWidget(self.audioCombo, 2, 1)

        layout.addWidget(QLabel('全局音量'), 3, 0)
        self.volumeSlider = Slider()
        self.volumeSlider.setValue(self.config.get('globalVolume', 30))
        layout.addWidget(self.volumeSlider, 3, 1)

        layout.setRowStretch(4, 1)
        return w

    # ---- 弹幕标签页 ----

    def _buildDanmakuTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # 弹幕窗设置
        browser_group = QGroupBox('弹幕窗')
        browser_layout = QGridLayout(browser_group)

        danmu_cfg = self.config.get('danmu', [[True, 50, 1, 7, 0, '【 [ {', 10, 0, True]] * 16)[0]

        browser_layout.addWidget(QLabel('透明度'), 0, 0)
        self.browserOpacity = Slider()
        self.browserOpacity.setValue(danmu_cfg[1])
        browser_layout.addWidget(self.browserOpacity, 0, 1)

        browser_layout.addWidget(QLabel('横向占比'), 1, 0)
        self.browserHori = QComboBox()
        self.browserHori.addItems([f'{x}%' for x in range(10, 110, 10)])
        self.browserHori.setCurrentIndex(danmu_cfg[2])
        browser_layout.addWidget(self.browserHori, 1, 1)

        browser_layout.addWidget(QLabel('纵向占比'), 2, 0)
        self.browserVert = QComboBox()
        self.browserVert.addItems([f'{x}%' for x in range(10, 110, 10)])
        self.browserVert.setCurrentIndex(danmu_cfg[3])
        browser_layout.addWidget(self.browserVert, 2, 1)

        browser_layout.addWidget(QLabel('字体大小'), 3, 0)
        self.browserFont = QComboBox()
        self.browserFont.addItems([str(i) for i in range(5, 26)])
        self.browserFont.setCurrentIndex(danmu_cfg[6])
        browser_layout.addWidget(self.browserFont, 3, 1)

        browser_layout.addWidget(QLabel('显示类型'), 4, 0)
        self.browserType = QComboBox()
        self.browserType.addItems(['弹幕和同传', '只显示弹幕', '只显示同传'])
        self.browserType.setCurrentIndex(danmu_cfg[4])
        browser_layout.addWidget(self.browserType, 4, 1)

        browser_layout.addWidget(QLabel('礼物/进入'), 5, 0)
        self.browserMsgs = QComboBox()
        self.browserMsgs.addItems(['显示礼物和进入', '只显示礼物', '只显示进入', '隐藏'])
        self.browserMsgs.setCurrentIndex(danmu_cfg[7])
        browser_layout.addWidget(self.browserMsgs, 5, 1)

        browser_layout.addWidget(QLabel('同传过滤'), 6, 0)
        self.browserFilter = QLineEdit()
        self.browserFilter.setText(danmu_cfg[5])
        self.browserFilter.setPlaceholderText('空格分隔关键词')
        browser_layout.addWidget(self.browserFilter, 6, 1)

        layout.addWidget(browser_group)

        # 滚动弹幕设置
        rolling_group = QGroupBox('滚动弹幕')
        rolling_layout = QGridLayout(rolling_group)

        rd = self.config.get('rollingDanmu', {})

        rolling_layout.addWidget(QLabel('透明度'), 0, 0)
        self.rollingOpacity = Slider()
        self.rollingOpacity.setValue(rd.get('opacity', 50))
        rolling_layout.addWidget(self.rollingOpacity, 0, 1)

        rolling_layout.addWidget(QLabel('显示区域'), 1, 0)
        self.rollingArea = QComboBox()
        self.rollingArea.addItems([f'{x}%' for x in range(10, 110, 10)])
        self.rollingArea.setCurrentIndex(rd.get('display_area', 7))
        rolling_layout.addWidget(self.rollingArea, 1, 1)

        rolling_layout.addWidget(QLabel('字体大小'), 2, 0)
        self.rollingFont = QComboBox()
        self.rollingFont.addItems([str(i) for i in range(5, 26)])
        self.rollingFont.setCurrentIndex(rd.get('font_size', 10))
        rolling_layout.addWidget(self.rollingFont, 2, 1)

        rolling_layout.addWidget(QLabel('弹幕速度'), 3, 0)
        self.rollingSpeed = Slider()
        self.rollingSpeed.setValue(rd.get('speed_percent', 85))
        rolling_layout.addWidget(self.rollingSpeed, 3, 1)

        rolling_layout.addWidget(QLabel('描边粗细'), 4, 0)
        self.rollingStroke = Slider()
        self.rollingStroke.setValue(rd.get('stroke_width', 30))
        rolling_layout.addWidget(self.rollingStroke, 4, 1)

        rolling_layout.addWidget(QLabel('阴影效果'), 5, 0)
        self.rollingShadow = QCheckBox()
        self.rollingShadow.setChecked(rd.get('shadow_enabled', False))
        rolling_layout.addWidget(self.rollingShadow, 5, 1)

        rolling_layout.addWidget(QLabel('顶部弹幕'), 6, 0)
        self.rollingTop = QCheckBox()
        self.rollingTop.setChecked(rd.get('top_enabled', True))
        rolling_layout.addWidget(self.rollingTop, 6, 1)

        rolling_layout.addWidget(QLabel('底部弹幕'), 7, 0)
        self.rollingBottom = QCheckBox()
        self.rollingBottom.setChecked(rd.get('bottom_enabled', True))
        rolling_layout.addWidget(self.rollingBottom, 7, 1)

        layout.addWidget(rolling_group)
        return w

    # ---- 缓存标签页 ----

    def _buildCacheTab(self):
        w = QWidget()
        layout = QGridLayout(w)
        layout.setVerticalSpacing(12)

        layout.addWidget(QLabel('最大缓存(MB)'), 0, 0)
        self.cacheSize = QLineEdit()
        self.cacheSize.setPlaceholderText('1-9000')
        current_mb = max(1, self.config.get('maxCacheSize', 2048000) // 1024000)
        self.cacheSize.setText(str(current_mb))
        layout.addWidget(self.cacheSize, 0, 1)

        layout.addWidget(QLabel('备份路径(留空则删除)'), 1, 0)
        path_layout = QHBoxLayout()
        self.cachePath = QLineEdit()
        self.cachePath.setText(self.config.get('saveCachePath', ''))
        path_layout.addWidget(self.cachePath)
        browse_btn = QPushButton('...')
        browse_btn.setFixedWidth(40)
        browse_btn.clicked.connect(self._browseCachePath)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout, 1, 1)

        layout.setRowStretch(2, 1)
        return w

    def _browseCachePath(self):
        path = QFileDialog.getExistingDirectory(self, '选择缓存备份路径')
        if path:
            self.cachePath.setText(path)

    # ---- 布局标签页 ----

    def _buildLayoutTab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        desc = QLabel('点击下方按钮打开布局选择面板，拖拽调整窗口排列。')
        desc.setWordWrap(True)
        layout.addWidget(desc)
        open_btn = QPushButton('打开布局设置')
        open_btn.setFixedHeight(40)
        open_btn.clicked.connect(self._layout_panel_fn)
        layout.addWidget(open_btn)
        layout.addStretch()
        return w

    # ---- 通用标签页 ----

    def _buildGeneralTab(self):
        w = QWidget()
        layout = QGridLayout(w)
        layout.setVerticalSpacing(12)

        self.startDanmu = QCheckBox('启动时自动加载弹幕')
        self.startDanmu.setChecked(self.config.get('startWithDanmu', True))
        layout.addWidget(self.startDanmu, 0, 0, 1, 2)

        self.startLive = QCheckBox('开播提醒')
        self.startLive.setChecked(self.config.get('showStartLive', True))
        layout.addWidget(self.startLive, 1, 0, 1, 2)

        self.checkUpdate = QCheckBox('启动时检查更新')
        self.checkUpdate.setChecked(self.config.get('checkUpdate', True))
        layout.addWidget(self.checkUpdate, 2, 0, 1, 2)

        layout.setRowStretch(3, 1)
        return w

    # ---- 应用 ----

    def _apply(self):
        """应用所有标签页的设置到 config 并保存"""
        cfg = self.config

        # 播放
        quality_map = [10000, 400, 250, 80, -1]
        quality = quality_map[self.qualityCombo.currentIndex()]
        cfg['quality'] = [quality] * 16
        cfg['hardwareDecode'] = (self.decodeCombo.currentIndex() == 0)
        cfg['audioChannel'] = [0 if self.audioCombo.currentIndex() == 0 else 5] * 16
        cfg['globalVolume'] = self.volumeSlider.value()

        # 弹幕窗
        for i in range(16):
            danmu = cfg['danmu'][i]
            danmu[1] = self.browserOpacity.value()
            danmu[2] = self.browserHori.currentIndex()
            danmu[3] = self.browserVert.currentIndex()
            danmu[4] = self.browserType.currentIndex()
            danmu[5] = self.browserFilter.text()
            danmu[6] = self.browserFont.currentIndex()
            danmu[7] = self.browserMsgs.currentIndex()

        # 滚动弹幕
        rd = cfg['rollingDanmu']
        rd['opacity'] = self.rollingOpacity.value()
        rd['display_area'] = self.rollingArea.currentIndex()
        rd['font_size'] = self.rollingFont.currentIndex()
        rd['speed_percent'] = self.rollingSpeed.value()
        rd['stroke_width'] = self.rollingStroke.value()
        rd['shadow_enabled'] = self.rollingShadow.isChecked()
        rd['top_enabled'] = self.rollingTop.isChecked()
        rd['bottom_enabled'] = self.rollingBottom.isChecked()

        # 缓存
        try:
            mb = int(self.cacheSize.text() or '2')
            cfg['maxCacheSize'] = max(1024000, min(mb * 1024000, 9216000000))
        except ValueError:
            pass
        cfg['saveCachePath'] = self.cachePath.text()

        # 通用
        cfg['startWithDanmu'] = self.startDanmu.isChecked()
        cfg['showStartLive'] = self.startLive.isChecked()
        cfg['checkUpdate'] = self.checkUpdate.isChecked()

        self.configManager.save()
        self.accept()
