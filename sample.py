# -*- coding: utf-8 -*-
import asyncio
import http.cookies
import random
from typing import *

import aiohttp

import blivedm
import blivedm.models.web as web_models

# 这里填一个已登录账号的cookie的SESSDATA字段的值。不填也可以连接，但是收到弹幕的用户名会打码，UID会变成0
SESSDATA = ''

session: Optional[aiohttp.ClientSession] = None

class blive:
    def __init__(self, room_id):
        self.room_id = room_id

    async def main(self):
        self.init_session()
        try:
            await self.run_single_client(self.room_id)
        finally:
            await session.close()


    def init_session(self):
        cookies = http.cookies.SimpleCookie()
        cookies['SESSDATA'] = SESSDATA
        cookies['SESSDATA']['domain'] = 'bilibili.com'

        global session
        session = aiohttp.ClientSession()
        session.cookie_jar.update_cookies(cookies)


    async def run_single_client(self, room_id):
        """
        演示监听一个直播间
        """
        # room_id = random.choice(TEST_ROOM_IDS)
        client = blivedm.BLiveClient(room_id, session=session)
        self.handler = MyHandler()
        client.set_handler(self.handler)

        client.start()
        try:
            # 演示5秒后停止
            # await asyncio.sleep(5)
            # client.stop()

            await client.join()
        finally:
            await client.stop_and_close()


# async def run_multi_clients():
#     """
#     演示同时监听多个直播间
#     """
#     clients = [blivedm.BLiveClient(room_id, session=session) for room_id in TEST_ROOM_IDS]
#     handler = MyHandler()
#     for client in clients:
#         client.set_handler(handler)
#         client.start()
#
#     try:
#         await asyncio.gather(*(
#             client.join() for client in clients
#         ))
#     finally:
#         await asyncio.gather(*(
#             client.stop_and_close() for client in clients
#         ))


class MyHandler(blivedm.BaseHandler):
    def __init__(self):
        self.data = {}
        self.giftLink = {}
    # # 演示如何添加自定义回调
    # _CMD_CALLBACK_DICT = blivedm.BaseHandler._CMD_CALLBACK_DICT.copy()
    #
    # # 入场消息回调
    # def __interact_word_callback(self, client: blivedm.BLiveClient, command: dict):
    #     print(f"[{client.room_id}] INTERACT_WORD: self_type={type(self).__name__}, room_id={client.room_id},"
    #           f" uname={command['data']['uname']}")
    # _CMD_CALLBACK_DICT['INTERACT_WORD'] = __interact_word_callback  # noqa

    def _on_heartbeat(self, client: blivedm.BLiveClient, message: web_models.HeartbeatMessage):
        # print(f'[{client.room_id}] 心跳')
        pass

    def _on_danmaku(self, client: blivedm.BLiveClient, message: web_models.DanmakuMessage):
        # print(f'[{client.room_id}] {message.uname}：{message.msg}')
        self.data = {
            'cmd': 'DANMU_MSG',
            'username': message.uname,
            'msg': message.msg,
        }

    def _on_gift(self, client: blivedm.BLiveClient, message: web_models.GiftMessage):
        # print(f'[{client.room_id}] {message.uname} 赠送{message.gift_name}x{message.num}'
        #       f' （{message.coin_type}瓜子x{message.total_coin}）')
        self.data = {
            'key': '%s_%s' % (message.uname, message.gift_name),
            'cmd': 'SEND_GIFT',
            'type': 'gift',
            'username': message.uname,
            'giftname': message.gift_name,
            'num': message.num,
            'price': 0 if message.coin_type == '银' else message.total_coin / 1000,
            'link': self.giftLink.get(message.gift_name, []),
        }

    def _on_buy_guard(self, client: blivedm.BLiveClient, message: web_models.GuardBuyMessage):
        # print(f'[{client.room_id}] {message.username} 购买{message.gift_name}')
        self.data = {
            'key': '%s_%s' % (message.username, message.gift_name),
            'cmd': 'GUARD_BUY',
            'type': 'guard',
            'username': message.username,
            'giftname': message.gift_name,
            'num': message.num,
            'price': message.price / 1000
        }

    def _on_super_chat(self, client: blivedm.BLiveClient, message: web_models.SuperChatMessage):
        # print(f'[{client.room_id}] 醒目留言 ¥{message.price} {message.uname}：{message.message}')
        self.data = {
            'key': '%s_%s' % (message.uname, message.message),
            'cmd': 'SUPER_CHAT_MESSAGE',
            'type': 'sc',
            'username': message.uname,
            'giftname': message.message,
            'num': 1,
            'price': message.price
        }


# if __name__ == '__main__':
#     asyncio.run(main())
