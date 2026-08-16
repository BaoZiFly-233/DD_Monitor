# -*- coding: utf-8 -*-
"""UI 健壮性回归测试 — 修复过的绘制/渲染崩溃场景"""

import pytest

pytest.importorskip("PySide6")


def test_all_player_layout_presets_are_valid_and_non_overlapping():
    """内置布局必须能完整映射到最多 16 个播放器且不能互相覆盖。"""
    from app.ui.layout_config import layoutList
    from app.ui.main_window import MAX_WINDOWS, MainWindow

    assert len(layoutList) == 20
    for preset in layoutList:
        normalised = MainWindow._normaliseLayoutConfig(preset)
        assert normalised == [tuple(item) for item in preset]
        assert 1 <= len(normalised) <= MAX_WINDOWS

        occupied = set()
        for y, x, h, w in normalised:
            cells = {
                (row, column)
                for row in range(y, y + h)
                for column in range(x, x + w)
            }
            assert occupied.isdisjoint(cells)
            occupied.update(cells)


@pytest.mark.parametrize(
    "invalid_layout",
    [
        None,
        [],
        [(0, 0, 1)],
        [(0, 0, 0, 1)],
        [(0, 0, 1, 1), (0, 0, 1, 1)],
        [(16, 0, 1, 1)],
        [(0, 0, 1, 1)] * 17,
    ],
)
def test_invalid_player_layouts_are_rejected_as_a_whole(invalid_layout):
    """损坏布局不能被部分应用，否则播放台会留下重叠或幽灵窗口。"""
    from app.ui.main_window import MainWindow

    assert MainWindow._normaliseLayoutConfig(invalid_layout) == []


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
    assert card.titleLabel.geometry().top() >= 73
    assert card.stateLabel.geometry().top() >= card.titleLabel.geometry().bottom()
    card.close()


def test_card_panel_scrolls_when_top_dock_is_short(qapp, monkeypatch, tmp_path):
    """多行 FlowLayout 应扩大内容高度，由滚动区接管而不是裁掉后续卡片。"""
    from app.ui.liver_select import CollectLiverInfo, LiverPanel
    from app.ui.main_window import ScrollArea

    monkeypatch.setattr(CollectLiverInfo, "start", lambda self: None)
    panel = LiverPanel({str(10000 + i): False for i in range(8)}, str(tmp_path))
    scroll = ScrollArea()
    scroll.setWidgetResizable(True)
    scroll.resize(390, 180)
    scroll.setWidget(panel)
    scroll.show()
    qapp.processEvents()
    panel.syncFlowHeight(scroll.viewport().width())
    qapp.processEvents()

    assert panel.minimumHeight() == panel.layout.heightForWidth(scroll.viewport().width())
    assert panel.minimumHeight() > scroll.viewport().height()
    assert scroll.verticalScrollBar().maximum() > 0
    scroll.close()
    scroll.deleteLater()


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
