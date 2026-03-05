"""
DD监控室视频播放窗口 - MPV 内核版本
使用 python-mpv 库直接播放直播流 URL，无需本地 FLV 缓存下载
相比 VLC 版本：启动更快，CPU 占用更低，支持更多格式
"""
import requests
import json
import os
import time
import shutil
import random
from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *
from CommonWidget import Slider
from remote import remoteThread
from danmu import TextBrowser, MpvDanmakuRenderer
import platform
import logging
import warnings
from datetime import datetime

# 确保 libmpv-2.dll 可被找到（将项目目录加入 PATH）
os.environ["PATH"] = os.path.dirname(os.path.abspath(__file__)) + os.pathsep + os.environ["PATH"]

try:
    import mpv
    HAS_MPV = True
except (ImportError, OSError):
    HAS_MPV = False
    logging.warning('python-mpv 未安装或 libmpv 未找到')

header = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


class PushButton(QPushButton):
    """文字/图标按钮"""

    def __init__(self, icon='', text=''):
        super(PushButton, self).__init__()
        self.setFixedSize(30, 30)
        self.setStyleSheet('background-color:#00000000')
        if icon:
            self.setIcon(icon)
        elif text:
            self.setText(text)


class GetStreamURL(QThread):
    """获取直播流地址
    MPV 版本不再下载 FLV 到本地，只获取流地址后直接交给 MPV 播放
    """
    streamUrl = Signal(str)
    downloadError = Signal()

    def __init__(self, sessionData=''):
        super(GetStreamURL, self).__init__()
        self.roomID = '0'
        self.quality = 250
        self.sessionData = sessionData if sessionData else ''
        # 兼容性属性 - DD监控室.py closeEvent 中会访问这些属性
        self.recordToken = False
        self.checkTimer = QTimer(self)

    def setConfig(self, roomID, quality, sessionData):
        self.roomID = roomID
        self.quality = quality
        self.sessionData = sessionData if sessionData else ''

    def getStreamUrl(self):
        url = "https://api.live.bilibili.com/xlive/app-room/v2/index/getRoomPlayInfo"
        onlyAudio = self.quality < 0
        params = {
            "appkey": "iVGUTjsxvpLeuDCf",
            "build": 6250300,
            "c_locale": "zh_CN",
            "channel": "bili",
            "codec": 0,
            "device": "android",
            "device_name": "MuMu",
            "dolby": 1,
            "format": "0,2",
            "free_type": 0,
            "http": 1,
            "mask": 0,
            "mobi_app": "android",
            "network": "wifi",
            "no_playurl": 0,
            "only_audio": int(onlyAudio),
            "only_video": 0,
            "platform": "android",
            "play_type": 0,
            "protocol": "0,1",
            "qn": (onlyAudio and 10000) or (not onlyAudio and self.quality),
            "room_id": self.roomID,
            "s_locale": "zh_CN",
            "statistics": '{"appId":1,"platform":3,"version":"6.25.0","abtest":""}',
            "ts": int(time.time())
        }
        cookies = {}
        if self.sessionData:
            cookies['SESSDATA'] = self.sessionData

        r = requests.get(url, params=params, headers=header, cookies=cookies)
        j = r.json()
        baseUrl = j['data']['playurl_info']['playurl']['stream'][0]['format'][0]['codec'][0]['base_url']
        extra = j['data']['playurl_info']['playurl']['stream'][0]['format'][0]['codec'][0]['url_info'][0]['extra']
        host = j['data']['playurl_info']['playurl']['stream'][0]['format'][0]['codec'][0]['url_info'][0]['host']
        streamUrl = host + baseUrl + extra
        return streamUrl

    def run(self):
        try:
            url = self.getStreamUrl()
            self.streamUrl.emit(url)
        except Exception as e:
            logging.error(str(e))
            logging.exception('直播地址获取失败')
            self.downloadError.emit()


class VideoFrame(QFrame):
    """视频播放容器"""
    rightClicked = Signal(QEvent)
    leftClicked = Signal()
    doubleClicked = Signal()

    def __init__(self):
        super(VideoFrame, self).__init__()
        self.setAcceptDrops(True)

    def mousePressEvent(self, QMouseEvent):
        if QMouseEvent.button() == Qt.RightButton:
            self.rightClicked.emit(QMouseEvent)
        elif QMouseEvent.button() == Qt.LeftButton:
            self.leftClicked.emit()

    def mouseDoubleClickEvent(self, QMouseEvent):
        self.doubleClicked.emit()


class ExportCache(QThread):
    """导出缓存的视频（兼容保留）"""
    finish = Signal(list)

    def __init__(self):
        super(ExportCache, self).__init__()
        self.ori = ''
        self.dst = ''
        self.cut = False

    def setArgs(self, ori, dst):
        self.ori, self.dst = ori, dst

    def run(self):
        try:
            if self.cut:
                shutil.move(self.ori, self.dst)
                self.cut = False
            else:
                shutil.copy(self.ori, self.dst)
                self.finish.emit([True, self.dst])
        except Exception:
            logging.exception('导出缓存失败')
            self.finish.emit([False, self.dst])


class ExportTip(QWidget):
    """导出提示"""

    def __init__(self):
        super(ExportTip, self).__init__()
        self.resize(600, 100)


class VideoWidget(QFrame):
    """
    视频播放窗口 - MPV 内核版本
    公共接口与 VideoWidget_vlc.py 保持一致，确保 DD监控室.py 可无缝切换
    """
    mutedChanged = Signal(list)
    volumeChanged = Signal(list)
    addMedia = Signal(list)
    deleteMedia = Signal(int)
    exchangeMedia = Signal(list)
    setDanmu = Signal()
    setTranslator = Signal(list)
    changeQuality = Signal(list)
    changeAudioChannel = Signal(list)
    popWindow = Signal(list)
    hideBarKey = Signal()
    fullScreenKey = Signal()
    muteExceptKey = Signal()
    closePopWindow = Signal(list)

    def __init__(self, id, volume, cacheFolder, top=False, title='', resize=[],
                 textSetting=[True, 20, 2, 6, 0, '【 [ {', 10, 0], maxCacheSize=2048000,
                 saveCachePath='', startWithDanmu=True, hardwareDecode=True, sessionData=''):
        super(VideoWidget, self).__init__()
        self.setAcceptDrops(True)
        self.installEventFilter(self)
        self.id = id
        self.title = ''
        self.uname = ''
        self.oldTitle = ''
        self.oldUname = ''
        self.hoverToken = False
        self.roomID = '0'
        self.liveStatus = 0
        self.liveStartTime = 0
        self.pauseToken = False
        self.quality = 250
        self.audioChannel = 0
        self.volume = volume
        self.volumeAmplify = 1.0
        self.muted = False
        self.hardwareDecode = hardwareDecode
        self.sessionData = sessionData if sessionData else ''
        self.leftButtonPress = False
        self.rightButtonPress = False
        self.fullScreen = False
        self.userPause = False
        self.cacheName = ''
        self.maxCacheSize = maxCacheSize
        self.saveCachePath = saveCachePath
        self.startWithDanmu = startWithDanmu
        self.retryTimes = 0
        self._mpv = None  # 延迟初始化
        self._stream_url = ''

        # 容器设置
        self.setFrameShape(QFrame.Box)
        self.setObjectName('video')

        self.top = top
        self.name_str = f"悬浮窗{self.id}" if self.top else f"嵌入窗{self.id}"
        if top:
            self.setWindowFlags(Qt.Window)
        else:
            self.setStyleSheet(
                '#video{border-width:1px;border-style:solid;border-color:gray}')
        self.textSetting = textSetting
        self.horiPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][self.textSetting[2]]
        self.vertPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][self.textSetting[3]]
        self.filters = textSetting[5].split(' ')
        self.opacity = 100
        if top:
            self.setWindowFlag(Qt.WindowStaysOnTopHint)
        if title:
            if top:
                self.setWindowTitle('%s %s' % (title, id + 1 - 9))
            else:
                self.setWindowTitle('%s %s' % (title, id + 1))

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # ---- 弹幕机 ----
        self.textBrowser = TextBrowser(self)
        self.setDanmuOpacity(self.textSetting[1])
        self.textBrowser.optionWidget.opacitySlider.setValue(
            self.textSetting[1])
        self.textBrowser.optionWidget.opacitySlider.value.connect(
            self.setDanmuOpacity)
        self.setHorizontalPercent(self.textSetting[2])
        self.textBrowser.optionWidget.horizontalCombobox.setCurrentIndex(
            self.textSetting[2])
        self.textBrowser.optionWidget.horizontalCombobox.currentIndexChanged.connect(
            self.setHorizontalPercent)
        self.setVerticalPercent(self.textSetting[3])
        self.textBrowser.optionWidget.verticalCombobox.setCurrentIndex(
            self.textSetting[3])
        self.textBrowser.optionWidget.verticalCombobox.currentIndexChanged.connect(
            self.setVerticalPercent)
        self.setTranslateBrowser(self.textSetting[4])
        self.textBrowser.optionWidget.translateCombobox.setCurrentIndex(
            self.textSetting[4])
        self.textBrowser.optionWidget.translateCombobox.currentIndexChanged.connect(
            self.setTranslateBrowser)
        self.setTranslateFilter(self.textSetting[5])
        self.textBrowser.optionWidget.translateFitler.setText(
            self.textSetting[5])
        self.textBrowser.optionWidget.translateFitler.textChanged.connect(
            self.setTranslateFilter)
        self.setFontSize(self.textSetting[6])
        self.textBrowser.optionWidget.fontSizeCombox.setCurrentIndex(
            self.textSetting[6])
        self.textBrowser.optionWidget.fontSizeCombox.currentIndexChanged.connect(
            self.setFontSize)
        self.setMsgsBrowser(self.textSetting[7])
        self.textBrowser.optionWidget.showEnterRoom.setCurrentIndex(
            self.textSetting[7])
        self.textBrowser.optionWidget.showEnterRoom.currentIndexChanged.connect(
            self.setMsgsBrowser)

        self.textBrowser.closeSignal.connect(self.closeDanmu)
        self.textBrowser.moveSignal.connect(self.moveTextBrowser)
        if not self.startWithDanmu:
            self.textSetting[0] = False
            self.textBrowser.hide()

        self.textPosDelta = QPoint(0, 0)
        self.deltaX = 0
        self.deltaY = 0

        # ---- 播放器布局 ----
        self.videoFrame = VideoFrame()
        self.videoFrame.rightClicked.connect(self.rightMouseClicked)
        self.videoFrame.leftClicked.connect(self.leftMouseClicked)
        self.videoFrame.doubleClicked.connect(self.doubleClick)
        layout.addWidget(self.videoFrame, 0, 0, 12, 12)

        # ---- MPV OSD 滚动弹幕渲染器 ----
        self.scrollingDanmaku = MpvDanmakuRenderer()

        # 直播间标题
        self.topLabel = QLabel()
        self.topLabel.setFixedHeight(30)
        self.topLabel.setObjectName('frame')
        self.topLabel.setStyleSheet("background-color:#293038")
        self.topLabel.setFont(QFont('微软雅黑', 15, QFont.Bold))
        layout.addWidget(self.topLabel, 0, 0, 1, 12)
        self.topLabel.hide()

        # 控制栏
        self.frame = QWidget()
        self.frame.setObjectName('frame')
        self.frame.setStyleSheet("background-color:#293038")
        self.frame.setFixedHeight(50)
        frameLayout = QHBoxLayout(self.frame)
        frameLayout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.frame, 11, 0, 1, 12)
        self.frame.hide()

        self.titleLabel = QLabel()
        self.titleLabel.setMaximumWidth(135)
        self.titleLabel.setStyleSheet('background-color:#00000000')
        self.setTitle()
        frameLayout.addWidget(self.titleLabel)
        self.timestampLabel = QLabel()
        self.timestampLabel.setMaximumWidth(100)
        self.timestampLabel.setStyleSheet('background-color:#00000000')
        self.timestampLabel.setText('0:00:00')
        frameLayout.addWidget(self.timestampLabel)
        self.play = PushButton(self.style().standardIcon(QStyle.SP_MediaPause))
        self.play.clicked.connect(self.mediaPlay)
        frameLayout.addWidget(self.play)
        self.reload = PushButton(
            self.style().standardIcon(QStyle.SP_BrowserReload))
        self.reload.clicked.connect(self.mediaReload)
        frameLayout.addWidget(self.reload)
        self.volumeButton = PushButton(
            self.style().standardIcon(QStyle.SP_MediaVolume))
        self.volumeButton.clicked.connect(self.mediaMute)
        frameLayout.addWidget(self.volumeButton)
        self.slider = Slider()
        self.slider.setStyleSheet('background-color:#00000000')
        self.slider.value.connect(self.setVolume)
        frameLayout.addWidget(self.slider)
        self.danmuButton = PushButton(text='弹')
        self.danmuButton.clicked.connect(self.showDanmu)
        frameLayout.addWidget(self.danmuButton)
        self.stop = PushButton(self.style().standardIcon(
            QStyle.SP_DialogCancelButton))
        self.stop.clicked.connect(self._mediaStop)
        frameLayout.addWidget(self.stop)

        # ---- IO 线程 ----
        self.getMediaURL = GetStreamURL(self.sessionData)
        self.getMediaURL.streamUrl.connect(self.setMedia)
        self.getMediaURL.downloadError.connect(self.mediaReload)

        self.danmu = remoteThread(self.roomID, self.sessionData)

        self.exportCache = ExportCache()
        self.exportCache.finish.connect(self.exportFinish)
        self.exportTip = ExportTip()

        # ---- 定时器 ----
        self.moveTimer = QTimer(self)
        self.moveTimer.timeout.connect(self.initTextPos)
        self.moveTimer.start(50)

        self.checkPlaying = QTimer(self)
        self.checkPlaying.timeout.connect(self.checkPlayStatus)

        if resize:
            self.resize(resize[0], resize[1])
        logging.info(f"{self.name_str} MPV 播放器构造完毕, 置顶?: {self.top}, 启用弹幕?: {self.startWithDanmu}")

        self.refreshTimeStampTimer = QTimer(self)
        self.refreshTimeStampTimer.timeout.connect(self.refreshTimeStamp)
        self.refreshTimeStampTimer.setInterval(1000)

    # ==== MPV 播放器管理 ====

    def _init_mpv(self):
        """延迟初始化 MPV 播放器 - 仅在需要播放时创建"""
        if self._mpv is not None:
            return
        if not HAS_MPV:
            logging.error('无法初始化 MPV: python-mpv 未安装或 libmpv 未找到')
            return
        try:
            wid = str(int(self.videoFrame.winId()))
            self._mpv = mpv.MPV(
                wid=wid,
                input_cursor='no',
                input_default_bindings='no',
                osd_level=0,
                keep_open='yes',
                idle='yes',
                hwdec='auto' if self.hardwareDecode else 'no',
                volume=self.volume,
                cache='yes',
                demuxer_max_bytes='50MiB',
                demuxer_max_back_bytes='20MiB',
            )
            logging.info(f'{self.name_str} MPV 实例已创建')
            # 绑定弹幕渲染器到 MPV
            self.scrollingDanmaku.setMpv(self._mpv)
        except Exception:
            logging.exception(f'{self.name_str} MPV 初始化失败')
            self._mpv = None

    def get_volume(self):
        """获取当前音量"""
        if self._mpv:
            try:
                return int(self._mpv.volume or 0)
            except Exception:
                return 0
        return 0

    def set_volume_direct(self, value):
        """直接设置音量（给 DD监控室.py 全局音量调用）"""
        if self._mpv:
            try:
                self._mpv.volume = int(value)
            except Exception:
                pass

    def get_mute(self):
        """获取静音状态"""
        if self._mpv:
            try:
                return bool(self._mpv.mute)
            except Exception:
                return False
        return False

    def set_audio_channel(self, channel):
        """设置音频通道（MPV 兼容层）"""
        self.audioChannel = channel

    # ==== 播放状态检测 ====

    def checkPlayStatus(self):
        """检测播放是否卡住"""
        if self._mpv and not self.isHidden() and self.liveStatus == 1 and not self.userPause:
            try:
                idle = self._mpv.core_idle
                if idle:
                    self.retryTimes += 1
                    if self.retryTimes > 10:
                        self.mediaReload()
                else:
                    self.retryTimes = 0
            except Exception:
                self.retryTimes += 1
                if self.retryTimes > 10:
                    self.mediaReload()

    def refreshTimeStamp(self):
        if self.liveStartTime:
            duration = time.time() - self.liveStartTime
            h, m = divmod(duration, 3600)
            m, s = divmod(m, 60)
            self.timestampLabel.setText('%01d:%02d:%02d' % (h, m, s))

    # ==== 弹幕机设置 ====

    def initTextPos(self):
        videoPos = self.mapToGlobal(self.videoFrame.pos())
        if self.textBrowser.pos() != videoPos:
            self.textBrowser.move(videoPos)
        else:
            self.moveTimer.stop()

    def setDanmuOpacity(self, value):
        if value < 7:
            value = 7
        self.textSetting[1] = value
        value = int(value / 101 * 256)
        color = str(hex(value))[2:] + '000000'
        self.textBrowser.textBrowser.setStyleSheet(
            'background-color:#%s' % color)
        self.textBrowser.transBrowser.setStyleSheet(
            'background-color:#%s' % color)
        self.textBrowser.msgsBrowser.setStyleSheet(
            'background-color:#%s' % color)
        self.setDanmu.emit()

    def setHorizontalPercent(self, index):
        self.textSetting[2] = index
        self.horiPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][index]
        width = self.width() * self.horiPercent
        self.textBrowser.resize(width, self.textBrowser.height())
        self.textBrowser.textBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.transBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.msgsBrowser.verticalScrollBar().setValue(100000000)
        self.setDanmu.emit()

    def setVerticalPercent(self, index):
        self.textSetting[3] = index
        self.vertPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][index]
        self.textBrowser.resize(self.textBrowser.width(),
                                self.height() * self.vertPercent)
        self.textBrowser.textBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.transBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.msgsBrowser.verticalScrollBar().setValue(100000000)
        self.setDanmu.emit()

    def setTranslateBrowser(self, index):
        self.textSetting[4] = index
        if index == 0:
            self.textBrowser.textBrowser.show()
            self.textBrowser.transBrowser.show()
        elif index == 1:
            self.textBrowser.transBrowser.hide()
            self.textBrowser.textBrowser.show()
        elif index == 2:
            self.textBrowser.textBrowser.hide()
            self.textBrowser.transBrowser.show()
        self.textBrowser.resize(
            self.width() * self.horiPercent, self.height() * self.vertPercent)
        self.setDanmu.emit()

    def setMsgsBrowser(self, index):
        self.textSetting[7] = index
        if index < 3:
            self.textBrowser.msgsBrowser.show()
        elif index == 3:
            self.textBrowser.msgsBrowser.hide()
        self.textBrowser.resize(
            self.width() * self.horiPercent, self.height() * self.vertPercent)
        self.setDanmu.emit()

    def setTranslateFilter(self, filterWords):
        self.textSetting[5] = filterWords
        self.filters = filterWords.split(' ')
        self.setDanmu.emit()

    def setFontSize(self, index):
        self.textSetting[6] = index
        self.textBrowser.textBrowser.setFont(
            QFont('Microsoft JhengHei', index + 5, QFont.Bold))
        self.textBrowser.transBrowser.setFont(
            QFont('Microsoft JhengHei', index + 5, QFont.Bold))
        self.textBrowser.msgsBrowser.setFont(
            QFont('Microsoft JhengHei', index + 5, QFont.Bold))
        self.setDanmu.emit()

    def resizeEvent(self, QEvent):
        try:
            self.titleLabel.hide() if self.width() < 350 else self.titleLabel.show()
            self.play.hide() if self.width() < 300 else self.play.show()
            self.danmuButton.hide() if self.width() < 250 else self.danmuButton.show()
            self.slider.hide() if self.width() < 200 else self.slider.show()
            width = self.width() * self.horiPercent
            self.textBrowser.resize(width, self.height() * self.vertPercent)
            self.textBrowser.textBrowser.verticalScrollBar().setValue(100000000)
            self.textBrowser.transBrowser.verticalScrollBar().setValue(100000000)
            self.textBrowser.msgsBrowser.verticalScrollBar().setValue(100000000)
            self.moveTextBrowser()
        except Exception:
            pass

    def moveEvent(self, QMoveEvent):
        videoPos = self.mapToGlobal(self.videoFrame.pos())
        self.textBrowser.move(videoPos + self.textPosDelta)

    def moveTextBrowser(self, point=None):
        videoPos = self.mapToGlobal(self.videoFrame.pos())
        if point:
            danmuX, danmuY = point.x(), point.y()
        else:
            danmuX, danmuY = self.textBrowser.x(), self.textBrowser.y()
        videoX, videoY = videoPos.x(), videoPos.y()
        videoW, videoH = self.videoFrame.width(), self.videoFrame.height()
        danmuW, danmuH = self.textBrowser.width(), self.textBrowser.height()
        smaller = False
        if danmuW > videoW or danmuH > videoH + 5:
            danmuX, danmuY = videoX, videoY
            smaller = True
        if not smaller:
            if danmuX < videoX:
                danmuX = videoX
            elif danmuX > videoX + videoW - danmuW:
                danmuX = videoX + videoW - danmuW
            if danmuY < videoY:
                danmuY = videoY
            elif danmuY > videoY + videoH - danmuH:
                danmuY = videoY + videoH - danmuH
        self.textBrowser.move(danmuX, danmuY)
        self.textPosDelta = self.textBrowser.pos() - videoPos
        self.deltaX, self.deltaY = self.textPosDelta.x(
        ) / max(self.width(), 1), self.textPosDelta.y() / max(self.height(), 1)

    def enterEvent(self, QEvent):
        self.hoverToken = True
        self.topLabel.show()
        self.frame.show()

    def leaveEvent(self, QEvent):
        self.hoverToken = False
        self.topLabel.hide()
        self.frame.hide()

    def doubleClick(self):
        if not self.top:
            self.popWindow.emit(
                [self.id, self.roomID, self.quality, True, self.startWithDanmu])
            self.mediaStop()

    def leftMouseClicked(self):
        drag = QDrag(self)
        mimeData = QMimeData()
        if self.top:
            mimeData.setText('')
        else:
            mimeData.setText('exchange:%s:%s' % (self.id, self.roomID))
        drag.setMimeData(mimeData)
        drag.exec_()

    def dragEnterEvent(self, QDragEnterEvent):
        QDragEnterEvent.accept()

    def dropEvent(self, QDropEvent):
        if QDropEvent.mimeData().hasText:
            text = QDropEvent.mimeData().text()
            if 'roomID' in text:
                self.stopDanmuMessage()
                self.roomID = text.split(':')[1]
                self.addMedia.emit([self.id, self.roomID])
                self.mediaReload()
                self.textBrowser.textBrowser.clear()
                self.textBrowser.transBrowser.clear()
                self.textBrowser.msgsBrowser.clear()
            elif 'exchange' in text:
                fromID, fromRoomID = text.split(':')[1:]
                fromID = int(fromID)
                if fromID != self.id:
                    self.exchangeMedia.emit(
                        [fromID, fromRoomID, self.id, self.roomID])

    def rightMouseClicked(self, event):
        menu = QMenu()
        openBrowser = menu.addAction('打开直播间')
        chooseQuality = menu.addMenu('选择画质 ►')
        originQuality = chooseQuality.addAction('原画')
        if self.quality == 10000:
            originQuality.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        bluerayQuality = chooseQuality.addAction('蓝光')
        if self.quality == 400:
            bluerayQuality.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        highQuality = chooseQuality.addAction('超清')
        if self.quality == 250:
            highQuality.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        lowQuality = chooseQuality.addAction('流畅')
        if self.quality == 80:
            lowQuality.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        onlyAudio = chooseQuality.addAction('仅播声音')
        if self.quality == -1:
            onlyAudio.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        chooseAmplify = menu.addMenu('音量增大 ►')
        ampActions = {}
        for amp_val in [0.5, 1.0, 1.5, 2.0, 3.0, 4.0]:
            action = chooseAmplify.addAction('x %.1f' % amp_val)
            if self.volumeAmplify == amp_val:
                action.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
            ampActions[action] = amp_val

        if not self.top:
            popWindow = menu.addAction('悬浮窗播放')
        else:
            opacityMenu = menu.addMenu('调节透明度 ►')
            opacityActions = {}
            for pct in [100, 80, 60, 40, 20]:
                act = opacityMenu.addAction(f'{pct}%')
                if self.opacity == pct:
                    act.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
                opacityActions[act] = pct
            fullScreen = menu.addAction(
                '退出全屏') if self.isFullScreen() else menu.addAction('全屏')
            exit = menu.addAction('退出')

        action = menu.exec_(self.mapToGlobal(event.pos()))
        if action == openBrowser:
            if self.roomID != '0':
                QDesktopServices.openUrl(
                    QUrl(r'https://live.bilibili.com/%s' % self.roomID))
        elif action == originQuality:
            self.changeQuality.emit([self.id, 10000])
            self.quality = 10000
            self.mediaReload()
        elif action == bluerayQuality:
            self.changeQuality.emit([self.id, 400])
            self.quality = 400
            self.mediaReload()
        elif action == highQuality:
            self.changeQuality.emit([self.id, 250])
            self.quality = 250
            self.mediaReload()
        elif action == lowQuality:
            self.changeQuality.emit([self.id, 80])
            self.quality = 80
            self.mediaReload()
        elif action == onlyAudio:
            self.changeQuality.emit([self.id, -1])
            self.quality = -1
            self.mediaReload()
        elif action in ampActions:
            self.volumeAmplify = ampActions[action]
            self._applyVolume()
        if not self.top:
            if action == popWindow:
                self.popWindow.emit(
                    [self.id, self.roomID, self.quality, False, self.startWithDanmu])
                self.mediaStop()
        elif self.top:
            if action in opacityActions:
                pct = opacityActions[action]
                self.setWindowOpacity(pct / 100.0)
                self.opacity = pct
            elif action == fullScreen:
                if self.isFullScreen():
                    self.showNormal()
                else:
                    self.showFullScreen()
            elif action == exit:
                self.closePopWindow.emit([self.id, self.roomID])
                self.hide()
                self.mediaStop()
                self.textBrowser.hide()

    def closeEvent(self, event):
        event.ignore()
        if self.top:
            self.closePopWindow.emit([self.id, self.roomID])
            self.hide()
            self.mediaStop()
            self.textBrowser.hide()

    def exportFinish(self, result):
        self.exportTip.hide()
        if result[0]:
            QMessageBox.information(self, '导出完成', result[1], QMessageBox.Ok)
        else:
            QMessageBox.information(self, '导出失败', result[1], QMessageBox.Ok)

    # ==== 音量控制 ====

    def _applyVolume(self):
        """应用音量和静音设置到 MPV"""
        if self._mpv:
            try:
                target_vol = int(self.volume * self.volumeAmplify)
                self._mpv.volume = target_vol
                self._mpv.mute = self.muted
            except Exception:
                pass

    def setVolume(self, value):
        self.volume = value
        self.slider.setValue(value)
        self._applyVolume()
        self.volumeChanged.emit([self.id, value])

    def closeDanmu(self):
        self.textSetting[0] = False

    def stopDanmuMessage(self):
        self.stopDanmu()

    def showDanmu(self):
        if self.textBrowser.isHidden():
            self.textBrowser.show()
            if not self.startWithDanmu:
                self.danmu.message.connect(self.playDanmu)
                self.danmu.stop()
                self.danmu.wait(500)
                self.danmu.start()
                self.textSetting[0] = True
                self.startWithDanmu = True
        else:
            self.textBrowser.hide()
            self.startWithDanmu = False
        self.textSetting[0] = not self.textBrowser.isHidden()
        self.setDanmu.emit()

    # ==== 播放控制 ====

    def mediaPlay(self, force=0, stopDownload=False, setUserPause=False):
        if force == 1:  # 暂停
            if self._mpv:
                try:
                    self._mpv.pause = True
                except Exception:
                    pass
            if setUserPause:
                self.userPause = True
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        elif force == 2:  # 播放
            if self._mpv:
                try:
                    self._mpv.pause = False
                except Exception:
                    pass
            if setUserPause:
                self.userPause = False
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:  # 切换
            is_paused = True
            if self._mpv:
                try:
                    is_paused = self._mpv.pause
                except Exception:
                    is_paused = True
            if not is_paused:
                if self._mpv:
                    try:
                        self._mpv.pause = True
                    except Exception:
                        pass
                self.userPause = True
                self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            else:
                if self._mpv:
                    try:
                        self._mpv.pause = False
                    except Exception:
                        pass
                self.userPause = False
                self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        if stopDownload:
            self.checkPlaying.stop()

    def mediaMute(self, force=0, emit=True):
        if force == 1:
            self.muted = False
            self.volumeButton.setIcon(
                self.style().standardIcon(QStyle.SP_MediaVolume))
        elif force == 2:
            self.muted = True
            self.volumeButton.setIcon(
                self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
        elif self.muted:
            self.muted = False
            self.volumeButton.setIcon(
                self.style().standardIcon(QStyle.SP_MediaVolume))
        else:
            self.muted = True
            self.volumeButton.setIcon(
                self.style().standardIcon(QStyle.SP_MediaVolumeMuted))
        self._applyVolume()
        if emit:
            self.mutedChanged.emit([self.id, self.muted])

    def mediaReload(self):
        self.checkPlaying.stop()
        if self.roomID != '0':
            self.playerRestart()
            self.setTitle()
            if self.liveStatus == 1:
                self.getMediaURL.setConfig(self.roomID, self.quality, self.sessionData)
                self.getMediaURL.start()
        else:
            self.mediaStop()

    def _mediaStop(self):
        self.mediaStop()

    def mediaStop(self, deleteMedia=True):
        self.oldTitle, self.oldUname = '', ''
        self.roomID = '0'
        self.topLabel.setText(('    窗口%s  未定义的直播间' %
                               (self.id + 1))[:20])
        self.titleLabel.setText('未定义')
        self.liveStartTime = 0
        self.timestampLabel.setText('0:00:00')
        self.playerRestart()
        self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        if deleteMedia:
            self.deleteMedia.emit(self.id)
        self.getMediaURL.recordToken = False
        self.getMediaURL.checkTimer.stop()
        self.checkPlaying.stop()
        self.stopDanmu()
        self.refreshTimeStampTimer.stop()

    def _safe_disconnect_danmu(self):
        """安全断开弹幕信号，抑制未连接时的 RuntimeWarning"""
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                self.danmu.message.disconnect(self.playDanmu)
            except (RuntimeError, TypeError):
                pass

    def stopDanmu(self):
        self._safe_disconnect_danmu()
        self.danmu.stop()
        self.danmu.wait(1000)

    def reloadDanmu(self):
        self.stopDanmu()
        self.danmu.setRoomID(self.roomID)
        self.danmu.message.connect(self.playDanmu)
        self.danmu.start()

    def setMedia(self, url):
        """播放直播流 - MPV 直接播放 URL，无需本地缓存"""
        self._init_mpv()
        self.retryTimes = 0
        self._stream_url = url
        self.cacheName = url  # 兼容性
        self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        # 重置弹幕字幕轨道状态（切换媒体后需要重新 sub-add）
        self.scrollingDanmaku.stop()
        self.scrollingDanmaku._sub_loaded = False

        if self._mpv:
            try:
                self._mpv.play(url)
                self._applyVolume()
            except Exception:
                logging.exception(f'{self.name_str} MPV 播放失败')

        self.checkPlaying.start(3000)
        self.refreshTimeStampTimer.start()

        # 启动弹幕
        self.danmu.setRoomID(self.roomID)
        self._safe_disconnect_danmu()
        if self.startWithDanmu:
            self.danmu.message.connect(self.playDanmu)
            self.danmu.stop()
            self.danmu.wait(500)
            self.danmu.start()
            self.textBrowser.show()

    def copyCache(self, copyFile):
        """兼容保留"""
        pass

    # ==== MPV 实例管理 ====

    def newPlayer(self):
        """延迟初始化 MPV"""
        pass  # MPV 在 setMedia 时按需初始化

    def playerRestart(self):
        """重置播放器"""
        if self._mpv:
            try:
                self._mpv.stop()
            except Exception:
                pass

    def playerFree(self):
        """销毁 MPV 实例"""
        self.scrollingDanmaku.stop()
        self.scrollingDanmaku.cleanup_file()
        if self._mpv:
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None

    def setTitle(self):
        if self.title != '未定义的直播间':
            self.oldTitle = self.title
        if self.uname != '未定义':
            self.oldUname = self.uname
        if self.roomID == '0':
            self.title = '未定义的直播间'
            self.uname = '未定义'
        else:
            params = {
                'req_biz': 'web_room_componet',
                'room_ids': [str(self.roomID)]
            }
            cookies = {}
            if self.sessionData:
                cookies['SESSDATA'] = self.sessionData
            try:
                r = requests.get(
                    r'https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo',
                    params=params, headers=header, cookies=cookies
                )
                data = json.loads(r.text)
                if data['message'] == '房间已加密':
                    self.title = '房间已加密'
                    self.uname = '房号: %s' % self.roomID
                elif not data['data']:
                    self.title = '房间好像不见了-_-？'
                    self.uname = '未定义'
                else:
                    data = data['data']['by_room_ids'][str(self.roomID)]
                    self.liveStatus = data['live_status']
                    self.liveStartTime = time.mktime(
                        datetime.strptime(data['live_time'], "%Y-%m-%d %H:%M:%S").timetuple())
                    self.title = data['title']
                    self.uname = data['uname']
                    if self.liveStatus != 1:
                        self.uname = '（未开播）' + self.uname
            except Exception as e:
                logging.error(str(e))
                self.title = '获取信息失败'
                self.uname = '房号: %s' % self.roomID
        self.topLabel.setText(
            ('    窗口%s  %s' % (self.id + 1, self.title))[:20])
        self.titleLabel.setText(self.uname)

    def playDanmu(self, message):
        token = False
        if message.startswith("## ") or message.startswith("** "):
            if self.textSetting[7] == 0:
                self.textBrowser.msgsBrowser.append(message)
            elif self.textSetting[7] == 1:
                if message.startswith("** "):
                    self.textBrowser.msgsBrowser.append(message)
            elif self.textSetting[7] == 2:
                if message.startswith("## "):
                    self.textBrowser.msgsBrowser.append(message)
            return
        for symbol in self.filters:
            if symbol in message:
                self.textBrowser.transBrowser.append(message)
                token = True
                break
        if not token:
            self.textBrowser.textBrowser.append(message + '\n')
            # 同时发送到滚动弹幕层
            if hasattr(self, 'scrollingDanmaku') and self.scrollingDanmaku:
                self.scrollingDanmaku.addDanmaku(message)

    def keyPressEvent(self, QKeyEvent):
        if QKeyEvent.key() == Qt.Key_Escape:
            if self.top and self.isFullScreen():
                self.showNormal()
            else:
                self.fullScreenKey.emit()
        elif QKeyEvent.key() == Qt.Key_H:
            self.hideBarKey.emit()
        elif QKeyEvent.key() == Qt.Key_F:
            self.fullScreenKey.emit()
        elif QKeyEvent.key() == Qt.Key_M or QKeyEvent.key() == Qt.Key_S:
            self.muteExceptKey.emit()
