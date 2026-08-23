"""各種取得作品 ID 的來源：排行榜、搜尋、使用者、熱門篩選。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Iterable, Sequence
from enum import Enum
from typing import Any
from urllib.parse import quote

from tqdm import tqdm

from .client import PixivBlockedError, PixivClient, PixivError

log = logging.getLogger(__name__)

RESULTS_PER_PAGE = 60

#: Pixiv 搜尋端點的 AI 過濾參數：1 = 隱藏 AI 生成作品，0 = 顯示。
#: 只有 /ajax/search/* 吃這個參數，排行榜與使用者作品列表不支援。
AI_HIDE = 1
AI_SHOW = 0


def ai_type_param(hide_ai: bool) -> int:
    return AI_HIDE if hide_ai else AI_SHOW


class SearchMode(str, Enum):
    ALL = 'all'
    SAFE = 'safe'
    R18 = 'r18'


class PopularOrder(str, Enum):
    ALL = 'popular_d'
    MALE = 'popular_male_d'
    FEMALE = 'popular_female_d'


class RankingMode(str, Enum):
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    ROOKIE = 'rookie'
    ORIGINAL = 'original'
    MALE = 'male'
    FEMALE = 'female'
    DAILY_R18 = 'daily_r18'
    WEEKLY_R18 = 'weekly_r18'
    MALE_R18 = 'male_r18'
    FEMALE_R18 = 'female_r18'


#: 只有這幾種排行榜支援 content=illust 過濾，其餘傳了也是白傳。
ILLUST_FILTERABLE = frozenset(
    {RankingMode.DAILY, RankingMode.WEEKLY, RankingMode.MONTHLY, RankingMode.ROOKIE}
)


def _dedupe(ids: Iterable[Any]) -> list[str]:
    """保序去重，順便統一轉成 str —— 各端點的 id 型別並不一致。"""
    return list(dict.fromkeys(str(i) for i in ids if i))


async def ranking(
    client: PixivClient,
    pages: int = 1,
    mode: RankingMode = RankingMode.DAILY,
    *,
    only_illust: bool = False,
) -> list[str]:
    referer = f'{client.config.base_url}/ranking.php'

    async def one_page(page: int) -> list[str]:
        params: dict[str, Any] = {'format': 'json', 'mode': mode.value, 'p': page}
        if only_illust and mode in ILLUST_FILTERABLE:
            params['content'] = 'illust'
        data = await client.get_json('/ranking.php', params=params, referer=referer)
        return [item['illust_id'] for item in data.get('contents', []) if 'illust_id' in item]

    results = await asyncio.gather(*(one_page(p) for p in range(1, max(1, pages) + 1)))
    return _dedupe(i for page in results for i in page)


async def search_illustrations(
    client: PixivClient,
    word: str,
    mode: SearchMode = SearchMode.ALL,
    *,
    hide_ai: bool = False,
) -> list[str]:
    data = await client.get_json(
        f'/ajax/search/illustrations/{quote(word, safe="")}',
        params={'word': word, 'mode': mode.value, 'ai_type': ai_type_param(hide_ai)},
    )
    body = data.get('body') or {}

    ids: list[Any] = [item['id'] for item in _entries(body, 'illust') if 'id' in item]
    # 未登入或關鍵字冷門時 Pixiv 改回傳 popular 區塊，兩種形狀都要吃。
    popular = body.get('popular') or {}
    for key in ('permanent', 'recent'):
        ids.extend(item['id'] for item in popular.get(key) or [] if 'id' in item)
    return _dedupe(ids)


async def user_illusts(client: PixivClient, user_id: str) -> list[str]:
    data = await client.get_json(
        f'/ajax/user/{quote(str(user_id), safe="")}/profile/all',
        referer=f'{client.config.base_url}/users/{user_id}',
    )
    illusts = (data.get('body') or {}).get('illusts')
    # 沒有任何作品時 Pixiv 回傳 [] 而不是 {}，直接迭代會拿到空結果而非爆炸。
    if isinstance(illusts, dict):
        return _dedupe(illusts.keys())
    return _dedupe(illusts or [])


async def premium_search(
    client: PixivClient,
    word: str,
    *,
    order: PopularOrder = PopularOrder.ALL,
    mode: SearchMode = SearchMode.ALL,
    pages: int = 1,
    only_illust: bool = True,
    hide_ai: bool = False,
) -> list[str]:
    path = f'/ajax/search/artworks/{quote(word, safe="")}'

    async def one_page(page: int) -> list[str]:
        params = {
            'word': word,
            'order': order.value,
            'mode': mode.value,
            's_mode': 's_tag',
            'type': 'illust_and_ugoira' if only_illust else 'all',
            'p': page,
            'ai_type': ai_type_param(hide_ai),
        }
        data = await client.get_json(path, params=params)
        entries = _entries(data.get('body') or {}, 'illustManga')
        return [item['id'] for item in entries if 'id' in item]

    results = await asyncio.gather(*(one_page(p) for p in range(1, max(1, pages) + 1)))
    return _dedupe(i for page in results for i in page)


#: Pixiv 會在作品達到收藏門檻時自動掛上 `<N>users入り` 標籤。把標籤直接加進
#: 搜尋詞，等於讓 Pixiv 在伺服器端先篩掉絕大多數作品——這比抓回幾千個 id
#: 再逐件查收藏數快上兩三個數量級。
USERS_TAG_THRESHOLDS = (100, 500, 1000, 5000, 10000, 20000, 30000, 50000, 100000)


def users_tag_for(min_bookmarks: int) -> str | None:
    """回傳不超過 min_bookmarks 的最大標準門檻標籤。"""
    eligible = [t for t in USERS_TAG_THRESHOLDS if t <= min_bookmarks]
    return f'{max(eligible)}users入り' if eligible else None


async def _search_ids(
    client: PixivClient, word: str, mode: SearchMode, pages: int, hide_ai: bool = False
) -> tuple[list[str], int]:
    path = f'/ajax/search/illustrations/{quote(word, safe="")}'

    def page_params(page: int) -> dict[str, Any]:
        return {
            'word': word,
            'p': page,
            's_mode': 's_tag',
            'type': 'illust_and_ugoira',
            'mode': mode.value,
            'ai_type': ai_type_param(hide_ai),
        }

    first = await client.get_json(path, params=page_params(1))
    total = ((first.get('body') or {}).get('illust') or {}).get('total', 0)
    if not total:
        return [], 0
    pages = min(max(1, pages), max(1, math.ceil(total / RESULTS_PER_PAGE)))

    async def one_page(page: int) -> list[str]:
        data = first if page == 1 else await client.get_json(path, params=page_params(page))
        entries = _entries(data.get('body') or {}, 'illust')
        return [item['id'] for item in entries if 'id' in item]

    results = await asyncio.gather(*(one_page(p) for p in range(1, pages + 1)))
    return _dedupe(i for page in results for i in page), total


async def popular_search(
    client: PixivClient,
    word: str,
    min_bookmarks: int,
    *,
    mode: SearchMode = SearchMode.ALL,
    pages: int = 10,
    use_users_tag: bool = True,
    show_progress: bool = True,
    hide_ai: bool = False,
) -> list[str]:
    """非 premium 帳號的熱門搜尋。

    注意 Pixiv 的搜尋預設是 `date_d`（最新優先），所以「抓前 N 頁再逐件過濾」
    實際上是在檢查「最新的 N×60 件作品」——剛投稿的作品還沒累積收藏，
    這條路幾乎必然回傳空清單，而且要花掉幾千次請求。因此優先走
    `users入り` 標籤，只有在標籤搜不到東西時才退回逐件查詢。
    """
    tag = users_tag_for(min_bookmarks) if use_users_tag else None
    candidates: list[str] = []

    if tag:
        query = f'{word} {tag}'
        log.info('以標籤搜尋：%s', query)
        candidates, total = await _search_ids(client, query, mode, pages, hide_ai)
        if not candidates:
            log.warning('標籤 %s 找不到結果，退回逐件查詢模式', tag)
        else:
            log.info('標籤命中 %d 件，取回 %d 件候選', total, len(candidates))
            if min_bookmarks in USERS_TAG_THRESHOLDS:
                # 門檻剛好等於標籤門檻時，命中標籤本身就是「收藏數 >= 門檻」的
                # 證明（收藏數只增不減），完全不需要再逐件驗證。
                log.info('門檻與標籤一致，略過逐件驗證')
                return candidates

    if not candidates:
        candidates, total = await _search_ids(client, word, mode, pages, hide_ai)
        log.info('搜尋「%s」共 %d 件，取回最新的 %d 件候選', word, total, len(candidates))

    if not candidates:
        return []

    # 逐件查收藏數是最貴的一步，先把預估時間講清楚，不要讓使用者對著空畫面等。
    eta = len(candidates) * max(client.config.request_interval, 0.0)
    log.info(
        '正在查詢 %d 件作品的收藏數（預估 %.0f 秒）…',
        len(candidates),
        eta,
    )

    bar = tqdm(total=len(candidates), disable=not show_progress, unit='件', desc='查收藏數')

    async def bookmarks(illust_id: str) -> str | None:
        try:
            data = await client.get_json(f'/ajax/illust/{illust_id}')
        except PixivBlockedError:
            # 斷路器跳開時每一件都會回 None，吞掉的話 popular_search 會以
            # 「成功但空清單」返回，使用者完全看不出整批已經被中止。
            raise
        except PixivError as exc:
            # 已刪除／受限的單一作品不該讓整批查詢失敗。
            log.debug('無法取得作品 %s 的資訊：%s', illust_id, exc)
            return None
        finally:
            bar.update(1)
        body = data.get('body') or {}
        count = body.get('bookmarkCount')
        if isinstance(count, int) and count >= min_bookmarks:
            return illust_id
        return None

    try:
        # gather 保序回傳、每個任務有各自的結果，不再共用同一個 list。
        filtered = await asyncio.gather(*(bookmarks(i) for i in candidates))
    finally:
        bar.close()

    kept = [i for i in filtered if i is not None]
    log.info('收藏數 >= %d 的作品共 %d 件', min_bookmarks, len(kept))
    return kept


def _entries(body: dict[str, Any], key: str) -> Sequence[dict[str, Any]]:
    section = body.get(key) or {}
    if isinstance(section, dict):
        return section.get('data') or []
    return []
