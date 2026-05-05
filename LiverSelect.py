"""
DD监控室主界面上方的控制条里的ScrollArea里面的卡片模块
包含主播开播/下播检测和刷新展示 置顶排序 录制管理等功能
"""
import json, time, logging, os, threading
from bilibili_api import live_area, user, sync
from bili_credential import build_credential, normalize_credential_data
from PySide6.QtWidgets import * 	# QAction,QFileDialog
from PySide6.QtGui import *		# QIcon,QPixmap
from PySide6.QtCore import * 		# QSize
import http_utils


header = http_utils.DEFAULT_HEADERS


def _chunked(items, size):
    for index in range(0, len(items), size):
        yield items[index:index + size]


class CardLabel(QLabel):
    def __init__(self, text='NA', fontColor='#f1fefb', size=11):
        super(CardLabel, self).__init__()
        # self.setFont(QFont('微软雅黑', size, QFont.Bold))
        self.setFont(QFont('华康少女文字W5(P)', size, QFont.Bold))
        self.setStyleSheet('color:%s;background-color:#00000000' % fontColor)
        self.setText(text)

    def setBrush(self, fontColor):
        self.setStyleSheet('color:%s;background-color:#00000000' % fontColor)


class OutlinedLabel(QLabel):
    def __init__(self, text='NA', fontColor='#FFFFFF', outColor='#222222', size=11):
        super().__init__()
        # self.setFont(QFont('微软雅黑', size, QFont.Bold))
        self.setFont(QFont('华康少女文字W5(P)', size, QFont.Bold))
        self.setStyleSheet('background-color:#00000000')
        self.setText(text)
        self.setBrush(fontColor)
        self.setPen(outColor)
        self.w = self.font().pointSize() / 15
        self.metrics = QFontMetrics(self.font())

    def setBrush(self, brush):
        brush = QColor(brush)
        if not isinstance(brush, QBrush):
            brush = QBrush(brush)
        self.brush = brush

    def setPen(self, pen):
        pen = QColor(pen)
        if not isinstance(pen, QPen):
            pen = QPen(pen)
        pen.setJoinStyle(Qt.RoundJoin)
        self.pen = pen

    def paintEvent(self, event):
        rect = self.rect()
        indent = self.indent()
        x = rect.left() + indent - min(self.metrics.leftBearing(self.text()[0]), 0)
        y = (rect.height() + self.metrics.ascent() - self.metrics.descent()) / 2
        path = QPainterPath()
        path.addText(x, y, self.font(), self.text())
        qp = QPainter(self)
        qp.setRenderHint(QPainter.Antialiasing)
        self.pen.setWidthF(self.w * 2)
        qp.strokePath(path, self.pen)
        qp.fillPath(path, self.brush)


class CircleImage(QWidget):
    """圆形头像框"""
    def __init__(self, parent=None):
        super(CircleImage, self).__init__(parent)
        self.setFixedSize(60, 60)
        self.circle_image = None

    def set_image(self, image):
        self.circle_image = image
        self.update()

    def paintEvent(self, event):
        if self.circle_image:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            pen = Qt.NoPen
            painter.setPen(pen)
            brush = QBrush(self.circle_image)
            painter.setBrush(brush)
            painter.drawRoundedRect(self.rect(), self.width() / 2, self.height() / 2)


class PushButton(QPushButton):
    def __init__(self, name, pushToken=False):
        super().__init__()
        self.setText(name)
        self.pushToken = pushToken
        if self.pushToken:
            self.setStyleSheet('background-color:#3daee9;border-width:1px')
        else:
            self.setStyleSheet('background-color:#31363b;border-width:1px')



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
        self.sessionData = ''

    def setCredential(self, credential, sessionData=''):
        self.credential = credential
        self.sessionData = sessionData

    def checkDownlods(self):
        with self._lock:
            if self.downloadToken:
                self.downloadToken = False
                if not self.downloadTime % 60:  # 每分钟刷新一次
                    self.downloadTimer.emit('%dmin' % (self.downloadTime / 60))
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
            from bili_credential import build_credential, normalize_credential_data
            cred_data = normalize_credential_data(self.credential, sessdata=self.sessionData)
            room = live.LiveRoom(int(self.roomID), credential=build_credential(cred_data, sessdata=self.sessionData))
            play_info = sync(room.get_room_play_url(screen_resolution=live.ScreenResolution.ORIGINAL))
            durl = play_info.get('durl', [])
            if not durl:
                raise RuntimeError('未获取到录制流地址')
            url = durl[0]['url']
            download = http_utils.get(url, stream=True, headers=header)
            with self._lock:
                self.recordToken = True
            self.downloadTime = 0
            self.cacheVideo = open(self.savePath, 'wb')
            try:
                for chunk in download.iter_content(chunk_size=512):
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


class DownloadImage(QThread):
    """下载图片（线程安全：使用 QImage 传递，主线程转 QPixmap）"""
    img = Signal(QPixmap)
    img_origin = Signal(QPixmap)
    _imgReady = Signal(QImage, int, int, bool)  # image, w, h, hasOrigin

    def __init__(self, scaleW, scaleH, keyFrame=False):
        super(DownloadImage, self).__init__()
        self.W = scaleW
        self.H = scaleH
        self.keyFrame = keyFrame
        self.url = ''
        self._imgReady.connect(self._onImageReady)

    def setUrl(self, url):
        self.url = str(url or '').strip()

    def run(self):
        if not self.url:
            return
        try:
            if self.W == 60:
                r = http_utils.get(self.url + '@100w_100h.jpg', headers=header)
            else:
                r = http_utils.get(self.url, headers=header)
            # QImage 是线程安全的，QPixmap 不是
            qimage = QImage.fromData(r.content)
            if not qimage.isNull():
                self._imgReady.emit(qimage, self.W, self.H, self.keyFrame)
        except Exception as e:
            logging.error(str(e))

    def _onImageReady(self, qimage, w, h, hasOrigin):
        """主线程回调：将 QImage 转换为 QPixmap"""
        pixmap = QPixmap.fromImage(qimage)
        self.img.emit(pixmap.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        if hasOrigin:
            self.img_origin.emit(pixmap)


class CoverLabel(QLabel):
    """封面的文字"""
    addToWindow = Signal(list)
    deleteCover = Signal(str)
    changeTopToken = Signal(list)

    def __init__(self, roomID, topToken=False):
        super(CoverLabel, self).__init__()
        QToolTip.setFont(QFont('微软雅黑', 16, QFont.Bold))
        self.setAcceptDrops(True)
        self.roomID = roomID
        self.topToken = topToken
        self.isPlaying = False  # 正在播放
        self.title = 'NA'  # 这里其实一开始设计的时候写错名字了 实际这里是用户名不是房间号 将错就错下去了
        self.roomTitle = ''  # 这里才是真的存放房间名的地方
        self.recordState = 0  # 0 无录制任务  1 录制中  2 等待开播录制
        self.savePath = ''
        self.setFixedSize(160, 90)
        self.setObjectName('cover')
        self.setFrameShape(QFrame.Box)
        self.firstUpdateToken = True
        self.layout = QGridLayout(self)
        self.profile = CircleImage()
        self.layout.addWidget(self.profile, 0, 4, 2, 2)
        if topToken:
            brush = '#FFC125'
            self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:#dfa616;background-color:#5a636d}')
        else:
            brush = '#f1fefb'
            self.setStyleSheet('background-color:#5a636d')  # 灰色背景
        self.titleLabel = OutlinedLabel(fontColor=brush)
        # self.titleLabel = CardLabel(fontColor=brush)
        self.layout.addWidget(self.titleLabel, 0, 0, 1, 6)
        # self.roomIDLabel = OutlinedLabel(roomID, fontColor=brush)
        # self.roomIDLabel = CardLabel(roomID, fontColor=brush)
        # self.layout.addWidget(self.roomIDLabel, 1, 0, 1, 6)
        self.stateLabel = OutlinedLabel(size=13)
        # self.stateLabel = CardLabel(size=13)
        self.stateLabel.setText('检测中')
        self.liveState = 0  # 0 未开播  1 直播中  2 投稿视频   -1 错误
        self.layout.addWidget(self.stateLabel, 1, 0, 1, 6)
        self.downloadFace = DownloadImage(60, 60)
        self.downloadFace.img.connect(self.updateProfile)
        self.downloadKeyFrame = DownloadImage(160, 90, True)
        self.downloadKeyFrame.img.connect(self.updateKeyFrame)
        self.downloadKeyFrame.img_origin.connect(self.setToolTipKeyFrame)
        self._lastKeyframeUrl = ''

        self.recordThread = RecordThread(roomID)
        self.recordThread.downloadTimer.connect(self.refreshStateLabel)
        self.recordThread.downloadError.connect(self.recordError)

    def updateLabel(self, info):
        if not info[0]:  # 用户或直播间不存在
            self.liveState = -1
            self.roomTitle = ''
            self.setToolTip(self.roomTitle)
            if info[2]:
                self.titleLabel.setText(info[2])
                self.stateLabel.setText('房间可能被封')
            else:
                self.titleLabel.setText(info[1])
                self.stateLabel.setText('无该房间或已加密')
            self.setStyleSheet('background-color:#8B3A3A')  # 红色背景
        else:
            if self.firstUpdateToken:  # 初始化
                self.firstUpdateToken = False
                avatar_url = str(info[3] or '').strip()
                if avatar_url:
                    self.downloadFace.setUrl(avatar_url)  # 启动下载头像线程
                    if not self.downloadFace.isRunning():
                        self.downloadFace.start()
                # self.roomIDLabel.setText(info[1])  # 房间号
                self.titleLabel.setText(info[2])  # 名字
                self.title = info[2]
            if info[4] == 1:  # 直播中
                self.liveState = 1
                keyframe_url = str((info[5] if len(info) > 5 else '') or '').strip()
                if not keyframe_url and len(info) > 7:
                    keyframe_url = str(info[7] or '').strip()
                if keyframe_url and keyframe_url != self._lastKeyframeUrl:
                    self._lastKeyframeUrl = keyframe_url
                    self.downloadKeyFrame.setUrl(keyframe_url)  # 启动下载关键帧线程
                    if not self.downloadKeyFrame.isRunning():
                        self.downloadKeyFrame.start()
                self.roomTitle = info[6]  # 房间直播标题
                # self.setToolTip(self.roomTitle)  # 改用self.setToolTipKeyFrame里面设置tooltip
            else:  # 未开播
                self.liveState = 0
                self._lastKeyframeUrl = ''
                self.roomTitle = ''  # 房间直播标题
                self.setToolTip(self.roomTitle)
                self.clear()
                if self.isPlaying:
                    self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:red;background-color:#5a636d}')
                elif self.topToken:
                    self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:#dfa616;background-color:#5a636d}')
                else:
                    self.setStyleSheet('background-color:#5a636d')  # 灰色背景
            self.refreshStateLabel()

    def refreshStateLabel(self, downloadTime=''):
        if self.liveState == 1:
            if self.recordState == 1:  # 录制中
                self.stateLabel.setBrush('#87CEFA')  # 录制中为蓝色字体
                if downloadTime:
                    self.stateLabel.setText('· 录制中 %s' % downloadTime)
            else:
                self.stateLabel.setBrush('#7FFFD4')  # 直播中为绿色字体
                self.stateLabel.setText('· 直播中')
        else:
            if self.recordState == 2:  # 等待录制
                self.stateLabel.setBrush('#FFA500')  # 待录制为橙色字体
                self.stateLabel.setText('· 等待开播')
            else:
                self.stateLabel.setBrush('#FF6A6A')  # 未开播为红色字体
                self.stateLabel.setText('· 未开播')

    def recordError(self, roomID):
        self.recordThread.checkTimer.stop()
        self.refreshStateLabel()
        QMessageBox.information(self, '录制中止', '%s %s 录制结束 请检查网络或主播是否掉线' % (self.title, roomID), QMessageBox.Ok)

    def updateProfile(self, img):
        self.profile.set_image(img)

    def updateKeyFrame(self, img):
        self.setPixmap(img)

    def setToolTipKeyFrame(self, img):
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
            mimeData.setText('roomID:%s' % self.roomID)
            drag.setMimeData(mimeData)
            drag.exec()
        elif QMouseEvent.button() == Qt.RightButton:
            menu = QMenu()
            addTo = menu.addMenu('添加至窗口 ►')
            addWindow = []
            for win in range(1, 10):
                addWindow.append(addTo.addAction('窗口%s' % win))
            if not self.topToken:
                top = menu.addAction('添加置顶')
            else:
                top = menu.addAction('取消置顶')
            record = None
            if self.recordState == 0:  # 无录制任务
                if self.liveState == 1:
                    record = menu.addAction('录制(最高画质)')
                elif self.liveState in [0, 2]:  # 未开播或轮播
                    record = menu.addAction('开播自动录制')
            else:  # 录制中或等待录制
                record = menu.addAction('取消录制')
            openBrowser = menu.addAction('打开直播间')
            copyRoomID = menu.addAction('复制房号 %s' % self.roomID)
            menu.addSeparator()  # 添加分割线，防止误操作
            delete = menu.addAction('删除')
            action = menu.exec(self.mapToGlobal(QMouseEvent.position().toPoint()))
            if action == delete:
                self.deleteCover.emit(self.roomID)
                self.roomID = '0'
                self.hide()
            elif action == top:
                if self.topToken:
                    self.titleLabel.setBrush('#f1fefb')
                    # self.roomIDLabel.setBrush('#f1fefb')
                    if self.isPlaying:
                        self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:red;background-color:#5a636d}')
                    else:
                        self.setStyleSheet('border-width:0px')
                else:
                    self.titleLabel.setBrush('#FFC125')
                    # self.roomIDLabel.setBrush('#FFC125')
                    if self.isPlaying:
                        self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:red;background-color:#5a636d}')
                    else:
                        self.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:#dfa616;background-color:#5a636d}')
                self.topToken = not self.topToken
                self.changeTopToken.emit([self.roomID, self.topToken])  # 发送修改后的置顶token
            elif action == record:
                if self.roomID != '0':
                    if self.recordState == 0:  # 无录制任务
                        saveName = '%s_%s_%s' % (self.title, self.roomTitle,
                                                 time.strftime('%Y-%m-%d-%H-%M-%S', time.localtime(time.time())))
                        self.savePath = QFileDialog.getSaveFileName(self, "选择保存路径", saveName, "*.flv")[0]
                        if self.savePath:  # 保存路径有效
                            if self.liveState == 1:  # 直播中
                                self.recordThread.setSavePath(self.savePath)
                                lp = getattr(self, '_liverPanel', None)
                                if lp is not None:
                                    self.recordThread.setCredential(getattr(lp, '_credential', None), getattr(lp, '_sessionData', ''))
                                self.recordThread.start()
                                self.recordThread.checkTimer.start(3000)
                                self.recordState = 1  # 改为录制状态
                                self.refreshStateLabel('0min')
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
            elif action == openBrowser:
                if self.roomID != '0':
                    QDesktopServices.openUrl(QUrl(r'https://live.bilibili.com/%s' % self.roomID))
            elif action == copyRoomID:
                clipboard = QApplication.clipboard()
                clipboard.setText(self.roomID)
            else:
                for index, i in enumerate(addWindow):
                    print(index, i)
                    if action == i:
                        self.addToWindow.emit([index, self.roomID])  # 添加至窗口 窗口 房号
                        break


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
                'https://api.live.bilibili.com/room/v3/area/getRoomList',
                {
                    'platform': 'web',
                    'parent_area_id': area,
                    'area_id': 0,
                    'page': page,
                    'sort_type': 'online',
                },
            ),
            (
                'https://api.live.bilibili.com/room/v1/Area/getListByAreaID',
                {
                    'areaId': area,
                    'page': page,
                    'sort': 'online',
                },
            ),
        ]
        if self._prefer_bili_api:
            try:
                return sync(live_area.get_list_by_area(
                    area,
                    page=page,
                    order='online',
                    credential=build_credential(self.credential),
                ))
            except Exception as e:
                message = str(e)
                if '-352' in message or 'fetch_live_area_data' in message:
                    self._prefer_bili_api = False
                    if not self._bili_api_disabled_logged:
                        logging.warning('热门列表切换到 HTTP fallback（bilibili-api 触发 -352 或分区数据缺失）')
                        self._bili_api_disabled_logged = True
                else:
                    logging.warning(f'热门列表 area={area} page={page} bilibili-api 查询失败: {e}')

        for api_url, params in fallback_requests:
            try:
                response = http_utils.get(api_url, params=params, headers=header)
                payload = response.json()
                if payload.get('code') != 0:
                    logging.warning(
                        f'热门列表 area={area} page={page} fallback 失败: {api_url} '
                        f'code={payload.get("code")} message={payload.get("message")}'
                    )
                    continue

                data = payload.get('data')
                if isinstance(data, dict):
                    return data
                if isinstance(data, list):
                    return {'list': data}
            except Exception as fallback_error:
                logging.warning(
                    f'热门列表 area={area} page={page} fallback 异常: {api_url}, err={fallback_error}'
                )
                continue

        return {'list': []}

    def run(self):
        roomInfoSummary = []
        try:
            try:
                sync(live_area.fetch_live_area_data())
            except Exception:
                logging.exception('热门分区数据预加载失败，继续使用旧缓存')
            for page_index, area in enumerate([9, 2, 3, 6, 1]):
                pageSummary = []
                for page in range(1, 6):
                    data = self._fetch_area_page(area, page)
                    room_list = (data or {}).get('list', [])
                    if not room_list:
                        break
                    for info in room_list:
                        pageSummary.append([
                            info.get('uname', ''),
                            info.get('title', ''),
                            str(info.get('roomid', '')),
                        ])
                    self.areaLoaded.emit(page_index, list(pageSummary))
                    time.sleep(0.1)
                roomInfoSummary.append(pageSummary)
        except Exception:
            logging.exception('热门列表加载失败')
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
        self.sessionData = ''
        self.credential = {}

    def setUID(self, uid):
        self.uid = uid

    def setSessionData(self, sessionData):
        self.sessionData = sessionData if sessionData else ''

    def setCredential(self, credential):
        self.credential = normalize_credential_data(credential, sessdata=self.sessionData)

    @staticmethod
    def _extract_follow_ids(follow_list):
        followsIDs = set()
        for info in follow_list:
            if isinstance(info, int):
                followsIDs.add(info)
            elif isinstance(info, dict):
                mid = info.get('mid') or info.get('uid') or info.get('mid_str')
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
            room_rows.append([
                info.get('uname', ''),
                info.get('title', ''),
                str(info.get('room_id', '')),
                info.get('live_status', 0),
            ])
        return room_rows

    def run(self):
        if not self.uid:
            self.roomInfoSummary.emit([])
            return
        followsIDs = set()
        roomIDList = []
        req_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://space.bilibili.com/',
        }
        cookies = {}
        if self.sessionData:
            cookies['SESSDATA'] = self.sessionData
        try:
            follow_list = sync(user.User(
                int(self.uid),
                credential=build_credential(self.credential, sessdata=self.sessionData)
            ).get_all_followings())
            followsIDs = self._extract_follow_ids(follow_list)
        except Exception:
            logging.exception('通过 bilibili-api-python 获取关注列表失败，回退至 HTTP API')
            try:
                for p in range(1, 11):
                    url = f'https://api.bilibili.com/x/relation/followings?vmid={self.uid}&pn={p}&ps=50&order=desc'
                    r = http_utils.get(url, headers=req_headers, cookies=cookies)
                    resp_data = r.json()
                    if resp_data.get('code') != 0:
                        logging.warning(f'关注列表获取失败: {resp_data.get("message", "未知错误")}')
                        break
                    followList = (resp_data.get('data') or {}).get('list') or []
                    if not followList:
                        break
                    followsIDs.update(self._extract_follow_ids(followList))
                    time.sleep(0.2)
            except Exception:
                logging.exception('关注列表添加失败')

        followsIDs = list(followsIDs)
        if not followsIDs:
            logging.error('没有获取到关注列表，请检查 UID 是否正确')
            self.roomInfoSummary.emit([])
            return

        for chunk in _chunked(followsIDs, 100):
            try:
                response = http_utils.post(
                    'https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids',
                    data=json.dumps({'uids': chunk}), headers=header, cookies=cookies
                )
                response.encoding = 'utf8'
                payload = json.loads(response.text)
                if payload.get('code') != 0:
                    logging.warning(f'直播状态查询失败: {payload.get("message", "未知错误")}')
                    continue
                room_chunk = self._build_room_rows(chunk, payload.get('data', {}))
                if room_chunk:
                    roomIDList.extend(room_chunk)
                    self.roomInfoChunk.emit(room_chunk)
            except Exception:
                logging.exception('直播间状态查询失败')
            time.sleep(0.1)
        self.roomInfoSummary.emit(roomIDList)


class DownloadVTBList(QThread):
    """更新 VTB 信息"""
    vtbList = Signal(list)

    def __init__(self, parent=None):
        super(DownloadVTBList, self).__init__(parent)

    def run(self):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.141 Safari/537.36'}
            r = http_utils.get(r'https://raw.githubusercontent.com/BaoZiFly-233/DD_Monitor/master/utils/vtb.csv', headers=headers)
            # r.encoding = 'utf8'
            vtbList = []
            html = r.text.split('\n')
            for cnt, line in enumerate(html):
                if 'blob-num js-line-number' in line:
                    vtbID = html[cnt + 1].split('>')[1].split('<')[0]
                    roomID = html[cnt + 2].split('>')[1].split('<')[0]
                    haco = html[cnt + 3].split('>')[1].split('<')[0]
                    vtbList.append('%s,%s,%s\n' % (vtbID, roomID, haco))
            if vtbList:
                self.vtbList.emit(vtbList)
        except Exception:
            logging.exception("vtbs 列表获取失败")


class HotLiverTable(QTableWidget):
    """关注列表"""
    addToWindow = Signal(list)

    def __init__(self):
        super().__init__()

    def contextMenuEvent(self, event):
        self.menu = QMenu(self)
        addTo = self.menu.addMenu('添加至窗口 ►')
        addWindow = []
        for win in range(1, 10):
            addWindow.append(addTo.addAction('窗口%s' % win))
        action = self.menu.exec(self.mapToGlobal(event.pos()))
        for index, i in enumerate(addWindow):
            if action == i:
                text=self.item(self.currentRow(), 2).text()
                self.addToWindow.emit([index, text])
                break


class AddLiverRoomWidget(QWidget):
    """添加直播间 - 独立弹窗"""
    roomList = Signal(dict)

    def __init__(self, application_path):
        super(AddLiverRoomWidget, self).__init__()
        self.application_path = application_path
        self.resize(600, 900)
        self.setWindowTitle('添加直播间（房号太多的话尽量分批次添加 避免卡死）')
        self.hotLiverDict = {0: [], 1: [], 2: [], 3: [], 4: [], 5: []}
        self.followLiverList = []
        self.followRoomInfo = []
        layout = QGridLayout(self)
        layout.addWidget(QLabel('请输入B站直播间房号 多个房号之间用空格隔开'), 0, 0, 1, 4)
        self.roomEditText = ''
        self.roomEdit = QLineEdit()
        # self.roomEdit.textChanged.connect(self.editChange)  # 手感不好 还是取消了
        layout.addWidget(self.roomEdit, 1, 0, 1, 5)
        confirm = QPushButton('完成')
        confirm.setFixedHeight(28)
        confirm.clicked.connect(self.sendSelectedRoom)
        confirm.setStyleSheet('background-color:#3daee9')
        layout.addWidget(confirm, 0, 4, 1, 1)

        self.tabWidget = QTabWidget()
        self.tabWidget.currentChanged.connect(self._onTabChanged)
        layout.addWidget(self.tabWidget, 2, 0, 5, 5)

        hotLiverPage = QWidget()
        hotLiverLayout = QGridLayout(hotLiverPage)
        hotLiverLayout.setContentsMargins(1, 1, 1, 1)

        self.virtual = PushButton('虚拟主播', True)
        self.virtual.clicked.connect(lambda: self.switchHotLiver(0))
        hotLiverLayout.addWidget(self.virtual, 0, 0, 1, 1)
        self.onlineGame = PushButton('网游')
        self.onlineGame.clicked.connect(lambda: self.switchHotLiver(1))
        hotLiverLayout.addWidget(self.onlineGame, 0, 1, 1, 1)
        self.mobileGame = PushButton('手游')
        self.mobileGame.clicked.connect(lambda: self.switchHotLiver(2))
        hotLiverLayout.addWidget(self.mobileGame, 0, 2, 1, 1)
        self.consoleGame = PushButton('单机')
        self.consoleGame.clicked.connect(lambda: self.switchHotLiver(3))
        hotLiverLayout.addWidget(self.consoleGame, 0, 3, 1, 1)
        self.entertainment = PushButton('娱乐')
        self.entertainment.clicked.connect(lambda: self.switchHotLiver(4))
        hotLiverLayout.addWidget(self.entertainment, 0, 4, 1, 1)
        self.buttonList = [self.virtual, self.onlineGame, self.mobileGame, self.consoleGame, self.entertainment]
        self.currentPage = 0

        self.progressBar = QProgressBar(self)
        self.progressBar.setGeometry(0, 0, self.width(), 20)
        self.progressBar.setRange(0,0)
        self.progressBar.hide()

        self.hotLiverTable = HotLiverTable()
        self.hotLiverTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hotLiverTable.verticalScrollBar().installEventFilter(self)
        self.hotLiverTable.verticalHeader().sectionClicked.connect(self.hotLiverAdd)
        self.hotLiverTable.setColumnCount(3)
        self.hotLiverTable.setRowCount(100)
        self.hotLiverTable.setVerticalHeaderLabels(['添加'] * 100)
        for i in range(100):
            self.hotLiverTable.setRowHeight(i, 40)
        self.hotLiverTable.setHorizontalHeaderLabels(['主播名', '直播间标题', '直播间房号'])
        self.hotLiverTable.setColumnWidth(0, 130)
        self.hotLiverTable.setColumnWidth(1, 240)
        self.hotLiverTable.setColumnWidth(2, 130)
        self.hotLiverTable.setEnabled(False) #启动时暂时禁用table
        hotLiverLayout.addWidget(self.hotLiverTable, 1, 0, 1, 5)
        self.getHotLiver = GetHotLiver()
        self.getHotLiver.roomInfoSummary.connect(self.collectHotLiverInfo)
        self.getHotLiver.areaLoaded.connect(self.collectHotLiverChunk)

        followsPage = QWidget()
        followsLayout = QGridLayout(followsPage)
        followsLayout.setContentsMargins(0, 0, 0, 0)
        followsLayout.addWidget(QLabel(), 0, 2, 1, 1)
        followsLayout.addWidget(QLabel('自动添加你关注的up直播间 （只能拉取最近关注的500名）'), 0, 3, 1, 3)
        self.uidEdit = QLineEdit()
        self.uidEdit.setPlaceholderText('请输入你的uid')
        self.uidEdit.setMinimumWidth(120)
        self.uidEdit.setMaximumWidth(300)
        followsLayout.addWidget(self.uidEdit, 0, 0, 1, 1)
        uidCheckButton = QPushButton('查询')
        uidCheckButton.setFixedHeight(27)
        uidCheckButton.setStyleSheet('background-color:#3daee9')
        uidCheckButton.clicked.connect(self.checkFollows)  # 查询关注
        followsLayout.addWidget(uidCheckButton, 0, 1, 1, 1)
        self.followsTable = QTableWidget()
        self.followsTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.followsTable.verticalScrollBar().installEventFilter(self)
        self.followsTable.verticalHeader().sectionClicked.connect(self.followLiverAdd)
        self.followsTable.setColumnCount(3)
        self.followsTable.setRowCount(500)
        self.followsTable.setVerticalHeaderLabels(['添加'] * 500)
        for i in range(500):
            self.followsTable.setRowHeight(i, 40)
        self.followsTable.setHorizontalHeaderLabels(['主播名', '直播间标题', '直播间房号'])
        self.followsTable.setColumnWidth(0, 130)
        self.followsTable.setColumnWidth(1, 240)
        self.followsTable.setColumnWidth(2, 130)
        followsLayout.addWidget(self.followsTable, 1, 0, 6, 6)
        self.getFollows = GetFollows()
        self.getFollows.roomInfoSummary.connect(self.collectFollowLiverInfo)
        self.getFollows.roomInfoChunk.connect(self.collectFollowLiverChunk)

        hacoPage = QWidget()  # 添加内置的vtb列表
        hacoLayout = QGridLayout(hacoPage)
        hacoLayout.setContentsMargins(1, 1, 1, 1)
        self.refreshButton = PushButton('更新名单')
        self.refreshButton.clicked.connect(self.refreshHacoList)
        hacoLayout.addWidget(self.refreshButton, 0, 0, 1, 1)
        self.vtbSearchButton = PushButton('查询VUP')
        self.vtbSearchButton.clicked.connect(self.vtbSearch)
        hacoLayout.addWidget(self.vtbSearchButton, 0, 1, 1, 1)
        self.hacoTable = QTableWidget()
        self.hacoTable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.hacoTable.verticalScrollBar().installEventFilter(self)
        self.hacoTable.verticalHeader().sectionClicked.connect(self.hacoAdd)
        self.hacoTable.setColumnCount(3)
        try:
            self.vtbList = []
            with open(os.path.join(self.application_path, 'utils/vtb.csv'), 'r', encoding='utf-8') as vtbs:
                for line in vtbs:
                    line = line.strip()
                    if line:
                        self.vtbList.append(line.split(','))
                    else:
                        self.vtbList.append(['', '', ''])
            self.hacoTable.setRowCount(len(self.vtbList))
            self.hacoTable.setVerticalHeaderLabels(['添加'] * len(self.vtbList))
            for i in range(len(self.vtbList)):
                self.hacoTable.setRowHeight(i, 40)
            for y, line in enumerate(self.vtbList):
                for x in range(3):
                    self.hacoTable.setItem(y, x, QTableWidgetItem(line[x]))
        except Exception:
            logging.exception('vtb.csv 解析失败')

        self.hacoTable.setHorizontalHeaderLabels(['主播名', '直播间房号', '所属'])
        self.hacoTable.setColumnWidth(0, 160)
        self.hacoTable.setColumnWidth(1, 160)
        self.hacoTable.setColumnWidth(2, 160)
        hacoLayout.addWidget(self.hacoTable, 1, 0, 10, 5)
        self.downloadVTBList = DownloadVTBList()
        self.downloadVTBList.vtbList.connect(self.collectVTBList)
        # self.downloadVTBList.start()

        self.tabWidget.addTab(hotLiverPage, '正在直播')
        self.tabWidget.addTab(hacoPage, '个人势/箱')
        self.tabWidget.addTab(followsPage, '关注添加')

    def editChange(self):  # 提取输入文本中的数字
        if len(self.roomEdit.text()) > len(self.roomEditText):
            roomEditText = ''
            roomIDList = self.roomEdit.text().split(' ')
            for roomID in roomIDList:
                strList = map(lambda x: x if x.isdigit() else '', roomID)
                roomID = ''
                digitToken = False
                for s in strList:
                    if s:
                        roomID += s
                        digitToken = True
                    elif digitToken:
                        roomID += ' '
                        if roomID not in roomEditText:
                            roomEditText += roomID
                        roomID = ''
                        digitToken = False
                if roomID:
                    roomID += ' '
                    if roomID not in roomEditText:
                        roomEditText += roomID
            self.roomEdit.setText(roomEditText)
            self.roomEditText = roomEditText

    def closeEvent(self, event):
        if self.getHotLiver.isRunning():
            self.getHotLiver.quit()
            self.getHotLiver.wait(2000)
        if self.getFollows.isRunning():
            self.getFollows.quit()
            self.getFollows.wait(2000)

    def collectHotLiverChunk(self, page, hotLiverList):
        self.hotLiverDict[page] = hotLiverList
        if self.tabWidget.currentIndex() == 0 and self.currentPage == page:
            self.hotLiverTable.setEnabled(True)
            self._fillHotLiverTable(page)

    def collectHotLiverInfo(self, info):
        self.hotLiverDict = {}
        self.progressBar.hide()
        self.hotLiverTable.setEnabled(True)
        for page, hotLiverList in enumerate(info):
            self.hotLiverDict[page] = hotLiverList
        if self.tabWidget.currentIndex() == 0:
            self._fillHotLiverTable(self.currentPage)

    def _onTabChanged(self, index):
        if index == 0:
            self._fillHotLiverTable(self.currentPage)
        elif index == 2:
            self._fillFollowTable()

    def switchHotLiver(self, index):
        if not self.buttonList[index].pushToken:
            self.currentPage = index
            for cnt, button in enumerate(self.buttonList):
                if cnt == index:  # 点击的按钮
                    button.pushToken = True
                    button.setStyleSheet('background-color:#3daee9;border-width:1px')
                else:
                    button.pushToken = False
                    button.setStyleSheet('background-color:#31363b;border-width:1px')
            self._fillHotLiverTable(index)

    def _fillHotLiverTable(self, index):
        """填充热门直播表格数据"""
        hotLiverList = self.hotLiverDict.get(index, [])
        rowCount = max(len(hotLiverList), 30)
        self.hotLiverTable.clearContents()
        self.hotLiverTable.setColumnCount(3)
        self.hotLiverTable.setRowCount(rowCount)
        self.hotLiverTable.setVerticalHeaderLabels(['添加'] * rowCount)
        for i in range(rowCount):
            self.hotLiverTable.setRowHeight(i, 40)
        self.hotLiverTable.setHorizontalHeaderLabels(['主播名', '直播间标题', '直播间房号'])
        self.hotLiverTable.setColumnWidth(0, 130)
        self.hotLiverTable.setColumnWidth(1, 240)
        self.hotLiverTable.setColumnWidth(2, 130)
        for y, line in enumerate(hotLiverList):
            for x, txt in enumerate(line):
                try:
                    self.hotLiverTable.setItem(y, x, QTableWidgetItem(txt))
                except Exception:
                    logging.exception('热门直播表填充失败')

    def refreshHacoList(self):
        if self.refreshButton.text() == '更新中...':
            return
        self.refreshButton.clicked.disconnect(self.refreshHacoList)
        self.refreshButton.setText('更新中...')
        self.downloadVTBList.start()

    def vtbSearch(self):
        QDesktopServices.openUrl(QUrl(r'https://vtbs.moe/detail'))

    def collectVTBList(self, vtbList):
        try:
            with open(os.path.join(self.application_path, 'utils/vtb.csv'), 'w', encoding='utf-8') as vtbs:
                for line in vtbList:
                    vtbs.write(line)
            self.vtbList = []
            for line in vtbList:
                self.vtbList.append(line.split(','))
            self.hacoTable.clear()
            self.hacoTable.setRowCount(len(self.vtbList))
            self.hacoTable.setVerticalHeaderLabels(['添加'] * len(self.vtbList))
            for i in range(len(self.vtbList)):
                self.hacoTable.setRowHeight(i, 40)
            self.hacoTable.setHorizontalHeaderLabels(['主播名', '直播间房号', '所属'])
            for y, line in enumerate(self.vtbList):
                for x in range(3):
                    self.hacoTable.setItem(y, x, QTableWidgetItem(line[x]))
            QMessageBox.information(self, '更新VUP名单', '更新完成', QMessageBox.Ok)
        except Exception:
            logging.exception('vtb.csv 写入失败')
            QMessageBox.information(self, '更新VUP名单', '更新失败 请检查网络', QMessageBox.Ok)
        self.refreshButton.setText('更新名单')
        self.refreshButton.clicked.connect(self.refreshHacoList)

    def sendSelectedRoom(self):
        self.closeEvent(None)
        tmpList = self.roomEdit.text().strip().replace('\t', ' ').split(' ')
        roomList = {}
        for i in tmpList:
            if i.isnumeric():
                roomList[i] = False  # 全部统一为字符串格式的roomid
        self.roomList.emit(roomList)
        self.roomEdit.clear()
        self.hide()

    def hotLiverAdd(self, row):
        try:
            hotLiverList = self.hotLiverDict[self.currentPage]
            roomID = hotLiverList[row][2]
            addedRoomID = self.roomEdit.text()
            if roomID not in addedRoomID:
                addedRoomID += ' %s' % roomID
                self.roomEdit.setText(addedRoomID)
        except Exception:
            logging.exception('热门主播添加失败')

    def hacoAdd(self, row):
        try:
            roomID = self.vtbList[row][1]
            if roomID:
                addedRoomID = self.roomEdit.text()
                if roomID not in addedRoomID:
                    addedRoomID += ' %s' % roomID
                    self.roomEdit.setText(addedRoomID)
        except Exception:
            logging.exception('hacoAdd 失败')

    def setSessionData(self, sessionData):
        """接收登录凭据，传递给 GetFollows"""
        self.sessionData = sessionData if sessionData else ''
        self.credential = normalize_credential_data(getattr(self, 'credential', {}), sessdata=self.sessionData)
        self.getFollows.setSessionData(self.sessionData)
        self.getFollows.setCredential(self.credential)
        self.getHotLiver.setCredential(self.credential)

    def setCredential(self, credential):
        self.credential = normalize_credential_data(credential, sessdata=getattr(self, 'sessionData', ''))
        self.getHotLiver.setCredential(self.credential)
        self.getFollows.setCredential(self.credential)

    def checkFollows(self):
        if self.uidEdit.text().isdigit():
            if self.getFollows.isRunning():
                logging.warning('关注列表查询正在进行中，请稍候')
                return
            self.followRoomInfo = []
            self.followLiverList = []
            self._fillFollowTable()
            self.getFollows.setUID(self.uidEdit.text())
            self.getFollows.setSessionData(getattr(self, 'sessionData', ''))
            self.getFollows.setCredential(getattr(self, 'credential', {}))
            self.getFollows.start()

    def collectFollowLiverChunk(self, info):
        if not info:
            return
        self.followRoomInfo.extend(info)
        if self.tabWidget.currentIndex() == 2:
            self._fillFollowTable()

    def _fillFollowTable(self):
        sorted_info = sorted(self.followRoomInfo, key=lambda x: x[3] if len(x) > 3 else 0, reverse=True)
        self.followLiverList = []
        row_count = max(len(sorted_info), 500)
        self.followsTable.clearContents()
        self.followsTable.setColumnCount(3)
        self.followsTable.setRowCount(row_count)
        self.followsTable.setVerticalHeaderLabels(['添加'] * row_count)
        for i in range(row_count):
            self.followsTable.setRowHeight(i, 40)
        self.followsTable.setHorizontalHeaderLabels(['主播名', '直播间标题', '直播间房号'])
        self.followsTable.setColumnWidth(0, 130)
        self.followsTable.setColumnWidth(1, 240)
        self.followsTable.setColumnWidth(2, 130)
        for y, line in enumerate(sorted_info):
            room_id = str(line[2]) if len(line) > 2 else ''
            self.followLiverList.append(room_id)
            live_status = line[3] if len(line) > 3 else 0
            for x in range(min(3, len(line))):
                try:
                    item = QTableWidgetItem(str(line[x]))
                    if live_status == 1:
                        item.setForeground(QColor('#7FFFD4'))
                        if x == 0:
                            item.setText('● ' + str(line[x]))
                    self.followsTable.setItem(y, x, item)
                except Exception:
                    logging.exception('关注列表添加失败')

    def collectFollowLiverInfo(self, info):
        self.followRoomInfo = list(info)
        self._fillFollowTable()

    def followLiverAdd(self, row):
        try:
            roomID = self.followLiverList[row]
            addedRoomID = self.roomEdit.text()
            if roomID not in addedRoomID:
                addedRoomID += ' %s' % roomID
                self.roomEdit.setText(addedRoomID)
        except Exception:
            logging.exception('关注列表添加失败')


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
                liverInfo = []
                data = json.dumps({'ids': self.roomIDList})  # 根据直播间房号批量获取直播间信息
                r = http_utils.post(r'https://api.live.bilibili.com/room/v2/Room/get_by_ids', data=data, headers=header)
                r.encoding = 'utf8'
                payload = json.loads(r.text)
                room_uid_data = payload.get('data', {}) if isinstance(payload, dict) else {}
                uidList = []
                for roomID in room_uid_data:
                    uid = room_uid_data[roomID].get('uid')
                    if uid:
                        uidList.append(uid)

                status_data = {}
                if uidList:
                    data = json.dumps({'uids': uidList})
                    r = http_utils.post(r'https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids', data=data, headers=header)
                    r.encoding = 'utf8'
                    payload = json.loads(r.text)
                    status_data = payload.get('data', {}) if isinstance(payload, dict) else {}

                if status_data:
                    # 构建 room_id → info 字典，O(n) 查找替代 O(n*m) 嵌套循环
                    room_info_map = {info['room_id']: (uid, info) for uid, info in status_data.items()}
                    for roomID in self.roomIDList:
                        matched = room_info_map.get(roomID)
                        if matched:
                            uid, info = matched
                            keyframe = info.get('keyframe') or info.get('cover') or ''
                            liverInfo.append([
                                uid,
                                str(roomID),
                                info.get('uname', ''),
                                info.get('face', ''),
                                info.get('live_status', 0),
                                keyframe,
                                info.get('title', ''),
                                info.get('cover', ''),
                            ])
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
                'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom',
                params={'room_id': room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(data, dict):
                return ((data.get('anchor_info') or {}).get('base_info') or {}).get('uname', '')
        except Exception:
            pass

        try:
            response = http_utils.get(
                'https://api.live.bilibili.com/room/v1/Room/room_init',
                params={'id': room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(data, dict):
                uid = data.get('uid')
                if uid:
                    return f'UID:{uid}'
        except Exception:
            pass
        return ''

    @staticmethod
    def _fetch_room_detail(room_id):
        room_id = str(room_id)
        try:
            response = http_utils.get(
                'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom',
                params={'room_id': room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(data, dict):
                room_info = data.get('room_info') or {}
                anchor_info = (data.get('anchor_info') or {}).get('base_info') or {}
                resolved_room_id = room_info.get('room_id') or room_id
                uid = room_info.get('uid') or anchor_info.get('uid')
                uname = anchor_info.get('uname') or room_info.get('uname') or ''
                face = anchor_info.get('face') or ''
                live_status = room_info.get('live_status', 0)
                keyframe = room_info.get('keyframe') or room_info.get('cover') or ''
                title = room_info.get('title', '')
                return [uid if uid else None, str(resolved_room_id), uname, face, live_status, keyframe, title, room_info.get('cover', '')]
        except Exception:
            pass

        try:
            response = http_utils.get(
                'https://api.live.bilibili.com/room/v1/Room/room_init',
                params={'id': room_id},
                headers=header,
            )
            payload = response.json()
            data = payload.get('data') if isinstance(payload, dict) else None
            if isinstance(data, dict):
                resolved_room_id = data.get('room_id') or room_id
                uid = data.get('uid')
                if uid:
                    try:
                        status_resp = http_utils.post(
                            'https://api.live.bilibili.com/room/v1/Room/get_status_info_by_uids',
                            data=json.dumps({'uids': [uid]}),
                            headers=header,
                        )
                        status_payload = status_resp.json()
                        status_data = status_payload.get('data') if isinstance(status_payload, dict) else None
                        if isinstance(status_data, dict):
                            status_info = status_data.get(str(uid)) or status_data.get(uid)
                            if isinstance(status_info, dict):
                                keyframe = status_info.get('keyframe') or status_info.get('cover') or ''
                                return [
                                    uid,
                                    str(status_info.get('room_id') or resolved_room_id),
                                    status_info.get('uname', f'UID:{uid}'),
                                    status_info.get('face', ''),
                                    status_info.get('live_status', 0),
                                    keyframe,
                                    status_info.get('title', ''),
                                    status_info.get('cover', ''),
                                ]
                    except Exception:
                        pass
                    return [uid, str(resolved_room_id), f'UID:{uid}', '', 0, '', '', '']
        except Exception:
            pass

        uname = CollectLiverInfo._fetch_room_uname(room_id)
        if uname:
            return [1, room_id, uname, '', 0, '', '', '']
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
        self.addLiverRoomWidget = AddLiverRoomWidget(self.application_path)
        self.addLiverRoomWidget.roomList.connect(self.addLiverRoomList)
        self.addLiverRoomWidget.hotLiverTable.addToWindow.connect(self.addCoverToPlayer)
        self.multiple = 1
        self.layout = QGridLayout(self)
        self.layout.setSpacing(9)
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
        self.collectLiverInfo = CollectLiverInfo(self._buildRoomIDListForCollector())
        self.collectLiverInfo.liverInfo.connect(self.refreshRoomPanel)
        self.collectLiverInfo.start()

    @staticmethod
    def _normalize_room_id(room_id):
        return str(room_id or '').strip()

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
                logging.warning(f'忽略非法房号: {room_id}')
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
        """接收登录凭据，传递给 AddLiverRoomWidget"""
        self.addLiverRoomWidget.setSessionData(sessionData)
        self._sessionData = sessionData

    def setCredential(self, credential):
        self.addLiverRoomWidget.setCredential(credential)
        self._credential = credential

    def autoFetchFollows(self, uid):
        """自动获取关注列表并添加到面板（登录后自动触发）"""
        sessdata = getattr(self.addLiverRoomWidget, 'sessionData', '')
        self.addLiverRoomWidget.getFollows.setUID(uid)
        self.addLiverRoomWidget.getFollows.setSessionData(sessdata)
        self.addLiverRoomWidget.getFollows.setCredential(getattr(self.addLiverRoomWidget, 'credential', {}))
        if not self.addLiverRoomWidget.getFollows.isRunning():
            logging.info(f'自动获取 UID={uid} 的关注列表 (sessdata={"有" if sessdata else "无"})')
            self.addLiverRoomWidget.getFollows.start()

    def openLiverRoomPanel(self):
        self.addLiverRoomWidget._fillHotLiverTable(self.addLiverRoomWidget.currentPage)
        if not self.addLiverRoomWidget.getHotLiver.isRunning():
            self.addLiverRoomWidget.getHotLiver.start()
        self.addLiverRoomWidget.hide()
        self.addLiverRoomWidget.show()

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
                        logging.warning(f'短号解析失败，保持原房号: {roomID}')
                except Exception:
                    logging.exception('房间号查询失败，保持原房号')
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
            self.roomIDDict[roomID] = bool(topToken)
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    @staticmethod
    def _resolve_short_room_id(room_id):
        room_id = str(room_id)
        try:
            response = http_utils.get(
                'https://api.live.bilibili.com/xlive/web-room/v1/index/getInfoByRoom',
                params={'room_id': room_id},
                headers=header,
            )
            payload = response.json()
            if payload.get('code') == 0 and isinstance(payload.get('data'), dict):
                room_info = payload['data'].get('room_info', {})
                resolved = room_info.get('room_id') or payload['data'].get('room_id')
                if resolved:
                    return str(resolved)
        except Exception:
            pass

        try:
            response = http_utils.get(
                'https://api.live.bilibili.com/room/v1/Room/room_init',
                params={'id': room_id},
                headers=header,
            )
            payload = response.json()
            if payload.get('code') == 0 and isinstance(payload.get('data'), dict):
                resolved = payload['data'].get('room_id')
                if resolved:
                    return str(resolved)
        except Exception:
            pass
        return None

    def refreshRoomPanel(self, liverInfo):  # 异步刷新图卡
        self.refreshCount += 1  # 刷新计数+1
        roomIDToRefresh = []
        roomIDStartLive = []
        firstRefresh = False
        for index, info in enumerate(liverInfo):
            if info[0]:  # uid有效
                for cover in self.coverList:
                    if cover.roomID == info[1]:  # 字符串房号
                        if cover.recordState == 2 and cover.liveState == 0 and info[4] == 1:  # 满足等待开播录制的3个条件
                            cover.recordThread.setSavePath(cover.savePath)  # 启动录制线程
                            cover.recordThread.setCredential(self._credential, self._sessionData)
                            cover.recordThread.start()
                            cover.recordThread.checkTimer.start(3000)
                            cover.recordState = 1  # 改为录制状态
                        elif cover.recordState == 1 and info[4] != 1:  # 满足停止录制的2个条件
                            cover.recordState = 0  # 取消录制
                            cover.recordThread.recordToken = False  # 设置录像线程标志位让它自行退出结束
                        cover.updateLabel(info)  # 更新数据
                if info[1] not in self.oldLiveStatus:  # 软件启动后第一次更新添加
                    self.oldLiveStatus[info[1]] = info[4]  # 房号: 直播状态
                    firstRefresh = True  # 第一次刷新
                elif self.oldLiveStatus[info[1]] != info[4]:  # 状态发生变化
                    if info[4] == 1:
                        roomIDStartLive.append(info[2])  # 添加开播主播名字
                    roomIDToRefresh.append(info[1])  # 发送给主界面要刷新的房间号
                    self.oldLiveStatus[info[1]] = info[4]  # 更新旧的直播状态列表
            else:  # 错误的房号
                for cover in self.coverList:
                    if cover.roomID == info[1]:
                        cover.updateLabel(info)
        if roomIDStartLive:
            self.startLiveList.emit(roomIDStartLive)
        self.refreshPanel()

    def addCoverToPlayer(self, info):
        self.addToWindow.emit(info)

    def deleteCover(self, roomID):
        roomID = self._normalize_room_id(roomID)
        self.roomIDDict.pop(roomID, None)
        self.oldLiveStatus.pop(roomID, None)
        for index, cover in enumerate(list(self.coverList)):
            if cover.roomID == roomID:
                cover.hide()
                self.layout.removeWidget(cover)
                self.coverList.pop(index)
                cover.setParent(None)
                cover.deleteLater()
                break
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    def deleteAll(self):
        """清空卡片槽 — 释放所有卡片控件并清理房间列表"""
        self.roomIDDict.clear()
        self.oldLiveStatus.clear()
        for cover in self.coverList:
            cover.hide()
            cover.deleteLater()
        self.coverList.clear()
        # _onDumpRoomConfig 会将空 roomid 写入 config 并保存
        self._applyRoomListMutation(request_refresh=True, refresh_panel=True, dump_config=True)

    def changeTop(self, info):
        roomID = self._normalize_room_id(info[0] if info else '')
        top_token = bool(info[1]) if isinstance(info, (list, tuple)) and len(info) > 1 else False
        if roomID in self.roomIDDict:
            self.roomIDDict[roomID] = top_token
        for cover in self.coverList:
            if cover.roomID == roomID:
                cover.topToken = top_token
                break
        self._applyRoomListMutation(request_refresh=False, refresh_panel=True, dump_config=True)

    def updatePlayingStatus(self, playerList):
        for cover in self.coverList:
            if cover.roomID in playerList:
                cover.isPlaying = True
                cover.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:red;background-color:#5a636d}')
            else:
                cover.isPlaying = False
                if cover.topToken:
                    cover.setStyleSheet('#cover{border-width:3px;border-style:solid;border-color:#dfa616;background-color:#5a636d}')
                else:
                    cover.setStyleSheet('#cover{border-width:0px;background-color:#5a636d}')

    def refreshPanel(self):
        for i in reversed(range(self.layout.count())):
            item = self.layout.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                self.layout.removeWidget(widget)

        for cover in self.coverList:
            cover.hide()

        tmpList = []
        for topToken in [True, False]:
            for liveState in [1, 0, -1]:  # 按顺序添加正在直播的 没在直播的 还有错误的卡片
                for cover in self.coverList:
                    if cover.liveState == liveState and cover.topToken == topToken and cover.roomID != '0':  # 符合条件的卡片
                        tmpList.append(cover)

        for cnt, cover in enumerate(tmpList):
            self.layout.addWidget(cover, cnt // self.multiple, cnt % self.multiple)
            cover.show()
        self.adjustSize()

    def getFirstRoomID(self):
        """获取卡片面板中第一个有效的房间号（用于快捷键加载）"""
        for roomID in self.roomIDDict:
            if roomID and roomID != '0':
                return str(roomID)
        return ''
