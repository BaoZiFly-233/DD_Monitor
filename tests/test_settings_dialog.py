"""设置对话框预览状态回归测试。"""

import time

from app.core.config_manager import ConfigManager, DEFAULT_CONFIG
from app.ui import settings_dialog


def _dialog(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir()
    manager = ConfigManager(str(tmp_path))
    config = dict(DEFAULT_CONFIG)
    manager.config = config
    return settings_dialog.SettingsDialog(None, config, manager, lambda: None, lambda: None)


def test_reject_restores_original_accent(qapp, tmp_path, monkeypatch):
    accent_changes = []
    monkeypatch.setattr(settings_dialog, "set_accent", accent_changes.append)
    dialog = _dialog(tmp_path)

    dialog._previewAccent(1)
    dialog.reject()

    assert accent_changes == ["teal", "blue"]
    dialog.deleteLater()


def test_applied_settings_do_not_restore_preview(qapp, tmp_path, monkeypatch):
    accent_changes = []
    monkeypatch.setattr(settings_dialog, "set_accent", accent_changes.append)
    dialog = _dialog(tmp_path)

    dialog._previewAccent(1)
    dialog._settings_applied = True
    dialog.reject()

    assert accent_changes == ["teal"]
    dialog.deleteLater()


def test_reopened_dialog_reuses_widget_and_discards_unapplied_values(qapp, tmp_path):
    dialog = _dialog(tmp_path)
    expected_volume = dialog.config["globalVolume"]
    dialog.show()
    qapp.processEvents()
    dialog.volumeSlider.setValue(87)
    started = time.perf_counter()
    dialog.close()
    close_elapsed = time.perf_counter() - started
    dialog._settings_applied = True
    dialog.show()
    qapp.processEvents()

    assert close_elapsed < 0.15
    assert dialog.volumeSlider.value() == expected_volume
    assert not dialog._settings_applied
    dialog.close()
    dialog.deleteLater()
