"""互動式選單。輸入一律經過驗證，打錯字會重問而不是噴 traceback。"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from .client import PixivClient
from .paths import Source
from .search import (
    PopularOrder,
    RankingMode,
    SearchMode,
    popular_search,
    premium_search,
    ranking,
    search_illustrations,
    user_illusts,
)

RULE = '=' * 50

MAIN_MENU = """
        0:Pixiv id mode
        1:Search mode
        2:Ranking mode
        3:User illusts
        4:Premium search(Need premium)
        5:Popular search(non premium)
"""

_SEARCH_MODES: Sequence[SearchMode] = (SearchMode.ALL, SearchMode.SAFE, SearchMode.R18)
_ORDERS: Sequence[PopularOrder] = (PopularOrder.ALL, PopularOrder.MALE, PopularOrder.FEMALE)
#: 選單編號 6 是 r18 子選單，所以編號與模式不是連續對應的。
_RANKING_BY_MENU = {
    0: RankingMode.DAILY,
    1: RankingMode.WEEKLY,
    2: RankingMode.MONTHLY,
    3: RankingMode.ROOKIE,
    4: RankingMode.ORIGINAL,
    5: RankingMode.FEMALE,
    7: RankingMode.MALE,
}
_R18_MODES: Sequence[RankingMode] = (
    RankingMode.DAILY_R18,
    RankingMode.WEEKLY_R18,
    RankingMode.MALE_R18,
    RankingMode.FEMALE_R18,
)


def ask_int(prompt: str, *, low: int | None = None, high: int | None = None) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print('請輸入數字。')
            continue
        if low is not None and value < low:
            print(f'請輸入不小於 {low} 的數字。')
            continue
        if high is not None and value > high:
            print(f'請輸入不大於 {high} 的數字。')
            continue
        return value


def ask_choice(prompt: str, options: Sequence[object]) -> int:
    return ask_int(prompt, low=0, high=len(options) - 1)


def ask_yes_no(prompt: str, *, default: bool = False) -> bool:
    suffix = '[Y/n]' if default else '[y/N]'
    while True:
        raw = input(f'{prompt}{suffix}:').strip().lower()
        if not raw:
            return default
        if raw in ('y', 'yes'):
            return True
        if raw in ('n', 'no'):
            return False
        print("請輸入 'y' 或 'n'。")


def ask_text(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print('不能留空。')


def _ranking_source(mode: RankingMode) -> Source:
    return Source('ranking', f'{mode.value}-{date.today().isoformat()}')


def _ask_hide_ai(client: PixivClient) -> bool:
    answer = ask_yes_no('隱藏 AI 生成作品', default=client.config.hide_ai)
    print(RULE)
    return answer


async def prompt_for_ids(client: PixivClient) -> tuple[list[str], Source]:
    print(MAIN_MENU)
    mode = ask_choice('Mode:', range(6))
    print(f'Mode:{mode}'.center(50, '='))

    if mode == 0:
        return [str(ask_int('Pixiv id:', low=1))], Source('id')

    if mode == 1:
        word = ask_text('Search:')
        print(RULE)
        print('0:All\n1:Safe\n2:R18(login)')
        search_mode = _SEARCH_MODES[ask_choice('mode:', _SEARCH_MODES)]
        print(RULE)
        hide_ai = _ask_hide_ai(client)
        ids = await search_illustrations(client, word, search_mode, hide_ai=hide_ai)
        return ids, Source('search', word)

    if mode == 2:
        return await _ranking_flow(client)

    if mode == 3:
        user_id = ask_int('user_id:', low=1)
        print(RULE)
        return await user_illusts(client, str(user_id)), Source('user', str(user_id))

    if mode == 4:
        word = ask_text('Search:')
        print(RULE)
        print('0:All popular\n1:Popular for male\n2:Popular for female')
        order = _ORDERS[ask_choice('order:', _ORDERS)]
        print(RULE)
        print('0:r18 & safe\n1:safe\n2:R18')
        search_mode = _SEARCH_MODES[ask_choice('mode:', _SEARCH_MODES)]
        print(RULE)
        pages = ask_int('pages:', low=1)
        print(RULE)
        only_illust = ask_yes_no('only_illust', default=True)
        print(RULE)
        hide_ai = _ask_hide_ai(client)
        ids = await premium_search(
            client,
            word,
            order=order,
            mode=search_mode,
            pages=pages,
            only_illust=only_illust,
            hide_ai=hide_ai,
        )
        return ids, Source('premium', word)

    word = ask_text('Search:')
    print(RULE)
    min_bookmarks = ask_int('collection:', low=0)
    print(RULE)
    print('0:All(login)\n1:Safe(login)\n2:R18(login)')
    search_mode = _SEARCH_MODES[ask_choice('Mode:', _SEARCH_MODES)]
    print(RULE)
    pages = ask_int('pages(每頁 60 件，建議 10):', low=1)
    print(RULE)
    hide_ai = _ask_hide_ai(client)
    ids = await popular_search(
        client, word, min_bookmarks, mode=search_mode, pages=pages, hide_ai=hide_ai
    )
    return ids, Source('popular', f'{word}-{min_bookmarks}')


async def _ranking_flow(client: PixivClient) -> tuple[list[str], Source]:
    print(
        """
            0:daily
            1:weekly
            2:monthly
            3:rookie
            4:original
            5:for female
            6:r18(login)
            7:for male
        """
    )
    choice = ask_choice('ranking_mode:', range(8))
    print(RULE)
    pages = ask_int('Page:', low=1)
    print(RULE)

    if choice == 6:
        print('0:daily_r18\n1:weekly_r18\n2:male_r18\n3:female_r18')
        mode = _R18_MODES[ask_choice('R18_mode:', _R18_MODES)]
        print(RULE)
        return await ranking(client, pages, mode), _ranking_source(mode)

    mode = _RANKING_BY_MENU[choice]
    only_illust = False
    if mode in (RankingMode.DAILY, RankingMode.WEEKLY, RankingMode.MONTHLY, RankingMode.ROOKIE):
        only_illust = ask_yes_no('Only illustration', default=False)
        print(RULE)
    ids = await ranking(client, pages, mode, only_illust=only_illust)
    return ids, _ranking_source(mode)
