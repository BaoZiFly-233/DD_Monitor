# -*- coding: utf-8 -*-
"""UI 健壮性回归测试 — 修复过的绘制/渲染崩溃场景"""

import pytest

pytest.importorskip("PySide6")


def test_outlined_label_empty_text_no_crash(qapp):
    """空文本绘制不崩溃（text()[0] IndexError 回归防护）"""
    from app.ui.liver_select import OutlinedLabel

    label = OutlinedLabel("")
    label.resize(160, 40)
    label.show()
    qapp.processEvents()
    label.repaint()  # 触发 paintEvent
    qapp.processEvents()
    label.close()


def test_outlined_label_normal_text(qapp):
    """正常文本绘制正常"""
    from app.ui.liver_select import OutlinedLabel

    label = OutlinedLabel("测试标题")
    label.resize(160, 40)
    label.show()
    qapp.processEvents()
    label.repaint()
    qapp.processEvents()
    label.close()


def test_outlined_label_multi_char_left_bearing(qapp):
    """首字符有 leftBearing 的文本（标点开头）绘制正常"""
    from app.ui.liver_select import OutlinedLabel

    label = OutlinedLabel("· 直播中")
    label.resize(160, 40)
    label.show()
    qapp.processEvents()
    label.repaint()
    qapp.processEvents()
    label.close()


def test_danmaku_settings_roundtrip():
    """DanmakuSettings 与 config 列表互转保持字段一致"""
    from app.danmaku.settings import DanmakuSettings

    src = [True, 50, 1, 7, 0, "【 [ {", 10, 0, True]
    settings = DanmakuSettings.from_config_list(src)
    assert settings.to_config_list() == src

    # 越界输入 clamp（与 config_manager 迁移一致）
    settings2 = DanmakuSettings.from_config_list([True, 999, 15, -3, 99, "x", 99, 7, False])
    assert settings2.opacity == 100
    assert settings2.horizontal_index == 9
    assert settings2.vertical_index == 0
    assert settings2.translate_mode == 2
    assert settings2.font_size <= 20
    assert settings2.show_enter_room <= 3
