"""Pixiv AJAX API 的非同步客戶端：速率控制、逾時、退避重試、串流下載。

Pixiv 位於 Cloudflare 後方。被判定為機器人時回傳的不是 Pixiv 自己的限流回應，
而是 Cloudflare 的挑戰頁（`Just a moment...`）。這兩者要分開處理：
一般 429 重試就好，Cloudflare 挑戰則要退得更久，而且連續發生就該直接收手——
繼續重試只會加深機器人嫌疑。
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlparse

import aiofiles
import aiohttp

from .config import Config
from .paths import sanitize_component

log = logging.getLogger(__name__)

#: 這些狀態碼代表「等一下再試就好」，其餘一律直接失敗。
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
#: Cloudflare 挑戰頁的特徵字串（一律小寫比對）。
CHALLENGE_MARKERS = (
    'just a moment',
    'cf-browser-verification',
    'cf_chl',
    'checking your browser',
    'attention required',
)
#: 挑戰頁一定是 HTML；正常的圖片／JSON 回應不會是這些型別，
#: 所以只有這些 content-type 需要進一步檢查 body。
HTML_TYPES = frozenset({'text/html', 'application/xhtml+xml'})
#: 診斷時只讀開頭這麼多 bytes，不把整份 body 拉進記憶體。
PEEK_BYTES = 4096
#: Retry-After 再長也不等超過這個秒數，免得整批卡死。
MAX_RETRY_AFTER = 120.0
CHUNK_SIZE = 1 << 16
_SAFE_NAME = re.compile(r'^[A-Za-z0-9._-]+$')


class PixivError(RuntimeError):
    """所有本專案主動拋出的錯誤基底。"""


class PixivHTTPError(PixivError):
    def __init__(
        self,
        status: int,
        url: str,
        message: str = '',
        *,
        retry_after: float | None = None,
    ) -> None:
        self.status = status
        self.url = url
        self.retry_after = retry_after
        detail = f'：{message}' if message else ''
        super().__init__(f'HTTP {status} {url}{detail}')


class PixivChallengeError(PixivHTTPError):
    """Cloudflare 認為我們是機器人，擋下了請求。"""


class PixivBlockedError(PixivError):
    """連續遭遇 Cloudflare 挑戰，已主動中止這次執行。"""


class PixivAPIError(PixivError):
    """HTTP 200 但 body 帶著 error=true（cookie 過期時最常見）。"""


class _RateLimiter:
    """全域最小請求間隔。

    Semaphore 只限制「同時幾個請求在飛」，不限制「每秒送出幾個」——
    併發 8 但每個都是 50ms 就結束的話，實際速率照樣可以衝到每秒上百次。
    這個限制器補上缺的那一半。
    """

    def __init__(self, interval: float) -> None:
        self._interval = max(0.0, interval)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self, sleep: Callable[[float], Awaitable[None]]) -> None:
        # 就算 interval 是 0 也不能直接返回——pause() 設下的 Cloudflare
        # cooldown 也記在 _next_at 上，跳過檢查等於被擋之後繼續全速轟炸。
        async with self._lock:
            loop = asyncio.get_running_loop()
            wait = self._next_at - loop.time()
            if wait > 0:
                await sleep(wait)
            self._next_at = max(loop.time(), self._next_at) + self._interval

    def pause(self, seconds: float) -> None:
        """把所有後續請求往後推——遇到挑戰頁時全體一起放慢。"""
        loop = asyncio.get_running_loop()
        self._next_at = max(self._next_at, loop.time() + seconds)


class PixivClient:
    """包住 aiohttp session，統一處理速率、重試與檔案落地。"""

    def __init__(
        self,
        config: Config,
        *,
        session: aiohttp.ClientSession | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.config = config
        self._session = session
        self._owns_session = session is None
        self._semaphore = asyncio.Semaphore(max(1, config.concurrency))
        self._limiter = _RateLimiter(config.request_interval)
        self._sleep = sleep or asyncio.sleep
        self._consecutive_challenges = 0
        self._blocked = False

    async def __aenter__(self) -> PixivClient:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(
                total=self.config.timeout, connect=self.config.connect_timeout
            )
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise PixivError('PixivClient 必須在 async with 區塊內使用')
        return self._session

    @property
    def blocked(self) -> bool:
        return self._blocked

    def url(self, path: str) -> str:
        if path.startswith(('http://', 'https://')):
            return path
        return f'{self.config.base_url.rstrip("/")}/{path.lstrip("/")}'

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        referer: str | None = None,
    ) -> dict[str, Any]:
        url = self.url(path)
        headers = self.config.headers(referer)

        async def attempt() -> dict[str, Any]:
            async with self.session.get(url, headers=headers, params=params) as resp:
                await _raise_for_status(resp)
                try:
                    # Pixiv 對 JSON 端點回傳 text/plain，不能用預設的 content-type 檢查。
                    data = await resp.json(content_type=None)
                except ValueError as exc:
                    # JSONDecodeError 是 ValueError，不轉型的話它會穿過
                    # download_all 的 except 直接炸掉整批下載。
                    raise PixivAPIError(f'{url} 回傳的不是合法 JSON：{exc}') from exc
            if not isinstance(data, dict):
                raise PixivAPIError(f'{url} 回傳了非預期的 JSON 結構')
            if data.get('error'):
                raise PixivAPIError(data.get('message') or f'{url} 回報 error=true')
            return data

        return await self._with_retry(attempt, url)

    async def download(self, url: str, dest: Path, *, referer: str | None = None) -> bool:
        """串流寫入暫存檔再 rename；回傳 False 代表檔案已存在而跳過。"""
        if dest.exists():
            return False
        headers = self.config.headers(referer)
        tmp = dest.with_name(dest.name + '.part')

        async def attempt() -> bool:
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                async with self.session.get(url, headers=headers) as resp:
                    await _raise_for_status(resp)
                    async with aiofiles.open(tmp, 'wb') as fh:
                        async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                            await fh.write(chunk)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            tmp.replace(dest)
            return True

        return await self._with_retry(attempt, url)

    def _ensure_not_blocked(self) -> None:
        if self._blocked:
            raise PixivBlockedError(
                f'已連續 {self.config.challenge_limit} 次遭 Cloudflare 擋下，本次執行不再發出請求'
            )

    async def _with_retry(self, attempt: Callable[[], Awaitable[Any]], url: str) -> Any:
        # 入口檢查擋掉之後才排隊的呼叫，semaphore 內的檢查擋掉「已經在排隊、
        # 但排到自己時斷路器才跳開」的那一批——gather 會一次送進上百個任務，
        # 只檢查入口的話它們早就全部通過了。
        self._ensure_not_blocked()

        last: BaseException | None = None
        for tries in range(self.config.max_retries + 1):
            try:
                await self._limiter.acquire(self._sleep)
                async with self._semaphore:
                    self._ensure_not_blocked()
                    result = await attempt()
            except PixivChallengeError as exc:
                last = exc
                if self._note_challenge():
                    raise PixivBlockedError(
                        f'連續 {self.config.challenge_limit} 次遭 Cloudflare 擋下，已中止。'
                        '請降低 concurrency、調高 request-interval，或稍後再試。'
                    ) from exc
            except PixivHTTPError as exc:
                if exc.status not in RETRY_STATUSES:
                    raise
                self._consecutive_challenges = 0
                last = exc
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                self._consecutive_challenges = 0
                last = exc
            else:
                self._consecutive_challenges = 0
                return result

            if tries < self.config.max_retries:
                await self._sleep(self._backoff_for(last, tries))

        assert last is not None
        raise last

    def _note_challenge(self) -> bool:
        """記一次 Cloudflare 挑戰；回傳 True 代表該中止整批。"""
        self._consecutive_challenges += 1
        # 遇到挑戰就讓全體請求一起放慢，而不是只有這一個等。
        self._limiter.pause(self.config.challenge_backoff)
        if self._consecutive_challenges >= self.config.challenge_limit:
            self._blocked = True
            return True
        return False

    def _backoff_for(self, exc: BaseException | None, tries: int) -> float:
        if isinstance(exc, PixivHTTPError) and exc.retry_after is not None:
            # 伺服器明講要等多久，就照做，不要自作聰明。
            delay = min(exc.retry_after, MAX_RETRY_AFTER)
        elif isinstance(exc, PixivChallengeError):
            delay = self.config.challenge_backoff * (2**tries)
        else:
            delay = self.config.retry_backoff * (2**tries)
        delay += random.uniform(0, self.config.retry_backoff)  # 加抖動避免同時重試
        log.debug('%.1fs 後重試（%s）', delay, _short(exc))
        return delay


def _short(exc: BaseException | None) -> str:
    text = str(exc) if exc else ''
    return text if len(text) <= 120 else text[:117] + '…'


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if target is None:
        return None
    import datetime as _dt

    now = _dt.datetime.now(_dt.timezone.utc)
    if target.tzinfo is None:
        target = target.replace(tzinfo=_dt.timezone.utc)
    return max(0.0, (target - now).total_seconds())


async def _peek(resp: aiohttp.ClientResponse, limit: int = PEEK_BYTES) -> str:
    """讀取回應開頭一小段當作診斷用。刻意不讀完整個 body。"""
    try:
        raw = await resp.content.read(limit)
    except Exception:  # pragma: no cover - 讀取失敗時不該蓋掉原始錯誤
        return ''
    try:
        encoding = resp.get_encoding()
    except Exception:  # pragma: no cover - content-type 怪異時退回 utf-8
        encoding = 'utf-8'
    return raw.decode(encoding or 'utf-8', errors='replace')


def _looks_like_challenge(body: str) -> bool:
    lowered = body.lower()
    return any(marker in lowered for marker in CHALLENGE_MARKERS)


def _content_type(resp: aiohttp.ClientResponse) -> str:
    return (resp.headers.get('Content-Type') or '').split(';')[0].strip().lower()


async def _raise_for_status(resp: aiohttp.ClientResponse) -> None:
    retry_after = _parse_retry_after(resp.headers.get('Retry-After'))

    if resp.status < 400:
        # Cloudflare 不一定用 4xx 送挑戰頁——200 + HTML 也很常見。只看狀態碼
        # 就放行的話，那份 HTML 會被當成圖片寫進 .png，或讓 JSON 解析炸出
        # 未被攔截的 ValueError。這裡靠 content-type 判斷值不值得再看一眼，
        # 正常的圖片／JSON 回應完全不會進到這個分支。
        if _content_type(resp) not in HTML_TYPES:
            return
        body = await _peek(resp)
        if _looks_like_challenge(body):
            raise PixivChallengeError(
                resp.status,
                str(resp.url),
                'Cloudflare 機器人挑戰頁（HTTP 200）',
                retry_after=retry_after,
            )
        raise PixivAPIError(
            f'{resp.url} 回傳了 HTML 而非預期的圖片或 JSON'
            f'（HTTP {resp.status}），可能是 cookie 失效或被導向登入頁'
        )

    # 讀一小段 body 當作診斷訊息，避免只看到一個光禿禿的狀態碼。
    body = await _peek(resp)
    if _looks_like_challenge(body):
        # 不要把整頁 HTML 倒進 log——訊息要能一眼看懂。
        raise PixivChallengeError(
            resp.status,
            str(resp.url),
            'Cloudflare 機器人挑戰頁',
            retry_after=retry_after,
        )

    snippet = body[:200].replace('\n', ' ').strip()
    raise PixivHTTPError(resp.status, str(resp.url), snippet, retry_after=retry_after)


def filename_from_url(url: str, *, fallback: str) -> str:
    """從圖片 URL 取檔名，並拒絕任何可能跳出目標目錄的名稱。"""
    # 刻意不用 PurePosixPath：它會把 '/a/' 正規化成 'a'，而結尾是斜線的
    # 網址根本沒有檔名，應該退回 fallback。同樣刻意不做 unquote。
    name = urlparse(url).path.rsplit('/', 1)[-1]
    if not name or name in ('.', '..') or not _SAFE_NAME.match(name):
        # fallback 內嵌 illust_id，而 id 可能是 `pixiv-dl id ../../evil` 這種
        # 直接來自指令列的字串——不消毒就會寫到輸出目錄外面。
        return sanitize_component(fallback, fallback='unnamed')
    return name
