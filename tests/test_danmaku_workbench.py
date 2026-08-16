from types import SimpleNamespace

from PySide6.QtWidgets import QWidget

from app.danmaku.events import DanmakuEvent
from app.ui.danmaku_workbench import DanmakuWorkbench
from app.ui.danmu import TextBrowser
from app.ui.video_widget import VideoWidget


def _event(index, **changes):
    values = {
        "event_id": f"workbench-{index}",
        "room_id": "100",
        "connection_id": 7,
        "text": f"message {index}",
        "uname": f"user {index}",
        "timestamp_ms": 1_700_000_000_000 + index,
    }
    values.update(changes)
    return DanmakuEvent(**values)


def test_workbench_uses_bounded_model_and_delegate(qapp):
    workbench = DanmakuWorkbench(max_events=3)
    workbench.appendEvents(
        [
            _event(1),
            _event(2, text="[EN] translated"),
            _event(3, kind="gift", text="sent a gift", uname="alice"),
            _event(4, kind="enter", text="entered", uname="bob"),
        ]
    )
    workbench.model.flush_pending()
    qapp.processEvents()

    assert workbench.model.rowCount() == 3
    assert workbench.model.dropped_count == 1
    assert workbench.listView.indexWidget(workbench.proxyModel.index(0, 0)) is None

    workbench.setTranslationRules(["[EN]"])
    workbench.setMode("translation")
    assert workbench.proxyModel.rowCount() == 1

    workbench.setMode("all")
    workbench.searchEdit.setText("ALICE")
    qapp.processEvents()
    assert workbench.proxyModel.rowCount() == 1
    assert workbench.proxyModel.index(0, 0).data() == "sent a gift"


def test_reapplying_display_policy_preserves_manual_mode(qapp):
    workbench = DanmakuWorkbench(max_events=20)
    workbench.setDisplayFilters(0, 0)
    workbench.setMode("interaction")

    workbench.setDisplayFilters(0, 0)

    assert workbench.proxyModel.mode == "interaction"
    assert workbench.segmented.currentRouteKey() == "interaction"


def test_manual_scroll_pauses_follow_until_return_to_latest(qapp):
    workbench = DanmakuWorkbench(max_events=100)
    workbench.resize(420, 280)
    workbench.show()
    workbench.appendEvents([_event(index) for index in range(80)])
    workbench.model.flush_pending()
    qapp.processEvents()

    bar = workbench.listView.verticalScrollBar()
    assert bar.maximum() > 0
    bar.setValue(0)
    qapp.processEvents()
    assert not workbench._auto_follow

    workbench.appendEvent(_event(81, text="newest"))
    workbench.model.flush_pending()
    qapp.processEvents()
    assert not workbench.latestButton.isHidden()

    workbench.scrollToLatest()
    qapp.processEvents()
    assert workbench._auto_follow
    assert workbench.latestButton.isHidden()
    workbench.close()


def test_text_browser_hosts_one_event_workbench(qapp):
    parent = QWidget()
    browser = TextBrowser(parent)
    browser.appendEvent(_event(1))
    browser.workbench.model.flush_pending()
    browser.setTranslationRules(["translation"])
    browser.setDisplayFilters(0, 0)
    browser.setFontSize(12)
    browser.setPanelOpacity(0.5)

    assert browser.workbench.model.rowCount() == 1
    assert browser.workbench.proxyModel.rowCount() == 1
    assert not hasattr(browser, "transBrowser")
    assert not hasattr(browser, "msgsBrowser")
    assert browser.optionWidget is None

    browser.optionButton.click()
    qapp.processEvents()
    assert browser.optionWidget is not None

    browser.optionWidget.close()
    browser.close()
    parent.close()
    qapp.processEvents()


def test_video_widget_drops_stale_and_duplicate_danmaku_events():
    accepted = []
    emitted = []
    stored = []
    seen = set()

    def append_event(event):
        if event.event_id in seen:
            return False
        seen.add(event.event_id)
        stored.append(event)
        return True

    widget = SimpleNamespace(
        roomID="100",
        _activeDanmuConnectionId=7,
        name_str="窗口 1",
        filters=[],
        danmakuModel=SimpleNamespace(append_event=append_event),
        playDanmu=accepted.append,
        danmakuEvent=SimpleNamespace(emit=emitted.append),
    )

    VideoWidget._onDanmakuEvent(widget, _event(1))
    VideoWidget._onDanmakuEvent(widget, _event(1))
    VideoWidget._onDanmakuEvent(widget, _event(2, room_id="200"))
    VideoWidget._onDanmakuEvent(widget, _event(3, connection_id=6))
    VideoWidget._onDanmakuEvent(widget, _event(4, kind="gift", text="gift"))

    assert [event.event_id for event in stored] == ["workbench-1", "workbench-4"]
    assert [event.event_id for event in accepted] == ["workbench-1"]
    assert [event.event_id for event in emitted] == ["workbench-1", "workbench-4"]


def test_media_reload_clears_history_only_when_room_changes():
    calls = []
    widget = SimpleNamespace(
        roomID="200",
        _danmakuHistoryRoomId="100",
        checkPlaying=SimpleNamespace(stop=lambda: calls.append("stop")),
        danmakuModel=SimpleNamespace(clear=lambda: calls.append("clear")),
        playerRestart=lambda: calls.append("restart"),
        setTitle=lambda: calls.append("title"),
        mediaStop=lambda: calls.append("media-stop"),
    )

    VideoWidget.mediaReload(widget)
    VideoWidget.mediaReload(widget)

    assert widget._danmakuHistoryRoomId == "200"
    assert calls.count("clear") == 1
    assert calls.count("restart") == 2
    assert calls.count("title") == 2
