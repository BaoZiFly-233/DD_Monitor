# -*- coding: utf-8 -*-
"""MPV runtime safety regression tests."""

from types import SimpleNamespace


def test_embedded_mpv_disables_all_builtin_scripts(monkeypatch):
    from app.ui import video_widget

    captured = {}
    player = object()

    class FakeMpvModule:
        @staticmethod
        def MPV(**options):
            captured.update(options)
            return player

    assigned_players = []
    widget = SimpleNamespace(
        _mpv=None,
        hardwareDecode=False,
        name_str="test-player",
        volume=40,
        videoFrame=SimpleNamespace(setPlayer=assigned_players.append),
        applyDanmuSettings=lambda: None,
    )
    monkeypatch.setattr(video_widget, "load_mpv_module", lambda: FakeMpvModule)

    video_widget.VideoWidget._init_mpv(widget)

    expected_script_options = {
        "load_scripts",
        "load_stats_overlay",
        "load_console",
        "load_commands",
        "load_auto_profiles",
        "load_select",
        "load_context_menu",
        "load_positioning",
    }
    assert expected_script_options == set(video_widget.MPV_EMBEDDED_SCRIPT_OPTIONS)
    assert all(captured[name] is False for name in expected_script_options)
    assert captured["osc"] == "no"
    assert captured["ytdl"] is False
    assert assigned_players == [player]
