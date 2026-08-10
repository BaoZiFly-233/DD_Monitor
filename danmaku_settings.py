"""弹幕配置数据模型 — 纯数据类，无 Qt 依赖。

从 danmu.py（弹幕机 UI 模块）中独立出来，便于配置层 / 渲染层 / UI 层
低耦合共享，且可在无 GUI 环境下单测。
"""

from dataclasses import dataclass

from constants import DEFAULT_DANMU_CONFIG


@dataclass
class DanmakuSettings:
    """弹幕配置 — 替代旧版 textSetting list 魔法索引。

    旧版索引: [0=enabled, 1=opacity, 2=horiz_idx, 3=vert_idx, 4=translate_mode,
                5=filters, 6=font_size, 7=enter_room, 8=rolling_enabled]
    """

    enabled: bool = True
    opacity: int = 50
    horizontal_index: int = 1
    vertical_index: int = 7
    translate_mode: int = 0
    translate_filters: str = "【 [ {"
    font_size: int = 10
    show_enter_room: int = 0
    rolling_enabled: bool = True

    def to_config_list(self):
        """导出为兼容旧 config.json 的列表格式"""
        return [
            self.enabled,
            self.opacity,
            self.horizontal_index,
            self.vertical_index,
            self.translate_mode,
            self.translate_filters,
            self.font_size,
            self.show_enter_room,
            self.rolling_enabled,
        ]

    @classmethod
    def from_config_list(cls, data):
        """从 config.json 列表格式恢复"""
        if data is None:
            data = list(DEFAULT_DANMU_CONFIG)
        elif isinstance(data, bool):
            data = [data, 20, 1, 7, 0, "【 [ {", 10, 0, data]
        elif not isinstance(data, (list, tuple)):
            data = list(DEFAULT_DANMU_CONFIG)
        lst = list(data)
        while len(lst) < 9:
            lst.append(DEFAULT_DANMU_CONFIG[len(lst)])
        lst = lst[:9]
        return cls(
            enabled=bool(lst[0]),
            opacity=max(7, int(lst[1])),
            horizontal_index=max(0, min(int(lst[2]), 9)),
            vertical_index=max(0, min(int(lst[3]), 9)),
            translate_mode=max(0, min(int(lst[4]), 2)),
            translate_filters=str(lst[5]),
            font_size=max(0, min(int(lst[6]), 25)),
            show_enter_room=max(0, min(int(lst[7]), 3)),
            rolling_enabled=bool(lst[8]),
        )

    # 兼容旧代码的列表索引访问
    _INDEX_MAP = {
        0: "enabled",
        1: "opacity",
        2: "horizontal_index",
        3: "vertical_index",
        4: "translate_mode",
        5: "translate_filters",
        6: "font_size",
        7: "show_enter_room",
        8: "rolling_enabled",
    }

    def __getitem__(self, index):
        if index in self._INDEX_MAP:
            return getattr(self, self._INDEX_MAP[index])
        raise IndexError(f"DanmakuSettings index out of range: {index}")

    def __setitem__(self, index, value):
        if index in self._INDEX_MAP:
            setattr(self, self._INDEX_MAP[index], value)
            return
        raise IndexError(f"DanmakuSettings index out of range: {index}")
