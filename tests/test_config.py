import os
from dataclasses import replace

import pytest
from conftest import API_KEY, API_KEY_SECRET_ID, set_api_key, set_secret_string

import config
from config import ConfigError, api_key, load_config

ENV = {name: os.environ[name] for name in ("TABLE_NAME", "API_KEY_SECRET_ID")}


def test_defaults():
    assert load_config(ENV) == config.Config(
        table_name="video-metadata",
        api_key_secret_id=API_KEY_SECRET_ID,
        retention_days=28,
        youtube_api_base_url="https://www.googleapis.com/youtube/v3",
        http_timeout_seconds=10,
        log_level="INFO",
    )


def test_overrides():
    loaded = load_config(
        ENV
        | {
            "RETENTION_DAYS": "7",
            "YOUTUBE_API_BASE_URL": "https://youtube.test/v3/",
            "HTTP_TIMEOUT_SECONDS": "3",
            "LOG_LEVEL": "debug",
        }
    )
    assert loaded.retention_days == 7
    assert loaded.youtube_api_base_url == "https://youtube.test/v3"
    assert loaded.http_timeout_seconds == 3
    assert loaded.log_level == "DEBUG"


@pytest.mark.parametrize(
    "overrides",
    [
        {"TABLE_NAME": ""},
        {"TABLE_NAME": "no spaces"},
        {"API_KEY_SECRET_ID": " "},
        {"RETENTION_DAYS": "four weeks"},
        {"RETENTION_DAYS": "0"},
        {"RETENTION_DAYS": "1.5"},
        {"YOUTUBE_API_BASE_URL": "http://www.googleapis.com/youtube/v3"},
        {"YOUTUBE_API_BASE_URL": "https://"},
        {"HTTP_TIMEOUT_SECONDS": "-1"},
        {"LOG_LEVEL": "LOUD"},
    ],
)
def test_invalid_env_fails(overrides):
    with pytest.raises(ConfigError):
        load_config(ENV | overrides)


def test_api_key_is_cached():
    assert api_key() == API_KEY
    set_api_key("rotated-key")
    assert api_key() == API_KEY


def test_api_key_is_read_from_key_value_secret():
    set_secret_string('{"API_KEY": " test-api-key ", "other": "x"}')
    assert api_key() == API_KEY


@pytest.mark.parametrize(
    "secret_string",
    [
        API_KEY,
        "[]",
        "{}",
        '{"API_KEY_SECRET_ID": "test-api-key"}',
        '{"API_KEY": " "}',
        '{"API_KEY": 1}',
    ],
)
def test_malformed_secret_fails_without_revealing_it(secret_string):
    set_secret_string(secret_string)
    with pytest.raises(ConfigError) as error:
        api_key()
    assert API_KEY not in str(error.value)


def test_failure_is_not_cached():
    set_api_key(" ")
    with pytest.raises(ConfigError):
        api_key()
    set_api_key(API_KEY)
    assert api_key() == API_KEY


def test_unreadable_secret_fails(monkeypatch):
    missing = replace(config.CONFIG, api_key_secret_id="test/missing")
    monkeypatch.setattr(config, "CONFIG", missing)
    with pytest.raises(ConfigError, match="ResourceNotFoundException"):
        api_key()
