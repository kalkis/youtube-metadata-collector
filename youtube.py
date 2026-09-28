import json
import urllib.request
from functools import cache
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode

from config import CONFIG, api_key

VIDEO_PARTS = (
    "snippet,contentDetails,status,statistics,topicDetails,"
    "liveStreamingDetails,paidProductPlacementDetails"
)


class YouTubeApiError(Exception):
    def __init__(self, method, status, reason):
        super().__init__(f"{method} failed with status {status}: {reason}")
        self.method, self.status, self.reason = method, status, reason


def _error_reason(error: HTTPError):
    try:
        return json.load(error)["error"]["errors"][0]["reason"]
    except (OSError, HTTPException, ValueError, LookupError, TypeError):
        return None


def _first_item(resource, **params) -> dict | None:
    method = f"{resource}.list"
    query = urlencode(params | {"key": api_key()})
    url = f"{CONFIG.youtube_api_base_url}/{resource}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=CONFIG.http_timeout_seconds) as reply:
            status, body = reply.status, reply.read()
    except HTTPError as e:
        raise YouTubeApiError(method, e.code, _error_reason(e)) from None
    except (OSError, HTTPException) as e:
        raise YouTubeApiError(method, None, type(e).__name__) from None
    if status != 200:
        raise YouTubeApiError(method, status, None)
    try:
        response = json.loads(body)
    except ValueError:
        response = None
    match response:
        case {"items": [dict() as item, *_]}:
            return item
        case dict() if not response.get("items"):
            return None
    raise YouTubeApiError(method, status, "invalidResponse")


def video(video_id) -> dict | None:
    return _first_item("videos", id=video_id, part=VIDEO_PARTS)


# Cached per invocation: the handler calls channel.cache_clear() on entry.
@cache
def channel(channel_id) -> dict | None:
    return _first_item("channels", id=channel_id, part="statistics")


@cache
def video_category(category_id) -> dict | None:
    return _first_item("videoCategories", id=category_id, part="snippet")
