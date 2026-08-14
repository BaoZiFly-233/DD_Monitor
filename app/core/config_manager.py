"""
配置管理模块
负责 config.json 的加载、保存、迁移、导入/导出
使用 QTimer 去抖动保存，避免频繁 I/O
"""

import os
import json
import logging
from urllib.parse import unquote

from PySide6.QtCore import QObject, QTimer

# 常量（定义在 constants.py，此处重导出以兼容旧代码 from config_manager import ...）
# 注意：config_manager 不依赖任何 UI 模块，保持配置层纯净
from app.core.constants import MAX_WINDOWS, WINDOW_CARD_WIDTH, DISPLAY_RATIOS, DEFAULT_DANMU_CONFIG  # noqa: E402,F401

DEFAULT_ROLLING_DANMU = {
    "font_family": "Microsoft YaHei",
    "opacity": 50,
    "display_area": 7,
    "font_size": 10,
    "speed_percent": 85,
    "stroke_width": 30,
    "shadow_enabled": False,
    "shadow_strength": 35,
    "top_enabled": True,
    "bottom_enabled": True,
    "fps": 60,
}


def _safe_int(value, default=0):
    """安全转 int：None/非数字/异常值回退默认，避免损坏 config 崩溃"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

DEFAULT_CONFIG = {
    "roomid": {},
    "layout": [(0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 1), (1, 1, 1, 1)],
    "player": ["0"] * MAX_WINDOWS,
    "quality": [80] * MAX_WINDOWS,
    "audioChannel": [0] * MAX_WINDOWS,
    "muted": [1] * MAX_WINDOWS,
    "volume": [50] * MAX_WINDOWS,
    "volumeAmplify": [1.0] * MAX_WINDOWS,
    "translator": [True] * MAX_WINDOWS,
    "danmu": [list(DEFAULT_DANMU_CONFIG) for _ in range(MAX_WINDOWS)],
    "rollingDanmu": dict(DEFAULT_ROLLING_DANMU),
    "globalVolume": 30,
    "control": True,
    "hardwareDecode": True,
    "maxCacheSize": 2048000,
    "saveCachePath": "",
    "startWithDanmu": True,
    "showStartLive": True,
    "checkUpdate": True,
    "theme": "dark",
    "accent": "blue",
    "popupGeometry": "",
    "sessionData": "",
    "loginUserInfo": {},
    "credential": {},
}


class ConfigManager(QObject):
    """配置管理器 — 加载、迁移、去抖动保存"""

    def __init__(self, application_path, parent=None):
        super().__init__(parent)
        self.application_path = application_path
        self.config_path = os.path.join(application_path, "resources", "config.json")
        self.config = {}
        self._dirty = False
        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._flush)

    # ---- 加载 ----

    def load(self):
        """加载配置，失败时尝试备份。始终返回合法 config 字典。"""
        self.config = self._load_json(self.config_path)
        if not self.config:
            for backup_number in [1, 2, 3]:
                backup_path = os.path.join(self.application_path, f"resources/config_备份{backup_number}.json")
                self.config = self._load_json(backup_path)
                if self.config:
                    logging.info(f"从备份 config_备份{backup_number}.json 恢复配置")
                    break
        if self.config:
            self._migrate()
        else:
            logging.warning("配置读取失败，使用默认配置")
            self.config = dict(DEFAULT_CONFIG)
        return self.config

    def _load_json(self, path):
        if not os.path.exists(path) or not os.path.getsize(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return json.loads(f.read())
        except Exception as e:
            logging.error(str(e))
            logging.exception(f"json 配置读取失败: {path}")
            return {}

    # ---- 迁移 ----

    def _migrate(self):
        """兼容旧版本配置格式"""
        cfg = self.config

        # 列表扩容到 MAX_WINDOWS（非 list 的异常数据一律重置为默认，防止 import_from 崩溃）
        for key in ["player", "volume", "danmu", "muted", "quality", "audioChannel", "translator"]:
            default = DEFAULT_CONFIG[key]
            if key not in cfg or not isinstance(cfg[key], list):
                cfg[key] = list(default)
            while len(cfg[key]) < MAX_WINDOWS:
                cfg[key].append(default[len(cfg[key]) % len(default)])
            cfg[key] = cfg[key][:MAX_WINDOWS]

        cfg["player"] = list(map(str, cfg["player"]))

        # roomid: list → dict 迁移；非 dict 异常数据重置为空 dict
        if isinstance(cfg.get("roomid"), list):
            room_list = cfg["roomid"]
            cfg["roomid"] = {}
            for rid in room_list:
                cfg["roomid"][str(rid)] = False
        elif not isinstance(cfg.get("roomid"), dict):
            cfg["roomid"] = {}
        if "0" in cfg.get("roomid", {}):
            del cfg["roomid"]["0"]

        # 弹幕配置迁移（逐项兜底：元素非 list/bool 时重置为默认）
        for index, text_setting in enumerate(cfg.get("danmu", [])):
            if isinstance(text_setting, bool):
                cfg["danmu"][index] = [text_setting, 20, 1, 7, 0, "【 [ {", 10, 0, text_setting]
            elif not isinstance(text_setting, list):
                cfg["danmu"][index] = list(DEFAULT_DANMU_CONFIG)
            else:
                defaults = list(DEFAULT_DANMU_CONFIG)
                while len(text_setting) < 8:
                    text_setting.append(defaults[len(text_setting)])
                if len(text_setting) < 9:
                    text_setting.append(bool(text_setting[0]))
                if len(text_setting) > 9:
                    del text_setting[9:]
                text_setting[0] = bool(text_setting[0])
                # 数值字段范围校验（损坏/手改 config 越界会导致 ComboBox
                # setCurrentIndex 越界显示异常）：
                # [1]=透明度 7-100 [2]/[3]=占比 index 0-10 [4]=类型 0-2
                # [6]=字号 index 0-20 [7]=礼物/进入 0-3
                text_setting[1] = max(7, min(_safe_int(text_setting[1], 20), 100))
                text_setting[2] = max(0, min(_safe_int(text_setting[2], 1), 10))
                text_setting[3] = max(0, min(_safe_int(text_setting[3], 7), 10))
                text_setting[4] = max(0, min(_safe_int(text_setting[4], 0), 2))
                text_setting[5] = str(text_setting[5] or "【 [ {")
                text_setting[6] = max(0, min(_safe_int(text_setting[6], 10), 20))
                text_setting[7] = max(0, min(_safe_int(text_setting[7], 0), 3))
                text_setting[8] = bool(text_setting[8])

        # 滚动弹幕默认值
        if "rollingDanmu" not in cfg or not isinstance(cfg.get("rollingDanmu"), dict):
            cfg["rollingDanmu"] = dict(DEFAULT_ROLLING_DANMU)
        for k, v in DEFAULT_ROLLING_DANMU.items():
            cfg["rollingDanmu"].setdefault(k, v)
        rd = cfg["rollingDanmu"]
        rd["font_family"] = str(rd.get("font_family", "Microsoft YaHei"))
        rd["opacity"] = max(7, min(int(rd.get("opacity", 50)), 100))
        rd["display_area"] = max(0, min(int(rd.get("display_area", 7)), 9))
        rd.pop("dense_level", None)
        rd["font_size"] = max(0, min(int(rd.get("font_size", 10)), 20))
        rd["speed_percent"] = max(50, min(int(rd.get("speed_percent", 85)), 200))
        rd["stroke_width"] = max(0, min(int(rd.get("stroke_width", 30)), 60))
        rd["shadow_enabled"] = bool(rd.get("shadow_enabled", False))
        rd["shadow_strength"] = max(0, min(int(rd.get("shadow_strength", 35)), 100))
        rd["top_enabled"] = bool(rd.get("top_enabled", True))
        rd["bottom_enabled"] = bool(rd.get("bottom_enabled", True))
        rd["fps"] = max(10, min(int(rd.get("fps", 60)), 120))

        # 补充缺失字段
        for field, default in DEFAULT_CONFIG.items():
            if field not in cfg:
                cfg[field] = default
                logging.warning(f"config 缺少字段 {field}，使用默认值")

        # sessionData URL 解码
        if cfg.get("sessionData") and "%" in cfg["sessionData"]:
            old_val = cfg["sessionData"]
            cfg["sessionData"] = unquote(old_val)
            logging.info(f"[LOGIN] config sessionData URL 解码: {old_val[:30]}... -> {cfg['sessionData'][:30]}...")

        # credential 规范化
        from app.core.bili_credential import normalize_credential_data

        cfg["credential"] = normalize_credential_data(cfg.get("credential", {}), sessdata=cfg.get("sessionData", ""))
        cfg["sessionData"] = cfg["credential"].get("sessdata", "")

    # ---- 保存 ----

    def save(self, immediate=False):
        """触发保存（默认去抖动 500ms）。immediate=True 立即写入。"""
        if immediate:
            self._dirty = True  # 确保立即保存即使此前无修改标记也写入
            self._flush()
            return
        if not self._dirty:
            self._dirty = True
            self._debounce_timer.start()

    def save_now(self):
        """立即保存（程序退出时调用）"""
        self._debounce_timer.stop()
        self._flush()

    def _flush(self):
        """实际写入磁盘 — 先轮转旧备份再写新配置，确保至少保留一个历史版本"""
        if not self._dirty:
            return
        self._dirty = False
        # 轮转备份：备份2 → 备份3, 备份1 → 备份2, 当前配置文件 → 备份1
        for src_num, dst_num in [(2, 3), (1, 2)]:
            src = os.path.join(self.application_path, f"resources/config_备份{src_num}.json")
            dst = os.path.join(self.application_path, f"resources/config_备份{dst_num}.json")
            try:
                if os.path.exists(src):
                    if os.path.exists(dst):
                        os.remove(dst)
                    os.rename(src, dst)
            except OSError:
                pass
        # 当前 config.json → 备份1
        backup1 = os.path.join(self.application_path, "resources/config_备份1.json")
        try:
            if os.path.exists(self.config_path):
                if os.path.exists(backup1):
                    os.remove(backup1)
                os.rename(self.config_path, backup1)
        except OSError:
            pass
        # 写入新配置
        self._write_json(self.config_path, self.config)

    def _write_json(self, path, data):
        try:
            parent = os.path.dirname(path)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8", errors="ignore") as f:
                f.write(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logging.error(str(e))
            logging.exception(f"config.json 写入失败: {path}")

    # ---- 导入/导出 ----

    def export_to(self, path):
        """导出配置到指定路径"""
        self._write_json(path, self.config)

    def import_from(self, path, current_layout):
        """从指定路径导入配置，保留当前 layout"""
        imported = self._load_json(path)
        if not imported:
            return False
        self.config = imported
        self._migrate()
        self.config["layout"] = current_layout
        return True
