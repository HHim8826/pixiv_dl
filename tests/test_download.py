"""下載流程的測試，重點是失敗必須被回報而不是靜默寫出壞檔案。"""

from __future__ import annotations

import pytest
from aiohttp import web

from pixiv_dl.client import PixivClient, PixivHTTPError, filename_from_url
from pixiv_dl.download import download_all
from support import config, png, run, serve


def _pages_handler(urls):
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({'body': [{'urls': {'original': u}} for u in urls]})

    return handler


async def _image(request: web.Request) -> web.Response:
    return web.Response(body=png(), content_type='image/png')


def test_downloads_every_page_of_an_illust(tmp_path):
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        base = holder['base']
        urls = [base + '/img/1_p0.png', base + '/img/1_p1.png']
        return await _pages_handler(urls)(request)

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': _image}) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert report.downloaded == 2
    # 多頁作品預設（auto）會另開以作品 id 命名的子資料夾。
    assert sorted(p.name for p in (tmp_path / '1').iterdir()) == ['1_p0.png', '1_p1.png']


def test_http_error_is_reported_and_writes_no_file(tmp_path):
    """迴歸測試：舊版沒有 raise_for_status，403 的 HTML 錯誤頁會被
    原封不動寫成 .png，而且 asyncio.wait 讓例外完全消失。"""
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        return await _pages_handler([holder['base'] + '/img/1_p0.png'])(request)

    async def forbidden(request: web.Request) -> web.Response:
        return web.Response(status=403, text='<html>Forbidden</html>')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': forbidden}) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert not report.ok
    assert report.downloaded == 0
    assert [i for i, _ in report.failures] == ['1']
    assert '403' in report.failures[0][1]
    assert list(tmp_path.iterdir()) == []  # 連 .part 暫存檔都不該留下


def test_existing_file_is_skipped(tmp_path):
    holder = {}
    hits = []

    async def pages(request: web.Request) -> web.Response:
        return await _pages_handler([holder['base'] + '/img/1_p0.png'])(request)

    async def image(request: web.Request) -> web.Response:
        hits.append(1)
        return web.Response(body=png(), content_type='image/png')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': image}) as base:
            holder['base'] = base
            (tmp_path / '1_p0.png').write_bytes(b'already here')
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.skipped == 1
    assert report.downloaded == 0
    assert hits == []
    assert (tmp_path / '1_p0.png').read_bytes() == b'already here'


def test_duplicate_ids_are_fetched_once(tmp_path):
    holder = {}
    page_hits = []

    async def pages(request: web.Request) -> web.Response:
        page_hits.append(request.match_info['i'])
        return await _pages_handler([holder['base'] + '/img/1_p0.png'])(request)

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': _image}) as base:
            holder['base'] = base
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1', '1', '1'], tmp_path, show_progress=False)

    run(scenario())
    assert page_hits == ['1']


def test_retries_on_rate_limit_then_succeeds(tmp_path):
    holder = {}
    attempts = []

    async def pages(request: web.Request) -> web.Response:
        return await _pages_handler([holder['base'] + '/img/1_p0.png'])(request)

    async def flaky(request: web.Request) -> web.Response:
        attempts.append(1)
        if len(attempts) < 3:
            return web.Response(status=429, text='slow down')
        return web.Response(body=png(), content_type='image/png')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages, '/img/{name}': flaky}) as base:
            holder['base'] = base
            cfg = config(base, tmp_path, max_retries=3, retry_backoff=0.0)
            async with PixivClient(cfg) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert len(attempts) == 3


def test_client_does_not_retry_client_errors(tmp_path):
    attempts = []

    async def not_found(request: web.Request) -> web.Response:
        attempts.append(1)
        return web.Response(status=404, text='nope')

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': not_found}) as base:
            cfg = config(base, tmp_path, max_retries=3, retry_backoff=0.0)
            async with PixivClient(cfg) as client:
                with pytest.raises(PixivHTTPError):
                    await client.get_json('/ajax/illust/1/pages')

    run(scenario())
    assert len(attempts) == 1


def test_missing_original_url_is_skipped_not_fatal(tmp_path):
    async def pages(request: web.Request) -> web.Response:
        return web.json_response({'body': [{'urls': {'original': None}}]})

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': pages}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, ['1'], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert report.downloaded == 0


def test_empty_id_list_is_not_an_error(tmp_path):
    """舊版對空清單會拋 ValueError，然後被 `except ValueError: pass` 吞掉。"""

    async def ping(request: web.Request) -> web.Response:
        return web.json_response({})

    async def scenario():
        async with serve({'/ping': ping}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await download_all(client, [], tmp_path, show_progress=False)

    report = run(scenario())
    assert report.ok
    assert report.downloaded == 0


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://i.pximg.net/img-original/1_p0.png', '1_p0.png'),
        ('https://i.pximg.net/a/..', 'fallback.jpg'),
        ('https://i.pximg.net/a/%2e%2e%2fevil.png', 'fallback.jpg'),
        ('https://i.pximg.net/a/', 'fallback.jpg'),
    ],
)
def test_filename_from_url_rejects_unsafe_names(url, expected):
    assert filename_from_url(url, fallback='fallback.jpg') == expected


def _two_page_scenario(tmp_path, multipage_dirs):
    holder = {}

    async def pages(request: web.Request) -> web.Response:
        base = holder['base']
        return await _pages_handler([base + '/img/1_p0.png', base + '/img/1_p1.png'])(request)

    async def single(request: web.Request) -> web.Response:
        return await _pages_handler([holder['base'] + '/img/2_p0.png'])(request)

    async def route(request: web.Request) -> web.Response:
        return await (pages if request.match_info['i'] == '1' else single)(request)

    async def scenario():
        async with serve({'/ajax/illust/{i}/pages': route, '/img/{name}': _image}) as base:
            holder['base'] = base
            cfg = config(base, tmp_path, multipage_dirs=multipage_dirs)
            async with PixivClient(cfg) as client:
                return await download_all(client, ['1', '2'], tmp_path, show_progress=False)

    return run(scenario())


def test_multipage_dirs_auto_groups_only_multipage_works(tmp_path):
    report = _two_page_scenario(tmp_path, 'auto')
    assert report.ok
    assert sorted(p.name for p in (tmp_path / '1').iterdir()) == ['1_p0.png', '1_p1.png']
    assert (tmp_path / '2_p0.png').is_file()  # 單張作品維持平鋪


def test_multipage_dirs_always_groups_everything(tmp_path):
    report = _two_page_scenario(tmp_path, 'always')
    assert report.ok
    assert (tmp_path / '1' / '1_p0.png').is_file()
    assert (tmp_path / '2' / '2_p0.png').is_file()


def test_multipage_dirs_never_keeps_everything_flat(tmp_path):
    report = _two_page_scenario(tmp_path, 'never')
    assert report.ok
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        '1_p0.png',
        '1_p1.png',
        '2_p0.png',
    ]
