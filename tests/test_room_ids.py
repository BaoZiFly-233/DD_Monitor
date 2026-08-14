"""添加直播间输入解析回归测试。"""

from PySide6.QtCore import QThread, Signal

from app.ui import liver_select
from app.ui.liver_select import merge_room_id, parse_room_ids


class _HotChunkBurst(QThread):
    chunk = Signal(int, list)

    def run(self):
        for i in range(80):
            if self.isInterruptionRequested():
                return
            page = i % 5
            self.chunk.emit(page, [[f"增量主播{i}", f"增量标题{i}", str(1000 + i)]])
            self.msleep(1)


def test_parse_room_ids_handles_common_separators_and_deduplicates():
    text = "123  456\n123，789; invalid"

    assert parse_room_ids(text) == ["123", "456", "789"]


def test_merge_room_id_uses_exact_tokens_not_substrings():
    assert merge_room_id("1234", "123") == "1234 123"
    assert merge_room_id("123 1234", "123") == "123 1234"


def test_merge_room_id_ignores_invalid_values():
    assert merge_room_id("123", "room-456") == "123"
    assert parse_room_ids("１２３") == []


def test_liver_panel_defers_add_room_window(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(liver_select.CollectLiverInfo, "start", lambda self: None)
    panel = liver_select.LiverPanel({}, str(tmp_path))

    panel.setSessionData("session")
    panel.setCredential({"sessdata": "session"})

    assert panel._addLiverRoomWidget is None
    panel.deleteLater()


def _add_room_widget(tmp_path):
    resources = tmp_path / "resources"
    resources.mkdir(exist_ok=True)
    (resources / "vtb.csv").write_text("", encoding="utf-8")
    return liver_select.AddLiverRoomWidget(str(tmp_path))


def test_hot_categories_coalesce_rapid_switches(qapp, tmp_path, monkeypatch):
    from PySide6.QtTest import QTest

    widget = _add_room_widget(tmp_path)
    widget.show()
    qapp.processEvents()
    for page in range(5):
        widget.collectHotLiverChunk(page, [[f"主播{page}", f"标题{page}", str(100 + page)]])

    fills = []
    original_fill = widget._fillHotLiverTable

    def tracked_fill(page):
        fills.append(page)
        original_fill(page)

    monkeypatch.setattr(widget, "_fillHotLiverTable", tracked_fill)
    burst = _HotChunkBurst()
    burst.chunk.connect(widget.collectHotLiverChunk)
    burst.start()
    for i in range(80):
        widget.switchHotLiver(i % 5)
        QTest.qWait(1)
    burst.wait()
    widget.switchHotLiver(4)
    QTest.qWait(widget._hotRefreshTimer.interval() + 80)

    assert widget.currentPage == 4
    assert fills == [4]
    assert widget.hotLiverTable.rowCount() == len(widget.hotLiverDict[4])
    assert widget.hotLiverTable.item(0, 0).text().startswith("增量主播")
    widget.shutdown()
    widget.deleteLater()


def test_add_room_window_close_only_hides(qapp, tmp_path, monkeypatch):
    import time
    from PySide6.QtTest import QTest

    def slow_run(worker):
        for _ in range(10):
            if worker.isInterruptionRequested():
                return
            worker.msleep(50)

    monkeypatch.setattr(liver_select.GetHotLiver, "run", slow_run)
    widget = _add_room_widget(tmp_path)
    widget.show()
    widget.getHotLiver.start()
    QTest.qWait(30)

    started = time.perf_counter()
    widget.close()
    qapp.processEvents()
    elapsed = time.perf_counter() - started

    assert widget.isHidden()
    assert not widget._shuttingDown
    assert widget.getHotLiver.isRunning()
    assert elapsed < 0.15
    widget.shutdown()
    widget.deleteLater()
