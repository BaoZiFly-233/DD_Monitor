# DD监控室 多平台扩展技术方案（B站 / 虎牙 / 斗鱼）

> 版本：v1.0（调研稿）  
> 日期：2026-08-06  
> 范围：B站现有能力风险兜底 + 新增虎牙、斗鱼（含斗鱼+）平台支持

---

## 目录

1. [B站 API 稳定性评估与兜底策略](#1-b站-api-稳定性评估与兜底策略)
2. [虎牙平台调研](#2-虎牙平台调研)
3. [斗鱼平台调研（含斗鱼+）](#3-斗鱼平台调研含斗鱼)
4. [统一架构设计](#4-统一架构设计)
5. [统一数据模型](#5-统一数据模型)
6. [接口封装设计](#6-接口封装设计)
7. [兼容层与降级处理](#7-兼容层与降级处理)
8. [可行性评估](#8-可行性评估)
9. [风险提示与合规声明](#9-风险提示与合规声明)
10. [实施路线图](#10-实施路线图)

---

## 1. B站 API 稳定性评估与兜底策略

### 1.1 当前状态（已实测）

| 维度 | 现状 | 评估 |
|---|---|---|
| bilibili-api-python | 17.4.2（2026-08 最新） | ✅ 活跃维护，fork 自原仓库持续更新 |
| 上游仓库 | nemo2011/bilibili-api，活跃 | ✅ 官方明确"接口可能改动，请及时更新最新版" |
| 内置 WBI 签名 | 已内置（`_enc_wbi` / `get_wbi_mixin_key`） | ✅ 17.x 自动处理 wbi 签名，无需手写 |
| 取流接口 | `get_room_play_info_v2` 自带风控应对 | ✅ 请求头/cookie 自动补充 |
| 弹幕协议 | blivedm vendored v1.1.6（与上游零差异） | ✅ 见上一轮审查 |

### 1.2 主要风险点

1. **接口变更风险**：B站接口非公开契约，随时可能改字段/加签名。历史上已发生：wbi 签名引入（2023）、`-352` 风控升级（2024）、`getRoomBaseInfo` 字段调整等。
2. **风控风险**：
   - `-352` 风控校验失败 → 需 `v_voucher` 验证码流程或等冷却
   - `412` 请求过快 → IP 暂时封禁
   - 登录态失效（SESSDATA 约 6 个月）
3. **维护者风险**：bilibili-api-python 是社区逆向维护，若维护者停更，接口一变动即失效。
4. **项目自身风险**：`LiverSelect.py` 依赖 `live_area` 分区接口，历史上触发过 `-352`（已有 fallback 到 HTTP 直连）。

### 1.3 兜底与容错策略

**分层降级（按优先级）：**

```
L1（现状）: bilibili-api-python 官方封装
  └─ 失败 → L2: 直接 HTTP 调用 B站公开 JSON 接口（api.live.bilibili.com）
      └─ 失败 → L3: 解析直播间页面 HTML（如 52pojie 总结的 playUrl 拼接方案）
          └─ 失败 → L4: 提示"平台接口临时不可用"，保留 UI 不崩溃
```

**具体措施：**

| 措施 | 说明 |
|---|---|
| ① 版本锁定 + 定期检查 | `>=17,<18` 已锁；每季度检查 18.x 发布并验证 |
| ② HTTP fallback 层 | `LiverSelect` 已示范（`-352` 时切换直连 API）；推广到取流/房间信息 |
| ③ 请求频率控制 | 全局限流：热门列表 ≥5s/页，房间轮询 ≥60s/轮（已具备） |
| ④ 登录态预检 | 启动时静默验证（已有 `FetchUserInfo`），过期提前提示 |
| ⑤ 弹幕降级 | blivedm → bilibili-api 自带 `LiveDanmaku`（同作者、随 pip 分发）→ 纯 HTTP 轮询房间状态（仅开播提醒，无弹幕） |
| ⑥ 错误上报 | 关键接口失败时写入日志 + 状态栏提示，不静默 |

**兜底弹幕实现（L2 方案预览）：**

```python
# fallback_danmaku.py（概念）
# 不依赖 blivedm，直接连 B站弹幕 WebSocket
# 地址: wss://broadcastlv.chat.bilibili.com/sub  （blivedm 内部即此协议）
# 鉴权: 无需登录，发送 {uid, roomid, protover: 2, buvid: <随机>} 认证包
# 数据: 二进制包 -> zlib 解压 -> JSON -> cmd 字段区分弹幕/礼物/SC
```

> 结论：B站现有依赖风险**可控但不可忽视**。建议保持当前方案 + 落实 L2 HTTP fallback 层，无需立即替换。

---

## 2. 虎牙平台调研

### 2.1 官方渠道（开放平台）

- 地址：`open.huya.com` / `dev.huya.com`
- 能力：弹幕 WebSocket（`ws-apiext.huya.com`）、开放 API（HTTPS `open-apiext.huya.com`）
- **鉴权门槛：仅对企业认证开发者开放**。需营业执照 + 授权书 + 邮件申请（`hy-ext@huya.com`），个人开发者不可用。
- 协议：JWT sToken 鉴权；WS 订阅命令 `subscribeNotice`；15s ping 心跳。
- 消息类型：`getMessageNotice`（弹幕）、`getSendItemNotice`（礼物）、`getVipEnterBannerNotice`（进场）等。

### 2.2 网页端逆向方案（无鉴权，社区常用）

**直播间信息 + 流地址**：抓 `https://m.huya.com/{roomId}` 页面

- 正则提取 `window.HNF_GLOBAL_INIT = {...}` → `roomInfo` 节点
  - `eLiveStatus`：1=未开播，2=直播中，3=录像
  - `tLiveInfo.tLiveStreamInfo.vStreamInfo.value[]` → 各 CDN 的 FLV/HLS 地址
- 或提取 `hyPlayerConfig`（base64 编码的 stream 配置，Dlink_Parse 方案）
- **流地址有效期**：CDN 带 `wsSecret`/`wsTime` 签名，需实时拼接（`real-url` 项目有成熟实现）
- 备选：`liveLineUrl` + `wsSecret` MD5 签名算法（见 leaf2006/real-url）

**弹幕**：网页版内部走虎牙自研 WebSocket（`wss://cdnws.api.huya.com`），协议为二进制 + zlib；社区已有逆向实现（多用于 Python 爬虫）。

### 2.3 数据字段速览

| 数据 | 来源 | 关键字段 |
|---|---|---|
| 房间信息 | 页面 `HNF_GLOBAL_INIT` | roomId、eLiveStatus、主播名、标题、封面 |
| 直播流 | 页面 streamInfo | sFlvUrl、sHlsUrl、sStreamName、sFlvAntiCode（签名） |
| 弹幕 | WS 推送 | sendNick（用户）、content（内容） |
| 礼物 | WS 推送 | sendNick、itemName、itemCount |
| 进场 | WS 推送 | userNick、nobleName |

### 2.4 可行性结论

| 维度 | 评估 |
|---|---|
| 房间/流信息 | ✅ 易（页面解析，无鉴权） |
| 弹幕 | ⚠️ 中等（二进制 WS 协议需逆向，社区有参考实现） |
| 礼物/进场 | ⚠️ 中等（同弹幕通道） |
| 开放平台 | 🔒 个人开发者不可用，仅作备选 |

---

## 3. 斗鱼平台调研（含斗鱼+）

### 3.1 官方渠道（开放平台）

- 地址：`open.douyu.com`（需登录查看协议文档）
- 弹幕服务器：`openbarrage.douyucdn.cn:8601`（TCP 长连接，协议 V1.4.1）
- **鉴权**：官方开放平台登录后可看文档，但实际接入门槛和虎牙类似（合作申请）

### 3.2 网页端逆向方案（社区主流）

**弹幕协议（核心难点）**：斗鱼私有 STT 序列化 + 二进制帧

```
帧格式（小端）: [消息长度4B][消息长度4B][消息类型2B][加密字段1B][保留字段1B][消息体][\0]
消息类型: 689=弹幕频道
序列化: key@=value/ 字段分隔；@→@A，/→@S 转义
```

连接流程（WebSocket 版，`wss://danmuproxy.douyu.com:8506` 或 6 端口轮换）：

```
1. loginreq: type@=loginreq/roomid@={rid}/username@=/uid@=/
2. joingroup: type@=joingroup/rid@={rid}/gid@=-9999/
3. 心跳:     type@=mrkl/ （约 30-45s 一次）
4. 接收:     chatmsg(弹幕: nn=昵称, txt=内容), dgb(礼物), uenter(进场)
```

**已有库参考**：
- `chenguaself/douyudm`（Node.js，WebSocket 实现，含 STT 编解码，6 端口轮换）
- `flxxyz/douyudm`（Node.js，弹幕+录制+ASS 导出）
- Python 社区大量 TCP 直连实现（协议 V1.4.1 编解码）

**直播间信息 + 流地址**：
- 房间信息：`https://www.douyu.com/{rid}` 页面解析，或
- 直播源接口：`https://www.douyu.com/betard/{rid}`（需 cookie + `sign` 参数，签名算法已由社区逆向）

### 3.3 斗鱼+ 客户端差异（重点）

> 斗鱼+（douyuplus）是第三方增强客户端。**"适配斗鱼+客户端"理解为：我们的监控室需要能解析斗鱼+ 体系下的房间/主播标识**。

| 维度 | 网页版 | 斗鱼+ 客户端 |
|---|---|---|
| 房间号 | 纯数字 rid | 数字 rid 相同；斗鱼+ 额外有房间别名/短链 |
| 弹幕协议 | WebSocket/TCP 均可 | 同网页协议（TCP 直连为主，老版本兼容） |
| 流地址 | betard 接口 + sign | 同网页版接口 |
| 特殊字段 | — | 斗鱼+ 会用到房间加密态（`room_id` vs `real_room_id`，短号需解析） |
| 鉴权 | 无需登录可看直播 | 无额外差异 |

**关键适配点**：
1. **短号解析**：斗鱼短号（如 9999）需通过 `https://www.douyu.com/{short}` 重定向或 `room_id` 接口解析为真实房间号（类似 B站短号 `_resolve_short_room_id` 已有先例）
2. **加密房间**：部分房间返回 `room_id`（显示号）与真实流房间号不同，取流需用真实号
3. **心跳差异**：弹幕心跳 30-45s，比 B站（30s）略宽松，需按平台配置

### 3.4 数据字段速览

| 数据 | 来源 | 关键字段 |
|---|---|---|
| 房间信息 | betard 接口 | room_id、room_name、owner_name、show_status、pic |
| 直播流 | betard 接口 | rtmp_url / flv_url / hls_url（多线路） |
| 弹幕 | WS/TCP | nn（昵称）、txt（内容）、col（颜色） |
| 礼物 | WS/TCP | nn、gfid（礼物id）、gfcnt（数量） |
| 进场 | WS/TCP | nn（昵称）、level |

### 3.5 可行性结论

| 维度 | 评估 |
|---|---|
| 房间/流信息 | ⚠️ 中等（betard 需 sign 签名逆向，页面解析可兜底） |
| 弹幕 | ⚠️ 中高（STT 协议编解码复杂度高，但社区库/文章充足） |
| 礼物/进场 | ⚠️ 中等（同弹幕通道解析） |
| 斗鱼+ 适配 | ⚠️ 中等（短号解析 + 加密房间号处理） |

---

## 4. 统一架构设计

### 4.1 设计目标

- **业务层零感知**：UI / 播放 / 录制层不关心平台差异，只面向统一模型
- **平台即插即用**：新增平台 = 新增一个 adapter，不动主流程
- **降级优先**：任何平台接口失败 → 降级 → 提示，绝不崩溃

### 4.2 架构分层

```
┌─────────────────────────────────────────────────────┐
│  UI 层（现有）                                       │
│  卡片面板 / 播放窗口 / 弹幕机 / 设置面板              │
└──────────────────────┬──────────────────────────────┘
                       │ 统一数据模型（dataclass）
┌──────────────────────▼──────────────────────────────┐
│  平台抽象层  platform/                               │
│  ├─ base.py        PlatformAdapter 抽象基类          │
│  ├─ bilibili.py    B站 adapter（封装现有实现）        │
│  ├─ huya.py        虎牙 adapter（新增）               │
│  ├─ douyu.py       斗鱼 adapter（新增）               │
│  └─ registry.py    平台注册表 + 工厂                 │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  能力模块                                            │
│  ├─ RoomInfoFetcher    直播间信息（轮询/一次性）      │
│  ├─ StreamURLFetcher   直播流地址获取                │
│  ├─ DanmakuChannel     弹幕推送（独立线程）           │
│  └─ LiveStatusWatcher  开播状态监控                  │
└─────────────────────────────────────────────────────┘
```

### 4.3 新增目录结构

```
platform/
├── __init__.py
├── base.py              # PlatformAdapter / 统一模型
├── models.py            # RoomInfo / StreamInfo / DanmakuEvent 等 dataclass
├── registry.py          # 平台注册、工厂函数
├── bilibili/
│   ├── __init__.py
│   ├── adapter.py       # 封装现有 bilibili-api + blivedm
│   └── http_fallback.py # L2 HTTP 直连兜底
├── huya/
│   ├── __init__.py
│   ├── adapter.py
│   ├── page_parser.py   # HNF_GLOBAL_INIT 解析
│   └── danmaku.py       # WS 弹幕
└── douyu/
    ├── __init__.py
    ├── adapter.py
    ├── stt.py           # STT 序列化/反序列化
    ├── protocol.py      # 帧编解码 / 心跳
    └── danmaku.py       # WS 弹幕
```

---

## 5. 统一数据模型

```python
# platform/models.py
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Platform(str, Enum):
    BILIBILI = "bilibili"
    HUYA = "huya"
    DOUYU = "douyu"


@dataclass(frozen=True)
class RoomInfo:
    """统一直播间信息（各平台 adapter 负责转换为本模型）"""
    platform: Platform
    room_id: str              # 平台内唯一真实房间号
    display_id: str           # 展示用房号（短号/别名，可能同 room_id）
    title: str
    uname: str                # 主播名
    face: str = ""            # 头像 URL
    cover: str = ""           # 封面/关键帧 URL
    live_status: int = 0      # 0=未开播 1=直播中 2=录像（对齐 B站）
    live_time: str = ""       # 开播时间（平台原始字符串）
    extra: dict = field(default_factory=dict)  # 平台私有字段


@dataclass(frozen=True)
class StreamInfo:
    """统一直播流信息"""
    platform: Platform
    room_id: str
    urls: list = field(default_factory=list)  # 按优先级排序的候选流 URL
    quality: int = 250        # 统一画质档位（见 QUALITY_MAP）
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class DanmakuEvent:
    """统一弹幕事件（remote.py 的 DanmakuEvent 升级版）"""
    platform: Platform
    kind: str = "danmaku"     # danmaku / gift / guard / super_chat / enter
    text: str = ""
    uname: str = ""
    color: str = "#FFFFFF"
    price: float = 0.0
    position: str = "scroll"  # scroll / top / bottom
    raw: dict = field(default_factory=dict)  # 平台原始消息


# 画质档位映射（各平台 → 统一档位）
# 10000=原画 400=蓝光 250=超清 80=流畅 -1=仅音频（对齐 B站）
QUALITY_MAP = {
    Platform.BILIBILI: {10000: 10000, 400: 400, 250: 250, 80: 80, -1: -1},
    Platform.HUYA: {10000: "原画", 400: "蓝光", 250: "超清", 80: "流畅", -1: None},
    Platform.DOUYU: {10000: "原画", 400: "蓝光", 250: "超清", 80: "流畅", -1: None},
}
```

---

## 6. 接口封装设计

```python
# platform/base.py
from abc import ABC, abstractmethod
from typing import Optional

from .models import DanmakuEvent, RoomInfo, StreamInfo


class PlatformAdapter(ABC):
    """平台适配器抽象基类 —— 所有平台实现此接口"""

    platform: str  # "bilibili" / "huya" / "douyu"

    # ---------- 直播间信息 ----------
    @abstractmethod
    async def fetch_room_info(self, room_id: str) -> Optional[RoomInfo]:
        """获取直播间信息（标题/主播/状态/封面）。失败返回 None。"""

    @abstractmethod
    async def resolve_room_id(self, input_id: str) -> str:
        """短号/别名 → 真实房间号。解析失败原样返回。"""

    # ---------- 直播流 ----------
    @abstractmethod
    async def fetch_stream_url(self, room_id: str, quality: int) -> Optional[StreamInfo]:
        """获取直播流地址。未开播/失败返回 None。"""

    # ---------- 弹幕 ----------
    @abstractmethod
    def create_danmaku_channel(self, room_id: str, on_event, session_data: str = "") -> "DanmakuChannel":
        """创建弹幕推送通道（QThread 封装）。"""

    # ---------- 开播状态 ----------
    @abstractmethod
    async def watch_live_status(self, room_id: str) -> int:
        """查询开播状态（供轮询监控）。"""


class DanmakuChannel(ABC):
    """弹幕通道抽象 —— remoteThread 的平台化泛化"""

    @abstractmethod
    def start(self): ...

    @abstractmethod
    def stop(self): ...

    @abstractmethod
    def is_running(self) -> bool: ...


# platform/registry.py
_ADAPTERS: dict = {}


def register(adapter_cls):
    _ADAPTERS[adapter_cls.platform] = adapter_cls()
    return adapter_cls


def get_adapter(platform: str) -> PlatformAdapter:
    if platform not in _ADAPTERS:
        raise ValueError(f"未注册的平台: {platform}")
    return _ADAPTERS[platform]
```

### 关键改造点（对接现有代码）

| 现有代码 | 改造方式 |
|---|---|
| `remote.py::remoteThread` | 泛化为 `DanmakuChannel`，按平台选择实现；`DanmakuHandler` 改为统一事件映射 |
| `VideoWidget_mpv.py::GetStreamURL` | 改为调用 `adapter.fetch_stream_url()`；`qn_mapping` 换 `QUALITY_MAP` |
| `VideoWidget_mpv.py::FetchRoomInfo` | 改为调用 `adapter.fetch_room_info()` |
| `LiverSelect.py::CollectLiverInfo` | 批量查询按平台分组，各平台 adapter 实现 `fetch_batch` |
| `DD监控室.py` 全局 | room_id 统一为 `"bilibili:123456"` 或 `"huya:123456"` 前缀格式（config 迁移） |

### 房间号格式约定

```
B站:   bilibili:1024
虎牙:  huya:518512
斗鱼:  douyu:9999
```

config 中 `roomid` / `player` 数组存上述格式；`_normalize_room_id` 兼容旧纯数字（默认 B站）。

---

## 7. 兼容层与降级处理

### 7.1 旧配置兼容

- 纯数字房号 → 自动补 `bilibili:` 前缀（迁移函数在 `config_manager._migrate` 中）
- `player` / `roomid` / `danmu` 等数组长度不变，只改元素格式

### 7.2 降级矩阵

| 场景 | 降级路径 |
|---|---|
| B站取流失败 | `bilibili-api` → HTTP playUrl → 页面拼接 → 提示重试 |
| B站弹幕失败 | blivedm → `LiveDanmaku` → 纯开播提醒（无弹幕） |
| 虎牙信息失败 | 页面 `HNF_GLOBAL_INIT` → `hyPlayerConfig` → 提示 |
| 虎牙弹幕失败 | WS 弹幕 → 仅显示直播间状态（无弹幕） |
| 斗鱼取流失败 | betard → 页面解析 → 提示 |
| 斗鱼弹幕失败 | 6 端口轮换 → TCP 直连 → 仅开播提醒 |
| 所有平台全部失败 | 状态栏黄条提示"网络异常/平台风控"，UI 不崩 |

### 7.3 降级实现要点

- **统一错误类型**：`PlatformError(平台, 阶段, 可重试)`，UI 统一渲染
- **重试策略**：复用 `http_utils.get(retries=)` + 指数退避
- **熔断**：单平台连续失败 N 次 → 停 60s 再试，防风控升级
- **弹幕通道级联**：`remoteThread` 改造为可插拔，主线程只接 `DanmakuEvent`

---

## 8. 可行性评估

| 平台 | 直播间信息 | 直播流 | 弹幕 | 礼物/进场 | 综合难度 | 建议 |
|---|---|---|---|---|---|---|
| B站（现状） | ✅ 已有 | ✅ 已有 | ✅ 已有 | ✅ 已有 | — | 保持 + L2 fallback |
| 虎牙 | ✅ 易 | ✅ 易（页面解析） | ⚠️ 中（WS 逆向） | ⚠️ 中 | ★★☆ | **第 2 优先** |
| 斗鱼 | ⚠️ 中（betard+sign） | ⚠️ 中 | ⚠️ 中高（STT 协议） | ⚠️ 中 | ★★★ | **第 3 优先** |
| 斗鱼+ 适配 | ⚠️ 短号/加密房处理 | ⚠️ 同斗鱼 | ⚠️ 同斗鱼 | ⚠️ 同斗鱼 | ★★★ | 与斗鱼一并实施 |

**排序建议**：B站兜底（L2）→ 虎牙 → 斗鱼 → 斗鱼+ 适配。虎牙先行因为其页面解析方案最成熟、无签名门槛；斗鱼因 STT 协议复杂排后。

### 工作量估算

| 模块 | 预估（人日） |
|---|---|
| B站 HTTP fallback 层 | 2-3 |
| platform 抽象层 + models + registry | 2-3 |
| 虎牙 adapter（信息+流+弹幕） | 3-5 |
| 斗鱼 adapter（STT+协议+弹幕） | 5-8 |
| 斗鱼+ 适配（短号/加密房） | 1-2 |
| UI 对接（房号格式、平台徽标、错误提示） | 2-3 |
| 回归测试 + 打包 | 2 |
| **合计** | **17-26 人日** |

---

## 9. 风险提示与合规声明

### 9.1 技术风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 虎牙/斗鱼接口随时变更 | 高 | 页面解析 + 多源降级；逆向实现封装在 adapter 内，变更只改一个文件 |
| STT 协议复杂度高 | 中 | 参考成熟库（douyudm）+ 充分单测 |
| 流地址签名时效短 | 中 | 播放前实时获取；断流重取（现有 `checkPlayStatus` 机制复用） |
| 多平台弹幕并发线程 | 中 | 每房间 1 线程（现架构已是），总量控制 ≤32 |
| 风控封禁 | 高 | 频率控制 + 熔断 + 代理支持 |

### 9.2 合规声明

> **重要**：虎牙、斗鱼网页端接口均为非官方逆向方案，仅限个人学习研究用途，禁止用于商业牟利、恶意刷屏、流量攻击等行为。本项目遵循各平台用户协议与《反不正当竞争法》精神，公开接口失效时优先降级而非暴力破解。若平台开放平台政策放宽（如企业认证免费开放），应优先迁移到官方接口。

---

## 10. 实施路线图

```
Phase 1（1-3 天）: platform 抽象层 + models + registry + B站 adapter 重构（不动现有 UI）
Phase 2（3-5 天）: B站 HTTP fallback 层（L2 兜底）+ 弹幕 LiveDanmaku 备选
Phase 3（5-10 天）: 虎牙 adapter（页面解析 + WS 弹幕）
Phase 4（8-14 天）: 斗鱼 adapter（STT + 协议 + WS/TCP）+ 斗鱼+ 短号适配
Phase 5（3-5 天）: UI 对接（房号前缀、平台徽标、错误降级提示）+ 回归测试
```

**验收标准**：三平台均可完成「添加房间 → 显示信息 → 播放 → 弹幕 → 开播提醒」全流程；任一平台接口失效时其余平台不受影响，且 UI 有明确降级提示。
