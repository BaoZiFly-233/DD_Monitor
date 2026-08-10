# -*- coding: utf-8 -*-
"""InstructionX_UIKit 集成桥 — 主题挂载工具

主界面全局样式已切换为 UIKit 暗色主题（DD监控室.py 中
``app.setStyleSheet(build_global_qss())``，替代原 qdark.qss）。mpv 播放器、
弹幕机、布局面板等自绘 / 带实例级内联样式的控件不依赖全局 QSS，观感不变。
本模块提供：

- init_uikit(): 把 UIKit 令牌状态同步为暗色，供 build_global_qss 与
  UIKit 自绘组件取色。
- build_global_qss(): 生成并缓存 UIKit 全量 QSS（全局应用）。
- apply_scoped_theme(widget): 把同一份 UIKit QSS 挂到指定控件子树
  （widget 级样式优先于 app 级），用于需要强调 UIKit 观感的弹窗子树。
- set_theme(dark): 切换明暗主题（始终同步 UIKit 令牌模式，再刷新全部 QSS）。
- set_accent(name): 切换配色方案（覆盖 ``color.primary`` 令牌族）。
- current_color / is_dark / theme_changed: 供自绘控件取当前主题令牌。
- confirm / info: UIKit 风格非阻塞确认框 / 信息框。

配色：UIKit 令牌系统支持运行时覆盖主色令牌族，本桥将 ``set_accent``
作为明暗之外的第三维参与 QSS 缓存键与 ``current_color`` 取色，
从而让全局 QSS、scoped 弹窗与自绘控件配色一致。
"""

from weakref import WeakSet

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from InstructionX_UIKit.theme import ThemeManager, build_qss
from InstructionX_UIKit.tokens import DARK, LIGHT

__all__ = [
    "init_uikit",
    "build_global_qss",
    "apply_scoped_theme",
    "set_theme",
    "set_accent",
    "current_color",
    "theme_changed",
    "is_dark",
    "confirm",
    "info",
    "ACCENT_NAMES",
]

_tm = ThemeManager.instance()
_current_dark = True
_current_accent = "blue"
_qss_cache: dict = {}
_scoped_widgets: "WeakSet" = WeakSet()

#: 配色方案：覆盖背景 + 边框 + 主色令牌族（亮 / 暗各一套）。
#: "blue" 为 UIKit 默认值，无覆盖；其余方案给整套界面一个明确的色调差异。
_ACCENT_PRESETS = {
    "blue": {},
    "teal": {
        "dark": {
            "color.bg.base": "#13211E",
            "color.bg.subtle": "#182923",
            "color.bg.muted": "#203530",
            "color.bg.elevated": "#1B2C27",
            "color.border": "#273B35",
            "color.border.strong": "#375049",
            "color.primary": "#5FA8A0",
            "color.primary.hover": "#76B8B0",
            "color.primary.pressed": "#8CC7C0",
            "color.primary.subtle": "#223A38",
            "color.on.primary": "#15181E",
        },
        "light": {
            "color.bg.base": "#F5FAF8",
            "color.bg.subtle": "#EDF5F1",
            "color.bg.muted": "#DEEBE5",
            "color.bg.elevated": "#FCFEFD",
            "color.border": "#D8E6E0",
            "color.border.strong": "#BBD1C8",
            "color.primary": "#2F7A72",
            "color.primary.hover": "#296862",
            "color.primary.pressed": "#225650",
            "color.primary.subtle": "#E7F1F0",
            "color.on.primary": "#FFFFFF",
        },
    },
    "purple": {
        "dark": {
            "color.bg.base": "#181620",
            "color.bg.subtle": "#1E1B29",
            "color.bg.muted": "#2A2638",
            "color.bg.elevated": "#242032",
            "color.border": "#342F45",
            "color.border.strong": "#4A4260",
            "color.primary": "#9B8AC4",
            "color.primary.hover": "#B0A2D1",
            "color.primary.pressed": "#C4B9DD",
            "color.primary.subtle": "#2E2A45",
            "color.on.primary": "#15181E",
        },
        "light": {
            "color.bg.base": "#F8F6FB",
            "color.bg.subtle": "#F0EDF7",
            "color.bg.muted": "#E4DFF0",
            "color.bg.elevated": "#FDFCFE",
            "color.border": "#DDD6EA",
            "color.border.strong": "#C0B4DA",
            "color.primary": "#6B5B9E",
            "color.primary.hover": "#5B4E86",
            "color.primary.pressed": "#4B406E",
            "color.primary.subtle": "#EFEBF7",
            "color.on.primary": "#FFFFFF",
        },
    },
    "orange": {
        "dark": {
            "color.bg.base": "#1E1914",
            "color.bg.subtle": "#252017",
            "color.bg.muted": "#342C20",
            "color.bg.elevated": "#2C251B",
            "color.border": "#3D3427",
            "color.border.strong": "#574A37",
            "color.primary": "#C88B5A",
            "color.primary.hover": "#D8A076",
            "color.primary.pressed": "#E7B692",
            "color.primary.subtle": "#3D2F22",
            "color.on.primary": "#15181E",
        },
        "light": {
            "color.bg.base": "#FBF8F4",
            "color.bg.subtle": "#F5EFE7",
            "color.bg.muted": "#ECE0D2",
            "color.bg.elevated": "#FEFDFB",
            "color.border": "#E8DCCB",
            "color.border.strong": "#D2BFA4",
            "color.primary": "#A96B38",
            "color.primary.hover": "#915C2F",
            "color.primary.pressed": "#794D26",
            "color.primary.subtle": "#F8EFE7",
            "color.on.primary": "#FFFFFF",
        },
    },
    "green": {
        "dark": {
            "color.bg.base": "#13211A",
            "color.bg.subtle": "#182921",
            "color.bg.muted": "#20352B",
            "color.bg.elevated": "#1B2D24",
            "color.border": "#273D32",
            "color.border.strong": "#375346",
            "color.primary": "#6BA98A",
            "color.primary.hover": "#82B99E",
            "color.primary.pressed": "#9AC8B1",
            "color.primary.subtle": "#22362D",
            "color.on.primary": "#15181E",
        },
        "light": {
            "color.bg.base": "#F5FAF6",
            "color.bg.subtle": "#EDF5EF",
            "color.bg.muted": "#DEEBE2",
            "color.bg.elevated": "#FCFEFC",
            "color.border": "#D8E6DC",
            "color.border.strong": "#BBD1C2",
            "color.primary": "#3E7E5F",
            "color.primary.hover": "#34684F",
            "color.primary.pressed": "#2A543F",
            "color.primary.subtle": "#E9F2EC",
            "color.on.primary": "#FFFFFF",
        },
    },
}

#: 配色方案名（设置面板下拉框用）
ACCENT_NAMES = tuple(_ACCENT_PRESETS)


class _ThemeSignals(QObject):
    """主题切换广播：自绘控件（视频控制条、布局面板等）监听后刷新颜色。"""

    theme_changed = Signal(bool)  # True=暗色


_theme_signals = _ThemeSignals()


def _tokens(dark: bool, accent: str) -> dict:
    """当前模式 + 当前配色的令牌视图（QSS 与 current_color 的唯一取色来源）。"""
    tokens = dict(DARK if dark else LIGHT)
    tokens.update(_ACCENT_PRESETS[accent].get("dark" if dark else "light", {}))
    return tokens


def current_color(token: str) -> str:
    """返回当前主题的语义色（如 "primary"、"bg.base" → "#RRGGBB"）。"""
    key = token if token.startswith("color.") else f"color.{token}"
    return _tokens(_current_dark, _current_accent).get(key, "#000000")


def is_dark() -> bool:
    """当前是否暗色主题（供自绘控件在构造时取一次）。"""
    return _current_dark


def theme_changed() -> Signal:
    """主题切换信号（bool 参数：True=暗色）。自绘控件连接后刷新硬编码颜色。"""
    return _theme_signals.theme_changed

#: 追加的全局 QSS 补丁：修复 Qt 6 下 QSlider 本体被 QWidget 背景规则
#: 涂成近黑（handle 上下露出两条深色边），滑条轨道色由
#: QSlider::groove/sub-page/add-page 单独控制。
_QSS_PATCH = """
QSlider { background-color: transparent; }
QSlider::groove:horizontal, QSlider::groove:vertical { margin: 0; }
"""


def init_uikit(dark: bool = True) -> None:
    """同步 UIKit 令牌为暗色（默认）或亮色。"""
    global _current_dark
    _current_dark = bool(dark)
    _tm.set_mode("dark" if dark else "light")


def _cached_qss(dark: bool, accent: str) -> str:
    """按（明暗, 配色）分别生成并缓存 UIKit 全量 QSS（幂等）。"""
    key = (dark, accent)
    if key not in _qss_cache:
        _qss_cache[key] = build_qss(_tokens(dark, accent)) + _QSS_PATCH
    return _qss_cache[key]


def build_global_qss() -> str:
    """返回当前主题（明暗 + 配色）对应的 UIKit 全量 QSS。"""
    return _cached_qss(_current_dark, _current_accent)


def _apply_current() -> None:
    """把当前（明暗 + 配色）主题应用到 app 级 QSS、scoped 弹窗并广播。"""
    qss = _cached_qss(_current_dark, _current_accent)
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(qss)
    for widget in list(_scoped_widgets):
        if widget is not None:
            widget.setStyleSheet(qss)
    _theme_signals.theme_changed.emit(_current_dark)


def set_theme(dark: bool) -> None:
    """切换全局明暗主题。

    先始终同步 UIKit 令牌模式，再应用缓存 QSS——即使 QSS 缓存命中也必须
    同步，否则切回深色后 ``current_color()`` 仍返回浅色令牌（自绘控件取色
    错误，视频控制条无法变回深色）。
    """
    dark = bool(dark)
    init_uikit(dark)
    _apply_current()


def set_accent(name: str) -> None:
    """切换配色方案（覆盖 ``color.primary`` 令牌族，立即生效并持久化由调用方负责）。"""
    global _current_accent
    if name not in _ACCENT_PRESETS:
        raise ValueError(f"未知配色: {name!r}，可用: {ACCENT_NAMES}")
    _current_accent = name
    _apply_current()


def apply_scoped_theme(widget) -> None:
    """把当前主题的 UIKit QSS 挂到 widget 及其全部子控件。

    在弹窗 __init__ 布局完成后调用一次即可；widget 级样式优先于 app 级，
    保证该弹窗子树内以 UIKit 观感为准。挂载过的弹窗会跟随全局主题切换。
    """
    widget.setStyleSheet(_cached_qss(_current_dark, _current_accent))
    _scoped_widgets.add(widget)


def confirm(parent, title, text, on_result=None, ok_text="确定", cancel_text="取消"):
    """弹出 UIKit 风格确认框（非阻塞，回调式）。

    ``on_result(ok: bool)`` 在用户选择后回调，等价于 QMessageBox 的
    ``reply == QMessageBox.Yes`` 分支。
    """
    from InstructionX_UIKit.components import Dialog

    dlg = Dialog.confirm(parent, title, text, on_result, ok_text, cancel_text)
    apply_scoped_theme(dlg)
    return dlg


def info(parent, title, text, on_close=None, ok_text="知道了"):
    """弹出 UIKit 风格信息框（非阻塞，仅确认按钮）。"""
    from InstructionX_UIKit.components import Dialog

    dlg = Dialog.info(parent, title, text, on_close, ok_text)
    apply_scoped_theme(dlg)
    return dlg
