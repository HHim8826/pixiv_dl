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
from support import config, png, run, serve

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


# --- 200 狀態碼的挑戰頁（Codex review #3838335831）---

CHALLENGE_HEADERS = {'Content-Type': 'text/html; charset=UTF-8'}


def test_challenge_page_with_200_status_is_detected(tmp_path):
    """迴歸測試：Cloudflare 不一定用 4xx 送挑戰頁。只看狀態碼就放行的話，
    那份 HTML 會被當成圖片寫進 .png 並計為成功。"""
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': [{'urls': {'original': holder['base'] + '/img/1_p0.png'}}]}
        )

    async def challenge_200(request: web.Request) -> web.Response:
        return web.Response(status=200, text=CHALLENGE_BODY, headers=CHALLENGE_HEADERS)

    async def scenario():
        routes = {'/ajax/illust/{i}/pages': pages, '/img/{name}': challenge_200}
        async with serve(routes) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert not report.ok
    assert report.downloaded == 0
    assert list(tmp_path.iterdir()) == []  # 沒有任何 HTML 被寫成圖片
    assert 'Cloudflare' in report.failures[0][1]


def test_challenge_page_with_200_status_trips_the_circuit_breaker(tmp_path):
    """200 的挑戰頁也要算進斷路器，否則會一路磨完整批。"""

    async def challenge_200(request: web.Request) -> web.Response:
        return web.Response(status=200, text=CHALLENGE_BODY, headers=CHALLENGE_HEADERS)

    async def scenario():
        _, sleep = _recording_sleep()
        async with serve({'/ajax/illust/{i}/pages': challenge_200}) as base:
            cfg = config(base, tmp_path, max_retries=0, challenge_limit=2)
            async with PixivClient(cfg, sleep=sleep) as client:
                with pytest.raises(PixivChallengeError):
                    await client.get_json('/ajax/illust/1/pages')
                with pytest.raises(PixivBlockedError):
                    await client.get_json('/ajax/illust/2/pages')
                return client.blocked

    assert run(scenario()) is True


def test_unexpected_html_without_markers_is_reported_not_written(tmp_path):
    """沒有挑戰特徵但仍是 HTML（例如被導向登入頁），一樣不能寫成圖片。"""
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': [{'urls': {'original': holder['base'] + '/img/1_p0.png'}}]}
        )

    async def login_page(request: web.Request) -> web.Response:
        return web.Response(
            status=200, text='<html><body>Please log in</body></html>', headers=CHALLENGE_HEADERS
        )

    async def scenario():
        routes = {'/ajax/illust/{i}/pages': pages, '/img/{name}': login_page}
        async with serve(routes) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert not report.ok
    assert list(tmp_path.iterdir()) == []
    assert 'HTML' in report.failures[0][1]


def test_malformed_json_becomes_a_pixiv_error(tmp_path):
    """JSONDecodeError 是 ValueError，不轉型會穿過 download_all 的 except
    直接炸掉整批 gather。"""
    from pixiv_dl.client import PixivAPIError

    async def broken(request: web.Request) -> web.Response:
        return web.Response(status=200, text='{not json', content_type='application/json')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': broken}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                with pytest.raises(PixivAPIError):
                    await client.get_json('/ajax/illust/1/pages')

    run(scenario())


def test_normal_responses_never_read_the_body_twice(tmp_path):
    """正常的圖片／JSON 回應不該進到 content-type 檢查的分支。"""
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': [{'urls': {'original': holder['base'] + '/img/1_p0.png'}}]}
        )

    async def image(request: web.Request) -> web.Response:
        return web.Response(body=png(512), content_type='image/png')

    async def scenario():
        routes = {'/ajax/illust/{i}/pages': pages, '/img/{name}': image}
        async with serve(routes) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert report.downloaded == 1
    # body 完整落地，沒有被診斷用的 peek 吃掉開頭。
    assert (tmp_path / '1_p0.png').stat().st_size == len(png(512))
