# -*- coding: utf-8 -*-
"""
通过QThread + websocket获取直播弹幕并返回给播放窗口模块做展示
"""
import asyncio
# import zlib
import json
import requests
from aiowebsocket.converses import AioWebSocket
from PySide2.QtCore import QThread, Signal
import logging
import struct
import brotli


def unpack(data: bytes):
    """
    解包数据
    """
    ret = []
    offset = 0
    header = struct.unpack(">IHHII", data[:16])
    if header[2] == 3:
        realData = brotli.decompress(data[16:])
    else:
        realData = data

    if header[2] == 1 and header[3] == 3:
        realData = realData[16:]
        # 心跳包协议特殊处理
        recvData = {
            "protocol_version": header[2],
            "datapack_type": header[3],
            "data": {
                "view": struct.unpack('>I', realData[0:4])[0]
            }
        }
        ret.append(recvData)
        return ret

    while offset < len(realData):
        header = struct.unpack(">IHHII", realData[offset:offset + 16])
        length = header[0]
        recvData = {
            "protocol_version": header[2],
            "datapack_type": header[3],
            "data": None
        }
        chunkData = realData[(offset + 16):(offset + length)]
        if header[2] == 0:
            recvData["data"] = json.loads(chunkData.decode())
        elif header[2] == 2:
            recvData["data"] = json.loads(chunkData.decode())
        elif header[2] == 1:
            if header[3] == 3:
                recvData["data"] = {
                    "view": struct.unpack(">I", chunkData)[0]}
            elif header[3] == 8:
                recvData["data"] = json.loads(chunkData.decode())
        ret.append(recvData)
        offset += length
    return ret


class remoteThread(QThread):
    message = Signal(str)

    def __init__(self, roomID):
        super(remoteThread, self).__init__()
        self.roomID = roomID
        if len(self.roomID) <= 3:
            if self.roomID == '0':
                return
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/63.0.3239.132 Safari/537.36 QIHU 360SE'}
            html = requests.get('https://live.bilibili.com/' +
                                self.roomID, headers=headers).text
            for line in html.split('\n'):
                if '"roomid":' in line:
                    self.roomID = line.split('"roomid":')[1].split(',')[0]

    async def startup(self, url):
        logging.info('尝试打开 %s 的弹幕Socket' % self.roomID)
        verifyData = {"roomid": int(self.roomID), "protover": 3}
        req = json.dumps(verifyData)
        head = bytearray(
            [0x00, 0x00, 0x00, 16 + len(req),
             0x00, 0x10, 0x00, 0x01,
             0x00, 0x00, 0x00, 0x07,
             0x00, 0x00, 0x00, 0x01]
        )
        data_raw = bytes(head + req.encode())

        async with AioWebSocket(url) as aws:
            try:
                converse = aws.manipulator
                # await converse.send(bytes.fromhex(data_raw))
                await converse.send(data_raw)
                tasks = [self.receDM(converse), self.sendHeartBeat(converse)]
                await asyncio.wait(tasks)
            except:
                logging.exception('弹幕Socket打开失败')

    async def sendHeartBeat(self, websocket):
        logging.debug("向%s发送心跳包" % self.roomID)
        hb = '00000010001000010000000200000001'
        while True:
            await asyncio.sleep(30)
            await websocket.send(bytes.fromhex(hb))

    async def receDM(self, websocket):
        while True:
            recv_text = await websocket.receive()
            logging.debug("从%s接收到DM" % self.roomID)
            self.printDM(recv_text)

    def printDM(self, data):
        captainName = {
            0: "",
            1: "总督",
            2: "提督",
            3: "舰长"
        }
        userType = {
            "#FF7C28": "+++",
            "#E17AFF": "++",
            "#00D1F1": "+",
            "": ""
        }
        adminType = ["", "*"]
        def getMetal(jd):
            try:
                medal = []
                if jd['cmd'] == 'DANMU_MSG':
                    jz = captainName[jd['info'][3][10]]
                    if jz:
                        medal.append(jz)
                    medal.append(jd['info'][3][1])
                    medal.append(str(jd['info'][3][0]))
                else:
                    jz = captainName[jd['data']['medal_info']['guard_level']]
                    if jz:
                        medal.append(jz)
                    medal.append(jd['data']['medal_info']['medal_name'])
                    medal.append(jd['data']['medal_info']['medal_level'])
                return "|" + "|".join(medal) + "|"
            except:
                return ""
        if data:
            data = unpack(data)
            for info in data:
                if info['datapack_type'] == 5:  # 弹幕 礼物
                    jd = info["data"]
                    try:
                        if jd['cmd'] == 'DANMU_MSG':
                            self.message.emit(f"{jd['info'][1]}")
                        elif jd['cmd'] == 'SUPER_CHAT_MESSAGE':
                            self.message.emit(
                                f"【SC(￥{jd['data']['price']}) {getMetal(jd)} {jd['data']['user_info']['uname']}: {jd['data']['message']}】"
                            )
                        elif jd['cmd'] == 'SEND_GIFT':
                            if jd['data']['coin_type'] == "gold":
                                self.message.emit(
                                    f"** {jd['data']['uname']} {jd['data']['action']}了 {jd['data']['num']} 个 {jd['data']['giftName']}"
                                )
                        elif jd['cmd'] == 'USER_TOAST_MSG':
                            self.message.emit(
                                f"** {jd['data']['username']} 上了 {jd['data']['num']} 个 {captainName[jd['data']['guard_level']]}"
                            )
                        elif jd['cmd'] == 'ROOM_BLOCK_MSG':
                            self.message.emit(
                                f"** 用户 {jd['data']['uname']} 已被管理员禁言"
                            )
                        elif jd['cmd'] == 'INTERACT_WORD':
                            self.message.emit(
                                f"## 用户 {jd['data']['uname']} 进入直播间"
                            )
                        elif jd['cmd'] == 'ENTRY_EFFECT':
                            self.message.emit(
                                f"## {jd['data']['copy_writing_v2']}"
                            )
                        elif jd['cmd'] == 'COMBO_SEND':
                            self.message.emit(
                                f"** {jd['data']['uname']} 共{jd['data']['action']}了 {jd['data']['combo_num']} 个 {jd['data']['gift_name']}"
                            )
                    except:
                        logging.exception('弹幕输出失败')

    def setRoomID(self, roomID):
        self.roomID = int(roomID)

    def run(self):
        remote = r'wss://broadcastlv.chat.bilibili.com:2245/sub'
        try:
            asyncio.set_event_loop(asyncio.new_event_loop())
            asyncio.get_event_loop().run_until_complete(self.startup(remote))
        except:
            logging.exception('弹幕主循环出错')