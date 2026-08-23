from __future__ import annotations

import pytest

from pixiv_dl.config import COOKIE_ENV, Config, ConfigError


def _write(tmp_path, text: str):
    path = tmp_path / 'config.toml'
    path.write_text(text, 'utf-8')
    return path


def test_reads_cookie_and_download_settings(tmp_path):
    path = _write(
        tmp_path,
        '[login]\ncookie = "abc"\n[download]\nout-dir = "pics"\nconcurrency = 3\n',
    )
    cfg = Config.load(path)
    assert cfg.cookie == 'abc'
    assert cfg.concurrency == 3
    assert cfg.out_dir == (tmp_path / 'pics').resolve()


def test_environment_variable_wins_over_file(tmp_path, monkeypatch):
    path = _write(tmp_path, '[login]\ncookie = "from-file"\n')
    monkeypatch.setenv(COOKIE_ENV, 'from-env')
    assert Config.load(path).cookie == 'from-env'


def test_missing_cookie_raises_with_guidance(tmp_path):
    cfg = Config.load(_write(tmp_path, '[login]\ncookie = ""\n'))
    with pytest.raises(ConfigError) as excinfo:
        cfg.require_cookie()
    assert COOKIE_ENV in str(excinfo.value)


def test_explicit_missing_path_is_an_error(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(tmp_path / 'nope.toml')


def test_invalid_toml_is_reported(tmp_path):
    with pytest.raises(ConfigError):
        Config.load(_write(tmp_path, 'this is not toml ['))


def test_headers_carry_cookie_and_referer(tmp_path):
    cfg = Config.load(_write(tmp_path, '[login]\ncookie = "abc"\n'))
    headers = cfg.headers('https://www.pixiv.net/ranking.php')
    assert headers['cookie'] == 'abc'
    assert headers['referer'] == 'https://www.pixiv.net/ranking.php'
