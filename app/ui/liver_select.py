"""
DD监控室主界面上方的控制条里的ScrollArea里面的卡片模块
包含主播开播/下播检测和刷新展示 置顶排序 录制管理等功能
"""

import json
import logging
import os
import re
import threading
import time
from bilibili_api import live_area, user, sync
from app.core.bili_credential import build_credential, normalize_credential_data
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QToolTip,
    QWidget,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDrag,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtCore import QBuffer, QIODevice, QMimeData, QRectF, Qt, QThread, QTimer, QUrl, Signal
from app.core import http_utils
from app.ui.common_widget import DownloadImage  # 公共图片下载线程
from qfluentwidgets_pro import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    FlowLayout,
    FluentIcon,
    LineEdit,
    PillPushButton,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    TableWidget,
    TabWidget,
)
from app.ui.title_bar import FluentWindow
from app.ui.uikit_bridge import current_color, info as uikit_info, theme_changed


header = http_utils.DEFAULT_HEADERS

# 全局提示框字体只需设置一次（CoverLabel 每次构造都调用属于无效开销）
QToolTip.setFont(QFont("微软雅黑", 16, QFont.Bold))


def _chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]


_ROOM_SEPARATOR_RE = re.compile(r"[\s,，;；]+")


def parse_room_ids(text):
    """解析、去重房号并保留输入顺序。"""
    room_ids = []
    seen = set()
    for token in _ROOM_SEPARATOR_RE.split(str(text or "").strip()):
        if token.isascii() and token.isdecimal() and token not in seen:
            room_ids.append(token)
            seen.add(token)
    return room_ids


def merge_room_id(text, room_id):
    """向输入文本追加完整房号，避免使用子串判断造成误判。"""
    room_ids = parse_room_ids(text)
    room_id = str(room_id or "").strip()
    if room_id.isascii() and room_id.isdecimal() and room_id not in room_ids:
        room_ids.append(room_id)
    return " ".join(room_ids)


class CircleImage(QWidget):
    """抗锯齿圆形头像。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self.circle_image = QPixmap()

    def set_image(self, image):
        self.circle_image = QPixmap(image)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        circle_rect = self.rect().adjusted(1, 1, -1, -1)
        if self.circle_image.isNull():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(current_color("bg.muted")))
            painter.drawEllipse(circle_rect)
            FluentIcon.PEOPLE.render(
                painter,
                QRectF(8, 8, 14, 14),
                fill=current_color("text.tertiary"),
            )
            return
        clip = QPainterPath()
        clip.addEllipse(circle_rect)
        painter.setClipPath(clip)
        pixmap = self.circle_image.scaled(
            self.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        x = (self.width() - pixmap.width()) // 2
        y = (self.height() - pixmap.height()) // 2
        painter.drawPixmap(x, y, pixmap)
        painter.setClipping(False)
        painter.setPen(QPen(QColor(current_color("border.strong")), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(circle_rect)


def _category_button(name, selected=False):
    """构造带业务选中标记的 Fluent 胶囊按钮。"""
    button = PillPushButton(name)
    button.pushToken = bool(selected)
    button.setChecked(button.pushToken)
    return button


class RecordThread(QThread):
    """获取直播推流并录制

    使用 bilibili_api.live.LiveRoom 获取流地址后下载到本地文件。
    """

    downloadTimer = Signal(str)
    downloadError = Signal(str)

    def __init__(self, roomID):
        super(RecordThread, self).__init__()
        import threading

        self._lock = threading.Lock()
        self.roomID = roomID
        self.recordToken = False
        self.downloadToken = False
        self.downloadTime = 0  # s
        self.checkTimer = QTimer(self)
        self.checkTimer.timeout.connect(self.checkDownlods)
        self.reconnectCount = 0
        self.credential = None
        self.sessionData = ""

    def setCredential(self, credential, sessionData=""):
        self.credential = credential
        self.sessionData = sessionData

    def checkDownlods(self):
        with self._lock:
            if self.downloadToken:
                self.downloadToken = False
                if not self.downloadTime % 60:  # 每分钟刷新一次
                    self.downloadTimer.emit("%dmin" % (self.downloadTime / 60))
                self.downloadTime += 3
            else:
                self.reconnectCount += 1
                if self.reconnectCount > 60:  # 60 x 3s = 180s重试 超时了就退出
                    self.downloadError.emit(self.roomID)

    def setSavePath(self, savePath):
        self.savePath = savePath

    def stopRecording(self):
        """安全停止录制（线程安全）"""
        with self._lock:
            self.recordToken = False

    def run(self):
        self.reconnectCount = 0
        try:
            from bilibili_api import live, sync
            from app.core.bili_credential import build_credential, normalize_credential_data

            cred_data = normalize_credential_data(self.credential, sessdata=self.sessionData)
            room = live.LiveRoom(int(self.roomID), credential=build_credential(cred_data, sessdata=self.sessionData))
            play_info = sync(room.get_room_play_url(screen_resolution=live.ScreenResolution.ORIGINAL))
            durl = play_info.get("durl", [])
            if not durl:
                raise RuntimeError("未获取到录制流地址")
            url = durl[0]["url"]
            download = http_utils.get(url, stream=True, headers=header)
            with self._lock:
                self.recordToken = True
            self.downloadTime = 0
            try:
                self.cacheVideo = open(self.savePath, "wb")
            except OSError:
                # 保存路径不可写/目录不存在：录制静默失败会误导用户（状态显示"录制中"）
                logging.exception("录制失败：无法写入保存路径 %s", self.savePath)
                self.downloadError.emit(self.roomID)
                return
            try:
                for chunk in download.iter_content(chunk_size=1024 * 1024):  # 1MB 分块，减少磁盘 IO 次数
                    with self._lock:
                        if not self.recordToken:
                            break
                    if chunk:
                        with self._lock:
                            self.downloadToken = True
                        self.cacheVideo.write(chunk)
            finally:
                self.cacheVideo.close()
        except Exception:
            logging.exception("下载视频到缓存失败")


class CoverLabel(CardWidget):
    """直播卡片：Fluent 圆角容器、封面与语义状态。"""

    addToWindow = Signal(list)
    deleteCover = Signal(str)
    changeTopToken = Signal(list)

    def __init__(self, roomID, topToken=False):
        super(CoverLabel, self).__init__()
        self.setAcceptDrops(True)
        self.roomID = roomID
        self.topToken = topToken
        self.isPlaying = False  # 正在播放
        self.title = "NA"  # 这里其实一开始设计的时候写错名字了 实际这里是用户名不是房间号 将错就错下去了
        self.roomTitle = ""  # 这里才是真的存放房间名的地方
        self.recordState = 0  # 0 无录制任务  1 录制中  2 等待开播录制
        self.savePath = ""
        self.setFixedSize(172, 124)
        self.setObjectName("cover")
        self.setBorderRadius(8)
        self.setClickEnabled(True)
        self._coverPixmap = QPixmap()
        self.firstUpdateToken = True

        # 封面与信息分层：上方 16:6.6 预览，下方头像/主播名/状态。
        # 小卡片不再把三类文字叠在图片上，任何封面亮度下都保持可读。
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(7, 7, 7, 7)
        self.layout.setSpacing(5)
        self.layout.addSpacing(66)
        footer = QHBoxLayout()
        footer.setContentsMargins(1, 0, 1, 0)
        footer.setSpacing(7)
        self.profile = CircleImage()
        footer.addWidget(self.profile, 0, Qt.AlignVCenter)
        details = QVBoxLayout()
        details.setContentsMargins(0, 0, 0, 0)
        details.setSpacing(1)
        self.titleLabel = BodyLabel("检测中")
        self.titleLabel.setFont(QFont("Microsoft YaHei UI", 9, QFont.DemiBold))
        self.titleLabel.setMaximumWidth(116)
        details.addWidget(self.titleLabel)
        self.stateLabel = CaptionLabel("检测中")
        self.stateLabel.setFont(QFont("Microsoft YaHei UI", 8, QFont.DemiBold))
        self.stateLabel.setMaximumWidth(116)
        details.addWidget(self.stateLabel, 0, Qt.AlignLeft)
        footer.addLayout(details, 1)
        self.layout.addLayout(footer)
        self.liveState = 0  # 0 未开播  1 直播中  2 投稿视频   -1 错误
        self._stateColorToken = "text.secondary"
        self._stateBackgroundToken = "bg.muted"
        self.downloadFace = DownloadImage(60, 60)
        self.downloadFace.img.connect(self.updateProfile)
        self.downloadKeyFrame = DownloadImage(160, 90, True)
        self.downloadKeyFrame.img.connect(self.updateKeyFrame)
        self.downloadKeyFrame.img_origin.connect(self.setToolTipKeyFrame)
        self._lastKeyframeUrl = ""

        self.recordThread = RecordThread(roomID)
        self.recordThread.downloadTimer.connect(self.refreshStateLabel)
        self.recordThread.downloadError.connect(self.recordError)

        self._applyTheme()
        theme_changed().connect(self._applyTheme)

    def _setTitleText(self, text):
        text = str(text or "未知主播")
        self.titleLabel.setText(self.titleLabel.fontMetrics().elidedText(text, Qt.ElideRight, 116))

    def _setState(self, text, color_token, background_token):
        self.stateLabel.setText(text)
        self._stateColorToken = color_token
        self._stateBackgroundToken = background_token
        self._applyTheme()

    def _applyTheme(self, *args):
        self.titleLabel.setStyleSheet(
            f"color:{current_color('text.primary')};background:transparent;"
        )
        self.stateLabel.setStyleSheet(
            f"color:{current_color(self._stateColorToken)};"
            f"background-color:{current_color(self._stateBackgroundToken)};"
            "border-radius:4px;padding:1px 5px;"
        )
        self.update()

    def updateLabel(self, info):
        if not info[0]:  # 用户或直播间不存在
            self.liveState = -1
            self.roomTitle = ""
            self.setToolTip(self.roomTitle)
            if info[2]:
                self._setTitleText(info[2])
                self._setState("房间可能被封", "danger", "danger.subtle")
            else:
                self._setTitleText(info[1])
                self._setState("房间不可用", "danger", "danger.subtle")
        else:
            if self.firstUpdateToken:  # 初始化
                avatar_url = str(info[3] or "").strip()
                if avatar_url:
                    self.firstUpdateToken = False  # 仅在头像有效时消费首次标记，URL 为空则下次刷新重试
                    self.downloadFace.setUrl(avatar_url)  # 启动下载头像线程
                    if not self.downloadFace.isRunning():
                        self.downloadFace.start()
                # self.roomIDLabel.setText(info[1])  # 房间号
                self._setTitleText(info[2])  # 名字
                self.title = info[2]
            if info[4] == 1:  # 直播中
                self.liveState = 1
                keyframe_url = str((info[5] if len(info) > 5 else "") or "").strip()
                if not keyframe_url and len(info) > 7:
                    keyframe_url = str(info[7] or "").strip()
                if keyframe_url and keyframe_url != self._lastKeyframeUrl:
                    self._lastKeyframeUrl = keyframe_url
                    self.downloadKeyFrame.setUrl(keyframe_url)  # 启动下载关键帧线程
                    if not self.downloadKeyFrame.isRunning():
                        self.downloadKeyFrame.start()
                self.roomTitle = info[6]  # 房间直播标题
                # self.setToolTip(self.roomTitle)  # 改用self.setToolTipKeyFrame里面设置tooltip
            else:  # 未开播
                self.liveState = 0
                self._lastKeyframeUrl = ""
                self.roomTitle = ""  # 房间直播标题
                self.setToolTip(self.roomTitle)
                self.clear()
            self.refreshStateLabel()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        preview_rect = QRectF(7, 7, self.width() - 14, 66)
        preview_path = QPainterPath()
        preview_path.addRoundedRect(preview_rect, 6, 6)
        painter.setClipPath(preview_path)
        painter.fillRect(preview_rect, QColor(current_color("bg.muted")))
        if not self._coverPixmap.isNull():
            target_size = preview_rect.size().toSize()
            cover = self._coverPixmap.scaled(
                target_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = int(preview_rect.x() + (preview_rect.width() - cover.width()) / 2)
            y = int(preview_rect.y() + (preview_rect.height() - cover.height()) / 2)
            painter.drawPixmap(x, y, cover)
        else:
            icon_rect = QRectF(
                preview_rect.center().x() - 10,
                preview_rect.center().y() - 10,
                20,
                20,
            )
            FluentIcon.VIDEO.render(
                painter,
                icon_rect,
                fill=current_color("text.tertiary"),
            )
        painter.setClipping(False)

        border_color = current_color("border")
        border_width = 1
        if self.isPlaying:
            border_color = current_color("primary")
            border_width = 2
        elif self.topToken:
            border_color = current_color("warning")
            border_width = 2
        painter.setPen(QPen(QColor(border_color), border_width))
        painter.setBrush(Qt.NoBrush)
        inset = 1 if border_width == 1 else 2
        painter.drawRoundedRect(self.rect().adjusted(inset, inset, -inset, -inset), 8, 8)

    def clear(self):
        self._coverPixmap = QPixmap()
        self._applyTheme()

    def setPixmap(self, pixmap):
        self._coverPixmap = QPixmap(pixmap)
        self._applyTheme()

    def refreshStateLabel(self, downloadTime=""):
        if self.liveState == 1:
            if self.recordState == 1:
                text = f"录制中 {downloadTime}" if downloadTime else "录制中"
                self._setState(text, "primary", "primary.subtle")
            else:
                self._setState("直播中", "success", "success.subtle")
        elif self.recordState == 2:
            self._setState("等待开播", "warning", "warning.subtle")
        else:
            self._setState("未开播", "text.secondary", "bg.muted")

    def recordError(self, roomID):
        self.recordThread.checkTimer.stop()
        self.refreshStateLabel()
        uikit_info(self, "录制中止", "%s %s 录制结束 请检查网络或主播是否掉线" % (self.title, roomID), level="error")

    def updateProfile(self, img):
        if not img.isNull():
            self.profile.set_image(img)

    def updateKeyFrame(self, img):
        if not img.isNull():
            self.setPixmap(img)

    def setToolTipKeyFrame(self, img):
        if img.isNull():
            return
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        img.save(buffer, "PNG", quality=100)
        image = bytes(buffer.data().toBase64()).decode()
        html = '<img src="data:image/png;base64,{}">'.format(image)
        self.setToolTip('<div style="text-align:center">%s</div><br>%s<br/>' % (self.roomTitle.strip(), html))

    def dragEnterEvent(self, QDragEnterEvent):
        QDragEnterEvent.acceptProposedAction()

    def mousePressEvent(self, QMouseEvent):  # 设置drag事件 发送拖动封面的房间号
        if QMouseEvent.button() == Qt.LeftButton:
            drag = QDrag(self)
            mimeData = QMimeData()
            mimeData.setText("roomID:%s" % self.roomID)
            drag.setMimeData(mimeData)
            drag.exec()
        elif QMouseEvent.button() == Qt.RightButton:
            # RoundMenu.exec 是非阻塞的（只显示菜单立即返回），不能用
            # exec 返回值判断选择；菜单项通过 triggered 信号处理
            menu = RoundMenu()
            addTo = menu.addMenu("添加至窗口 ►")
            for win in range(1, 10):
                act = addTo.addAction("窗口%s" % win)
                act.triggered.connect(lambda checked=False, w=win: self.addToWindow.emit([w - 1, self.roomID]))
            top = menu.addAction("取消置顶" if self.topToken else "添加置顶")
            top.triggered.connect(self._toggleTop)
            record = menu.addAction(self._recordActionText())
            record.triggered.connect(self._toggleRecord)
            openBrowser = menu.addAction("打开直播间")
            openBrowser.triggered.connect(
                lambda: QDesktopServices.openUrl(QUrl(r"https://live.bilibili.com/%s" % self.roomID))
                if self.roomID != "0"
                else None
            )
            copyRoomID = menu.addAction("复制房号 %s" % self.roomID)
            copyRoomID.triggered.connect(lambda: QApplication.clipboard().setText(self.roomID))
            menu.addSeparator()  # 添加分割线，防止误操作
            delete = menu.addAction("删除")
            delete.triggered.connect(self._deleteSelf)
            menu.exec(self.mapToGlobal(QMouseEvent.position().toPoint()))

    def _recordActionText(self):
        """录制菜单项的文案（按当前录制/直播状态）"""
        if self.recordState == 0:  # 无录制任务
            if self.liveState == 1:
                return "录制(最高画质)"
            if self.liveState in [0, 2]:  # 未开播或轮播
                return "开播自动录制"
        return "取消录制"

    def _toggleTop(self):
        """切换置顶状态"""
        self.topToken = not self.topToken
        self.changeTopToken.emit([self.roomID, self.topToken])  # 发送修改后的置顶token
        self._applyTheme()

    def _deleteSelf(self):
        """右键菜单"删除"：从面板移除卡片"""
        self.deleteCover.emit(self.roomID)
        self.roomID = "0"
        self.hide()

    def _toggleRecord(self):
        """录制状态机：开始录制 / 取消录制 / 等待录制"""
        if self.roomID == "0":
            return
        if self.recordState == 0:  # 无录制任务
            saveName = "%s_%s_%s" % (
                self.title,
                self.roomTitle,
                time.strftime("%Y-%m-%d-%H-%M-%S", time.localtime(time.time())),
            )
            self.savePath = QFileDialog.getSaveFileName(self, "选择保存路径", saveName, "*.flv")[0]
            if self.savePath:  # 保存路径有效
                if self.liveState == 1:  # 直播中
                    self.recordThread.setSavePath(self.savePath)
                    lp = getattr(self, "_liverPanel", None)
                    if lp is not None:
                        self.recordThread.setCredential(
                            getattr(lp, "_credential", None), getattr(lp, "_sessionData", "")
                        )
                    self.recordThread.start()
                    self.recordThread.checkTimer.start(3000)
                    self.recordState = 1  # 改为录制状态
                    self.refreshStateLabel("0min")
                elif self.liveState in [0, 2]:  # 未开播或轮播中
                    self.recordState = 2  # 改为等待录制状态
                    self.refreshStateLabel()
        elif self.recordState == 1:  # 录制中→取消录制
            self.recordState = 0  # 取消录制
            self.recordThread.checkTimer.stop()
            self.recordThread.stopRecording()  # 设置录像线程标志位让它自行退出结束
            self.refreshStateLabel()
        elif self.recordState == 2:  # 等待录制→取消录制
            self.recordState = 0  # 取消录制
            self.recordThread.checkTimer.stop()
            self.refreshStateLabel()


class GetHotLiver(QThread):
    """获取热门直播列表"""

    roomInfoSummary = Signal(list)
    areaLoaded = Signal(int, list)

    def __init__(self):
        super(GetHotLiver, self).__init__()
        self.credential = {}
        self._prefer_bili_api = True
        self._bili_api_disabled_logged = False

    def setCredential(self, credential):
        self.credential = normalize_credential_data(credential)

    def _fetch_area_page(self, area, page):
        fallback_requests = [
            (
                "https://api.live.bilibili.com/room/v3/area/getRoomList",
                {
                    "platform": "web",
                    "parent_area_id": area,
                    "area_id": 0,
                    "page": page,
                    "sort_type": "online",
                },
            ),
            (
                "https://api.live.bilibili.com/room/v1/Area/getListByAreaID",
                {
                    "areaId": area,
                    "page": page,
                    "sort": "online",
                },
            ),
        ]
        if self._prefer_bili_api:
            try:
                return sync(
                    live_area.get_list_by_area(
                        area,
                        page=page,
                        order="online",
                        credential=build_credential(self.credential),
                    )
                )
            except Exception as e:
                message = str(e)
                if "-352" in message or "fetch_live_area_data" in message:
                    self._prefer_bili_api = False
                    if not self._bili_api_disabled_logged:
                        logging.warning("热门列表切换到 HTTP fallback（bilibili-api 触发 -352 或分区数据缺失）")
                        self._bili_api_disabled_logged = True
                else:
                    logging.warning(f"热门列表 area={area} page={page} bilibili-api 查询失败: {e}")

        for api_url, params in fallback_requests:
            try:
                response = http_utils.get(api_url, params=params, headers=header)
                payload = response.json()
                if payload.get("code") != 0:
                    logging.warning(
                        f"热门列表 area={area} page={page} fallback 失败: {api_url} "
                        f"code={payload.get('code')} message={payload.get('message')}"
                    )
                    continue

                data = payload.get("data")
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    return {"list": data}
            except Exception as fallback_error:
                logging.warning(f"热门列表 area={area} page={page} fallback 异常: {api_url}, err={fallback_error}")
                continue

        return {"list": []}

    def run(self):
        roomInfoSummary = []
        try:
            try:
                sync(live_area.fetch_live_area_data())
            except Exception:
                logging.exception("热门分区数据预加载失败，继续使用旧缓存")
            for page_index, area in enumerate([9, 2, 3, 6, 1]):
                if self.isInterruptionRequested():
                    return
                pageSummary = []
                for page in range(1, 6):
                    if self.isInterruptionRequested():
                        return
                    data = self._fetch_area_page(area, page)
                    room_list = (data or {}).get("list", [])
                    if not room_list:
                        break
                    for info in room_list:
                        pageSummary.append(
                            [
                                info.get("uname", ""),
                                info.get("title", ""),
                                str(info.get("roomid", "")),
                            ]
                        )
                    if self.isInterruptionRequested():
                        return
                    self.areaLoaded.emit(page_index, list(pageSummary))
                    self.msleep(100)
                roomInfoSummary.append(pageSummary)
        except Exception:
            logging.exception("热门列表加载失败")
        if not self.isInterruptionRequested():
            self.roomInfoSummary.emit(roomInfoSummary)


class GetFollows(QThread):
    """获取关注列表
    需要 cookie (SESSDATA) 才能正常工作
    """

    roomInfoSummary = Signal(list)
    roomInfoChunk = Signal(list)

    def __init__(self):
        super(GetFollows, self).__init__()
        self.uid = None
        self.sessionData = ""
        self.credential = {}

    def setUID(self, uid):
        self.uid = uid

    def setSessionData(self, sessionData):
        self.sessionData = sessionData if sessionData else ""

    def setCredential(self, credential):
        self.credential = normalize_credential_data(credential, sessdata=self.sessionData)

    @staticmethod
    def _extract_follow_ids(follow_list):
        followsIDs = set()
        for info in follow_list:
            if isinstance(info, int):
                followsIDs.add(info)
            elif isinstance(info, dict):
                mid = info.get("mid") or info.get("uid") or info.get("mid_str")
                if mid:
                    try:
                        followsIDs.add(int(mid))
                    except (TypeError, ValueError):
                        continue
        return followsIDs

    @staticmethod
    def _build_room_rows(followsIDs, room_map):
        room_rows = []
        for followID in followsIDs:
            info = room_map.get(str(followID))
            if not info:
                continue
            room_rows.append(
                [
                    info.get("uname", ""),
                    info.get("title", ""),
                    str(info.get("room_id", "")),
                    info.get("live_status", 0),
                ]
            )
        return room_rows

    def run(self):
        if not self.uid:
            self.roomInfoSummary.emit([])
            return
        followsIDs = set()
        roomIDList = []
        network_error = None
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://space.bilibili.com/",
        }
        cookies = {}
        if self.sessionData:
            cookies["SESSDATA"] = self.sessionData
        try:
            follow_list = sync(
                user.User(
                    int(self.uid), credential=build_credential(self.credential, sessdata=self.sessionData)
                ).get_all_followings()
            )
            followsIDs = self._extract_follow_ids(follow_list)
        except Exception as e:
            network_error = e
            logging.exception("通过 bilibili-api-python 获取关注列表失败，回退至 HTTP API")
            try:
                for p in range(1, 11):
                    if self.isInterruptionRequested():
                        return
                    url = f"https://api.bilibili.com/x/relation/followings?vmid={self.uid}&pn={p}&ps=50&order=desc"
                    r = http_utils.get(url, headers=req_headers, cookies=cookies)
                    resp_data = r.json()
                    if resp_data.get("code") != 0:
                        logging.warning(f"关注列表获取失败: {resp_data.get('message', '未知错误')}")
                        break
                    followList = (resp_data.get("data") or {}).get("list") or []
                    if not followList:
                        break
                    followsIDs.update(self._extract_follow_ids(followList))
                    self.msleep(200)
            except Exception as e2:
                network_error = e2
                logging.exception("关注列表添加失败")

        followsIDs = list(followsIDs)
        if not followsIDs:
            if network_error is not None:
                # 请求确实失败（网络/接口错误）才算异常
                logging.error(f"获取关注列表失败（网络错误: {network_error}）— 请检查网络或代理设置")
            else:
                # 请求成功但关注数为 0（新号/取消全部关注），属正常情况
                logging.info("关注列表为空（当前账号未关注任何主播）")
            self.roomInfoSummary.emit([])
            return

        for chunk in _chunked(followsIDs, 100):
            if self.isInterruptionRequested():
                return
            try:
                response = http_utils.post(
                    "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                    data=json.dumps({"uids": chunk}),
                    headers=header,
                    cookies=cookies,
                )
                response.encoding = "utf8"
                payload = json.loads(response.text)
                if payload.get("code") != 0:
                    logging.warning(f"直播状态查询失败: {payload.get('message', '未知错误')}")
                    continue
                room_chunk = self._build_room_rows(chunk, payload.get("data", {}))
                if room_chunk:
                    roomIDList.extend(room_chunk)
                    self.roomInfoChunk.emit(room_chunk)
            except Exception:
                logging.exception("直播间状态查询失败")
            self.msleep(100)
        if not self.isInterruptionRequested():
            self.roomInfoSummary.emit(roomIDList)


class DownloadVTBList(QThread):
    """更新 VTB 信息"""

    vtbList = Signal(list)

    def __init__(self, parent=None):
        super(DownloadVTBList, self).__init__(parent)

    def run(self):
        vtbList = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Safari/537.36"
            }
            r = http_utils.get(
                r"https://raw.githubusercontent.com/BaoZiFly-233/DD_Monitor/master/resources/vtb.csv", headers=headers
            )
            # raw URL 返回纯 CSV 文本（每行: 主播名,房号,所属），
            # 旧解析按 blob 页面 HTML 行号标记 split(">")，对 raw 内容永不命中 -> 名单恒空
            for line in r.text.split("\n"):
                if self.isInterruptionRequested():
                    return
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                if len(parts) >= 3 and parts[1].isdigit():
                    vtbList.append("%s,%s,%s\n" % (parts[0], parts[1], parts[2]))
        except Exception:
            logging.exception("vtbs 列表获取失败")
        # 无论成功失败都发射信号：空列表让 UI 走"更新失败"并恢复按钮，
        # 避免信号永不发射导致"更新中..."按钮永久卡死且 clicked 断开
        if not self.isInterruptionRequested():
            self.vtbList.emit(vtbList)


class HotLiverTable(TableWidget):
    """关注列表"""

    addToWindow = Signal(list)

    def __init__(self):
        super().__init__()

    def contextMenuEvent(self, event):
        # RoundMenu.exec 非阻塞，菜单项通过 triggered 信号处理
        menu = RoundMenu(self)
        addTo = menu.addMenu("添加至窗口 ►")
        for win in range(1, 10):
            act = addTo.addAction("窗口%s" % win)
            act.triggered.connect(lambda checked=False, w=win, m=self: self._addHotLiverToWindow(w))
        menu.exec(self.mapToGlobal(event.pos()))

    def _addHotLiverToWindow(self, win):
        """热门直播表格右键：把当前行房号加入指定窗口"""
        try:
            item = self.item(self.currentRow(), 2)
            text = item.text() if item is not None else ""
        except Exception:
            text = ""
        self.addToWindow.emit([win - 1, text])


class AddLiverRoomWidget(FluentWindow):
    """添加直播间 - Fluent 独立窗口。"""

    roomList = Signal(dict)

    def __init__(self, application_path):
        super().__init__(title="添加直播间")
        self.application_path = application_path
        self.resize(680, 760)
        self.setMinimumSize(560, 520)
        self.hotLiverDict = {0: [], 1: [], 2: [], 3: [], 4: [], 5: []}
        self.followLiverList = []
        self.followRoomInfo = []
        layout = QGridLayout(self)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(12)
        self.roomEdit = LineEdit()
        self.roomEdit.setClearButtonEnabled(True)
        self.roomEdit.setPlaceholderText("输入直播间房号，多个房号用空格分隔")
        self.roomEdit.returnPressed.connect(self.sendSelectedRoom)
        layout.addWidget(self.roomEdit, 0, 0, 1, 4)
        confirm = PrimaryPushButton(FluentIcon.ADD, "添加")
        confirm.setFixedHeight(32)
        confirm.clicked.connect(self.sendSelectedRoom)
        layout.addWidget(confirm, 0, 4, 1, 1)

        self.tabWidget = TabWidget()
        self.tabWidget.setMovable(False)
        self.tabWidget.tabBar.setTabsClosable(False)
        self.tabWidget.tabBar.setAddButtonVisible(False)
        self.tabWidget.currentChanged.connect(self._onTabChanged)
        layout.addWidget(self.tabWidget, 1, 0, 5, 5)

        hotLiverPage = QWidget()
        hotLiverLayout = QGridLayout(hotLiverPage)
        hotLiverLayout.setContentsMargins(1, 1, 1, 1)

        self.virtual = _category_button("虚拟主播", True)
        self.virtual.clicked.connect(lambda: self.switchHotLiver(0))
        hotLiverLayout.addWidget(self.virtual, 0, 0, 1, 1)
        self.onlineGame = _category_button("网游")
        self.onlineGame.clicked.connect(lambda: self.switchHotLiver(1))
        hotLiverLayout.addWidget(self.onlineGame, 0, 1, 1, 1)
        self.mobileGame = _category_button("手游")
        self.mobileGame.clicked.connect(lambda: self.switchHotLiver(2))
        hotLiverLayout.addWidget(self.mobileGame, 0, 2, 1, 1)
        self.consoleGame = _category_button("单机")
        self.consoleGame.clicked.connect(lambda: self.switchHotLiver(3))
        hotLiverLayout.addWidget(self.consoleGame, 0, 3, 1, 1)
        self.entertainment = _category_button("娱乐")
        self.entertainment.clicked.connect(lambda: self.switchHotLiver(4))
        hotLiverLayout.addWidget(self.entertainment, 0, 4, 1, 1)
        self.buttonList = [self.virtual, self.onlineGame, self.mobileGame, self.consoleGame, self.entertainment]
        self.currentPage = 0
        self._shuttingDown = False
        self._hotRefreshTimer = QTimer(self)
        self._hotRefreshTimer.setSingleShot(True)
        self._hotRefreshTimer.setInterval(35)
        self._hotRefreshTimer.timeout.connect(self._flushHotLiverTable)
        self._followRefreshTimer = QTimer(self)
        self._followRefreshTimer.setSingleShot(True)
        self._followRefreshTimer.setInterval(35)
        self._followRefreshTimer.timeout.connect(self._flushFollowTable)

        self.progressBar = ProgressBar()
        self.progressBar.setRange(0, 0)
        self.progressBar.hide()
        hotLiverLayout.addWidget(self.progressBar, 1, 0, 1, 5)
        self.hotStatusLabel = CaptionLabel("暂无直播数据")
        hotLiverLayout.addWidget(self.hotStatusLabel, 2, 0, 1, 5)

        self.hotLiverTable = HotLiverTable()
        self.hotLiverTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hotLiverTable.verticalScrollBar().installEventFilter(self)
        self.hotLiverTable.verticalHeader().sectionClicked.connect(self.hotLiverAdd)
        self.hotLiverTable.setColumnCount(3)
        self.hotLiverTable.setRowCount(0)
        self.hotLiverTable.verticalHeader().setDefaultSectionSize(40)
        self.hotLiverTable.setHorizontalHeaderLabels(["主播名", "直播间标题", "直播间房号"])
        self.hotLiverTable.horizontalHeader().setStretchLastSection(True)
        self.hotLiverTable.setColumnWidth(0, 150)
        self.hotLiverTable.setColumnWidth(1, 300)
        self.hotLiverTable.setEnabled(False)
        hotLiverLayout.addWidget(self.hotLiverTable, 3, 0, 1, 5)
        self.getHotLiver = GetHotLiver()
        self.getHotLiver.roomInfoSummary.connect(self.collectHotLiverInfo)
        self.getHotLiver.areaLoaded.connect(self.collectHotLiverChunk)
        self.getHotLiver.finished.connect(self._onHotLiverFinished)

        followsPage = QWidget()
        followsLayout = QGridLayout(followsPage)
        followsLayout.setContentsMargins(0, 0, 0, 0)
        self.uidEdit = LineEdit()
        self.uidEdit.setPlaceholderText("用户 UID")
        self.uidEdit.setMinimumWidth(120)
        self.uidEdit.setMaximumWidth(300)
        followsLayout.addWidget(self.uidEdit, 0, 0, 1, 1)
        uidCheckButton = PrimaryPushButton(FluentIcon.SEARCH, "查询")
        uidCheckButton.setFixedHeight(28)
        uidCheckButton.clicked.connect(self.checkFollows)  # 查询关注
        followsLayout.addWidget(uidCheckButton, 0, 1, 1, 1)
        self.followsTable = TableWidget()
        self.followsTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.followsTable.verticalScrollBar().installEventFilter(self)
        self.followsTable.verticalHeader().sectionClicked.connect(self.followLiverAdd)
        self.followsTable.setColumnCount(3)
        self.followsTable.setRowCount(0)
        self.followsTable.verticalHeader().setDefaultSectionSize(40)
        self.followsTable.setHorizontalHeaderLabels(["主播名", "直播间标题", "直播间房号"])
        self.followsTable.horizontalHeader().setStretchLastSection(True)
        self.followsTable.setColumnWidth(0, 150)
        self.followsTable.setColumnWidth(1, 300)
        followsLayout.addWidget(self.followsTable, 1, 0, 6, 6)
        self.getFollows = GetFollows()
        self.getFollows.roomInfoSummary.connect(self.collectFollowLiverInfo)
        self.getFollows.roomInfoChunk.connect(self.collectFollowLiverChunk)

        hacoPage = QWidget()  # 添加内置的vtb列表
        hacoLayout = QGridLayout(hacoPage)
        hacoLayout.setContentsMargins(1, 1, 1, 1)
        self.refreshButton = PushButton(FluentIcon.UPDATE, "更新名单")
        self.refreshButton.clicked.connect(self.refreshHacoList)
        hacoLayout.addWidget(self.refreshButton, 0, 0, 1, 1)
        self.vtbSearchButton = PushButton(FluentIcon.SEARCH, "查询 VUP")
        self.vtbSearchButton.clicked.connect(self.vtbSearch)
        hacoLayout.addWidget(self.vtbSearchButton, 0, 1, 1, 1)
        self.hacoTable = TableWidget()
        self.hacoTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hacoTable.verticalScrollBar().installEventFilter(self)
        self.hacoTable.verticalHeader().sectionClicked.connect(self.hacoAdd)
        self.hacoTable.setColumnCount(3)
        try:
            self.vtbList = []
            with open(os.path.join(self.application_path, "resources/vtb.csv"), "r", encoding="utf-8") as vtbs:
                for line in vtbs:
                    line = line.strip()
                    if line:
                        parts = line.split(",")
                        # 防御：少于 3 列的行补空列，避免 line[x] IndexError 导致整表加载失败
                        while len(parts) < 3:
                            parts.append("")
                        self.vtbList.append(parts[:3])
                    else:
                        self.vtbList.append(["", "", ""])
            self.hacoTable.setRowCount(len(self.vtbList))
            self.hacoTable.verticalHeader().setDefaultSectionSize(40)
            self.hacoTable.setVerticalHeaderLabels(["+"] * len(self.vtbList))
            for y, line in enumerate(self.vtbList):
                for x in range(3):
                    self.hacoTable.setItem(y, x, QTableWidgetItem(line[x]))
        except Exception:
            logging.exception("vtb.csv 解析失败")

        self.hacoTable.setHorizontalHeaderLabels(["主播名", "直播间房号", "所属"])
        self.hacoTable.setColumnWidth(0, 160)
        self.hacoTable.setColumnWidth(1, 160)
        self.hacoTable.setColumnWidth(2, 160)
        hacoLayout.addWidget(self.hacoTable, 1, 0, 10, 5)
        self.downloadVTBList = DownloadVTBList()
        self.downloadVTBList.vtbList.connect(self.collectVTBList)
        # self.downloadVTBList.start()

        self.tabWidget.addTab(hotLiverPage, "正在直播")
        self.tabWidget.addTab(hacoPage, "个人势/箱")
        self.tabWidget.addTab(followsPage, "关注添加")

    def closeEvent(self, event):
        # 工具窗口普通关闭只隐藏；网络线程继续安全收尾，避免 GUI 线程卡 2-6 秒。
        if not self._shuttingDown:
            event.ignore()
            self.hide()
            return
        event.accept()

    def shutdown(self):
        """应用退出时请求后台任务停止并等待；普通关闭不调用。"""
        self._shuttingDown = True
        self._hotRefreshTimer.stop()
        self._followRefreshTimer.stop()
        workers = (self.getHotLiver, self.getFollows, self.downloadVTBList)
        for worker in workers:
            if worker.isRunning():
                worker.requestInterruption()
        for worker in workers:
            if worker.isRunning():
                worker.wait(3000)
        self.hide()

    def _scheduleHotLiverTable(self):
        if not self._shuttingDown:
            self._hotRefreshTimer.start()

    def _flushHotLiverTable(self):
        if not self._shuttingDown and self.isVisible() and self.tabWidget.currentIndex() == 0:
            self._fillHotLiverTable(self.currentPage)

    def _scheduleFollowTable(self):
        if not self._shuttingDown:
            self._followRefreshTimer.start()

    def _flushFollowTable(self):
        if not self._shuttingDown and self.isVisible() and self.tabWidget.currentIndex() == 2:
            self._fillFollowTable()

    def collectHotLiverChunk(self, page, hotLiverList):
        self.hotLiverDict[page] = hotLiverList
        if self.tabWidget.currentIndex() == 0 and self.currentPage == page:
            self.hotLiverTable.setEnabled(True)
            self._scheduleHotLiverTable()

    def collectHotLiverInfo(self, info):
        self.hotLiverDict = {}
        self.progressBar.hide()
        self.hotLiverTable.setEnabled(True)
        for page, hotLiverList in enumerate(info):
            self.hotLiverDict[page] = hotLiverList
        if self.tabWidget.currentIndex() == 0:
            self._scheduleHotLiverTable()

    def _onHotLiverFinished(self):
        self.progressBar.hide()
        self.hotLiverTable.setEnabled(True)
        if self.tabWidget.currentIndex() == 0:
            self._scheduleHotLiverTable()

    def _onTabChanged(self, index):
        if index == 0:
            self._scheduleHotLiverTable()
        elif index == 2:
            self._scheduleFollowTable()

    def switchHotLiver(self, index):
        if not self.buttonList[index].pushToken:
            self.currentPage = index
            for count, button in enumerate(self.buttonList):
                button.pushToken = count == index
                button.setChecked(button.pushToken)
            self._scheduleHotLiverTable()

    def _fillHotLiverTable(self, index):
        """按实际数据行数填充热门直播表，避免预建空白行。"""
        hotLiverList = self.hotLiverDict.get(index, [])
        row_count = len(hotLiverList)
        self.hotLiverTable.setUpdatesEnabled(False)
        try:
            self.hotLiverTable.clearContents()
            self.hotLiverTable.setRowCount(row_count)
            if row_count:
                self.hotLiverTable.setVerticalHeaderLabels(["+"] * row_count)
            for row, line in enumerate(hotLiverList):
                for column, text in enumerate(line[:3]):
                    self.hotLiverTable.setItem(row, column, QTableWidgetItem(str(text)))
        finally:
            self.hotLiverTable.setUpdatesEnabled(True)
        self.hotStatusLabel.setVisible(not hotLiverList)
        if not hotLiverList:
            self.hotStatusLabel.setText("正在加载直播列表..." if self.getHotLiver.isRunning() else "当前分类暂无直播")

    def refreshHacoList(self):
        if self.refreshButton.text() == "更新中...":
            return
        self.refreshButton.clicked.disconnect(self.refreshHacoList)
        self.refreshButton.setText("更新中...")
        self.downloadVTBList.start()

    def vtbSearch(self):
        QDesktopServices.openUrl(QUrl(r"https://vtbs.moe/detail"))

    def collectVTBList(self, vtbList):
        try:
            if not vtbList:
                uikit_info(self, "更新VUP名单", "更新失败 请检查网络", level="error")
                return
            with open(os.path.join(self.application_path, "resources/vtb.csv"), "w", encoding="utf-8") as vtbs:
                for line in vtbList:
                    vtbs.write(line)
            self.vtbList = []
            for line in vtbList:
                self.vtbList.append(line.split(","))
            self.hacoTable.clear()
            self.hacoTable.setRowCount(len(self.vtbList))
            self.hacoTable.setVerticalHeaderLabels(["+"] * len(self.vtbList))
            self.hacoTable.setHorizontalHeaderLabels(["主播名", "直播间房号", "所属"])
            for y, line in enumerate(self.vtbList):
                for x in range(3):
                    self.hacoTable.setItem(y, x, QTableWidgetItem(line[x]))
            uikit_info(self, "更新VUP名单", "更新完成", level="success")
        except Exception:
            logging.exception("vtb.csv 写入失败")
            uikit_info(self, "更新VUP名单", "更新失败 请检查网络", level="error")
        finally:
            # 恢复按钮状态与连接（无论成功/失败/空名单）
            self.refreshButton.setText("更新名单")
            self.refreshButton.clicked.connect(self.refreshHacoList)

    def sendSelectedRoom(self):
        room_list = {room_id: False for room_id in parse_room_ids(self.roomEdit.text())}
        self.roomList.emit(room_list)
        self.roomEdit.clear()
        self.hide()

    def _appendRoomID(self, room_id):
        merged_text = merge_room_id(self.roomEdit.text(), room_id)
        if merged_text != self.roomEdit.text().strip():
            self.roomEdit.setText(merged_text)

    def hotLiverAdd(self, row):
        try:
            self._appendRoomID(self.hotLiverDict[self.currentPage][row][2])
        except (IndexError, KeyError, TypeError):
            logging.exception("热门主播添加失败")

    def hacoAdd(self, row):
        try:
            self._appendRoomID(self.vtbList[row][1])
        except (IndexError, TypeError):
            logging.exception("hacoAdd 失败")

    def setSessionData(self, sessionData):
        """接收登录凭据，传递给 GetFollows"""
        self.sessionData = sessionData if sessionData else ""
        self.credential = normalize_credential_data(getattr(self, "credential", {}), sessdata=self.sessionData)
        self.getFollows.setSessionData(self.sessionData)
        self.getFollows.setCredential(self.credential)
        self.getHotLiver.setCredential(self.credential)

    def setCredential(self, credential):
        self.credential = normalize_credential_data(credential, sessdata=getattr(self, "sessionData", ""))
        self.getHotLiver.setCredential(self.credential)
        self.getFollows.setCredential(self.credential)

    def checkFollows(self):
        if self.uidEdit.text().isdigit():
            if self.getFollows.isRunning():
                logging.warning("关注列表查询正在进行中，请稍候")
                return
            self.followRoomInfo = []
            self.followLiverList = []
            self._fillFollowTable()
            self.getFollows.setUID(self.uidEdit.text())
            self.getFollows.setSessionData(getattr(self, "sessionData", ""))
            self.getFollows.setCredential(getattr(self, "credential", {}))
            self.getFollows.start()

    def collectFollowLiverChunk(self, info):
        if not info:
            return
        self.followRoomInfo.extend(info)
        if self.tabWidget.currentIndex() == 2:
            self._scheduleFollowTable()

    def _fillFollowTable(self):
        """填充关注表格。

        setRowCount 与 setRowHeight 均按实际数据行数（最少 30 行兜底），
        避免旧实现固定 500 行导致 chunk 分批到达时反复全量重建（性能优化）。
        """
        sorted_info = sorted(self.followRoomInfo, key=lambda x: x[3] if len(x) > 3 else 0, reverse=True)
        self.followLiverList = []
        row_count = len(sorted_info)
        self.followsTable.setUpdatesEnabled(False)
        self.followsTable.clearContents()
        self.followsTable.setRowCount(row_count)
        if row_count:
            self.followsTable.setVerticalHeaderLabels(["+"] * row_count)
        for y, line in enumerate(sorted_info):
            room_id = str(line[2]) if len(line) > 2 else ""
            self.followLiverList.append(room_id)
            live_status = line[3] if len(line) > 3 else 0
            for x in range(min(3, len(line))):
                try:
                    item = QTableWidgetItem(str(line[x]))
                    if live_status == 1:
                        item.setForeground(QColor("#7FFFD4"))
                        if x == 0:
                            item.setText("● " + str(line[x]))
                    self.followsTable.setItem(y, x, item)
                except Exception:
                    logging.exception("关注列表添加失败")
        self.followsTable.setUpdatesEnabled(True)

    def collectFollowLiverInfo(self, info):
        self.followRoomInfo = list(info)
        self._scheduleFollowTable()

    def followLiverAdd(self, row):
        try:
            self._appendRoomID(self.followLiverList[row])
        except IndexError:
            logging.exception("关注列表添加失败")


class CollectLiverInfo(QThread):
    """批量获取直播间信息
    + 直播状态 'live_status'
    + 标题 'title'
    + 封面 'cover'
    + 关键帧 'keyframe'
    + 头像 'face'

    使用 B站 room/v2/Room/get_by_ids + get_status_info_by_uids 批量 API。
    bilibili-api-python 暂不提供批量接口，手动 HTTP 调用是当前最优方案。
    """

    liverInfo = Signal(list)

    def __init__(self, roomIDList):
        super(CollectLiverInfo, self).__init__()
        self.roomIDList = roomIDList
        self._running = False
        self._refresh_requested = False
        self._wake_event = threading.Event()

    def setRoomIDList(self, roomIDList):
        self.roomIDList = roomIDList
        self._refresh_requested = True
        self._wake_event.set()

    def requestRefresh(self):
        self._refresh_requested = True
        self._wake_event.set()
        if not self.isRunning():
            self.start()

    def stop(self):
        """优雅停止轮询"""
        self._running = False
        self._wake_event.set()

    def run(self):
        logging.debug("Collecting Liver Info...")
        self._running = True
        while self._running:
            try:
                self._wake_event.clear()
                self._refresh_requested = False
                # 房间列表为空时跳过网络请求，只等待（避免每 60s 空请求浪费流量）
                if not self.roomIDList:
                    if self._running and not self._refresh_requested:
                        self._wake_event.wait(timeout=60.0)
                    continue
                liverInfo = []
                data = json.dumps({"ids": self.roomIDList})  # 根据直播间房号批量获取直播间信息
                r = http_utils.post(r"https://api.live.bilibili.com/room/v2/Room/get_by_ids", data=data, headers=header)
                r.encoding = "utf8"
                payload = json.loads(r.text)
                room_uid_data = payload.get("data", {}) if isinstance(payload, dict) else {}
                uidList = []
                for roomID in room_uid_data:
                    uid = room_uid_data[roomID].get("uid")
                    if uid:
                        uidList.append(uid)

                status_data = {}
                if uidList:
                    data = json.dumps({"uids": uidList})
                    r = http_utils.post(
                        r"https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids", data=data, headers=header
                    )
                    r.encoding = "utf8"
                    payload = json.loads(r.text)
                    status_data = payload.get("data", {}) if isinstance(payload, dict) else {}

                if status_data:
                    # 构建 room_id → info 字典，O(n) 查找替代 O(n*m) 嵌套循环
                    room_info_map = {info["room_id"]: (uid, info) for uid, info in status_data.items()}
                    for roomID in self.roomIDList:
                        matched = room_info_map.get(roomID)
                        if matched:
                            uid, info = matched
                            keyframe = info.get("keyframe") or info.get("cover") or ""
                            liverInfo.append(
                                [
                                    uid,
                                    str(roomID),
                                    info.get("uname", ""),
                                    info.get("face", ""),
                                    info.get("live_status", 0),
                                    keyframe,
                                    info.get("title", ""),
                                    info.get("cover", ""),
                                ]
                            )
                        else:
                            detail = self._fetch_room_detail(roomID)
                            if detail:
                                liverInfo.append(detail)
                else:
                    # 批量接口失败时逐个兜底，避免卡片长期停在“检测中”
                    for roomID in self.roomIDList:
                        detail = self._fetch_room_detail(roomID)
                        if detail:
                            liverInfo.append(detail)
                if liverInfo:
                    self.liverInfo.emit(liverInfo)
                # 冷却等待：支持 requestRefresh()/stop() 事件唤醒
                if self._running and not self._refresh_requested:
                    self._wake_event.wait(timeout=60.0)
            except Exception as e:
                logging.error(str(e))
                if self._running:
                    self._wake_event.wait(timeout=3.0)

    @staticmethod
    def _fetch_room_uname(room_id):
        room_id = str(room_id)
        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom",
                params={"room_id": room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                return ((data.get("anchor_info") or {}).get("base_info") or {}).get("uname", "")
        except Exception:
            pass

        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/room/v1/Room/room_init",
                params={"id": room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                uid = data.get("uid")
                if uid:
                    return f"UID:{uid}"
        except Exception:
            pass
        return ""

    @staticmethod
    def _fetch_room_detail(room_id):
        room_id = str(room_id)
        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom",
                params={"room_id": room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                room_info = data.get("room_info") or {}
                anchor_info = (data.get("anchor_info") or {}).get("base_info") or {}
                resolved_room_id = room_info.get("room_id") or room_id
                uid = room_info.get("uid") or anchor_info.get("uid")
                uname = anchor_info.get("uname") or room_info.get("uname") or ""
                face = anchor_info.get("face") or ""
                live_status = room_info.get("live_status", 0)
                keyframe = room_info.get("keyframe") or room_info.get("cover") or ""
                title = room_info.get("title", "")
                return [
                    uid if uid else None,
                    str(resolved_room_id),
                    uname,
                    face,
                    live_status,
                    keyframe,
                    title,
                    room_info.get("cover", ""),
                ]
        except Exception:
            pass

        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/room/v1/Room/room_init",
                params={"id": room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            if isinstance(data, dict):
                resolved_room_id = data.get("room_id") or room_id
                uid = data.get("uid")
                if uid:
                    try:
                        status_resp = http_utils.post(
                            "https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids",
                            data=json.dumps({"uids": [uid]}),
                            headers=header,
                        )
                        status_payload = status_resp.json()
                        status_data = status_payload.get("data") if isinstance(status_payload, dict) else None
                        if isinstance(status_data, dict):
                            status_info = status_data.get(str(uid)) or status_data.get(uid)
                            if isinstance(status_info, dict):
                                keyframe = status_info.get("keyframe") or status_info.get("cover") or ""
                                return [
                                    uid,
                                    str(status_info.get("room_id") or resolved_room_id),
                                    status_info.get("uname", f"UID:{uid}"),
                                    status_info.get("face", ""),
                                    status_info.get("live_status", 0),
                                    keyframe,
                                    status_info.get("title", ""),
                                    status_info.get("cover", ""),
                                ]
                    except Exception:
                        pass
                    return [uid, str(resolved_room_id), f"UID:{uid}", "", 0, "", "", ""]
        except Exception:
            pass

        uname = CollectLiverInfo._fetch_room_uname(room_id)
        if uname:
            return [1, room_id, uname, "", 0, "", "", ""]
        return None


class LiverPanel(QWidget):
    """关注的直播间"""

    addToWindow = Signal(list)
    dumpConfig = Signal()
    refreshIDList = Signal(list)
    startLiveList = Signal(list)

    def __init__(self, roomIDDict, app_path):
        super(LiverPanel, self).__init__()
        self.application_path = app_path
        self.refreshCount = 0
        self.oldLiveStatus = {}
        self._addLiverRoomWidget = None
        self._sessionData = ""
        self._credential = {}
        self._displayOrder = []
        # Fluent FlowLayout：卡片流式自动换行，随容器宽度自适应列数
        self.layout = FlowLayout(self, needAni=False)
        self.layout.setHorizontalSpacing(10)
        self.layout.setVerticalSpacing(10)
        self.layout.setContentsMargins(7, 7, 7, 7)
        self.coverList = []
        self.roomIDDict = self._normalize_room_dict(roomIDDict)
        for roomID, topToken in self.roomIDDict.items():
            self.coverList.append(CoverLabel(roomID, topToken))
            self.coverList[-1].addToWindow.connect(self.addCoverToPlayer)  # 添加至窗口播放信号
            self.coverList[-1].deleteCover.connect(self.deleteCover)
            self.coverList[-1]._liverPanel = self  # 保存面板引用，录制时需要 credential
            self.coverList[-1].changeTopToken.connect(self.changeTop)
        for cover in self.coverList:  # 先添加置顶卡片
            if cover.topToken:
                self.layout.addWidget(cover)
        for cover in self.coverList:  # 再添加普通卡片
            if not cover.topToken:
                self.layout.addWidget(cover)
        self.refreshPanel()
        self.collectLiverInfo = CollectLiverInfo(self._buildRoomIDListForCollector())
        self.collectLiverInfo.liverInfo.connect(self.refreshRoomPanel)
        self.collectLiverInfo.start()

    def syncFlowHeight(self, width=None):
        """让滚动内容高度匹配当前列数，避免多行卡片被 viewport 裁切。"""
        content_width = max(1, int(width or self.width()))
        required_height = max(0, self.layout.heightForWidth(content_width))
        if self.minimumHeight() != required_height:
            self.setMinimumHeight(required_height)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.syncFlowHeight(event.size().width())

    @property
    def addLiverRoomWidget(self):
        """兼容旧调用点，并在首次需要时构造添加窗口。"""
        return self._ensureAddLiverRoomWidget()

    def _ensureAddLiverRoomWidget(self):
        if self._addLiverRoomWidget is None:
            widget = AddLiverRoomWidget(self.application_path)
            widget.roomList.connect(self.addLiverRoomList)
            widget.hotLiverTable.addToWindow.connect(self.addCoverToPlayer)
            widget.setSessionData(self._sessionData)
            widget.setCredential(self._credential)
            self._addLiverRoomWidget = widget
        return self._addLiverRoomWidget

    def closeAddLiverRoomWidget(self):
        if self._addLiverRoomWidget is not None:
            self._addLiverRoomWidget.shutdown()

    @staticmethod
    def _normalize_room_id(room_id):
        return str(room_id or "").strip()

    @classmethod
    def _normalize_room_dict(cls, room_dict):
        normalized = {}
        if not isinstance(room_dict, dict):
            return normalized
        for room_id, top_token in room_dict.items():
            key = cls._normalize_room_id(room_id)
            if not key:
                continue
            normalized[key] = bool(top_token)
        return normalized

    def _buildRoomIDListForCollector(self):
        room_ids = []
        for room_id in self.roomIDDict.keys():
            try:
                room_ids.append(int(room_id))
            except (TypeError, ValueError):
                logging.warning(f"忽略非法房号: {room_id}")
        return room_ids

    def _applyRoomListMutation(self, request_refresh=True, refresh_panel=True, dump_config=True):
        self.collectLiverInfo.setRoomIDList(self._buildRoomIDListForCollector())
        if request_refresh:
            self.collectLiverInfo.requestRefresh()
        if refresh_panel:
            self.refreshPanel()
        if dump_config:
            self.dumpConfig.emit()

    def setSessionData(self, sessionData):
        """保存登录凭据，并在添加窗口已创建时同步。"""
        self._sessionData = sessionData or ""
        if self._addLiverRoomWidget is not None:
            self._addLiverRoomWidget.setSessionData(self._sessionData)

    def setCredential(self, credential):
        self._credential = credential or {}
        if self._addLiverRoomWidget is not None:
            self._addLiverRoomWidget.setCredential(self._credential)

    def autoFetchFollows(self, uid):
        """自动获取关注列表并添加到面板（登录后自动触发）。"""
        widget = self._ensureAddLiverRoomWidget()
        widget.getFollows.setUID(uid)
        widget.getFollows.setSessionData(self._sessionData)
        widget.getFollows.setCredential(self._credential)
        if not widget.getFollows.isRunning():
            logging.info(f"自动获取 UID={uid} 的关注列表 (sessdata={'有' if self._sessionData else '无'})")
            widget.getFollows.start()

    def openLiverRoomPanel(self):
        widget = self._ensureAddLiverRoomWidget()
        if not widget.getHotLiver.isRunning():
            widget.progressBar.show()
            widget.getHotLiver.start()
        widget._fillHotLiverTable(widget.currentPage)
        widget.show()
        widget.raise_()
        widget.activateWindow()

    def addLiverRoomList(self, roomDict):
        logging.debug("接收到新的主播列表")
        room_dict = self._normalize_room_dict(roomDict)
        new_items = []
        for roomID, topToken in room_dict.items():
            if len(roomID) <= 5:  # 查询短号
                try:
                    resolved_room_id = self._resolve_short_room_id(roomID)
                    if resolved_room_id:
                        roomID = resolved_room_id
                    else:
                        logging.warning(f"短号解析失败，保持原房号: {roomID}")
                except Exception:
                    logging.exception("房间号查询失败，保持原房号")
            roomID = self._normalize_room_id(roomID)
            if not roomID:
                continue
            if roomID not in self.roomIDDict:
                new_items.append((roomID, bool(topToken)))
            else:
                self.roomIDDict[roomID] = bool(topToken)
                for cover in self.coverList:
                    if cover.roomID == roomID:
                        cover.topToken = bool(topToken)
                        break
        for roomID, topToken in new_items:
            self.coverList.append(CoverLabel(roomID, topToken))
            self.coverList[-1].addToWindow.connect(self.addCoverToPlayer)  # 添加至播放窗口
            self.coverList[-1].deleteCover.connect(self.deleteCover)
            self.coverList[-1].changeTopToken.connect(self.changeTop)
            self.coverList[-1]._liverPanel = self
            self.roomIDDict[roomID] = bool(topToken)
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    @staticmethod
    def _resolve_short_room_id(room_id):
        room_id = str(room_id)
        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom",
                params={"room_id": room_id},
                headers=header,
            )
            payload = response.json()
            if payload.get("code") == 0 and isinstance(payload.get("data"), dict):
                room_info = payload["data"].get("room_info", {})
                resolved = room_info.get("room_id") or payload["data"].get("room_id")
                if resolved:
                    return str(resolved)
        except Exception:
            pass

        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/room/v1/Room/room_init",
                params={"id": room_id},
                headers=header,
            )
            payload = response.json()
            if payload.get("code") == 0 and isinstance(payload.get("data"), dict):
                resolved = payload["data"].get("room_id")
                if resolved:
                    return str(resolved)
        except Exception:
            pass
        return None

    def refreshRoomPanel(self, liverInfo):  # 异步刷新图卡
        self.refreshCount += 1  # 刷新计数+1
        roomIDToRefresh = []
        roomIDStartLive = []
        # 建立房号→卡片索引，避免 O(房间数 × 卡片数) 的双重循环
        cover_by_id = {cover.roomID: cover for cover in self.coverList}
        for index, info in enumerate(liverInfo):
            if info[0]:  # uid有效
                cover = cover_by_id.get(info[1])
                if cover is not None:  # 字符串房号
                    if (
                        cover.recordState == 2 and cover.liveState == 0 and info[4] == 1
                    ):  # 满足等待开播录制的3个条件
                        cover.recordThread.setSavePath(cover.savePath)  # 启动录制线程
                        cover.recordThread.setCredential(self._credential, self._sessionData)
                        cover.recordThread.start()
                        cover.recordThread.checkTimer.start(3000)
                        cover.recordState = 1  # 改为录制状态
                    elif cover.recordState == 1 and info[4] != 1:  # 满足停止录制的2个条件
                        cover.recordState = 0  # 取消录制
                        cover.recordThread.stopRecording()  # 置 recordToken=False（线程安全），让 run() 自行退出
                        cover.recordThread.checkTimer.stop()  # 停止轮询，避免 180s 后误弹"录制结束"提示
                    cover.updateLabel(info)  # 更新数据
                if info[1] not in self.oldLiveStatus:  # 软件启动后第一次更新添加
                    self.oldLiveStatus[info[1]] = info[4]  # 房号: 直播状态
                elif self.oldLiveStatus[info[1]] != info[4]:  # 状态发生变化
                    if info[4] == 1:
                        roomIDStartLive.append(info[2])  # 添加开播主播名字
                    roomIDToRefresh.append(info[1])  # 发送给主界面要刷新的房间号
                    self.oldLiveStatus[info[1]] = info[4]  # 更新旧的直播状态列表
            else:  # 错误的房号
                cover = cover_by_id.get(info[1])
                if cover is not None:
                    cover.updateLabel(info)
        if roomIDStartLive:
            self.startLiveList.emit(roomIDStartLive)
        if roomIDToRefresh:
            # 开播/下播状态变化，通知主界面刷新对应播放器
            self.refreshIDList.emit(roomIDToRefresh)
        self.refreshPanel()

    def addCoverToPlayer(self, info):
        self.addToWindow.emit(info)

    def _stopCoverRecording(self, cover):
        """删除卡片前安全停止录制线程，避免运行中的 QThread 被析构触发 Qt abort。

        返回 True 表示线程已安全退出，可立即销毁控件；
        返回 False 表示线程未在超时内退出（网络阻塞等），控件改为线程结束后延迟清理。
        """
        thread = cover.recordThread
        if thread is None:
            return True
        thread.checkTimer.stop()
        if thread.isRunning():
            thread.stopRecording()  # 置 recordToken=False，让 run() 循环自行退出
            if not thread.wait(3000):  # 等待退出（超时保护）
                # 线程仍卡在网络 IO：此时绝不能 deleteLater（运行中的 QThread 被析构会触发 Qt abort）
                logging.warning("录制线程 %s 未在 3s 内退出，延迟清理控件", thread.roomID)
                thread.finished.connect(cover.deleteLater, Qt.QueuedConnection)
                return False
        return True

    def deleteCover(self, roomID):
        roomID = self._normalize_room_id(roomID)
        self.roomIDDict.pop(roomID, None)
        self.oldLiveStatus.pop(roomID, None)
        for index, cover in enumerate(list(self.coverList)):
            if cover.roomID == roomID:
                safe_to_destroy = self._stopCoverRecording(cover)
                cover.hide()
                self.layout.removeWidget(cover)
                self.coverList.pop(index)
                cover.setParent(None)
                if safe_to_destroy:
                    cover.deleteLater()
                break
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    def deleteAll(self):
        """清空卡片槽 — 释放所有卡片控件并清理房间列表"""
        self.roomIDDict.clear()
        self.oldLiveStatus.clear()
        for cover in list(self.coverList):
            safe_to_destroy = self._stopCoverRecording(cover)
            cover.hide()
            if safe_to_destroy:
                cover.deleteLater()
        self.coverList.clear()
        # _onDumpRoomConfig 会将空 roomid 写入 config 并保存
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    def changeTop(self, info):
        roomID = self._normalize_room_id(info[0] if info else "")
        top_token = bool(info[1]) if isinstance(info, (list, tuple)) and len(info) > 1 else False
        if roomID in self.roomIDDict:
            self.roomIDDict[roomID] = top_token
        for cover in self.coverList:
            if cover.roomID == roomID:
                cover.topToken = top_token
                break
        self._applyRoomListMutation(request_refresh=False, refresh_panel=True, dump_config=True)

    def updatePlayingStatus(self, playerList):
        """同步播放状态到卡片边框样式（播放态为语义红边框，其余走主题样式）"""
        player_set = set(playerList)
        for cover in self.coverList:
            is_playing = cover.roomID in player_set
            if cover.isPlaying != is_playing:
                cover.isPlaying = is_playing
                cover._applyTheme()

    def refreshPanel(self):
        """仅在显示顺序变化时重排卡片，状态刷新不触发布局抖动。"""
        state_order = {1: 0, 0: 1, -1: 2}
        indexed_covers = [
            (index, cover)
            for index, cover in enumerate(self.coverList)
            if cover.roomID != "0"
        ]
        ordered_covers = [
            cover
            for _, cover in sorted(
                indexed_covers,
                key=lambda item: (
                    not item[1].topToken,
                    state_order.get(item[1].liveState, 3),
                    item[0],
                ),
            )
        ]
        if ordered_covers == self._displayOrder:
            return

        for index in reversed(range(self.layout.count())):
            item = self.layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self.layout.removeWidget(widget)

        for cover in self.coverList:
            cover.hide()
        for cover in ordered_covers:
            self.layout.addWidget(cover)
            cover.show()

        self._displayOrder = ordered_covers
        self.syncFlowHeight()

    def getFirstRoomID(self):
        """获取卡片面板中第一个有效的房间号（用于快捷键加载）"""
        for roomID in self.roomIDDict:
            if roomID and roomID != "0":
                return str(roomID)
        return ""
