# -*- coding: utf-8 -*-
"""UI 健壮性回归测试 — 修复过的绘制/渲染崩溃场景"""

import pytest

pytest.importorskip("PySide6")


def test_cover_card_rounding_and_empty_text_are_safe(qapp):
    """新直播卡片使用抗锯齿圆角，空标题和空封面均可安全绘制。"""
    from PySide6.QtGui import QImage, QPixmap
    from app.ui.liver_select import CoverLabel

    card = CoverLabel("1")
    card._setTitleText("")
    card.updateKeyFrame(QPixmap())
    card.updateProfile(QImage())
    card.show()
    qapp.processEvents()
    card.repaint()
    qapp.processEvents()

    assert card.getBorderRadius() == 8
    assert card.titleLabel.text() == "未知主播"
    assert card._coverPixmap.isNull()
    card.close()


def test_global_danmaku_panel_uses_scrollable_embedded_pages(qapp):
    from qfluentwidgets_pro import SmoothScrollArea

    from app.core.config_manager import DEFAULT_CONFIG
    from app.ui.danmu import BrowserOptionWidget, GlobalDanmuOption

    panel = GlobalDanmuOption(DEFAULT_CONFIG["danmu"][0], DEFAULT_CONFIG["rollingDanmu"])
    panel.show()
    qapp.processEvents()

    pages = panel.findChildren(SmoothScrollArea)
    assert len(pages) == 2
    assert isinstance(panel.browserOptionWidget, BrowserOptionWidget)
    assert any(page.verticalScrollBar().maximum() > 0 for page in pages)
    panel.close()
    panel.deleteLater()


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
