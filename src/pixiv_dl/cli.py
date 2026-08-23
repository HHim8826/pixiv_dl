"""命令列入口。不給子命令時退回原本的互動式選單。"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import platform
import sys
from argparse import SUPPRESS
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from . import __version__, interactive
from .client import PixivBlockedError, PixivClient
from .config import Config, ConfigError
from .download import download_all
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

BANNER = r"""  _
 |_)  o      o           /\    _      ._    _     ._
 |    |  ><  |  \/      /--\  _>  \/  | |  (_  o  |_)  \/
                    __            /               |    /
"""

log = logging.getLogger(__name__)

_ORDERS = {'all': PopularOrder.ALL, 'male': PopularOrder.MALE, 'female': PopularOrder.FEMALE}


#: 共用選項的預設值。這些選項以 SUPPRESS 註冊，子解析器才不會把
#: 寫在子命令「前面」的值重設成 None。
_COMMON_DEFAULTS = {
    'config': None,
    'out_dir': None,
    'concurrency': None,
    'verbose': False,
    'no_progress': False,
    'path_template': None,
    'flat': False,
}


def _common_options() -> argparse.ArgumentParser:
    """共用選項寫在子命令前或後都要能生效。"""
    common = argparse.ArgumentParser(add_help=False)
    add = common.add_argument
    add('--config', type=Path, default=SUPPRESS, help='設定檔路徑（預設自動尋找 config.toml）')
    add('--out-dir', type=Path, default=SUPPRESS, help='輸出目錄')
    add('--concurrency', type=int, default=SUPPRESS, help='同時進行的請求數上限')
    add('-v', '--verbose', action='store_true', default=SUPPRESS, help='輸出除錯訊息')
    add('--no-progress', action='store_true', default=SUPPRESS, help='不顯示進度條')
    add(
        '--path-template',
        default=SUPPRESS,
        help="輸出子目錄範本，可用 {kind} {label} {date}（預設 '{kind}/{label}'）",
    )
    add('--flat', action='store_true', default=SUPPRESS, help='全部平鋪在輸出目錄，不分子資料夾')
    return common


def _add_ai_flags(parser: argparse.ArgumentParser) -> None:
    """AI 過濾三態：未指定時沿用設定檔，兩個旗標可個別覆蓋。"""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        '--hide-ai',
        dest='hide_ai',
        action='store_true',
        default=None,
        help='隱藏 AI 生成作品（送出 ai_type=1）',
    )
    group.add_argument(
        '--show-ai',
        dest='hide_ai',
        action='store_false',
        default=None,
        help='顯示 AI 生成作品（送出 ai_type=0）',
    )


def build_parser() -> argparse.ArgumentParser:
    common = _common_options()
    parser = argparse.ArgumentParser(
        prog='pixiv-dl',
        description='Pixiv 非同步下載器。不帶子命令時進入互動模式。',
        parents=[common],
    )
    parser.add_argument('--version', action='version', version=f'pixiv-dl {__version__}')
    sub = parser.add_subparsers(dest='command')

    def add_command(name: str, help_text: str) -> argparse.ArgumentParser:
        return sub.add_parser(name, help=help_text, parents=[common])

    p_id = add_command('id', '直接依作品 ID 下載')
    p_id.add_argument('illust_ids', nargs='+')

    p_search = add_command('search', '關鍵字搜尋')
    p_search.add_argument('word')
    p_search.add_argument('--mode', choices=[m.value for m in SearchMode], default='all')
    _add_ai_flags(p_search)

    p_rank = add_command('ranking', '排行榜')
    p_rank.add_argument('--mode', choices=[m.value for m in RankingMode], default='daily')
    p_rank.add_argument('--pages', type=int, default=1)
    p_rank.add_argument(
        '--only-illust',
        action='store_true',
        help='只要插畫（僅 daily/weekly/monthly/rookie 支援）',
    )

    p_user = add_command('user', '下載某使用者的全部作品')
    p_user.add_argument('user_id')

    p_premium = add_command('premium', '人氣排序搜尋（需 premium 帳號）')
    p_premium.add_argument('word')
    p_premium.add_argument('--order', choices=sorted(_ORDERS), default='all')
    p_premium.add_argument('--mode', choices=[m.value for m in SearchMode], default='all')
    p_premium.add_argument('--pages', type=int, default=1)
    p_premium.add_argument('--all-types', action='store_true', help='插畫以外的類型也一起抓')
    _add_ai_flags(p_premium)

    p_popular = add_command('popular', '依收藏數過濾搜尋結果（免 premium）')
    p_popular.add_argument('word')
    p_popular.add_argument('--min-bookmarks', type=int, required=True)
    p_popular.add_argument('--mode', choices=[m.value for m in SearchMode], default='all')
    p_popular.add_argument('--pages', type=int, default=10)
    p_popular.add_argument(
        '--no-users-tag',
        action='store_true',
        help='不要用 users入り 標籤加速（慢很多，且多半搜不到東西）',
    )
    _add_ai_flags(p_popular)

    return parser


def source_for(args: argparse.Namespace) -> Source:
    """把指令與其參數轉成輸出目錄的來源描述。"""
    if args.command == 'search':
        return Source('search', args.word)
    if args.command == 'ranking':
        # 排行榜每天不同，日期是內容的一部分，不加會逐日互相覆蓋。
        return Source('ranking', f'{args.mode}-{date.today().isoformat()}')
    if args.command == 'user':
        return Source('user', str(args.user_id))
    if args.command == 'premium':
        return Source('premium', args.word)
    if args.command == 'popular':
        return Source('popular', f'{args.word}-{args.min_bookmarks}')
    return Source(args.command or 'misc')


async def collect_ids(args: argparse.Namespace, client: PixivClient) -> list[str]:
    # 旗標沒指定時（None）沿用設定檔的預設值。
    hide_ai = client.config.hide_ai if getattr(args, 'hide_ai', None) is None else args.hide_ai

    if args.command == 'id':
        return [str(i) for i in args.illust_ids]
    if args.command == 'search':
        return await search_illustrations(client, args.word, SearchMode(args.mode), hide_ai=hide_ai)
    if args.command == 'ranking':
        return await ranking(
            client, args.pages, RankingMode(args.mode), only_illust=args.only_illust
        )
    if args.command == 'user':
        return await user_illusts(client, args.user_id)
    if args.command == 'premium':
        return await premium_search(
            client,
            args.word,
            order=_ORDERS[args.order],
            mode=SearchMode(args.mode),
            pages=args.pages,
            only_illust=not args.all_types,
            hide_ai=hide_ai,
        )
    if args.command == 'popular':
        return await popular_search(
            client,
            args.word,
            args.min_bookmarks,
            mode=SearchMode(args.mode),
            pages=args.pages,
            use_users_tag=not args.no_users_tag,
            show_progress=not args.no_progress,
            hide_ai=hide_ai,
        )
    raise ValueError(f'未知的命令：{args.command}')


def _print_blocked_advice() -> None:
    print(
        '\n被 Cloudflare 的機器人偵測擋下，已提前中止。建議：\n'
        '  1. 把 config.toml 的 request-interval 調大（例如 1.0）\n'
        '  2. 把 concurrency 調小（例如 2）\n'
        '  3. 等幾分鐘再跑；已下載的檔案會自動跳過，可以直接續傳',
        file=sys.stderr,
    )


async def run(args: argparse.Namespace, config: Config) -> int:
    async with PixivClient(config) as client:
        try:
            if args.command is None:
                ids, source = await interactive.prompt_for_ids(client)
            else:
                ids = await collect_ids(args, client)
                source = source_for(args)
        except PixivBlockedError as exc:
            # 取得 id 的階段（例如 popular 的逐件查詢）就被擋下時，
            # 也要給出和下載階段一致的說明與離開碼。
            print(exc, file=sys.stderr)
            _print_blocked_advice()
            return 1

        dest = config.out_dir / source.subdir(config.path_template)
        log.info('輸出目錄：%s', dest)
        report = await download_all(client, ids, dest, show_progress=not args.no_progress)

    print(report.summary())
    if report.blocked:
        _print_blocked_advice()
    if report.failures:
        print('失敗的作品：', file=sys.stderr)
        for illust_id, reason in report.failures[:20]:
            print(f'  {illust_id}: {reason}', file=sys.stderr)
        if len(report.failures) > 20:
            print(f'  …另有 {len(report.failures) - 20} 件', file=sys.stderr)
    return 0 if report.ok else 1


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    for name, default in _COMMON_DEFAULTS.items():
        if not hasattr(args, name):
            setattr(args, name, default)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s %(message)s',
    )

    if platform.system() == 'Windows':
        # aiohttp 在 Windows 的 Proactor loop 上關閉時會噴假錯誤。
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        config = Config.load(args.config)
        if args.out_dir is not None:
            config = dataclasses.replace(config, out_dir=args.out_dir.resolve())
        if args.concurrency is not None:
            config = dataclasses.replace(config, concurrency=args.concurrency)
        if args.flat:
            # 只清空 path_template 不夠：multipage_dirs 預設 auto，多頁作品
            # 仍會落到 out_dir/<illust_id>/，就不是承諾的「全部平鋪」。
            config = dataclasses.replace(config, path_template='', multipage_dirs='never')
        elif args.path_template is not None:
            config = dataclasses.replace(config, path_template=args.path_template)
        config.require_cookie()
    except ConfigError as exc:
        print(f'設定錯誤：{exc}', file=sys.stderr)
        return 2

    if args.command is None:
        print(BANNER)

    try:
        return asyncio.run(run(args, config))
    except KeyboardInterrupt:
        print('\n已中斷', file=sys.stderr)
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
