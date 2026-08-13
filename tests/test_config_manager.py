# -*- coding: utf-8 -*-
"""ConfigManager 测试 — 加载 / 迁移 / 保存轮转 / 异常兜底。"""

import json
import os

import pytest

from app.core.config_manager import DEFAULT_CONFIG, ConfigManager


@pytest.fixture
def cm(tmp_path):
    """隔离的 ConfigManager（不触碰真实 resources/config.json）"""
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    return ConfigManager(str(tmp_path))


class TestLoad:
    def test_missing_config_returns_defaults(self, cm):
        cfg = cm.load()
        assert cfg["player"] == ["0"] * 16
        assert len(cfg["danmu"]) == 16

    def test_corrupt_json_returns_defaults(self, cm):
        config_path = cm.config_path
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        cfg = cm.load()
        assert cfg["player"] == ["0"] * 16

    def test_empty_config_returns_defaults(self, cm):
        config_path = cm.config_path
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write("")
        cfg = cm.load()
        assert cfg["player"] == ["0"] * 16


class TestMigrate:
    def test_legacy_roomid_list(self, cm):
        cm.config = {"roomid": ["1", "2", "3"]}
        cm._migrate()
        assert cm.config["roomid"] == {"1": False, "2": False, "3": False}

    def test_roomid_contains_zero(self, cm):
        cm.config = {"roomid": ["0", "5"]}
        cm._migrate()
        assert "0" not in cm.config["roomid"]
        assert cm.config["roomid"] == {"5": False}

    def test_short_lists_padded(self, cm):
        cm.config = {"volume": [10, 20]}
        cm._migrate()
        assert len(cm.config["volume"]) == 16

    def test_long_lists_truncated(self, cm):
        cm.config = {"volume": list(range(30))}
        cm._migrate()
        assert len(cm.config["volume"]) == 16

    def test_legacy_bool_danmu(self, cm):
        cm.config = {"danmu": [True, False]}
        cm._migrate()
        assert cm.config["danmu"][0][0] is True
        assert cm.config["danmu"][0][8] is True
        assert cm.config["danmu"][1][0] is False

    def test_short_danmu_list_padded(self, cm):
        cm.config = {"danmu": [[True, 50]]}
        cm._migrate()
        assert len(cm.config["danmu"][0]) == 9

    def test_rolling_danmu_defaults_merged(self, cm):
        cm.config = {"rollingDanmu": {"fps": 90}}
        cm._migrate()
        rd = cm.config["rollingDanmu"]
        assert rd["fps"] == 90
        assert "font_family" in rd  # 缺省字段补齐

    def test_missing_fields_filled(self, cm):
        cm.config = {}
        cm._migrate()
        for field in DEFAULT_CONFIG:
            assert field in cm.config

    def test_session_data_url_decode(self, cm):
        cm.config = {"sessionData": "abc%3D123"}
        cm._migrate()
        assert cm.config["sessionData"] == "abc=123"


class TestMigrateRobustness:
    """异常格式输入必须兜底而非崩溃（import_from 手动导入可能触发）"""

    @pytest.mark.parametrize(
        "bad_cfg",
        [
            {"player": None},
            {"player": "abc"},
            {"player": 123},
            {"danmu": "bad"},
            {"danmu": 123},
            {"danmu": [123]},  # 元素非 list/bool
            {"roomid": "abc"},
            {"roomid": 123},
            {"volume": None},
        ],
    )
    def test_abnormal_inputs_do_not_crash(self, cm, bad_cfg):
        cm.config = dict(bad_cfg)
        cm._migrate()
        assert isinstance(cm.config["player"], list) and len(cm.config["player"]) == 16
        assert isinstance(cm.config["danmu"], list) and len(cm.config["danmu"]) == 16
        assert isinstance(cm.config["roomid"], dict)

    def test_import_from_bad_file(self, cm, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text('{"player": null, "danmu": "x"}', encoding="utf-8")
        # 不应抛异常，返回 True 且配置合法
        assert cm.import_from(str(bad_file), current_layout=[(0, 0, 1, 1)]) is True
        assert cm.config["layout"] == [(0, 0, 1, 1)]
        assert isinstance(cm.config["player"], list)


class TestSave:
    def test_save_writes_file(self, cm):
        cm.config = dict(DEFAULT_CONFIG)
        cm.save(immediate=True)
        assert os.path.exists(cm.config_path)
        saved = json.loads(open(cm.config_path, encoding="utf-8").read())
        assert saved["player"] == ["0"] * 16

    def test_backup_rotation(self, cm):
        """保存两次后产生 备份1（第一次保存的旧配置被轮转为备份）"""
        cm.config = dict(DEFAULT_CONFIG)
        cm.config["volume"] = [10] * 16
        cm.save(immediate=True)
        # 第一次保存：无旧文件可轮转，backup1 尚不存在
        assert not os.path.exists(os.path.join(cm.application_path, "resources/config_备份1.json"))

        cm.config["volume"] = [20] * 16
        cm.save(immediate=True)
        backup1 = os.path.join(cm.application_path, "resources/config_备份1.json")
        assert os.path.exists(backup1)
        # 备份内容是第一次保存的旧配置
        saved_backup = json.loads(open(backup1, encoding="utf-8").read())
        assert saved_backup["volume"][0] == 10

    def test_save_after_migrate(self, cm):
        cm.load()
        cm.config["volume"] = [77] * 16
        cm.save(immediate=True)
        saved = json.loads(open(cm.config_path, encoding="utf-8").read())
        assert saved["volume"][0] == 77

    def test_export_import_roundtrip(self, cm, tmp_path):
        cm.config = dict(DEFAULT_CONFIG)
        cm.config["volume"] = [88] * 16
        export_path = tmp_path / "export.json"
        cm.export_to(str(export_path))

        cm2 = ConfigManager(str(tmp_path / "other"))
        assert cm2.import_from(str(export_path), current_layout=[(0, 0, 1, 1)]) is True
        assert cm2.config["volume"][0] == 88
