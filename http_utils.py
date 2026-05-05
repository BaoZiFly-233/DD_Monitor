"""
共享 HTTP 会话管理
提供全局 requests.Session 实现 TCP 连接复用，统一超时和 User-Agent 配置
"""
import time
import requests
from requests.adapters import HTTPAdapter

# 默认超时（秒）：连接超时 8s，读取超时 20s
DEFAULT_TIMEOUT = (8, 20)

# 默认请求头
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
}


def _create_session() -> requests.Session:
    """创建配置好连接池的 Session"""
    s = requests.Session()
    s.headers.update(DEFAULT_HEADERS)
    # 连接池配置：最大 20 连接，每个 host 最多 10 连接
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=10, max_retries=2)
    s.mount('https://', adapter)
    s.mount('http://', adapter)
    return s


# 全局共享 Session 实例
session = _create_session()


def get(url, **kwargs):
    """带默认超时的 GET 请求

    可选参数：
    - retries: 失败后重试次数（默认 0）
    - retry_backoff: 指数退避起始秒数（默认 0.2）
    """
    retries = max(0, int(kwargs.pop('retries', 0) or 0))
    retry_backoff = max(0.0, float(kwargs.pop('retry_backoff', 0.2) or 0.0))
    kwargs.setdefault('timeout', DEFAULT_TIMEOUT)
    last_error = None
    for attempt in range(retries + 1):
        try:
            return session.get(url, **kwargs)
        except requests.RequestException as e:
            last_error = e
            if attempt >= retries:
                raise
            if retry_backoff > 0:
                time.sleep(retry_backoff * (2 ** attempt))
    if last_error is not None:
        raise last_error


def post(url, **kwargs):
    """带默认超时的 POST 请求"""
    kwargs.setdefault('timeout', DEFAULT_TIMEOUT)
    return session.post(url, **kwargs)
