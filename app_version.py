"""应用版本与元信息 — 发版时唯一的修改入口。

发版流程：只改这里的 VERSION（可选更新 RELEASE_DATE），其余位置自动同步：
- 主窗口标题 / 关于窗口 / 启动画面版本号
- 版本更新检查（checkUpdate，tuple 比较，支持 x.y.z）
- Windows 打包脚本（scripts/build_win.bat 自动读取）
- CI workflow_dispatch 的默认值需手动同步（tag 触发时自动取 tag）
"""

import re

APP_NAME = 'DD监控室'
VERSION = '3.51'             # 主版本号（x.y 或 x.y.z）
VERSION_SUFFIX = '魔改版'     # 展示后缀（可为空字符串）
RELEASE_DATE = '2026/04/28'  # 发版日期

# 展示用："3.51魔改版"
DISPLAY_VERSION = f'{VERSION}{VERSION_SUFFIX}'


def parse_version(text):
    """'3.51' -> (3, 51)；'3.5.2' -> (3, 5, 2)。用于版本比较，规避 float 比较的坑。"""
    return tuple(int(part) for part in re.findall(r'\d+', text or ''))
