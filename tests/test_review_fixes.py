"""Copilot review 指出的問題的迴歸測試。"""

from __future__ import annotations

import asyncio

import aiohttp
import pytest
from aiohttp import web

from pixiv_dl.client import PixivBlockedError, PixivClient, filename_from_url
from pixiv_dl.download import download_all
from pixiv_dl.search import popular_search
from support import config, png, run, serve


async def _ok(request: web.Request) -> web.Response:
    return web.json_response({})


def test_fallback_filename_cannot_escape_the_output_dir(tmp_path):
    """`pixiv-dl id ../../evil` 會讓 illust_id 直接進到 fallback 檔名，
    不消毒的話 target / fallback 會寫到輸出目錄外面。"""
    name = filename_from_url('https://i.pximg.net/a/', fallback='../../evil_p0.jpg')
    assert '..' not in name.split('_')[0] or '/' not in name
    dest = (tmp_path / name).resolve()
    assert dest.parent == tmp_path.resolve()


def test_hostile_illust_id_stays_inside_output_dir(tmp_path):
    """端到端：惡意 id 一路走到落地都不能跑出去。"""
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        # 原圖網址沒有安全檔名，強制走 fallback 路徑。
        return web.json_response({'body': [{'urls': {'original': holder['base'] + '/img/'}}]})

    async def image(request: web.Request) -> web.Response:
        return web.Response(body=png(), content_type='image/png')

    async def scenario():
        async with serve({'/ajax/illust/{i:.*}/pages': pages, '/img/': image}) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['../../evil'], tmp_path, show_progress=False)

    run(scenario())
    escaped = [p for p in tmp_path.parent.iterdir() if p.name.startswith('evil')]
    assert escaped == [], f'檔案跑到輸出目錄外面：{escaped}'


@pytest.mark.parametrize(
    'exc_type',
    [aiohttp.ClientPayloadError, aiohttp.ServerDisconnectedError],
)
def test_non_oserror_client_errors_are_recorded_not_fatal(tmp_path, exc_type):
    """_with_retry 重試用盡後會原樣拋出 aiohttp.ClientError。

    ClientConnectorError 剛好也是 OSError 所以本來就接得到，但
    ClientPayloadError／ServerDisconnectedError 不是——連線在下載中途
    被切斷時，例外會穿過 download_all 炸掉整批 gather。
    """
    assert not issubclass(exc_type, OSError)  # 確認這個案例真的有意義

    async def scenario():
        async with serve({'/ping': _ok}) as base:
            cfg = config(base, tmp_path, max_retries=0)
            async with PixivClient(cfg) as client:

                async def boom(*args, **kwargs):
                    raise exc_type('連線中途被切斷')

                client.get_json = boom
                return await download_all(client, ['1', '2', '3'], tmp_path, show_progress=False)

    report = run(scenario())
    assert not report.ok
    assert len(report.failures) == 3  # 三件都被記錄，沒有任何一件炸穿 gather


def test_popular_search_propagates_blocked_instead_of_returning_empty(tmp_path):
    """斷路器跳開時若被 broad catch 吞掉，popular_search 會以
    「成功但空清單」返回，使用者看不出整批已中止。"""
    CHALLENGE = '<!DOCTYPE html><title>Just a moment...</title>'

    async def search(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': {'illust': {'data': [{'id': str(i)} for i in range(20)], 'total': 20}}}
        )

    async def challenge(request: web.Request) -> web.Response:
        return web.Response(status=429, text=CHALLENGE, content_type='text/html')

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': challenge,
        }
        async with serve(routes) as base:
            cfg = config(base, tmp_path, concurrency=1, max_retries=0, challenge_limit=2)
            async with PixivClient(cfg) as client:
                with pytest.raises(PixivBlockedError):
                    # min_bookmarks 不等於標籤門檻，強制走逐件驗證。
                    await popular_search(
                        client, 'miku', 3000, pages=1, use_users_tag=False, show_progress=False
                    )

    run(scenario())


def test_rate_limiter_pause_applies_even_when_interval_is_zero(tmp_path):
    """interval=0 時若 acquire 直接返回，pause() 設下的 Cloudflare
    cooldown 會失效，等於被擋之後繼續全速轟炸。"""
    from pixiv_dl.client import _RateLimiter

    delays: list[float] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    async def scenario():
        limiter = _RateLimiter(0.0)
        await limiter.acquire(sleep)
        limiter.pause(30.0)
        await limiter.acquire(sleep)

    run(scenario())
    assert delays, 'interval=0 時 cooldown 被完全忽略'
    assert max(delays) > 25.0


def test_flat_also_disables_multipage_subdirs(tmp_path):
    """--flat 承諾「全部平鋪、等同舊版」，只清 path_template 不夠。"""
    import dataclasses

    from pixiv_dl.cli import build_parser
    from pixiv_dl.config import Config

    args = build_parser().parse_args(['--flat', 'search', 'miku'])
    cfg = Config(cookie='x')
    assert cfg.multipage_dirs == 'auto'
    if args.flat:
        cfg = dataclasses.replace(cfg, path_template='', multipage_dirs='never')
    assert cfg.path_template == ''
    assert cfg.multipage_dirs == 'never'


def test_flat_end_to_end_produces_no_subdirs(tmp_path):
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        base = holder['base']
        return web.json_response(
            {'body': [{'urls': {'original': f'{base}/img/1_p{k}.png'}} for k in range(3)]}
        )

    async def image(request: web.Request) -> web.Response:
        return web.Response(body=png(), content_type='image/png')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': image}) as base:
            holder['base'] = base
            cfg = config(base, tmp_path, multipage_dirs='never')
            async with PixivClient(cfg) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert [p.name for p in tmp_path.iterdir() if p.is_dir()] == []
    assert len(list(tmp_path.glob('*.png'))) == 3


def test_config_example_matches_documented_defaults():
    """範本裡的值若和程式預設不同，註解必須講清楚，否則使用者會以為
    自己拿到的是文件上寫的預設值。"""
    import pathlib

    text = pathlib.Path('config.example.toml').read_text('utf-8')
    assert 'request-interval = 0.2' in text
    # 註解要標明程式內建預設，避免與 README 的說明互相矛盾。
    assert '0.35' in text


def test_client_error_types_are_not_covered_by_the_other_excepts():
    """確認新增的 except 分支不是多餘的。"""
    from pixiv_dl.client import PixivError

    for exc_type in (aiohttp.ClientPayloadError, aiohttp.ServerDisconnectedError):
        assert not issubclass(exc_type, PixivError)
        assert not issubclass(exc_type, OSError)
        assert not issubclass(exc_type, asyncio.TimeoutError)
