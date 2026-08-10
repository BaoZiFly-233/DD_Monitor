# -*- coding: utf-8 -*-
"""DanmakuSettings 数据类测试 — 序列化 / 反序列化 / 索引兼容 / 边界钳制。"""

from danmaku_settings import DanmakuSettings


class TestFromConfigList:
    def test_full_list(self):
        s = DanmakuSettings.from_config_list([True, 50, 1, 7, 0, "【 [ {", 10, 0, True])
        assert s.enabled is True
        assert s.opacity == 50
        assert s.horizontal_index == 1
        assert s.vertical_index == 7
        assert s.translate_mode == 0
        assert s.translate_filters == "【 [ {"
        assert s.font_size == 10
        assert s.show_enter_room == 0
        assert s.rolling_enabled is True

    def test_bool_legacy_format(self):
        """旧版 config 中弹幕配置直接是 bool（enabled），需扩展为完整列表"""
        s = DanmakuSettings.from_config_list(True)
        assert s.enabled is True
        assert s.opacity == 20  # bool 格式的 legacy 默认透明度
        assert s.rolling_enabled is True

        s2 = DanmakuSettings.from_config_list(False)
        assert s2.enabled is False
        assert s2.rolling_enabled is False

    def test_short_list_padded(self):
        """长度不足 9 的列表按默认值补齐"""
        s = DanmakuSettings.from_config_list([True, 50, 1])
        assert s.vertical_index == 7  # 默认值
        assert s.translate_filters == "【 [ {"
        assert s.rolling_enabled is True

    def test_long_list_truncated(self):
        s = DanmakuSettings.from_config_list(list(range(12)))
        assert len(s.to_config_list()) == 9

    def test_none_input(self):
        """None / 空输入应回退到默认值而不是崩溃"""
        s = DanmakuSettings.from_config_list(None)
        assert s.enabled is True
        assert s.opacity == 50


class TestToConfigList:
    def test_roundtrip(self):
        src = [True, 60, 2, 5, 1, "【", 12, 1, False]
        s = DanmakuSettings.from_config_list(src)
        assert s.to_config_list() == src

    def test_roundtrip_defaults(self):
        s = DanmakuSettings()
        assert s.to_config_list() == [True, 50, 1, 7, 0, "【 [ {", 10, 0, True]


class TestIndexCompatibility:
    """旧代码用 textSetting[2] 形式的魔法索引访问，必须保持兼容"""

    def test_getitem(self):
        s = DanmakuSettings.from_config_list([True, 50, 1, 7, 0, "【 [ {", 10, 0, True])
        assert s[0] is True
        assert s[1] == 50
        assert s[2] == 1
        assert s[3] == 7
        assert s[6] == 10
        assert s[8] is True

    def test_setitem(self):
        s = DanmakuSettings()
        s[2] = 5
        assert s.horizontal_index == 5
        s[8] = False
        assert s.rolling_enabled is False

    def test_getitem_out_of_range(self):
        s = DanmakuSettings()
        try:
            _ = s[9]
            raise AssertionError("应抛出 IndexError")
        except IndexError:
            pass
        try:
            _ = s[-1]
            raise AssertionError("应抛出 IndexError")
        except IndexError:
            pass


class TestBoundaryClamping:
    def test_opacity_min_floor(self):
        s = DanmakuSettings.from_config_list([True, 1, 1, 7, 0, "【 [ {", 10, 0, True])
        assert s.opacity == 7  # 最低 7

    def test_horizontal_index_clamp(self):
        s = DanmakuSettings.from_config_list([True, 50, 99, 0, 0, "【 [ {", 10, 0, True])
        assert s.horizontal_index == 9  # 上限 9（DISPLAY_RATIOS 索引）
        s2 = DanmakuSettings.from_config_list([True, 50, -3, 0, 0, "【 [ {", 10, 0, True])
        assert s2.horizontal_index == 0

    def test_font_size_clamp(self):
        s = DanmakuSettings.from_config_list([True, 50, 1, 7, 0, "【 [ {", 99, 0, True])
        assert s.font_size == 25
