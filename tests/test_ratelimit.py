"""Cloudflare 挑戰處理與速率控制。

實測背景：以 concurrency=8、無速率上限跑 150 件作品時，Pixiv 背後的
Cloudflare 會回傳 `Just a moment...` 挑戰頁（HTTP 429），29 件因此失敗。
"""

from __future__ import annotations

import pytest
from aiohttp import web

from pixiv_dl.client import (
    PixivBlockedError,
    PixivChallengeError,
    PixivClient,
    PixivHTTPError,
    _parse_retry_after,
)
from pixiv_dl.download import download_all
from support import config, run, serve

CHALLENGE_BODY = (
    '<!DOCTYPE html><html lang="en-US"><head><title>Just a moment...</title>'
    '<meta http-equiv="Content-Type" content="text/html; charset=UTF-8">'
    '<meta http-equiv="X-UA-Compatible" content="IE=Edge"><meta name="robots">'
)


def _recording_sleep():
    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    return delays, sleep


def test_challenge_page_is_recognised_not_dumped(tmp_path):
    """挑戰頁要被辨識成專屬錯誤，訊息不能是 200 字元的 HTML。"""

    async def challenge(request: web.Request) -> web.Response:
        return web.Response(status=429, text=CHALLENGE_BODY, content_type='text/html')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': challenge}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                with pytest.raises(PixivChallengeError) as excinfo:
                    await client.get_json('/ajax/illust/1/pages')
                return str(excinfo.value)

    message = run(scenario())
    assert 'Cloudflare 機器人挑戰頁' in message
    assert '<!DOCTYPE' not in message
    assert '<meta' not in message
    assert len(message) < 120


def test_challenge_backs_off_far_longer_than_plain_429(tmp_path):
    """一般 429 用 retry_backoff，挑戰頁要用大得多的 challenge_backoff。"""

    async def challenge(request: web.Request) -> web.Response:
        return web.Response(status=429, text=CHALLENGE_BODY, content_type='text/html')

    async def plain(request: web.Request) -> web.Response:
        return web.Response(status=429, text='rate limited')

    async def scenario(handler):
        delays, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': handler}) as base:
            cfg = config(
                base,
                tmp_path,
                max_retries=2,
                retry_backoff=1.0,
                challenge_backoff=15.0,
                challenge_limit=99,
            )
            async with PixivClient(cfg, sleep=sleep) as client:
                with pytest.raises(PixivHTTPError):
                    await client.get_json('/ajax/illust/1/pages')
        return delays

    challenge_delays = run(scenario(challenge))
    plain_delays = run(scenario(plain))

    assert min(challenge_delays) >= 15.0
    assert max(plain_delays) < 15.0


def test_retry_after_header_is_honoured(tmp_path):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=429, text='slow down', headers={'Retry-After': '42'})

    async def scenario():
        delays, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': handler}) as base:
            cfg = config(base, tmp_path, max_retries=1, retry_backoff=1.0)
            async with PixivClient(cfg, sleep=sleep) as client:
                with pytest.raises(PixivHTTPError):
                    await client.get_json('/ajax/illust/1/pages')
        return delays

    delays = run(scenario())
    # 42 秒 + 最多 1 秒抖動，總之要照伺服器講的等，而不是用 1 秒退避。
    assert 42.0 <= delays[0] <= 43.0


def test_circuit_breaker_stops_the_whole_run(tmp_path):
    """連續挑戰達上限就整批中止，不要再對 Cloudflare 送出任何請求。"""
    hits = []

    async def challenge(request: web.Request) -> web.Response:
        hits.append(request.path)
        return web.Response(status=429, text=CHALLENGE_BODY, content_type='text/html')

    async def scenario():
        _, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': challenge}) as base:
            cfg = config(base, tmp_path, concurrency=1, max_retries=1, challenge_limit=3)
            async with PixivClient(cfg, sleep=sleep) as client:
                report = await download_all(
                    client, [str(i) for i in range(50)], tmp_path, show_progress=False
                )
                return report, client.blocked

    report, blocked = run(scenario())
    assert blocked
    assert report.blocked
    # 50 件作品，但只送出少數幾個請求就收手了。
    assert len(hits) <= 5, f'中止後仍送出 {len(hits)} 個請求'
    assert len(report.failures) == 50


def test_blocked_client_refuses_further_requests(tmp_path):
    async def challenge(request: web.Request) -> web.Response:
        return web.Response(status=429, text=CHALLENGE_BODY, content_type='text/html')

    async def scenario():
        _, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': challenge}) as base:
            cfg = config(base, tmp_path, max_retries=0, challenge_limit=1)
            async with PixivClient(cfg, sleep=sleep) as client:
                with pytest.raises(PixivBlockedError):
                    await client.get_json('/ajax/illust/1/pages')
                with pytest.raises(PixivBlockedError):
                    await client.get_json('/ajax/illust/2/pages')

    run(scenario())


def test_success_resets_the_challenge_counter(tmp_path):
    """偶發的挑戰不該累積成中止——只有「連續」才算。"""
    calls = []

    async def flaky(request: web.Request) -> web.Response:
        calls.append(1)
        if len(calls) % 2 == 1:
            return web.Response(status=429, text=CHALLENGE_BODY, content_type='text/html')
        return web.json_response({'body': []})

    async def scenario():
        _, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': flaky}) as base:
            cfg = config(base, tmp_path, concurrency=1, max_retries=1, challenge_limit=2)
            async with PixivClient(cfg, sleep=sleep) as client:
                for i in range(6):
                    await client.get_json(f'/ajax/illust/{i}/pages')
                return client.blocked

    assert run(scenario()) is False


def test_rate_limiter_spaces_requests_out(tmp_path):
    """Semaphore 管併發，request_interval 管速率——後者才是限流的關鍵。"""

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({'body': []})

    async def scenario():
        delays, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': handler}) as base:
            cfg = config(base, tmp_path, concurrency=8, request_interval=0.5)
            async with PixivClient(cfg, sleep=sleep) as client:
                import asyncio

                await asyncio.gather(
                    *(client.get_json(f'/ajax/illust/{i}/pages') for i in range(5))
                )
        return delays

    delays = run(scenario())
    # 併發 8 但間隔 0.5s：五個請求裡至少四個必須被要求等待。
    assert len([d for d in delays if d > 0]) >= 4


@pytest.mark.parametrize(
    ('header', 'expected'),
    [('30', 30.0), ('0', 0.0), ('not-a-number', None), (None, None)],
)
def test_parse_retry_after(header, expected):
    assert _parse_retry_after(header) == expected
