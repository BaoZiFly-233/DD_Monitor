"""全局常量模块 — 不依赖任何其他业务模块。

将散落在 config_manager / danmu 等模块中的常量集中于此，
消除纯配置层对 UI 层的反向依赖（config_manager 不再 import danmu）。
"""

# 窗口数量上限（主窗口播放器格子数）
MAX_WINDOWS = 16

# 窗口卡片宽度（用于计算主窗口能容纳的格子数量）
WINDOW_CARD_WIDTH = 169

# 弹幕水平/垂直显示比例选项（索引 0~9，对应 10%~100%）
DISPLAY_RATIOS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]

# 弹幕配置默认值（兼容旧 config.json list 格式）
# 索引: [0=enabled, 1=opacity, 2=horiz_idx, 3=vert_idx, 4=translate_mode,
#        5=filters, 6=font_size, 7=enter_room, 8=rolling_enabled]
DEFAULT_DANMU_CONFIG = [True, 50, 1, 7, 0, "【 [ {", 10, 0, True]
