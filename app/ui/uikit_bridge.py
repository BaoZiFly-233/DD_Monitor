# -*- coding: utf-8 -*-
"""qfluentwidgets_pro 集成桥 — 主题与取色工具

组件库为 qfluentwidgets_pro（PySide6-Fluent-Widgets-Pro，Fluent Design，
含原版 Pro 组件复现）。业务代码直接使用 qfluentwidgets 组件；本模块仅
提供主题与自绘控件取色工具：

- init_uikit(): 设置 Fluent 明暗主题（setTheme）。
- set_theme(dark) / set_accent(name): Fluent 明暗 / 主题色切换。
- current_color / is_dark / theme_changed: 自绘控件取色（令牌表本地化，
  primary 族与 themeColor() 保持一致）。
- confirm / info: Fluent MessageBox 非阻塞确认框 / 信息框。
"""


from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from qfluentwidgets_pro import (
    MessageBox,
    RoundMenu,
    Theme,
    isDarkTheme,
    setTheme,
    setThemeColor,
    themeColor,
)
from qfluentwidgets_pro.common.config import qconfig

__all__ = [
    "init_uikit",
    "set_theme",
    "set_accent",
    "set_menu_animation",
    "current_color",
    "theme_changed",
    "is_dark",
    "confirm",
    "info",
    "ACCENT_NAMES",
]

_current_dark = True
_current_accent = "blue"

#: 基础令牌表（自 InstructionX_UIKit tokens 迁移，供自绘控件取色）
_DARK = {
    "color.bg.base": "#17181B",
    "color.bg.subtle": "#1C1E22",
    "color.bg.muted": "#24262B",
    "color.bg.elevated": "#202226",
    "color.border": "#30333A",
    "color.border.strong": "#444850",
    "color.text.primary": "#F1F2F4",
    "color.text.secondary": "#B4B7BD",
    "color.text.tertiary": "#7C8088",
    "color.text.disabled": "#545860",
    "color.primary": "#6D9BD2",
    "color.primary.hover": "#85ABDA",
    "color.primary.pressed": "#9EBCE2",
    "color.primary.subtle": "#253246",
    "color.on.primary": "#141518",
    "color.success": "#6BA98A",
    "color.success.subtle": "#22362D",
    "color.warning": "#D2A668",
    "color.warning.subtle": "#3A3226",
    "color.danger": "#CD7A7A",
    "color.danger.subtle": "#3E2A2A",
    "color.overlay": "rgba(0,0,0,0.55)",
}
_LIGHT = {
    "color.bg.base": "#FFFFFF",
    "color.bg.subtle": "#F6F7F9",
    "color.bg.muted": "#EFF1F5",
    "color.bg.elevated": "#FFFFFF",
    "color.border": "#E3E6EB",
    "color.border.strong": "#C9CFD8",
    "color.text.primary": "#1C2330",
    "color.text.secondary": "#59636F",
    "color.text.tertiary": "#98A0AC",
    "color.text.disabled": "#C2C8D0",
    "color.primary": "#3F5E8C",
    "color.primary.hover": "#35507A",
    "color.primary.pressed": "#2B4266",
    "color.primary.subtle": "#EBEFF5",
    "color.on.primary": "#FFFFFF",
    "color.success": "#3E7E5F",
    "color.success.subtle": "#E9F2EC",
    "color.warning": "#C08A3E",
    "color.warning.subtle": "#F7F0E3",
    "color.danger": "#B25050",
    "color.danger.subtle": "#F7EBEB",
    "color.overlay": "rgba(28,35,48,0.45)",
}

#: 配色方案：覆盖背景 + 主色令牌族（亮 / 暗各一套）。
#: "blue" 为 Fluent 默认蓝（qfluentwidgets themeColor 默认值），无覆盖。
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

#: Fluent 默认主题蓝（"blue" 配色）
_DEFAULT_BLUE = {"dark": "#7C98C4", "light": "#3F5E8C"}


class _ThemeSignals(QObject):
    """主题切换广播：自绘控件（视频控制条、布局面板等）监听后刷新颜色。"""

    theme_changed = Signal(bool)  # True=暗色


_theme_signals = _ThemeSignals()
_qconfig_hooked = False


def _tokens(dark: bool, accent: str) -> dict:
    """当前模式 + 当前配色的令牌视图（current_color 的唯一取色来源）。"""
    tokens = dict(_DARK if dark else _LIGHT)
    tokens.update(_ACCENT_PRESETS[accent].get("dark" if dark else "light", {}))
    return tokens


def current_color(token: str) -> str:
    """返回当前主题的语义色（如 "primary"、"bg.base" → "#RRGGBB"）。"""
    key = token if token.startswith("color.") else f"color.{token}"
    if key == "color.primary":
        return themeColor().name()
    return _tokens(_current_dark, _current_accent).get(key, "#000000")


def is_dark() -> bool:
    """当前是否暗色主题（供自绘控件在构造时取一次）。"""
    return isDarkTheme()


def theme_changed() -> Signal:
    """主题切换信号（bool 参数：True=暗色）。自绘控件连接后刷新硬编码颜色。"""
    return _theme_signals.theme_changed


def _apply_accent_color() -> None:
    """把当前配色的主色写入 qfluentwidgets 主题色（themeColor）。"""
    preset = _ACCENT_PRESETS[_current_accent]
    mode = "dark" if _current_dark else "light"
    color = preset.get(mode, {}).get("color.primary") or _DEFAULT_BLUE[mode]
    setThemeColor(QColor(color))


# ---------------------------------------------------------------------------
# 原生控件 Fluent 化 QSS（app 级）
#
# qfluentwidgets 只把 QSS 挂到自己的组件实例上（app 级 QSS 为空），因此
# 原生控件（QScrollBar/QGroupBox/QTextBrowser 等无对应组件的控件）保持
# 系统观感。这里在 app 级挂一套 Fluent 风格 QSS；组件实例 QSS 优先级
# 更高，互不冲突。
# ---------------------------------------------------------------------------


def _build_native_qss() -> str:
    """生成原生控件 QSS（令牌色，随主题/配色重建）。

    应用里的 QComboBox/QLineEdit/QCheckBox/QTabWidget/QTableWidget/
    QScrollArea 已全部替换为 qfluentwidgets 组件（组件级 QSS 渲染），
    这里只覆盖无对应组件的少量原生控件。
    """
    tokens = _tokens(_current_dark, _current_accent)
    c = lambda k: tokens[f"color.{k}"]  # noqa: E731

    return f"""
/* ===== 菜单栏（顶栏 Fluent 观感；下拉菜单已用 RoundMenu 自绘） ===== */
QMenuBar {{
    background-color: {c("bg.base")}; color: {c("text.primary")};
    border-bottom: 1px solid {c("border")};
}}
QMenuBar::item {{
    background: transparent; padding: 5px 10px; border-radius: 4px;
}}
QMenuBar::item:selected {{ background-color: {c("bg.muted")}; }}
QMenuBar::item:pressed {{ background-color: {c("primary.subtle")}; }}

/* ===== 可停靠工作面板 ===== */
QDockWidget {{
    color: {c("text.primary")}; background-color: {c("bg.subtle")};
    border: 1px solid {c("border")}; font: 600 13px "Microsoft YaHei UI";
}}
QDockWidget::title {{
    background-color: {c("bg.elevated")}; color: {c("text.primary")};
    border-bottom: 1px solid {c("border")}; padding: 7px 8px;
    text-align: left;
}}
QDockWidget::close-button, QDockWidget::float-button {{
    border: none; background: transparent; padding: 2px;
}}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background-color: {c("bg.muted")}; border-radius: 4px;
}}

/* ===== 滚动条（Fluent 细圆条；剩余原生滚动区域：弹幕机/更新说明等） ===== */
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {c("border.strong")}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {c("text.tertiary")}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px; margin: 0 2px 2px 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c("border.strong")}; border-radius: 4px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {c("text.tertiary")}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

/* ===== 分组框 ===== */
QGroupBox {{
    border: 1px solid {c("border")}; border-radius: 8px; margin-top: 10px;
    padding-top: 6px; background: transparent; color: {c("text.primary")};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c("text.primary")};
}}

/* ===== 进度条（启动闪屏） ===== */
QProgressBar {{
    background-color: {c("bg.muted")}; border: none; border-radius: 4px;
    text-align: center; color: transparent; min-height: 8px;
}}
QProgressBar::chunk {{ background-color: {c("primary")}; border-radius: 4px; }}

/* ===== 文本浏览 ===== */
QTextBrowser, QTextEdit {{
    background-color: {c("bg.base")}; color: {c("text.primary")};
    border: 1px solid {c("border")}; border-radius: 6px;
    selection-background-color: {c("primary")}; selection-color: {c("on.primary")};
}}
"""


def _apply_native_qss() -> None:
    """把原生控件 Fluent QSS 挂到 app 级（qfluentwidgets 组件实例 QSS 优先）。"""
    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(_build_native_qss())


def _apply_palette() -> None:
    """把主题令牌写入 QPalette，让原生控件（QDialog/QTabWidget/QGroupBox/
    QComboBox 等）背景文字随明暗主题，与 Fluent 组件一致。

    qfluentwidgets 只美化自身组件、不设置 palette；不补 palette 时原生
    控件在暗色主题下仍是系统亮色，界面撕裂。QMenu 等窗口底色同样取自
    palette，主题色下自然融合（菜单为直角无圆角干预，无白角问题）。
    """
    app = QApplication.instance()
    if app is None:
        return
    tokens = _tokens(_current_dark, _current_accent)
    c = lambda k: QColor(tokens[f"color.{k}"])  # noqa: E731
    p = QPalette()
    p.setColor(QPalette.Window, c("bg.base"))
    p.setColor(QPalette.WindowText, c("text.primary"))
    p.setColor(QPalette.Base, c("bg.elevated"))
    p.setColor(QPalette.AlternateBase, c("bg.subtle"))
    p.setColor(QPalette.Text, c("text.primary"))
    p.setColor(QPalette.PlaceholderText, c("text.tertiary"))
    p.setColor(QPalette.Button, c("bg.muted"))
    p.setColor(QPalette.ButtonText, c("text.primary"))
    p.setColor(QPalette.BrightText, c("on.primary"))
    p.setColor(QPalette.Highlight, c("primary"))
    p.setColor(QPalette.HighlightedText, c("on.primary"))
    p.setColor(QPalette.Link, c("primary"))
    p.setColor(QPalette.LinkVisited, c("primary.hover"))
    p.setColor(QPalette.ToolTipBase, c("bg.elevated"))
    p.setColor(QPalette.ToolTipText, c("text.primary"))
    p.setColor(QPalette.Light, c("bg.base"))
    p.setColor(QPalette.Midlight, c("bg.subtle"))
    p.setColor(QPalette.Mid, c("border.strong"))
    p.setColor(QPalette.Dark, c("border"))
    p.setColor(QPalette.Shadow, c("border"))
    disabled = c("text.disabled")
    p.setColor(QPalette.Disabled, QPalette.Text, disabled)
    p.setColor(QPalette.Disabled, QPalette.WindowText, disabled)
    p.setColor(QPalette.Disabled, QPalette.ButtonText, disabled)
    app.setPalette(p)


def init_uikit(dark: bool = True) -> None:
    """设置 Fluent 明暗主题（默认暗色），同步调色板 + 原生控件 QSS。"""
    global _current_dark, _qconfig_hooked
    _current_dark = bool(dark)
    setTheme(Theme.DARK if dark else Theme.LIGHT)
    _apply_accent_color()
    _apply_palette()
    _apply_native_qss()
    if not _qconfig_hooked:
        _qconfig_hooked = True
        qconfig.themeChanged.connect(lambda t: _theme_signals.theme_changed.emit(t == Theme.DARK))


def build_global_qss() -> str:
    """qfluentwidgets 由 setTheme 自动管理全局 QSS，无需手动挂载。"""
    return ""


def apply_scoped_theme(widget) -> None:
    """qfluentwidgets 全局样式覆盖全部弹窗子树，保留为空操作。"""


def set_theme(dark: bool) -> None:
    """切换全局明暗主题（Fluent setTheme + 调色板 + 原生控件 QSS）。"""
    global _current_dark
    _current_dark = bool(dark)
    setTheme(Theme.DARK if dark else Theme.LIGHT)
    _apply_accent_color()
    _apply_palette()
    _apply_native_qss()


def set_accent(name: str) -> None:
    """切换配色方案（覆盖主题主色，立即生效并持久化由调用方负责）。"""
    global _current_accent
    if name not in _ACCENT_PRESETS:
        raise ValueError(f"未知配色: {name!r}，可用: {ACCENT_NAMES}")
    if name == _current_accent:
        return
    _current_accent = name
    _apply_accent_color()
    _apply_native_qss()


def set_menu_animation(enabled: bool) -> None:
    """开关菜单弹出动画（设置面板"菜单动画"选项）。

    默认开启；低配机掉帧/不习惯动画的用户可在设置中关闭。
    """
    RoundMenu.animationEnabled = bool(enabled)


def confirm(parent, title, text, on_result=None, ok_text="确定", cancel_text="取消"):
    """弹出 Fluent 风格确认框（非阻塞，回调式）。

    ``on_result(ok: bool)`` 在用户选择后回调。
    """
    mb = MessageBox(title, text, parent)
    mb.yesSignal.connect(lambda: on_result(True) if on_result else None)
    mb.cancelSignal.connect(lambda: on_result(False) if on_result else None)
    mb.show()
    return mb


def info(parent, title, text, on_close=None, ok_text="知道了", level="info"):
    """Fluent InfoBar 通知（右下角滑入，3 秒自动消失，非阻塞）。

    level: "info" / "success" / "warning" / "error"（决定图标与配色）。
    与 confirm() 的区别：通知类提示用 InfoBar，重要决策用 MessageBox。
    """
    from qfluentwidgets_pro import InfoBar, InfoBarPosition

    method = getattr(InfoBar, level if level in ("info", "success", "warning", "error") else "info")
    bar = method(
        title=title,
        content=text,
        duration=3000,
        position=InfoBarPosition.BOTTOM_RIGHT,
        parent=parent,
    )
    if on_close:
        bar.closedSignal.connect(lambda: on_close())
    return bar
