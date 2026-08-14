"""直播流地址与房间信息后台任务。

本模块只负责 B 站接口访问和响应整理。播放器状态、MPV 生命周期以及界面
更新留在 :mod:`app.ui.video_widget`，后台任务通过 Qt 信号回传结果。
"""

import logging
from dataclasses import dataclass
from urllib.parse import urlparse, urlsplit

from bilibili_api import live, sync
from PySide6.QtCore import QThread, Signal

from app.core import http_utils
from app.core.bili_credential import build_credential, normalize_credential_data


def is_valid_stream_url(url) -> bool:
    """返回 URL 是否为可交给 MPV 的 HTTP(S) 地址。"""
    value = str(url or "").strip()
    if not value:
        return False
    parsed = urlsplit(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@dataclass(frozen=True)
class StreamResult:
    """一次取流请求的不可变结果。"""

    request_id: int
    room_id: str
    quality: int
    urls: tuple[str, ...]


class GetStreamURL(QThread):
    """在后台获取直播流候选地址。"""

    streamUrl = Signal(object)
    downloadError = Signal()

    def __init__(self, sessionData=""):
        super().__init__()
        self.roomID = "0"
        self.quality = 250
        self.sessionData = sessionData or ""
        self.credential = normalize_credential_data(sessdata=self.sessionData)
        self.recordToken = False
        self._stream_candidates = []
        self._preferredCdnHost = ""
        self._fetch_room_id = "0"
        self._fetch_quality = self.quality
        self._request_id = 0

    def markCdnGood(self, url):
        """记住稳定 CDN，下一次取流时优先返回同一主机。"""
        host = urlparse(str(url)).hostname
        if host:
            self._preferredCdnHost = host

    def setConfig(self, roomID, quality, sessionData, credential=None):
        self.roomID = roomID
        self.quality = quality
        self.sessionData = sessionData or ""
        self.credential = normalize_credential_data(credential, sessdata=self.sessionData)
        self.recordToken = True
        self._request_id += 1

    def getStreamUrl(self):
        """同步获取当前配置对应的地址，供诊断和兼容调用使用。"""
        urls = self._get_stream_urls(
            self.roomID,
            self.quality,
            self.sessionData,
            self.credential,
            self._preferredCdnHost,
        )
        self._stream_candidates = urls
        return urls

    @staticmethod
    def _get_stream_urls(room_id, quality, session_data, credential, preferred_host):
        only_audio = quality < 0
        qn_mapping = {
            10000: live.ScreenResolution.ORIGINAL,
            400: live.ScreenResolution.BLU_RAY,
            250: live.ScreenResolution.ULTRA_HD,
            150: live.ScreenResolution.HD,
            80: live.ScreenResolution.FLUENCY,
        }
        room = live.LiveRoom(
            int(room_id),
            credential=build_credential(credential, sessdata=session_data),
        )
        qn = qn_mapping.get(abs(quality), live.ScreenResolution.ORIGINAL)
        play_info = sync(room.get_room_play_info_v2(live_qn=qn))
        stream = play_info["playurl_info"]["playurl"]["stream"][0]
        format_info = stream["format"][0]
        codec_info = format_info["codec"][0]
        media_info = codec_info["audio_codecs"][0] if only_audio and codec_info.get("audio_codecs") else codec_info
        base_url = media_info["base_url"]

        stream_urls = []
        invalid_count = 0
        for url_info in media_info.get("url_info", []):
            stream_url = f"{url_info.get('host', '')}{base_url}{url_info.get('extra', '')}"
            if is_valid_stream_url(stream_url) and stream_url not in stream_urls:
                stream_urls.append(stream_url)
            else:
                invalid_count += 1
        if not stream_urls:
            raise RuntimeError("未获取到可用直播流地址")

        if preferred_host:
            preferred = [url for url in stream_urls if urlparse(url).hostname == preferred_host]
            others = [url for url in stream_urls if urlparse(url).hostname != preferred_host]
            stream_urls = preferred + others
        if invalid_count:
            logging.warning("房间 %s 过滤掉 %s 条无效流地址", room_id, invalid_count)
        return stream_urls

    def run(self):
        request_id = self._request_id
        room_id = str(self.roomID)
        quality = self.quality
        session_data = self.sessionData
        credential = dict(self.credential)
        preferred_host = self._preferredCdnHost
        try:
            if not self.recordToken:
                return
            self._fetch_room_id = room_id
            self._fetch_quality = quality
            urls = self._get_stream_urls(room_id, quality, session_data, credential, preferred_host)
            if not self.recordToken or request_id != self._request_id:
                logging.info("请求配置已变化，丢弃获取到的流地址")
                return
            self._stream_candidates = urls
            self.streamUrl.emit(StreamResult(request_id, room_id, quality, tuple(urls)))
        except Exception as error:
            if not self.recordToken or request_id != self._request_id:
                return
            logging.error(str(error))
            logging.exception("直播地址获取失败")
            self.downloadError.emit()


class FetchRoomInfo(QThread):
    """在后台获取房间标题、主播和直播状态。"""

    roomInfo = Signal(dict)

    def __init__(self):
        super().__init__()
        self.roomID = "0"
        self.sessionData = ""

    def setConfig(self, roomID, sessionData=""):
        self.roomID = roomID
        self.sessionData = sessionData

    def run(self):
        room_id = str(self.roomID)
        session_data = self.sessionData
        if room_id == "0":
            self.roomInfo.emit({"roomID": room_id, "error": "no_room"})
            return

        params = {"req_biz": "web_room_componet", "room_ids": [room_id]}
        cookies = {"SESSDATA": session_data} if session_data else {}
        try:
            response = http_utils.get(
                "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo",
                params=params,
                headers=http_utils.DEFAULT_HEADERS,
                cookies=cookies,
            )
            data = response.json()
            result = {"roomID": room_id}
            if data["message"] == "房间已加密":
                result.update(title="房间已加密", uname=f"房号: {room_id}", live_status=0)
            elif not data["data"]:
                result.update(title="房间好像不见了-_-？", uname="未定义", live_status=0)
            else:
                info = data["data"]["by_room_ids"][room_id]
                result.update(
                    live_status=info["live_status"],
                    live_time=info["live_time"],
                    title=info["title"],
                    uname=info["uname"],
                )
            self.roomInfo.emit(result)
        except Exception as error:
            logging.error(str(error))
            self.roomInfo.emit(
                {
                    "roomID": room_id,
                    "title": "获取信息失败",
                    "uname": f"房号: {room_id}",
                    "live_status": 0,
                }
            )
