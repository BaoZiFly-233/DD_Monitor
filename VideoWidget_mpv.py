"""
DD监控室视频播放窗口 - MPV 内核版本
使用 python-mpv 库直接播放直播流 URL，无需本地 FLV 缓存下载
降低 CPU 和内存占用
"""
import json
import os
import sys
import time
from PySide6.QtWidgets import *
from PySide6.QtGui import *
from PySide6.QtCore import *
from bilibili_api import live, sync
from bili_credential import build_credential, normalize_credential_data
from CommonWidget import Slider
from remote import DanmakuEvent, remoteThread
from danmu import TextBrowser, DanmakuSettings, DISPLAY_RATIOS
from danmaku_renderer import DanmakuRenderer
from mpv_gl_widget import MpvGLWidget
import logging
import warnings
from datetime import datetime
from urllib.parse import urlsplit
import http_utils

_MPV_DLL_HANDLES = []
_MPV_MODULE = None


def prepare_mpv_runtime():
    candidate_dirs = []

    def add_candidate(path):
        if not path:
            return
        abs_path = os.path.abspath(path)
        if os.path.isdir(abs_path) and abs_path not in candidate_dirs:
            candidate_dirs.append(abs_path)

    module_dir = os.path.dirname(os.path.abspath(__file__))
    add_candidate(module_dir)
    add_candidate(os.path.dirname(module_dir))

    if getattr(sys, 'frozen', False):
        add_candidate(os.path.dirname(sys.executable))

    add_candidate(getattr(sys, '_MEIPASS', None))

    for base_dir in tuple(candidate_dirs):
        add_candidate(os.path.join(base_dir, 'mpv'))

    current_path = os.environ.get("PATH", "")
    path_entries = [entry for entry in current_path.split(os.pathsep) if entry]
    prepend_entries = [entry for entry in candidate_dirs if entry not in path_entries]
    if prepend_entries:
        os.environ["PATH"] = os.pathsep.join(prepend_entries + path_entries)

    if os.name == 'nt' and hasattr(os, 'add_dll_directory'):
        for candidate_dir in candidate_dirs:
            try:
                _MPV_DLL_HANDLES.append(os.add_dll_directory(candidate_dir))
            except (FileNotFoundError, OSError):
                continue

    return candidate_dirs


def load_mpv_module():
    global _MPV_MODULE
    if _MPV_MODULE is not None:
        return _MPV_MODULE

    prepare_mpv_runtime()
    try:
        import mpv as mpv_module
    except (ImportError, OSError):
        logging.warning('python-mpv 未安装或 libmpv 未找到，后续调用将重试')
        return None

    _MPV_MODULE = mpv_module
    return _MPV_MODULE

header = http_utils.DEFAULT_HEADERS


def _is_valid_stream_url(url):
    value = str(url or '').strip()
    if not value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


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
    streamUrl = Signal(object)
    downloadError = Signal()

    def __init__(self, sessionData=''):
        super(GetStreamURL, self).__init__()
        self.roomID = '0'
        self.quality = 250
        self.sessionData = sessionData if sessionData else ''
        self.credential = normalize_credential_data(sessdata=self.sessionData)
        # 兼容性属性桩（DD监控室.py closeEvent 中会访问）
        self.recordToken = False

    def setConfig(self, roomID, quality, sessionData, credential=None):
        self.roomID = roomID
        self.quality = quality
        self.sessionData = sessionData if sessionData else ''
        self.credential = normalize_credential_data(credential, sessdata=self.sessionData)

    def getStreamUrl(self):
        onlyAudio = self.quality < 0
        qn_mapping = {
            10000: live.ScreenResolution.ORIGINAL,
            400: live.ScreenResolution.BLU_RAY,
            250: live.ScreenResolution.ULTRA_HD,
            150: live.ScreenResolution.HD,
            80: live.ScreenResolution.FLUENCY,
        }
        room = live.LiveRoom(int(self.roomID), credential=build_credential(self.credential, sessdata=self.sessionData))
        qn = qn_mapping.get(abs(self.quality), live.ScreenResolution.ORIGINAL)
        play_info = sync(room.get_room_play_info_v2(live_qn=qn))
        stream = play_info['playurl_info']['playurl']['stream'][0]
        format_info = stream['format'][0]
        codec_info = format_info['codec'][0]
        media_info = codec_info['audio_codecs'][0] if onlyAudio and codec_info.get('audio_codecs') else codec_info
        base_url = media_info['base_url']
        stream_urls = []
        invalid_count = 0
        for url_info in media_info.get('url_info', []):
            stream_url = f"{url_info.get('host', '')}{base_url}{url_info.get('extra', '')}"
            if _is_valid_stream_url(stream_url) and stream_url not in stream_urls:
                stream_urls.append(stream_url)
            else:
                invalid_count += 1
        if not stream_urls:
            raise RuntimeError('未获取到可用直播流地址')
        if invalid_count > 0:
            logging.warning(f'房间 {self.roomID} 过滤掉 {invalid_count} 条无效流地址')
        self.streamUrlCandidates = stream_urls
        return stream_urls
    def run(self):
        try:
            urls = self.getStreamUrl()
            self.streamUrl.emit(urls)
        except Exception as e:
            logging.error(str(e))
            logging.exception('直播地址获取失败')
            self.downloadError.emit()


class FetchRoomInfo(QThread):
    """后台获取房间信息，避免阻塞主线程"""
    roomInfo = Signal(dict)

    def __init__(self):
        super().__init__()
        self.roomID = '0'
        self.sessionData = ''

    def setConfig(self, roomID, sessionData=''):
        self.roomID = roomID
        self.sessionData = sessionData

    def run(self):
        if self.roomID == '0':
            self.roomInfo.emit({'roomID': self.roomID, 'error': 'no_room'})
            return
        params = {
            'req_biz': 'web_room_componet',
            'room_ids': [str(self.roomID)]
        }
        cookies = {}
        if self.sessionData:
            cookies['SESSDATA'] = self.sessionData
        try:
            r = http_utils.get(
                'https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo',
                params=params, headers=header, cookies=cookies
            )
            data = r.json()
            result = {'roomID': self.roomID}
            if data['message'] == '房间已加密':
                result['title'] = '房间已加密'
                result['uname'] = '房号: %s' % self.roomID
                result['live_status'] = 0
            elif not data['data']:
                result['title'] = '房间好像不见了-_-？'
                result['uname'] = '未定义'
                result['live_status'] = 0
            else:
                info = data['data']['by_room_ids'][str(self.roomID)]
                result['live_status'] = info['live_status']
                result['live_time'] = info['live_time']
                result['title'] = info['title']
                result['uname'] = info['uname']
            self.roomInfo.emit(result)
        except Exception as e:
            logging.error(str(e))
            self.roomInfo.emit({
                'roomID': self.roomID,
                'title': '获取信息失败',
                'uname': '房号: %s' % self.roomID,
                'live_status': 0,
            })


class VideoFrame(MpvGLWidget):
    """视频播放容器：MPV render API + QOpenGLWidget。"""

    def __init__(self, danmaku_renderer, parent=None):
        super(VideoFrame, self).__init__(danmaku_renderer=danmaku_renderer, parent=parent)
        self.setAcceptDrops(True)



class VideoWidget(QFrame):
    """
    视频播放窗口 - MPV 内核版本
    信号连接由 DD监控室.py 中的 _connectVideoWidget 完成
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
                 textSetting=[True, 20, 2, 6, 0, '【 [ {', 10, 0, True], maxCacheSize=2048000,
                 saveCachePath='', startWithDanmu=True, hardwareDecode=True, sessionData='', credential=None,
                 rollingSetting=None, danmakuBaseViewport=None):
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
        self.credential = normalize_credential_data(credential, sessdata=self.sessionData)
        self.leftButtonPress = False
        self.rightButtonPress = False
        self.fullScreen = False
        self.userPause = False
        self.cacheName = ''
        self.maxCacheSize = maxCacheSize
        self.saveCachePath = saveCachePath
        self.startWithDanmu = startWithDanmu
        self.retryTimes = 0
        self._idleStreak = 0  # 连续 idle 计数，防网络波动误判
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
        self.textSetting = DanmakuSettings.from_config_list(textSetting)
        self.horiPercent = DISPLAY_RATIOS[self.textSetting.horizontal_index]
        self.vertPercent = DISPLAY_RATIOS[self.textSetting.vertical_index]
        self.filters = self.textSetting.translate_filters.split(' ')
        default_rolling_setting = {
            'font_family': 'Microsoft YaHei',
            'opacity': self.textSetting[1],
            'display_area': self.textSetting[3],
            'font_size': self.textSetting[6],
            'speed_percent': 85,
            'stroke_width': 30,
            'shadow_enabled': False,
            'shadow_strength': 35,
            'top_enabled': True,
            'bottom_enabled': True,
        }
        self.rollingSetting = rollingSetting if rollingSetting is not None else default_rolling_setting
        for key, value in default_rolling_setting.items():
            self.rollingSetting.setdefault(key, value)
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
        self.textBrowser = None
        if not self.startWithDanmu:
            self.textSetting[0] = False
            self.textSetting[8] = False

        self.textPosDelta = QPoint(0, 0)
        self.deltaX = 0
        self.deltaY = 0
        self._danmakuBaseViewport = QSize(danmakuBaseViewport) if danmakuBaseViewport is not None else QSize()
        self._minOverlayFontSize = 18
        self._minBrowserFontSize = 10

        # ---- OpenGL 滚动弹幕渲染器 ----
        self.scrollingDanmaku = DanmakuRenderer()

        # ---- 播放器布局 ----
        self.videoFrame = VideoFrame(self.scrollingDanmaku)
        self.videoFrame.setPlaybackActive(False)
        self.videoFrame.rightClicked.connect(self.rightMouseClicked)
        self.videoFrame.leftClicked.connect(self.leftMouseClicked)
        self.videoFrame.doubleClicked.connect(self.doubleClick)
        layout.addWidget(self.videoFrame, 0, 0, 12, 12)

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
        self._controls_keep_until = 0.0
        self._controls_hide_timer = QTimer(self)
        self._controls_hide_timer.setSingleShot(True)
        self._controls_hide_timer.timeout.connect(self._hideControlsIfNeeded)

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
        self.danmuButton.clicked.connect(self.cycleDanmuDisplayMode)
        frameLayout.addWidget(self.danmuButton)
        self.danmuDensityLabel = QLabel('')
        self.danmuDensityLabel.setFixedWidth(32)
        self.danmuDensityLabel.setAlignment(Qt.AlignCenter)
        self.danmuDensityLabel.setStyleSheet('color:#aaa;font-size:10px;background:transparent')
        frameLayout.addWidget(self.danmuDensityLabel)
        self.stop = PushButton(self.style().standardIcon(
            QStyle.SP_DialogCancelButton))
        self.stop.clicked.connect(self._mediaStop)
        frameLayout.addWidget(self.stop)
        for control_button in (self.play, self.reload, self.volumeButton, self.danmuButton, self.stop):
            control_button.pressed.connect(self._onControlInteracted)
            control_button.clicked.connect(self._onControlInteracted)

        # ---- IO 线程 ----
        self.getMediaURL = GetStreamURL(self.sessionData)
        self.getMediaURL.credential = self.credential
        self.getMediaURL.streamUrl.connect(self.setMedia)
        self.getMediaURL.downloadError.connect(self.mediaReload)

        self.fetchRoomInfo = FetchRoomInfo()
        self.fetchRoomInfo.roomInfo.connect(self._onRoomInfo)

        self.danmu = remoteThread(self.roomID, self.sessionData)
        self._danmuPendingRestart = False
        self.danmu.finished.connect(self._onDanmuFinished)

        # ---- 定时器 ----
        # moveTimer: 按需启动，位置稳定后自动停止（避免 32 窗口空转）
        self.moveTimer = QTimer(self)
        self.moveTimer.timeout.connect(self.initTextPos)
        self.moveTimer.setSingleShot(False)
        self.moveTimer.setInterval(50)

        self.checkPlaying = QTimer(self)
        self.checkPlaying.timeout.connect(self.checkPlayStatus)

        if resize:
            self.resize(resize[0], resize[1])
        logging.info(f"{self.name_str} MPV 播放器构造完毕, 置顶?: {self.top}, 启用弹幕?: {self.startWithDanmu}")

        self.refreshTimeStampTimer = QTimer(self)
        self.refreshTimeStampTimer.timeout.connect(self.refreshTimeStamp)
        self.refreshTimeStampTimer.setInterval(1000)

        self._danmuDensityTimer = QTimer(self)
        self._danmuDensityTimer.timeout.connect(self._updateDanmuDensity)
        self._danmuDensityTimer.setInterval(1000)

    def ensureTextBrowser(self):
        if self.textBrowser is not None:
            return self.textBrowser

        self.textBrowser = TextBrowser(self)
        self.textBrowser.closeSignal.connect(self.closeDanmu)
        self.textBrowser.moveSignal.connect(self.moveTextBrowser)

        option_widget = self.textBrowser.optionWidget
        option_widget.opacitySlider.setValue(self.textSetting[1])
        option_widget.horizontalCombobox.setCurrentIndex(self.textSetting[2])
        option_widget.verticalCombobox.setCurrentIndex(self.textSetting[3])
        option_widget.translateCombobox.setCurrentIndex(self.textSetting[4])
        option_widget.translateFitler.setText(self.textSetting[5])
        option_widget.fontSizeCombox.setCurrentIndex(self.textSetting[6])
        option_widget.showEnterRoom.setCurrentIndex(self.textSetting[7])

        option_widget.opacitySlider.value.connect(self.setDanmuOpacity)
        option_widget.horizontalCombobox.currentIndexChanged.connect(self.setHorizontalPercent)
        option_widget.verticalCombobox.currentIndexChanged.connect(self.setVerticalPercent)
        option_widget.translateCombobox.currentIndexChanged.connect(self.setTranslateBrowser)
        option_widget.translateFitler.textChanged.connect(self.setTranslateFilter)
        option_widget.fontSizeCombox.currentIndexChanged.connect(self.setFontSize)
        option_widget.showEnterRoom.currentIndexChanged.connect(self.setMsgsBrowser)

        self.applyDanmuSettings()
        if not self.textSetting[0]:
            self.textBrowser.hide()
        self.moveTextBrowser()
        return self.textBrowser

    def applyDanmuSettings(self):
        browser_opacity = max(self.textSetting[1], 7)
        rolling_opacity = max(int(self.rollingSetting.get('opacity', browser_opacity)), 7)
        browser_font_size, overlay_font_size = self._resolveDanmakuFontSizes()
        rolling_enabled = self.isRollingDanmuEnabled()
        self.scrollingDanmaku.setEnabled(rolling_enabled)
        self.scrollingDanmaku.setOpacity(rolling_opacity / 100.0)
        self.scrollingDanmaku.setFontFamily(str(self.rollingSetting.get('font_family', 'Microsoft YaHei')))
        self.scrollingDanmaku.setFontSize(overlay_font_size)
        self.scrollingDanmaku.setDisplayArea(self._rollingDisplayRatio())
        self.scrollingDanmaku.setDenseLevel(0)
        self.scrollingDanmaku.setSpeedFactor(self._rollingSpeedFactor())
        self.scrollingDanmaku.setStrokeWidth(self._rollingStrokeWidth())
        self.scrollingDanmaku.setShadowEnabled(bool(self.rollingSetting.get('shadow_enabled', False)))
        self.scrollingDanmaku.setShadowStrength(int(self.rollingSetting.get('shadow_strength', 35)))
        self.scrollingDanmaku.setTopEnabled(bool(self.rollingSetting.get('top_enabled', True)))
        self.scrollingDanmaku.setBottomEnabled(bool(self.rollingSetting.get('bottom_enabled', True)))
        self.videoFrame.update()
        self._updateDanmuButtonState()
        self._danmuDensityTimer.start()

        if self.textBrowser is None:
            return

        alpha_hex = format(max(0, min(255, int(round(browser_opacity / 100.0 * 255)))), '02x')
        self.textBrowser.textBrowser.setStyleSheet(f'background-color:#{alpha_hex}000000')
        self.textBrowser.transBrowser.setStyleSheet(f'background-color:#{alpha_hex}000000')
        self.textBrowser.msgsBrowser.setStyleSheet(f'background-color:#{alpha_hex}000000')

        self.textBrowser.textBrowser.setFont(QFont('Microsoft JhengHei', browser_font_size, QFont.Bold))
        self.textBrowser.transBrowser.setFont(QFont('Microsoft JhengHei', browser_font_size, QFont.Bold))
        self.textBrowser.msgsBrowser.setFont(QFont('Microsoft JhengHei', browser_font_size, QFont.Bold))

        if self.textSetting[4] == 0:
            self.textBrowser.textBrowser.show()
            self.textBrowser.transBrowser.show()
        elif self.textSetting[4] == 1:
            self.textBrowser.transBrowser.hide()
            self.textBrowser.textBrowser.show()
        elif self.textSetting[4] == 2:
            self.textBrowser.textBrowser.hide()
            self.textBrowser.transBrowser.show()

        if self.textSetting[7] < 3:
            self.textBrowser.msgsBrowser.show()
        else:
            self.textBrowser.msgsBrowser.hide()

        self.textBrowser.resize(self.width() * self.horiPercent, self.height() * self.vertPercent)
        self.textBrowser.textBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.transBrowser.verticalScrollBar().setValue(100000000)
        self.textBrowser.msgsBrowser.verticalScrollBar().setValue(100000000)

    def _rollingSpeedFactor(self):
        return max(0.5, min(int(self.rollingSetting.get('speed_percent', 85)) / 100.0, 2.0))

    def _rollingStrokeWidth(self):
        return max(0.0, min(int(self.rollingSetting.get('stroke_width', 30)) / 10.0, 8.0))

    def _resolveDanmakuFontSizes(self):
        browser_base_size = int(self.textSetting[6]) + 5
        rolling_base_size = int(self.rollingSetting.get('font_size', self.textSetting[6])) + 5
        overlay_base_size = max(24, int(rolling_base_size * 2.2))
        scale = self._resolveDanmakuScale()
        browser_font_size = max(self._minBrowserFontSize, int(round(browser_base_size * scale)))
        overlay_font_size = max(self._minOverlayFontSize, int(round(overlay_base_size * scale)))
        browser_font_size = min(browser_font_size, browser_base_size)
        overlay_font_size = min(overlay_font_size, overlay_base_size)
        return browser_font_size, overlay_font_size

    def _resolveDanmakuScale(self):
        current_width = max(self.videoFrame.width(), 0)
        current_height = max(self.videoFrame.height(), 0)
        if current_width <= 0 or current_height <= 0:
            return 1.0

        if self._danmakuBaseViewport.isEmpty():
            self._danmakuBaseViewport = QSize(current_width, current_height)
            return 1.0

        base_width = max(self._danmakuBaseViewport.width(), 1)
        base_height = max(self._danmakuBaseViewport.height(), 1)
        width_scale = current_width / base_width
        height_scale = current_height / base_height
        return min(width_scale, height_scale, 1.0)

    def setDanmakuBaseViewport(self, viewport_size):
        self._danmakuBaseViewport = QSize(viewport_size)
        self.applyDanmuSettings()

    def isBrowserDanmuEnabled(self):
        return bool(self.textSetting[0])

    def isRollingDanmuEnabled(self):
        return bool(self.textSetting[8])

    def _rollingDisplayRatio(self):
        index = int(self.rollingSetting.get('display_area', self.textSetting[3]))
        index = max(0, min(index, 9))
        return [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0][index]

    def _currentDanmuDisplayMode(self):
        browser_enabled = self.isBrowserDanmuEnabled()
        rolling_enabled = self.isRollingDanmuEnabled()
        if browser_enabled and rolling_enabled:
            return 0
        if browser_enabled:
            return 1
        return 2

    def _updateDanmuButtonState(self):
        state_text = ['弹幕：全开', '弹幕：仅弹幕机', '弹幕：全关'][self._currentDanmuDisplayMode()]
        self.danmuButton.setToolTip(state_text)

    def _updateDanmuDensity(self):
        """更新弹幕密度指示"""
        if self.isRollingDanmuEnabled():
            count = self.scrollingDanmaku.activeCount()
            if count > 0:
                self.danmuDensityLabel.setText(str(count))
                if count > 30:
                    self.danmuDensityLabel.setStyleSheet('color:#e74c3c;font-size:10px;background:transparent')
                elif count > 15:
                    self.danmuDensityLabel.setStyleSheet('color:#f39c12;font-size:10px;background:transparent')
                else:
                    self.danmuDensityLabel.setStyleSheet('color:#aaa;font-size:10px;background:transparent')
            else:
                self.danmuDensityLabel.setText('')
        else:
            self.danmuDensityLabel.setText('')
            self._danmuDensityTimer.stop()

    def _applyDanmuDisplayState(self, browser_enabled, rolling_enabled, restart_thread=False):
        self.textSetting[0] = bool(browser_enabled)
        self.textSetting[8] = bool(rolling_enabled)
        self.startWithDanmu = self.textSetting[0] or self.textSetting[8]

        if self.textSetting[0]:
            self.showTextBrowser()
        else:
            self.hideTextBrowser()

        if not self.textSetting[8]:
            self.scrollingDanmaku.reset()

        if not self.startWithDanmu:
            self.stopDanmu()
        elif restart_thread and self.roomID != '0':
            self._restartDanmu()

        self.applyDanmuSettings()
        self._onControlInteracted()
        self.setDanmu.emit()

    def cycleDanmuDisplayMode(self):
        next_mode = (self._currentDanmuDisplayMode() + 1) % 3
        if next_mode == 0:
            self._applyDanmuDisplayState(True, True, restart_thread=True)
        elif next_mode == 1:
            self._applyDanmuDisplayState(True, False, restart_thread=True)
        else:
            self._applyDanmuDisplayState(False, False)

    def setRollingDanmuOpacity(self, value, emit_signal=True):
        self.rollingSetting['opacity'] = max(7, int(value))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuDisplayArea(self, index, emit_signal=True):
        self.rollingSetting['display_area'] = max(0, min(int(index), 9))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuFontSize(self, index, emit_signal=True):
        self.rollingSetting['font_size'] = max(0, min(int(index), 20))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuFontFamily(self, family, emit_signal=True):
        self.rollingSetting['font_family'] = str(family).strip() or 'Microsoft YaHei'
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuSpeed(self, value, emit_signal=True):
        self.rollingSetting['speed_percent'] = max(50, min(int(value), 200))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuStrokeWidth(self, value, emit_signal=True):
        self.rollingSetting['stroke_width'] = max(0, min(int(value), 60))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuShadowEnabled(self, enabled, emit_signal=True):
        self.rollingSetting['shadow_enabled'] = bool(enabled)
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuShadowStrength(self, value, emit_signal=True):
        self.rollingSetting['shadow_strength'] = max(0, min(int(value), 100))
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuTopEnabled(self, enabled, emit_signal=True):
        self.rollingSetting['top_enabled'] = bool(enabled)
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def setRollingDanmuBottomEnabled(self, enabled, emit_signal=True):
        self.rollingSetting['bottom_enabled'] = bool(enabled)
        self.applyDanmuSettings()
        if emit_signal:
            self.setDanmu.emit()

    def showTextBrowser(self):
        if not self.isBrowserDanmuEnabled():
            return
        self.ensureTextBrowser().show()

    def hideTextBrowser(self):
        if self.textBrowser is not None:
            self.textBrowser.hide()

    def applyCredentialContext(self, sessionData=None, credential=None):
        """统一同步播放器、取流线程和弹幕线程的登录态。"""
        if sessionData is not None:
            self.sessionData = sessionData if sessionData else ''
        base_credential = self.credential if credential is None else credential
        self.credential = normalize_credential_data(base_credential, sessdata=self.sessionData)
        self.getMediaURL.sessionData = self.sessionData
        self.getMediaURL.credential = self.credential
        self.danmu.setSessionData(self.sessionData)

    # ==== MPV 播放器管理 ====

    def _init_mpv(self):
        """延迟初始化 MPV 播放器 - 仅在需要播放时创建"""
        if self._mpv is not None:
            return
        mpv_module = load_mpv_module()
        if mpv_module is None:
            logging.error('无法初始化 MPV: python-mpv 未安装或 libmpv 未找到')
            return
        try:
            hwdec_mode = 'auto-copy' if self.hardwareDecode else 'no'
            # Windows + OpenGL 渲染路径下硬件解码会导致画面花屏/green frames
            # MPV 的 gpu-hwdec-interop 在 libmpv + ANGLE 组合下不稳定
            # 上游追踪: mpv-player/mpv 和 shinchiro/mpv-winbuild-cmake
            if sys.platform.startswith('win') and hwdec_mode != 'no':
                logging.warning('%s MPV OpenGL 渲染路径暂时禁用硬件解码以规避花屏', self.name_str)
                hwdec_mode = 'no'
            self._mpv = mpv_module.MPV(
                vo='libmpv',
                input_cursor='no',
                input_default_bindings='no',
                osd_level=0,
                keep_open='yes',
                idle='yes',
                osc='no',
                ytdl=False,
                http_header_fields=f"User-Agent: {header['User-Agent']},Referer: https://live.bilibili.com/",
                hwdec=hwdec_mode,
                gpu_hwdec_interop='no',
                volume=self.volume,
                cache='yes',
                demuxer_max_bytes='50MiB',
                demuxer_max_back_bytes='20MiB',
            )
            logging.info(f'{self.name_str} MPV 实例已创建')
            self.videoFrame.setPlayer(self._mpv)
            self.applyDanmuSettings()
        except Exception as e:
            logging.exception('%s MPV 初始化失败: %s', self.name_str, e)
            self._mpv = None

    def get_volume(self):
        """获取当前音量"""
        if self._mpv:
            try:
                return int(self._mpv.volume or 0)
            except Exception as e:
                logging.debug('%s get_volume 失败: %s', self.name_str, e)
                return 0
        return 0

    def set_volume_direct(self, value):
        """直接设置音量（给 DD监控室.py 全局音量调用）"""
        if self._mpv:
            try:
                self._mpv.volume = int(value)
            except Exception as e:
                logging.debug('%s get_mute 失败: %s', self.name_str, e)
                return False
        return False

    def set_audio_channel(self, channel):
        """设置音频通道（MPV 兼容层）"""
        self.audioChannel = channel

    # ==== 播放状态检测 ====

    def checkPlayStatus(self):
        """检测播放是否卡住 — 连续多次 idle 才触发重试，避免网络波动误判"""
        if self.roomID == '0':
            return
        if self._mpv and not self.isHidden() and self.liveStatus == 1 and not self.userPause:
            try:
                idle = self._mpv.core_idle
                if idle:
                    self._idleStreak += 1
                    if self._idleStreak < 3:  # 连续3次(9s)才确认是真断流
                        return
                    if self._tryPlayNextStreamCandidate(max_tries=2):
                        self._idleStreak = 0
                        return
                    self.retryTimes += 1
                    if self.retryTimes > 4:  # 4×3s=12s 后重载
                        self._idleStreak = 0
                        self.mediaReload()
                    if self.retryTimes > 8 and self.quality > 80:
                        old_q = self.quality
                        self.quality = self._nextLowerQuality(self.quality)
                        logging.warning('%s 自适应画质: %s -> %s', self.name_str, old_q, self.quality)
                        self.retryTimes = 0
                        self._idleStreak = 0
                        self.mediaReload()
                else:
                    self._idleStreak = 0
                    self.retryTimes = 0
            except Exception as e:
                logging.debug('%s checkPlayStatus 异常: %s', self.name_str, e)
                self.retryTimes += 1
                if self.retryTimes > 4:
                    self.mediaReload()
        return False

    @staticmethod
    def _nextLowerQuality(current):
        """自适应画质：返回下一档画质"""
        order = [10000, 400, 250, 80, -1]
        try:
            idx = order.index(current)
            if idx < len(order) - 1:
                return order[idx + 1]
        except ValueError:
            pass
        return 80  # 默认降到流畅

    def refreshTimeStamp(self):
        if self.liveStartTime:
            duration = time.time() - self.liveStartTime
            h, m = divmod(duration, 3600)
            m, s = divmod(m, 60)
            self.timestampLabel.setText('%01d:%02d:%02d' % (h, m, s))

    def _tryPlayNextStreamCandidate(self, max_tries=2):
        if not self._mpv or self._stream_candidate_index + 1 >= len(self._stream_candidates):
            return False
        tried = 0
        while (self._stream_candidate_index + 1 < len(self._stream_candidates)
               and tried < max_tries):
            self._stream_candidate_index += 1
            next_url = self._stream_candidates[self._stream_candidate_index]
            tried += 1
            if not _is_valid_stream_url(next_url):
                logging.warning(f'{self.name_str} 跳过无效流地址: {next_url}')
                continue
            try:
                self._stream_url = next_url
                self.cacheName = next_url
                self._mpv.play(next_url)
                self._applyVolume()
                self.retryTimes = 0
                self._idleStreak = 0
                self.videoFrame.setPlaybackActive(True)
                if self._stream_candidate_index > 0:
                    logging.warning(f'{self.name_str} 切换到备用流 #{self._stream_candidate_index + 1}')
                return True
            except Exception:
                logging.exception(f'{self.name_str} 备用流切换失败')
        self.videoFrame.setPlaybackActive(False)
        return False

    # ==== 弹幕机设置 ====

    def initTextPos(self):
        if self.textBrowser is None:
            self.moveTimer.stop()
            return
        videoPos = self.mapToGlobal(self.videoFrame.pos())
        if self.textBrowser.pos() != videoPos:
            self.textBrowser.move(videoPos)
        else:
            self.moveTimer.stop()

    def setDanmuOpacity(self, value):
        if value < 7:
            value = 7
        self.textSetting[1] = value
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def setHorizontalPercent(self, index):
        self.textSetting[2] = index
        self.horiPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][index]
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def setVerticalPercent(self, index):
        self.textSetting[3] = index
        self.vertPercent = [0.1, 0.2, 0.3, 0.4, 0.5,
                            0.6, 0.7, 0.8, 0.9, 1.0][index]
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def setTranslateBrowser(self, index):
        self.textSetting[4] = index
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def setMsgsBrowser(self, index):
        self.textSetting[7] = index
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def setTranslateFilter(self, filterWords):
        self.textSetting[5] = filterWords
        self.filters = filterWords.split(' ')
        self.setDanmu.emit()

    def setFontSize(self, index):
        self.textSetting[6] = index
        self.applyDanmuSettings()
        self.setDanmu.emit()

    def resizeEvent(self, QEvent):
        try:
            self.titleLabel.hide() if self.width() < 350 else self.titleLabel.show()
            self.play.hide() if self.width() < 300 else self.play.show()
            self.danmuButton.show()
            self.slider.hide() if self.width() < 200 else self.slider.show()
            self.applyDanmuSettings()
            if self.textBrowser is not None:
                self.moveTextBrowser()
                if not self.moveTimer.isActive():
                    self.moveTimer.start()
        except Exception:
            pass

    def moveEvent(self, QMoveEvent):
        if self.textBrowser is None:
            return
        videoPos = self.mapToGlobal(self.videoFrame.pos())
        self.textBrowser.move(videoPos + self.textPosDelta)
        if not self.moveTimer.isActive():
            self.moveTimer.start()

    def moveTextBrowser(self, point=None):
        if self.textBrowser is None:
            return
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

    def _isCursorInsideSelf(self):
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def _showControls(self, keep_ms=0):
        if keep_ms > 0:
            self._controls_keep_until = max(
                self._controls_keep_until, time.monotonic() + keep_ms / 1000.0
            )
        self.topLabel.show()
        self.frame.show()

    def _hideControlsIfNeeded(self):
        if QApplication.mouseButtons() != Qt.NoButton:
            self._controls_hide_timer.start(120)
            return
        if self._isCursorInsideSelf():
            return
        if time.monotonic() < self._controls_keep_until:
            remaining_ms = max(120, int((self._controls_keep_until - time.monotonic()) * 1000))
            self._controls_hide_timer.start(remaining_ms)
            return
        self.hoverToken = False
        self.topLabel.hide()
        self.frame.hide()

    def _onControlInteracted(self):
        self.hoverToken = True
        self._showControls(keep_ms=1800)
        if self._controls_hide_timer.isActive():
            self._controls_hide_timer.stop()

    def enterEvent(self, QEvent):
        self.hoverToken = True
        self._showControls()
        if self._controls_hide_timer.isActive():
            self._controls_hide_timer.stop()

    def leaveEvent(self, QEvent):
        if self._isCursorInsideSelf():
            return
        self.hoverToken = False
        self._controls_hide_timer.start(120)

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
        drag.exec()

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
                if self.textBrowser is not None:
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

        action = menu.exec(self.mapToGlobal(event.pos()))
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
                self.hideTextBrowser()

    def closeEvent(self, event):
        event.ignore()
        if self.top:
            self.closePopWindow.emit([self.id, self.roomID])
            self.hide()
            self.mediaStop()
            self.hideTextBrowser()

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
        self._applyDanmuDisplayState(False, False)

    def stopDanmuMessage(self):
        self.stopDanmu()

    def showDanmu(self):
        self._applyDanmuDisplayState(True, True, restart_thread=True)

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
            self.setTitle()  # 异步获取房间信息，播放在 _onRoomInfo 回调中触发
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
        self.videoFrame.setPlaybackActive(False)
        self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        if deleteMedia:
            self.deleteMedia.emit(self.id)
        self.getMediaURL.recordToken = False
        self.checkPlaying.stop()
        self.stopDanmu()
        self.refreshTimeStampTimer.stop()
        self.hideTextBrowser()

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
        self._danmuPendingRestart = False
        self.danmu.stop()
        self.scrollingDanmaku.reset()
        # 非阻塞：不调用 wait()，线程收到 stop 信号后退出，
        # finished 信号会触发 _onDanmuFinished

    def _restartDanmu(self):
        """内部：请求重启弹幕线程（如果线程在运行则等 finished 信号）"""
        self.danmu.setRoomID(self.roomID)
        self.danmu.setSessionData(self.sessionData)
        self._safe_disconnect_danmu()
        self.danmu.message.connect(self.playDanmu)
        if self.danmu.isRunning():
            self._danmuPendingRestart = True
            self.danmu.stop()
        else:
            self.danmu.start()

    def _onDanmuFinished(self):
        """弹幕线程结束回调 — 处理待重启请求"""
        if self._danmuPendingRestart:
            self._danmuPendingRestart = False
            self.danmu.start()

    def reloadDanmu(self):
        self._restartDanmu()

    def setMedia(self, url):
        """接收直播流 - MPV 播放 URL 入口"""
        stream_candidates = url if isinstance(url, (list, tuple)) else [url]
        self._stream_candidates = [
            stream.strip()
            for stream in stream_candidates
            if isinstance(stream, str) and _is_valid_stream_url(stream.strip())
        ]
        self._stream_candidate_index = -1
        if not self._stream_candidates:
            logging.error('%s 未获取到可播放的流地址', self.name_str)
            self.videoFrame.setPlaybackActive(False)
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.checkPlaying.stop()
            self.refreshTimeStampTimer.stop()
            return

        self._init_mpv()
        if not self._mpv:
            logging.error(f'{self.name_str} MPV 播放器未初始化或加载失败')
            self.videoFrame.setPlaybackActive(False)
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.checkPlaying.stop()
            self.refreshTimeStampTimer.stop()
            return

        self.retryTimes = 0
        self._stream_url = self._stream_candidates[0]
        self.cacheName = self._stream_url
        self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        self.scrollingDanmaku.reset()

        if not self._tryPlayNextStreamCandidate():
            self.videoFrame.setPlaybackActive(False)
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.checkPlaying.stop()
            self.refreshTimeStampTimer.stop()
            return

        self.checkPlaying.start(3000)
        self.refreshTimeStampTimer.start()

        if self.startWithDanmu:
            self._restartDanmu()
            self.showTextBrowser()

    def playerRestart(self):
        """重置播放器"""
        if self._mpv:
            try:
                self._mpv.stop()
            except Exception:
                pass
        self.videoFrame.setPlaybackActive(False)

    def playerFree(self):
        """销毁 MPV 实例"""
        self.scrollingDanmaku.stop()
        self.scrollingDanmaku.cleanup_file()
        self.videoFrame.setPlaybackActive(False)
        if self._mpv:
            self.videoFrame.setPlayer(None)
            try:
                self._mpv.terminate()
            except Exception:
                pass
            self._mpv = None

    def setTitle(self):
        """异步获取房间信息（不阻塞主线程）"""
        if self.title != '未定义的直播间':
            self.oldTitle = self.title
        if self.uname != '未定义':
            self.oldUname = self.uname
        if self.roomID == '0':
            self.title = '未定义的直播间'
            self.uname = '未定义'
            self._updateTitleLabels()
        else:
            self.fetchRoomInfo.setConfig(self.roomID, self.sessionData)
            if not self.fetchRoomInfo.isRunning():
                self.fetchRoomInfo.start()

    def _onRoomInfo(self, result):
        """房间信息回调（主线程执行）- 获取到房间信息后自动触发播放"""
        # 确保结果与当前房间匹配
        if str(result.get('roomID', '')) != str(self.roomID):
            return
        self.title = result.get('title', '获取信息失败')
        self.uname = result.get('uname', '房号: %s' % self.roomID)
        self.liveStatus = result.get('live_status', 0)
        live_time = result.get('live_time', '')
        if live_time:
            try:
                self.liveStartTime = time.mktime(
                    datetime.strptime(live_time, "%Y-%m-%d %H:%M:%S").timetuple())
            except (ValueError, OSError):
                self.liveStartTime = 0
        else:
            self.liveStartTime = 0
        if self.liveStatus != 1 and self.uname and not self.uname.startswith('（未开播）'):
            self.uname = '（未开播）' + self.uname
        self._updateTitleLabels()
        # 直播中则自动开始播放
        if self.liveStatus == 1 and self.roomID != '0':
            self.getMediaURL.setConfig(self.roomID, self.quality, self.sessionData, self.credential)
            if not self.getMediaURL.isRunning():
                self.getMediaURL.start()
        else:
            self.videoFrame.setPlaybackActive(False)
            self.play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            self.checkPlaying.stop()
            self.refreshTimeStampTimer.stop()
            self.timestampLabel.setText('0:00:00')

    def _updateTitleLabels(self):
        """更新标题和标签文字"""
        self.topLabel.setText(
            ('    窗口%s  %s' % (self.id + 1, self.title))[:20])
        self.titleLabel.setText(self.uname)

    @staticmethod
    def _coerceDanmakuEvent(message):
        if isinstance(message, DanmakuEvent):
            return message
        if isinstance(message, dict):
            raw_kind = str(message.get('kind', 'danmaku'))
            fallback_position = raw_kind if raw_kind in {'scroll', 'top', 'bottom'} else 'scroll'
            position = str(message.get('position', message.get('dm_position', fallback_position)))
            return DanmakuEvent(
                kind=raw_kind,
                text=message.get('text', ''),
                uname=message.get('uname', ''),
                color=message.get('color', '#FFFFFF'),
                price=float(message.get('price', 0.0) or 0.0),
                position=position,
            )
        return DanmakuEvent(kind='danmaku', text=str(message))

    @staticmethod
    def _normalizeDanmakuPosition(position):
        normalized = str(position or 'scroll').strip().lower()
        if normalized in {'top', 'bottom', 'scroll'}:
            return normalized
        return 'scroll'

    def _isRollingPositionEnabled(self, position):
        if position == 'top':
            return bool(self.rollingSetting.get('top_enabled', True))
        if position == 'bottom':
            return bool(self.rollingSetting.get('bottom_enabled', True))
        return True

    def playDanmu(self, message):
        event = self._coerceDanmakuEvent(message)
        text = event.text
        kind = event.kind
        color = event.color
        position = self._normalizeDanmakuPosition(getattr(event, 'position', 'scroll'))
        text_browser = self.ensureTextBrowser() if self.isBrowserDanmuEnabled() else None

        if kind in {'gift', 'guard', 'enter'}:
            if text_browser is None:
                return
            if self.textSetting[7] == 0:
                text_browser.msgsBrowser.append(text)
            elif self.textSetting[7] == 1 and kind in {'gift', 'guard'}:
                text_browser.msgsBrowser.append(text)
            elif self.textSetting[7] == 2 and kind == 'enter':
                text_browser.msgsBrowser.append(text)
            return

        token = False
        if text_browser is not None:
            for symbol in self.filters:
                if symbol and symbol in text:
                    text_browser.transBrowser.append(text)
                    token = True
                    break
        if not token and text_browser is not None:
            text_browser.textBrowser.append(text + '\n')
        if self.isRollingDanmuEnabled() and self._isRollingPositionEnabled(position) and hasattr(self, 'scrollingDanmaku') and self.scrollingDanmaku:
            self.scrollingDanmaku.addDanmaku(text, color=color, kind=position, uname=event.uname)

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
