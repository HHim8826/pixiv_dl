"""下載作品：逐頁串流落地，失敗會被收集並回報，不會被靜默吞掉。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp
from tqdm import tqdm

from .client import PixivBlockedError, PixivClient, PixivError, filename_from_url
from .paths import illust_dir

log = logging.getLogger(__name__)


@dataclass
class DownloadReport:
    downloaded: int = 0
    skipped: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)
    #: 是否因連續 Cloudflare 挑戰而提前中止。
    blocked: bool = False

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        parts = [f'下載 {self.downloaded} 個檔案', f'跳過 {self.skipped} 個既有檔案']
        if self.failures:
            parts.append(f'失敗 {len(self.failures)} 件')
        return '，'.join(parts)


async def illust_pages(client: PixivClient, illust_id: str) -> list[dict[str, object]]:
    data = await client.get_json(f'/ajax/illust/{illust_id}/pages')
    body = data.get('body')
    return body if isinstance(body, list) else []


async def download_illust(
    client: PixivClient,
    illust_id: str,
    out_dir: Path,
    *,
    multipage_dirs: str = 'auto',
) -> tuple[int, int]:
    """回傳 (實際下載數, 因已存在而跳過數)。"""
    downloaded = skipped = 0
    pages = await illust_pages(client, illust_id)
    target = illust_dir(out_dir, illust_id, len(pages), multipage_dirs)
    for index, page in enumerate(pages):
        urls = page.get('urls') if isinstance(page, dict) else None
        url = urls.get('original') if isinstance(urls, dict) else None
        if not url:
            # 受限或已刪除的作品拿不到原圖網址，跳過比拋錯更貼近使用者預期。
            log.warning('作品 %s 第 %d 頁沒有原圖網址，略過', illust_id, index)
            continue
        name = filename_from_url(url, fallback=f'{illust_id}_p{index}.jpg')
        if await client.download(url, target / name):
            downloaded += 1
        else:
            skipped += 1
    return downloaded, skipped


async def download_all(
    client: PixivClient,
    illust_ids: Sequence[str],
    out_dir: Path | None = None,
    *,
    show_progress: bool = True,
) -> DownloadReport:
    out_dir = out_dir or client.config.out_dir
    ids = list(dict.fromkeys(str(i) for i in illust_ids if i))
    report = DownloadReport()
    if not ids:
        log.warning('沒有任何作品可下載')
        return report

    out_dir.mkdir(parents=True, exist_ok=True)
    bar = tqdm(total=len(ids), disable=not show_progress, unit='件')

    async def one(illust_id: str) -> None:
        try:
            downloaded, skipped = await download_illust(
                client, illust_id, out_dir, multipage_dirs=client.config.multipage_dirs
            )
            report.downloaded += downloaded
            report.skipped += skipped
        except PixivBlockedError as exc:
            # 已被 Cloudflare 擋下，剩下的都會是同一個原因，不要洗版。
            report.failures.append((illust_id, str(exc)))
            report.blocked = True
        except (PixivError, OSError, asyncio.TimeoutError, aiohttp.ClientError) as exc:
            # _with_retry 重試用盡後會原樣拋出 aiohttp.ClientError，
            # 不接住的話連線被重置就會炸掉整批 gather。
            report.failures.append((illust_id, str(exc)))
            log.error('作品 %s 下載失敗：%s', illust_id, exc)
        finally:
            bar.update(1)

    try:
        await asyncio.gather(*(one(i) for i in ids))
    finally:
        bar.close()

    return report
