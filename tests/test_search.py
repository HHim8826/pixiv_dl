"""搜尋與排行榜的行為測試，含兩個歷史 bug 的迴歸測試。"""

from __future__ import annotations

from aiohttp import web

from pixiv_dl.client import PixivClient
from pixiv_dl.search import (
    RankingMode,
    SearchMode,
    popular_search,
    search_illustrations,
    user_illusts,
)
from pixiv_dl.search import ranking as ranking_search
from support import config, run, serve


def _ranking_query(tmp_path, mode: RankingMode, only_illust: bool):
    seen = []

    async def handler(request: web.Request) -> web.Response:
        seen.append(dict(request.query))
        return web.json_response({'contents': [{'illust_id': 1}, {'illust_id': 2}]})

    async def scenario():
        async with serve({'/ranking.php': handler}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await ranking_search(client, 1, mode, only_illust=only_illust)

    ids = run(scenario())
    return ids, seen[0]


def test_ranking_adds_content_filter_when_requested(tmp_path):
    ids, query = _ranking_query(tmp_path, RankingMode.DAILY, True)
    assert ids == ['1', '2']
    assert query['content'] == 'illust'


def test_ranking_omits_content_filter_when_not_requested(tmp_path):
    """迴歸測試：舊版的 `mode == 'daily' or 'weekly' or ...` 恆為真，
    導致 only_illust=False 從來沒有生效過。"""
    _, query = _ranking_query(tmp_path, RankingMode.DAILY, False)
    assert 'content' not in query


def test_ranking_ignores_content_filter_for_unsupported_mode(tmp_path):
    _, query = _ranking_query(tmp_path, RankingMode.FEMALE, True)
    assert 'content' not in query


def test_popular_search_filters_by_bookmark_count(tmp_path):
    """迴歸測試：舊版重用同一個 tasks list，收藏數過濾的結果會被
    未過濾的 id 清單隨機蓋掉。"""
    bookmarks = {'1': 10, '2': 6000, '3': 9000, '4': 4999}

    async def search(request: web.Request) -> web.Response:
        return web.json_response(
            {
                'body': {
                    'illust': {
                        'data': [{'id': i} for i in bookmarks],
                        'total': len(bookmarks),
                    }
                }
            }
        )

    async def illust(request: web.Request) -> web.Response:
        illust_id = request.match_info['illust_id']
        return web.json_response({'body': {'bookmarkCount': bookmarks[illust_id]}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base, PixivClient(config(base, tmp_path)) as client:
            # 明確走逐件驗證路徑——這正是本測試要保護的邏輯。
            return await popular_search(
                client, 'miku', 5000, pages=1, use_users_tag=False, show_progress=False
            )

    assert sorted(run(scenario())) == ['2', '3']


def test_popular_search_skips_unavailable_illusts(tmp_path):
    async def search(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': {'illust': {'data': [{'id': '1'}, {'id': '2'}], 'total': 2}}}
        )

    async def illust(request: web.Request) -> web.Response:
        if request.match_info['illust_id'] == '1':
            return web.json_response({'error': True, 'message': '作品已刪除'})
        return web.json_response({'body': {'bookmarkCount': 9000}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base, PixivClient(config(base, tmp_path)) as client:
            return await popular_search(
                client, 'miku', 5000, pages=1, use_users_tag=False, show_progress=False
            )

    assert run(scenario()) == ['2']


def test_search_illustrations_reads_popular_sections(tmp_path):
    async def handler(request: web.Request) -> web.Response:
        assert request.query['mode'] == 'r18'
        return web.json_response(
            {
                'body': {
                    'popular': {
                        'permanent': [{'id': '10'}],
                        'recent': [{'id': '11'}, {'id': '10'}],
                    }
                }
            }
        )

    async def scenario():
        async with serve({'/ajax/search/illustrations/{word}': handler}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await search_illustrations(client, 'ミク', SearchMode.R18)

    assert run(scenario()) == ['10', '11']


def test_user_illusts_handles_empty_list_shape(tmp_path):
    async def handler(request: web.Request) -> web.Response:
        return web.json_response({'body': {'illusts': []}})

    async def scenario():
        async with serve({'/ajax/user/{user_id}/profile/all': handler}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await user_illusts(client, '123')

    assert run(scenario()) == []


def test_users_tag_for_picks_largest_threshold_at_or_below():
    from pixiv_dl.search import users_tag_for

    assert users_tag_for(3000) == '1000users入り'
    assert users_tag_for(5000) == '5000users入り'
    assert users_tag_for(150) == '100users入り'
    assert users_tag_for(99) is None


def test_popular_search_uses_users_tag_to_shrink_candidates(tmp_path):
    """收藏數過濾原本要逐件查上千件；改用 users入り 標籤讓 Pixiv 先篩。"""
    queries = []
    detail_hits = []

    async def search(request: web.Request) -> web.Response:
        queries.append(request.query['word'])
        if 'users入り' in request.query['word']:
            data = [{'id': '1'}, {'id': '2'}]
        else:  # 沒有標籤時是「最新的幾千件」，這裡模擬成一大坨
            data = [{'id': str(i)} for i in range(100, 160)]
        return web.json_response({'body': {'illust': {'data': data, 'total': len(data)}}})

    async def illust(request: web.Request) -> web.Response:
        detail_hits.append(request.match_info['illust_id'])
        return web.json_response({'body': {'bookmarkCount': 7000}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await popular_search(client, 'miku', 3000, pages=1, show_progress=False)

    result = run(scenario())
    assert result == ['1', '2']
    assert queries[0] == 'miku 1000users入り'
    # 關鍵：只查了 2 件的收藏數，不是 60 件。
    assert sorted(detail_hits) == ['1', '2']


def test_popular_search_falls_back_when_tag_finds_nothing(tmp_path):
    queries = []

    async def search(request: web.Request) -> web.Response:
        word = request.query['word']
        queries.append(word)
        if 'users入り' in word:
            return web.json_response({'body': {'illust': {'data': [], 'total': 0}}})
        return web.json_response({'body': {'illust': {'data': [{'id': '9'}], 'total': 1}}})

    async def illust(request: web.Request) -> web.Response:
        return web.json_response({'body': {'bookmarkCount': 8000}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await popular_search(client, 'obscure', 5000, pages=1, show_progress=False)

    assert run(scenario()) == ['9']
    assert len(queries) == 2
    assert 'users入り' in queries[0] and 'users入り' not in queries[1]


def test_popular_search_can_disable_tag_shortcut(tmp_path):
    queries = []

    async def search(request: web.Request) -> web.Response:
        queries.append(request.query['word'])
        return web.json_response({'body': {'illust': {'data': [{'id': '5'}], 'total': 1}}})

    async def illust(request: web.Request) -> web.Response:
        return web.json_response({'body': {'bookmarkCount': 6000}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await popular_search(
                    client, 'miku', 5000, pages=1, use_users_tag=False, show_progress=False
                )

    assert run(scenario()) == ['5']
    assert queries == ['miku']


def test_popular_search_returns_empty_without_hanging(tmp_path):
    async def search(request: web.Request) -> web.Response:
        return web.json_response({'body': {'illust': {'data': [], 'total': 0}}})

    async def scenario():
        async with serve({'/ajax/search/illustrations/{word}': search}) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await popular_search(client, 'nothing', 5000, pages=1, show_progress=False)

    assert run(scenario()) == []


def test_exact_threshold_skips_verification_entirely(tmp_path):
    """min_bookmarks 剛好等於標籤門檻時，命中標籤即為證明，不必逐件查。"""
    detail_hits = []

    async def search(request: web.Request) -> web.Response:
        return web.json_response(
            {'body': {'illust': {'data': [{'id': str(i)} for i in range(20)], 'total': 20}}}
        )

    async def illust(request: web.Request) -> web.Response:
        detail_hits.append(request.match_info['illust_id'])
        return web.json_response({'body': {'bookmarkCount': 9999}})

    async def scenario():
        routes = {
            '/ajax/search/illustrations/{word}': search,
            '/ajax/illust/{illust_id}': illust,
        }
        async with serve(routes) as base:
            async with PixivClient(config(base, tmp_path)) as client:
                return await popular_search(client, 'miku', 5000, pages=1, show_progress=False)

    assert len(run(scenario())) == 20
    assert detail_hits == [], f'不該再查任何一件，實際查了 {len(detail_hits)} 件'
