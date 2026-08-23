"""測試用的本地 Pixiv 替身，只需要 aiohttp 自帶的 web server。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from aiohttp import web

from pixiv_dl.config import Config


def run(coro: Any) -> Any:
    return asyncio.run(coro)


@asynccontextmanager
async def serve(routes: dict[str, Callable[..., Any]]):
    app = web.Application()
    for path, handler in routes.items():
        app.router.add_route('GET', path, handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield f'http://127.0.0.1:{port}'
    finally:
        await runner.cleanup()


def config(base_url: str, out_dir, **overrides: Any) -> Config:
    defaults: dict[str, Any] = {
        'cookie': 'test-cookie',
        'base_url': base_url,
        'out_dir': out_dir,
        'max_retries': 0,
        'retry_backoff': 0.0,
        'request_interval': 0.0,  # 測試不需要真的等
        'challenge_backoff': 0.0,
        'timeout': 10.0,
        'connect_timeout': 5.0,
    }
    defaults.update(overrides)
    return Config(**defaults)


def png(size: int = 32) -> bytes:
    return b'\x89PNG\r\n\x1a\n' + b'\x00' * size
