# -*- coding: utf-8 -*-
"""Model-driven danmaku workbench widgets."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QStackedWidget, QStyle, QVBoxLayout, QWidget

from qfluentwidgets_pro import (
    BodyLabel,
    FluentIcon,
    InfoBadge,
    PrimaryPushButton,
    SearchLineEdit,
    SegmentedWidget,
    isDarkTheme,
    themeColor,
)
from qfluentwidgets_pro.common.font import getFont
from qfluentwidgets_pro.components.widgets.list_view import RoundListItemDelegate, RoundListView

from app.danmaku.model import DanmakuEventModel, DanmakuFilterProxyModel, DanmakuRole


_KIND_COLORS = {
    "danmaku": ("弹幕", QColor("#2563EB")),
    "gift": ("礼物", QColor("#D97706")),
    "guard": ("上舰", QColor("#C2415C")),
    "super_chat": ("醒目", QColor("#7C3AED")),
    "enter": ("进场", QColor("#16835A")),
    "follow": ("关注", QColor("#16835A")),
    "share": ("分享", QColor("#0F766E")),
    "like": ("点赞", QColor("#0F766E")),
    "system": ("系统", QColor("#64748B")),
}


class DanmakuItemDelegate(RoundListItemDelegate):
    """Paint compact two-line event rows without per-row child widgets."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font_size = 13

    def setFontSize(self, size):
        size = max(10, min(int(size), 24))
        if size == self._font_size:
            return
        self._font_size = size
        if self.parent():
            self.parent().viewport().update()

    def sizeHint(self, option, index):
        return QSize(max(option.rect.width(), 220), max(58, self._font_size * 3 + 19))

    def paint(self, painter, option, index):
        event = index.data(DanmakuRole.EVENT)
        if event is None:
            return super().paint(painter, option, index)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(7, 3, -7, -3)
        dark = isDarkTheme()
        hovered = index.row() == self.hoverRow
        selected = bool(option.state & QStyle.StateFlag.State_Selected)

        if selected:
            background = QColor(themeColor())
            background.setAlpha(42 if dark else 28)
        elif hovered:
            background = QColor(255, 255, 255, 18) if dark else QColor(0, 0, 0, 12)
        else:
            background = QColor(255, 255, 255, 8) if dark else QColor(255, 255, 255, 120)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 7, 7)

        label, badge_color = _KIND_COLORS.get(event.kind, ("消息", QColor("#64748B")))
        if event.is_translation:
            label, badge_color = "同传", QColor("#0F766E")

        badge_font = getFont(max(10, self._font_size - 2), QFont.Weight.DemiBold)
        painter.setFont(badge_font)
        badge_width = max(38, QFontMetrics(badge_font).horizontalAdvance(label) + 14)
        badge_rect = rect.adjusted(8, 8, 0, 0)
        badge_rect.setWidth(badge_width)
        badge_rect.setHeight(20)
        badge_background = QColor(badge_color)
        badge_background.setAlpha(44 if dark else 30)
        painter.setBrush(badge_background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(badge_rect, 6, 6)
        painter.setPen(badge_color.lighter(125) if dark else badge_color.darker(110))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, label)

        primary = QColor(245, 247, 250) if dark else QColor(32, 35, 42)
        secondary = QColor(174, 181, 193) if dark else QColor(99, 105, 116)
        user_font = getFont(max(11, self._font_size - 1), QFont.Weight.DemiBold)
        body_font = getFont(self._font_size)
        meta_font = getFont(max(10, self._font_size - 2))

        header_x = badge_rect.right() + 10
        header_right = rect.right() - 10
        time_text = event.time_label
        painter.setFont(meta_font)
        time_width = QFontMetrics(meta_font).horizontalAdvance(time_text)
        painter.setPen(secondary)
        painter.drawText(
            header_right - time_width,
            rect.top() + 9,
            time_width,
            19,
            Qt.AlignmentFlag.AlignVCenter,
            time_text,
        )

        user_text = event.uname or "直播间"
        if event.medal_name:
            medal = f"{event.medal_level} {event.medal_name}".strip()
            user_text = f"[{medal}] {user_text}"
        if event.price > 0:
            user_text += f"  ￥{event.price:g}"
        user_width = max(20, header_right - time_width - header_x - 8)
        painter.setFont(user_font)
        painter.setPen(primary)
        user_text = QFontMetrics(user_font).elidedText(user_text, Qt.TextElideMode.ElideRight, user_width)
        painter.drawText(
            header_x,
            rect.top() + 8,
            user_width,
            20,
            Qt.AlignmentFlag.AlignVCenter,
            user_text,
        )

        body_rect = rect.adjusted(10, 29, -10, -5)
        painter.setFont(body_font)
        body_color = QColor(event.color) if event.kind == "danmaku" else primary
        lightness = body_color.lightness() if body_color.isValid() else -1
        if (
            not body_color.isValid()
            or (dark and lightness < 90)
            or (not dark and (lightness < 55 or lightness > 205))
        ):
            body_color = primary
        painter.setPen(QPen(body_color))
        body_text = QFontMetrics(body_font).elidedText(
            event.display_text,
            Qt.TextElideMode.ElideRight,
            body_rect.width(),
        )
        painter.drawText(body_rect, Qt.AlignmentFlag.AlignVCenter, body_text)
        painter.restore()


class DanmakuWorkbench(QWidget):
    """Searchable, bounded live event view with PiliPlus-style follow control."""

    def __init__(self, parent=None, max_events=500, event_model=None):
        super().__init__(parent)
        self._auto_follow = True
        self._scrolling_programmatically = False
        self._display_policy = None
        self._translation_rules = ()

        self.model = (
            event_model
            if event_model is not None
            else DanmakuEventModel(max_events=max_events, parent=self)
        )
        self.proxyModel = DanmakuFilterProxyModel(self)
        self.proxyModel.setSourceModel(self.model)

        self.segmented = SegmentedWidget(self)
        for route, text in (
            ("all", "全部"),
            ("chat", "弹幕"),
            ("translation", "同传"),
            ("interaction", "互动"),
        ):
            self.segmented.addItem(route, text, lambda checked=False, key=route: self.setMode(key))
        self.segmented.setCurrentItem("all")

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("搜索用户或内容")
        self.searchEdit.setClearButtonEnabled(True)
        self.searchEdit.setMinimumWidth(180)
        self.searchEdit.textChanged.connect(self.proxyModel.set_search_text)

        self.countBadge = InfoBadge.info("0 条", self)
        self.countBadge.setMinimumWidth(48)

        self.listView = RoundListView(self)
        self.listView.setModel(self.proxyModel)
        self.itemDelegate = DanmakuItemDelegate(self.listView)
        self.listView.setItemDelegate(self.itemDelegate)
        self.listView.setUniformItemSizes(True)
        self.listView.setWordWrap(False)
        self.listView.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.listView.setSelectionMode(RoundListView.SelectionMode.SingleSelection)
        self.listView.setVerticalScrollMode(RoundListView.ScrollMode.ScrollPerPixel)

        self.emptyPage = QWidget(self)
        empty_layout = QVBoxLayout(self.emptyPage)
        empty_layout.setContentsMargins(20, 20, 20, 20)
        empty_layout.addStretch(1)
        empty_label = BodyLabel("等待直播消息", self.emptyPage)
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        empty_layout.addStretch(1)

        self.stack = QStackedWidget(self)
        self.stack.addWidget(self.emptyPage)
        self.stack.addWidget(self.listView)

        self.latestButton = PrimaryPushButton(FluentIcon.DOWN, "回到最新", self)
        self.latestButton.setVisible(False)
        self.latestButton.clicked.connect(self.scrollToLatest)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self.segmented, 0)
        header.addStretch(1)
        header.addWidget(self.searchEdit, 1)
        header.addWidget(self.countBadge, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.latestButton, 0, Qt.AlignmentFlag.AlignRight)

        scroll_bar = self.listView.verticalScrollBar()
        scroll_bar.valueChanged.connect(self._on_scroll_value_changed)
        self.model.rowsInserted.connect(self._on_model_changed)
        self.model.rowsRemoved.connect(self._on_model_changed)
        self.model.modelReset.connect(self._on_model_changed)
        self.model.droppedChanged.connect(self._update_state)
        self.proxyModel.rowsInserted.connect(self._update_state)
        self.proxyModel.rowsRemoved.connect(self._update_state)
        self.proxyModel.modelReset.connect(self._update_state)
        self._update_state()

    def appendEvent(self, event):
        return self.model.append_event(event)

    def appendEvents(self, events):
        return self.model.append_events(events)

    def clear(self):
        self.model.clear()
        self._auto_follow = True
        self.latestButton.hide()

    def setMode(self, mode):
        self.proxyModel.set_mode(mode)
        if self.segmented.currentRouteKey() != mode:
            self.segmented.setCurrentItem(mode)
        self._auto_follow = True
        self._update_state()
        self.scrollToLatest()

    def setDisplayFilters(self, translation_mode=0, interaction_mode=0):
        policy = (int(translation_mode), int(interaction_mode))
        if policy == self._display_policy:
            return
        self._display_policy = policy
        self.proxyModel.set_display_policy(*policy)
        default_mode = {0: "all", 1: "chat", 2: "translation"}.get(policy[0], "all")
        self.setMode(default_mode)

    def setTranslationRules(self, words):
        rules = tuple(str(word).strip() for word in words if str(word).strip())
        if rules == self._translation_rules:
            return
        self._translation_rules = rules
        self.model.reclassify_translations(rules)
        self._update_state()

    def setFontSize(self, size):
        self.itemDelegate.setFontSize(size)
        self.listView.doItemsLayout()

    def scrollToLatest(self):
        self._scrolling_programmatically = True
        self.listView.scrollToBottom()
        self._scrolling_programmatically = False
        self._auto_follow = True
        self.latestButton.hide()

    def _on_model_changed(self, *args):
        self._update_state()
        if self._auto_follow:
            self.scrollToLatest()

    def _on_scroll_value_changed(self, value):
        if self._scrolling_programmatically:
            return
        bar = self.listView.verticalScrollBar()
        at_bottom = value >= max(0, bar.maximum() - 4)
        self._auto_follow = at_bottom
        self.latestButton.setVisible(not at_bottom and self.proxyModel.rowCount() > 0)

    def _update_state(self, *args):
        count = self.proxyModel.rowCount()
        dropped = self.model.dropped_count
        self.countBadge.setText(f"{count} 条")
        self.countBadge.setToolTip(f"历史队列已丢弃 {dropped} 条旧消息" if dropped else "")
        self.stack.setCurrentWidget(self.listView if count else self.emptyPage)
