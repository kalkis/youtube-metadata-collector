import contextlib
import io
import json
import traceback
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlsplit

import pytest
from conftest import API_KEY, FIXTURES, set_api_key

import youtube
from config import CONFIG, ConfigError
from youtube import YouTubeApiError

VIDEO_ID = "dQw4w9WgXcQ"
CHANNEL_ID = "UCPdaxSov0mgwh77JvjQO2jQ"
ITEM = {"id": VIDEO_ID}
LEAKY_URL = f"{CONFIG.youtube_api_base_url}/videos?key={API_KEY}"


def http_error(status, body):
    return HTTPError(LEAKY_URL, status, "error", {}, io.BytesIO(body))


def fixture_error(status, name):
    return http_error(status, (FIXTURES / f"{name}.json").read_bytes())


class FakeApi:
    def __init__(self):
        self.requests = []
        self.result = {"items": [ITEM]}

    def urlopen(self, url, timeout):
        parts = urlsplit(url)
        self.requests.append(
            (
                f"{parts.scheme}://{parts.netloc}{parts.path}",
                dict(parse_qsl(parts.query)),
                timeout,
            )
        )
        if isinstance(self.result, Exception):
            raise self.result
        status, body = (
            self.result
            if isinstance(self.result, tuple)
            else (200, json.dumps(self.result).encode())
        )
        return contextlib.nullcontext(SimpleNamespace(status=status, read=lambda: body))


@pytest.fixture(autouse=True)
def api(monkeypatch):
    youtube.channel.cache_clear()
    youtube.video_category.cache_clear()
    fake = FakeApi()
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)
    return fake


def test_video_request(api):
    assert youtube.video(VIDEO_ID) == ITEM
    assert api.requests == [
        (
            f"{CONFIG.youtube_api_base_url}/videos",
            {
                "id": VIDEO_ID,
                "part": "snippet,contentDetails,status,statistics,topicDetails,"
                "liveStreamingDetails,paidProductPlacementDetails",
                "key": API_KEY,
            },
            CONFIG.http_timeout_seconds,
        )
    ]


@pytest.mark.parametrize(
    "call, resource, part",
    [
        (lambda: youtube.channel(CHANNEL_ID), "channels", "statistics"),
        (lambda: youtube.video_category("22"), "videoCategories", "snippet"),
    ],
)
def test_other_requests(api, call, resource, part):
    assert call() == ITEM
    url, params, _ = api.requests[0]
    assert url == f"{CONFIG.youtube_api_base_url}/{resource}"
    assert params["part"] == part
    assert params["key"] == API_KEY


@pytest.mark.parametrize(
    "response", [{"items": []}, {"kind": "youtube#videoListResponse"}]
)
def test_no_items_returns_none(api, response):
    api.result = response
    assert youtube.video(VIDEO_ID) is None


def test_video_is_not_cached(api):
    youtube.video(VIDEO_ID)
    youtube.video(VIDEO_ID)
    assert len(api.requests) == 2


def test_channel_is_cached_until_cleared(api):
    youtube.channel(CHANNEL_ID)
    youtube.channel(CHANNEL_ID)
    assert len(api.requests) == 1
    youtube.channel.cache_clear()
    youtube.channel(CHANNEL_ID)
    assert len(api.requests) == 2


def test_empty_category_is_cached(api):
    api.result = {"items": []}
    assert youtube.video_category("22") is None
    assert youtube.video_category("22") is None
    assert len(api.requests) == 1


def test_failure_is_not_cached(api):
    api.result = URLError("unreachable")
    with pytest.raises(YouTubeApiError):
        youtube.channel(CHANNEL_ID)
    api.result = {"items": [ITEM]}
    assert youtube.channel(CHANNEL_ID) == ITEM
    assert len(api.requests) == 2


@pytest.mark.parametrize(
    "result, status, reason",
    [
        (fixture_error(403, "error_quota_exceeded"), 403, "quotaExceeded"),
        (fixture_error(400, "error_key_invalid"), 400, "badRequest"),
        (http_error(500, b"<html>oops</html>"), 500, None),
        (URLError("unreachable"), None, "URLError"),
        (TimeoutError("timed out"), None, "TimeoutError"),
        ((204, b""), 204, None),
        ((200, b"not json"), 200, "invalidResponse"),
        ((200, b'{"items": ["x"]}'), 200, "invalidResponse"),
        ((200, b"[]"), 200, "invalidResponse"),
    ],
)
def test_errors(api, result, status, reason):
    api.result = result
    with pytest.raises(YouTubeApiError) as error:
        youtube.video(VIDEO_ID)
    assert (error.value.method, error.value.status, error.value.reason) == (
        "videos.list",
        status,
        reason,
    )
    assert error.value.__cause__ is None
    logged = "".join(traceback.format_exception(error.value))
    assert API_KEY not in logged
    assert "key=" not in logged


def test_unreadable_api_key_makes_no_request(api):
    set_api_key(" ")
    with pytest.raises(ConfigError):
        youtube.video(VIDEO_ID)
    assert api.requests == []
