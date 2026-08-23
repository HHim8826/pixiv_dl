"""輸出路徑的組裝與清理。

搜尋詞會直接變成資料夾名，所以這裡的清理是安全性測試，不只是格式測試。
"""

from __future__ import annotations

from argparse import Namespace
from datetime import date
from pathlib import Path

import pytest

from pixiv_dl.paths import (
    DEFAULT_TEMPLATE,
    MAX_COMPONENT_BYTES,
    Source,
    illust_dir,
    sanitize_component,
)

# --- 清理 ---


@pytest.mark.parametrize(
    ('raw', 'expected'),
    [
        ('miku', 'miku'),
        ('初音ミク', '初音ミク'),
        ('a b', 'a b'),
        # 分隔符被替換掉，`..` 留著也無害——整串已經是單一個路徑片段。
        ('touhou/../../etc', 'touhou_.._.._etc'),
        (r'a\b', 'a_b'),
        ('a:b*c?d', 'a_b_c_d'),
        ('  spaced  ', 'spaced'),
    ],
)
def test_sanitize_component(raw, expected):
    assert sanitize_component(raw) == expected


@pytest.mark.parametrize('raw', ['..', '.', '', '   ', '///', '..  '])
def test_sanitize_rejects_traversal_and_empty(raw):
    assert sanitize_component(raw, fallback='safe') in ('safe', '___')
    assert sanitize_component(raw, fallback='safe') not in ('..', '.', '')


@pytest.mark.parametrize('name', ['CON', 'con', 'NUL', 'COM1', 'LPT9', 'aux.txt'])
def test_sanitize_escapes_windows_reserved_names(name):
    result = sanitize_component(name)
    assert result.startswith('_')


@pytest.mark.parametrize(
    'char',
    [
        'a',  # 1 byte
        'あ',  # 3 bytes
        '𠮷',  # 4 bytes（BMP 外）
        '🎨',  # 4 bytes emoji
    ],
)
def test_sanitize_truncates_by_utf8_bytes_not_characters(char):
    """迴歸測試：80 個 4-byte 字元 = 320 bytes，超過多數檔案系統的
    255 bytes 單層上限，mkdir 會在下載開始前就 ENAMETOOLONG。"""
    result = sanitize_component(char * 300)
    assert len(result.encode('utf-8')) <= MAX_COMPONENT_BYTES
    assert result  # 不能截成空字串


def test_truncated_name_stays_valid_utf8():
    """截斷不能把多位元組字元切成兩半。"""
    result = sanitize_component('🎨' * 300)
    assert result.encode('utf-8').decode('utf-8') == result
    assert '�' not in result


def test_sanitize_never_ends_with_dot_or_space():
    """Windows 會默默吃掉結尾的點和空白，建立與查找的名稱就會對不上。"""
    for raw in ('name.', 'name ', 'name. . ', 'name...'):
        assert not sanitize_component(raw).endswith(('.', ' '))


# --- Source -> 子目錄 ---


def test_default_template_is_kind_over_label():
    assert Source('search', 'miku').subdir() == Path('search') / 'miku'


def test_empty_label_collapses_to_kind_only():
    assert Source('id').subdir() == Path('id')


def test_empty_template_means_flat():
    assert Source('search', 'miku').subdir('') == Path()
    assert Source('search', 'miku').subdir('   ') == Path()


def test_label_containing_slash_stays_one_component():
    """搜尋詞裡的 `/` 不能變成目錄分隔，否則就是路徑注入。"""
    result = Source('search', 'a/b/c').subdir()
    assert len(result.parts) == 2
    assert result.parts[1] == 'a_b_c'


def test_template_can_use_date():
    result = Source('ranking', 'daily').subdir('{date}/{kind}/{label}')
    assert result.parts[0] == date.today().isoformat()
    assert result.parts[1:] == ('ranking', 'daily')


def test_template_can_combine_fields_in_one_segment():
    assert Source('ranking', 'daily').subdir('{kind}-{label}') == Path('ranking-daily')


def test_unknown_template_field_raises_with_guidance():
    with pytest.raises(ValueError) as excinfo:
        Source('search', 'miku').subdir('{artist}/{label}')
    message = str(excinfo.value)
    assert 'artist' in message
    assert 'kind' in message and 'label' in message and 'date' in message


def test_template_segments_that_render_empty_are_dropped():
    assert Source('id').subdir('{kind}/{label}') == Path('id')


# --- 多頁作品 ---


@pytest.mark.parametrize(
    ('mode', 'page_count', 'expected'),
    [
        ('auto', 1, Path('base')),
        ('auto', 2, Path('base') / '98765'),
        ('auto', 30, Path('base') / '98765'),
        ('always', 1, Path('base') / '98765'),
        ('always', 5, Path('base') / '98765'),
        ('never', 1, Path('base')),
        ('never', 30, Path('base')),
    ],
)
def test_illust_dir(mode, page_count, expected):
    assert illust_dir(Path('base'), '98765', page_count, mode) == expected


# --- CLI 來源判定 ---


def _args(**kw):
    return Namespace(**kw)


def test_source_for_each_command():
    from pixiv_dl.cli import source_for

    today = date.today().isoformat()
    cases = [
        (_args(command='search', word='miku'), Source('search', 'miku')),
        (
            _args(command='ranking', mode='daily'),
            Source('ranking', f'daily-{today}'),
        ),
        (_args(command='user', user_id='54321'), Source('user', '54321')),
        (_args(command='premium', word='miku'), Source('premium', 'miku')),
        (
            _args(command='popular', word='miku', min_bookmarks=5000),
            Source('popular', 'miku-5000'),
        ),
        (_args(command='id'), Source('id')),
    ]
    for args, expected in cases:
        assert source_for(args) == expected, args.command


def test_ranking_label_carries_the_date():
    """排行榜每天內容不同，沒有日期會逐日互相覆蓋。"""
    from pixiv_dl.cli import source_for

    subdir = source_for(_args(command='ranking', mode='weekly')).subdir(DEFAULT_TEMPLATE)
    assert subdir.parts[0] == 'ranking'
    assert subdir.parts[1].startswith('weekly-')
    assert date.today().isoformat() in subdir.parts[1]


def test_search_word_with_hostile_characters_is_contained(tmp_path):
    """完整路徑必須留在輸出根目錄底下。"""
    from pixiv_dl.cli import source_for

    args = _args(command='search', word='../../../../Windows/System32')
    dest = (tmp_path / source_for(args).subdir()).resolve()
    assert tmp_path.resolve() in dest.parents
