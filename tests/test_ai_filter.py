"""AI 生成作品過濾：`ai_type=1` 隱藏、`ai_type=0` 顯示。

只有 /ajax/search/* 端點吃這個參數；排行榜與使用者作品列表不支援，
所以那兩條路徑必須確定「沒有」送出 ai_type。
"""

from __future__ import annotations

import pytest
from aiohttp import web

from pixiv_dl.client import PixivClient
from pixiv_dl.config import Config
from pixiv_dl.search import (
    AI_HIDE,
    AI_SHOW,
    PopularOrder,
    RankingMode,
    ai_type_param,
    popular_search,
    premium_search,
    ranking,
    search_illustrations,
    user_illusts,
)
from support import config, run, serve


def test_ai_type_param_mapping():
    assert ai_type_param(True) == AI_HIDE == 1
    assert ai_type_param(False) == AI_SHOW == 0


def _capture(routes_factory, call, tmp_path, **cfg_kwargs):
    """跑一次查詢，回傳伺服器實際收到的 query 參數。"""
    seen: list[dict[str, str]] = []

    async def scenario():
        async with serve(routes_factory(seen)) as base:
            async with PixivClient(config(base, tmp_path, **cfg_kwargs)) as client:
                await call(client)

    run(scenario())
    return seen


def _search_routes(seen):
    async def handler(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response({'body': {'illust': {'data': [{'id': '1'}], 'total': 1}}})

    async def illust(request: web.Request) -> web.Response:
        return web.json_response({'body': {'bookmarkCount': 99999}})

    return {
        '/ajax/search/illustrations/{word}': handler,
        '/ajax/search/artworks/{word}': handler,
        '/ajax/illust/{illust_id}': illust,
    }


@pytest.mark.parametrize(('hide_ai', 'expected'), [(True, '1'), (False, '0')])
def test_search_illustrations_sends_ai_type(tmp_path, hide_ai, expected):
    seen = _capture(
        _search_routes,
        lambda c: search_illustrations(c, 'miku', hide_ai=hide_ai),
        tmp_path,
    )
    assert seen[0]['ai_type'] == expected


@pytest.mark.parametrize(('hide_ai', 'expected'), [(True, '1'), (False, '0')])
def test_premium_search_sends_ai_type(tmp_path, hide_ai, expected):
    seen = _capture(
        _search_routes,
        lambda c: premium_search(c, 'miku', order=PopularOrder.ALL, hide_ai=hide_ai),
        tmp_path,
    )
    assert seen[0]['ai_type'] == expected


@pytest.mark.parametrize(('hide_ai', 'expected'), [(True, '1'), (False, '0')])
def test_popular_search_sends_ai_type(tmp_path, hide_ai, expected):
    seen = _capture(
        _search_routes,
        lambda c: popular_search(c, 'miku', 5000, pages=1, show_progress=False, hide_ai=hide_ai),
        tmp_path,
    )
    assert seen[0]['ai_type'] == expected


def test_popular_search_keeps_ai_type_on_the_tag_query(tmp_path):
    """標籤加速路徑也要帶上 ai_type，否則過濾會在最關鍵的那一步失效。"""
    seen = _capture(
        _search_routes,
        lambda c: popular_search(c, 'miku', 5000, pages=1, show_progress=False, hide_ai=True),
        tmp_path,
    )
    assert 'users入り' in seen[0]['word']
    assert seen[0]['ai_type'] == '1'


def test_popular_search_keeps_ai_type_on_the_fallback_query(tmp_path):
    """標籤搜不到而退回逐件查詢時，ai_type 不能掉。"""
    seen: list[dict[str, str]] = []

    async def search(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        if 'users入り' in request.query['word']:
            return web.json_response({'body': {'illust': {'data': [], 'total': 0}}})
        return web.json_response({'body': {'illust': {'data': [{'id': '1'}], 'total': 1}}})

    async def illust(request: web.Request) -> web.Response:
        return web.json_response({'body': {'bookmarkCount': 99999}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                await popular_search(
                    client, 'miku', 5000, pages=1, show_progress=False, hide_ai=True
                )

    run(scenario())
    assert len(seen) == 2
    assert all(q['ai_type'] == '1' for q in seen)


def _no_ai_routes(seen):
    async def rank(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response({'contents': [{'illust_id': 1}]})

    async def profile(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response({'body': {'illusts': {'1': None}}})

    return {'/ranking.php': rank, '/ajax/user/{user_id}/profile/all': profile}


def test_ranking_does_not_send_ai_type(tmp_path):
    """排行榜端點不支援 ai_type，送了只是雜訊。"""
    seen = _capture(_no_ai_routes, lambda c: ranking(c, 1, RankingMode.DAILY), tmp_path)
    assert 'ai_type' not in seen[0]


def test_user_illusts_does_not_send_ai_type(tmp_path):
    seen = _capture(_no_ai_routes, lambda c: user_illusts(c, '123'), tmp_path)
    assert 'ai_type' not in seen[0]


def test_config_reads_hide_ai(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[login]\ncookie = "x"\n[search]\nhide-ai = true\n', 'utf-8')
    assert Config.load(path).hide_ai is True


def test_config_hide_ai_defaults_to_false(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[login]\ncookie = "x"\n', 'utf-8')
    assert Config.load(path).hide_ai is False


# --- CLI 旗標與設定檔的優先權 ---


def _parse(argv):
    from pixiv_dl.cli import build_parser

    return build_parser().parse_args(argv)


@pytest.mark.parametrize(
    ('argv', 'expected'),
    [
        (['search', 'miku'], None),
        (['search', 'miku', '--hide-ai'], True),
        (['search', 'miku', '--show-ai'], False),
        (['premium', 'miku', '--hide-ai'], True),
        (['popular', 'miku', '--min-bookmarks', '5000', '--show-ai'], False),
    ],
)
def test_cli_parses_ai_flags(argv, expected):
    assert _parse(argv).hide_ai is expected


def test_cli_rejects_both_ai_flags_at_once():
    with pytest.raises(SystemExit):
        _parse(['search', 'miku', '--hide-ai', '--show-ai'])


@pytest.mark.parametrize(
    ('flag', 'config_default', 'expected'),
    [
        (None, True, '1'),  # 未給旗標 -> 沿用設定檔
        (None, False, '0'),
        ('--show-ai', True, '0'),  # 旗標覆蓋設定檔
        ('--hide-ai', False, '1'),
    ],
)
def test_flag_overrides_config_default(tmp_path, flag, config_default, expected):
    from pixiv_dl.cli import collect_ids

    seen: list[dict[str, str]] = []
    argv = ['search', 'miku'] + ([flag] if flag else [])
    args = _parse(argv)

    async def scenario():
        async with serve(_search_routes(seen)) as base:
            cfg = config(base, tmp_path, hide_ai=config_default)
            async with PixivClient(cfg) as client:
                await collect_ids(args, client)

    run(scenario())
    assert seen[0]['ai_type'] == expected
