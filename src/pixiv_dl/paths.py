"""輸出路徑的組裝與清理。

搜尋詞會直接變成資料夾名稱，而搜尋詞是使用者輸入——`../../etc` 或 `CON`
都可能出現。所有路徑片段一律經過 `sanitize_component` 才落地。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

#: Windows 不允許的字元。其他平台也一起擋，讓同一份設定在各平台產出同樣的結構。
#: 含 `/` 與 `\`，所以路徑穿越在這一步就被截斷。
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

#: Windows 的保留裝置名稱，加了副檔名也一樣不能用。
_RESERVED = frozenset(
    {
        'CON',
        'PRN',
        'AUX',
        'NUL',
        *(f'COM{i}' for i in range(1, 10)),
        *(f'LPT{i}' for i in range(1, 10)),
    }
)

#: 單一路徑片段的長度上限。Pixiv 的搜尋詞可以很長，而多數檔案系統的
#: 單層名稱上限是 255 bytes——中日文一個字最多 4 bytes，抓 80 字元安全。
MAX_COMPONENT = 80

MULTIPAGE_MODES = ('auto', 'always', 'never')
DEFAULT_TEMPLATE = '{kind}/{label}'


def sanitize_component(text: str, *, fallback: str = 'unnamed') -> str:
    """把任意字串轉成單一個安全的路徑片段。"""
    cleaned = _ILLEGAL.sub('_', text).strip()
    # Windows 會默默吃掉結尾的點與空白，導致「建立的目錄」和「之後找的目錄」
    # 名字對不上——先自己去掉，行為才可預測。
    cleaned = cleaned.rstrip('. ')
    if cleaned in ('', '.', '..'):
        return fallback
    if cleaned.split('.')[0].upper() in _RESERVED:
        cleaned = f'_{cleaned}'
    if len(cleaned) > MAX_COMPONENT:
        cleaned = cleaned[:MAX_COMPONENT].rstrip('. ') or fallback
    return cleaned


@dataclass(frozen=True)
class Source:
    """一次下載的來源，決定檔案落在哪個子目錄。

    kind 是指令名（ranking / search / user …），label 是查詢的識別字串
    （排行榜模式加日期、搜尋關鍵字、使用者 id）。
    """

    kind: str
    label: str = ''

    def subdir(self, template: str = DEFAULT_TEMPLATE) -> Path:
        """依範本組出相對目錄。空範本代表全部平鋪在根目錄。"""
        if not template.strip():
            return Path()

        values = {
            'kind': self.kind,
            'label': self.label,
            'date': date.today().isoformat(),
        }

        parts: list[str] = []
        # 先按 `/` 切開再逐段格式化，這樣值裡面的 `/` 不會被當成目錄分隔。
        for segment in template.split('/'):
            try:
                rendered = segment.format(**values)
            except (KeyError, IndexError) as exc:
                raise ValueError(
                    f'path-template 用到了不存在的欄位：{segment}'
                    f'（可用的有 {", ".join(sorted(values))}）'
                ) from exc
            rendered = rendered.strip(' -_')
            if rendered:
                parts.append(sanitize_component(rendered, fallback=self.kind or 'misc'))
        return Path(*parts)


def illust_dir(base: Path, illust_id: str, page_count: int, mode: str = 'auto') -> Path:
    """決定單一作品的落地目錄。

    auto：只有多頁作品才開子資料夾，避免一件 30 頁的作品把整層洗版，
    同時不讓單張作品多一層無謂的巢狀。
    """
    if mode == 'always' or (mode == 'auto' and page_count > 1):
        return base / sanitize_component(illust_id, fallback='illust')
    return base
