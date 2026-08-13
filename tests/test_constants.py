# -*- coding: utf-8 -*-
"""全局常量一致性测试 — 防止常量被改动导致跨模块不同步。"""

from app.core.constants import (
    DEFAULT_DANMU_CONFIG,
    DISPLAY_RATIOS,
    MAX_WINDOWS,
    WINDOW_CARD_WIDTH,
)
from app.core.config_manager import DEFAULT_CONFIG, DEFAULT_ROLLING_DANMU
from app.danmaku.settings import DanmakuSettings


class TestWindowConstants:
    def test_max_windows_sane(self):
        assert 4 <= MAX_WINDOWS <= 64

    def test_config_lists_length(self):
        """所有按窗口数量的配置列表长度必须等于 MAX_WINDOWS"""
        for key in ["player", "quality", "audioChannel", "muted", "volume", "translator", "danmu"]:
            assert len(DEFAULT_CONFIG[key]) == MAX_WINDOWS, f"{key} 长度 != MAX_WINDOWS"

    def test_danmu_config_list(self):
        assert len(DEFAULT_DANMU_CONFIG) == 9
        assert DanmakuSettings.from_config_list(DEFAULT_DANMU_CONFIG).to_config_list() == DEFAULT_DANMU_CONFIG

    def test_card_width_positive(self):
        assert WINDOW_CARD_WIDTH > 100


class TestDisplayRatios:
    def test_length(self):
        """DISPLAY_RATIOS 索引 0~9，与 DanmakuSettings 的钳制上限 9 对应"""
        assert len(DISPLAY_RATIOS) == 10

    def test_monotonic(self):
        assert DISPLAY_RATIOS == sorted(DISPLAY_RATIOS)
        assert DISPLAY_RATIOS[0] > 0 and DISPLAY_RATIOS[-1] <= 1.0

    def test_single_source(self):
        """所有模块引用同一对象，避免复制导致不同步"""
        from app.core import config_manager
        from app.ui import danmu
        from app.ui import video_widget  # noqa: F401

        assert danmu.DISPLAY_RATIOS is DISPLAY_RATIOS
        assert config_manager.DISPLAY_RATIOS is DISPLAY_RATIOS


class TestRollingDanmuDefaults:
    def test_keys_complete(self):
        required = {
            "font_family",
            "opacity",
            "display_area",
            "font_size",
            "speed_percent",
            "stroke_width",
            "shadow_enabled",
            "shadow_strength",
            "top_enabled",
            "bottom_enabled",
            "fps",
        }
        assert required.issubset(set(DEFAULT_ROLLING_DANMU))

    def test_fps_range(self):
        assert 10 <= DEFAULT_ROLLING_DANMU["fps"] <= 120
