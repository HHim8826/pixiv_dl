"""設定載入：環境變數 > 設定檔 > 內建預設值。

cookie 刻意不放進 pyproject.toml —— 那是打包用的檔案且會被 git 追蹤，
把 session cookie 寫進去等於準備把它推上公開 repo。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - 3.9 / 3.10
    import tomli as tomllib  # type: ignore[no-redef]

from .paths import DEFAULT_TEMPLATE, MULTIPAGE_MODES

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
)
DEFAULT_BASE_URL = 'https://www.pixiv.net'

CONFIG_ENV = 'PIXIV_DL_CONFIG'
COOKIE_ENV = 'PIXIV_COOKIE'
CONFIG_FILENAME = 'config.toml'


class ConfigError(RuntimeError):
    """設定檔缺失或內容無效。"""


@dataclass(frozen=True)
class Config:
    cookie: str = ''
    user_agent: str = DEFAULT_USER_AGENT
    out_dir: Path = Path('img')
    # Pixiv 在 Cloudflare 後方，併發 8 + 無速率上限會直接觸發機器人挑戰。
    concurrency: int = 4
    #: 全域最小請求間隔（秒）。這是比 concurrency 更重要的那個旋鈕。
    request_interval: float = 0.35
    timeout: float = 60.0
    connect_timeout: float = 10.0
    max_retries: int = 3
    retry_backoff: float = 1.0
    #: 遇到 Cloudflare 挑戰頁時的基礎退避，遠大於一般 429。
    challenge_backoff: float = 15.0
    #: 連續幾次挑戰就放棄整批（繼續打只會更慘）。
    challenge_limit: int = 5
    #: 輸出子目錄範本。空字串 = 全部平鋪在 out_dir（v3.0 的舊行為）。
    path_template: str = DEFAULT_TEMPLATE
    #: 多頁作品是否另開子資料夾：auto / always / never。
    multipage_dirs: str = 'auto'
    #: 送出 ai_type=1 隱藏 AI 生成作品；False 則送 0（顯示全部）。
    #: 只影響搜尋類端點，排行榜與使用者作品列表不支援這個參數。
    hide_ai: bool = False
    base_url: str = DEFAULT_BASE_URL

    def headers(self, referer: str | None = None) -> dict[str, str]:
        return {
            'referer': referer or f'{self.base_url}/',
            'cookie': self.cookie,
            'user-agent': self.user_agent,
        }

    def require_cookie(self) -> None:
        """在真正送出請求前檢查 cookie，錯誤訊息要能指引使用者。"""
        if not self.cookie.strip():
            raise ConfigError(
                '找不到 Pixiv cookie。請擇一設定：\n'
                f'  1. 環境變數 {COOKIE_ENV}\n'
                f'  2. 複製 config.example.toml 成 {CONFIG_FILENAME} 並填入 [login].cookie'
            )

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """依序尋找設定檔；環境變數優先權高於檔案內容。"""
        resolved = _resolve_config_path(path)
        raw: dict[str, Any] = {}
        if resolved is not None:
            try:
                raw = tomllib.loads(resolved.read_text('utf-8'))
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f'{resolved} 不是合法的 TOML：{exc}') from exc
        elif path is not None:
            raise ConfigError(f'找不到設定檔：{path}')

        login = raw.get('login') or {}
        download = raw.get('download') or {}
        search = raw.get('search') or {}

        values: dict[str, Any] = {
            'cookie': os.environ.get(COOKIE_ENV) or login.get('cookie', ''),
            'user_agent': login.get('user-agent') or DEFAULT_USER_AGENT,
        }
        base = resolved.parent if resolved is not None else Path.cwd()
        out_dir = download.get('out-dir')
        values['out_dir'] = (base / out_dir).resolve() if out_dir else (base / 'img').resolve()
        for key, cast in (
            ('concurrency', int),
            ('request-interval', float),
            ('timeout', float),
            ('connect-timeout', float),
            ('max-retries', int),
            ('retry-backoff', float),
            ('challenge-backoff', float),
            ('challenge-limit', int),
        ):
            if key in download:
                values[key.replace('-', '_')] = cast(download[key])

        if 'path-template' in download:
            values['path_template'] = str(download['path-template'])
        if 'multipage-dirs' in download:
            mode = str(download['multipage-dirs']).lower()
            if mode not in MULTIPAGE_MODES:
                raise ConfigError(
                    f'multipage-dirs 只能是 {" / ".join(MULTIPAGE_MODES)}，得到 {mode!r}'
                )
            values['multipage_dirs'] = mode

        if 'hide-ai' in search:
            values['hide_ai'] = bool(search['hide-ai'])

        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in values.items() if k in known})


def _resolve_config_path(path: Path | None) -> Path | None:
    if path is not None:
        return path if path.is_file() else None

    candidates = []
    env_path = os.environ.get(CONFIG_ENV)
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / CONFIG_FILENAME)
    candidates.append(Path(__file__).resolve().parents[2] / CONFIG_FILENAME)
    candidates.append(Path.home() / '.config' / 'pixiv_dl' / CONFIG_FILENAME)

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
