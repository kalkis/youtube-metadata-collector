import contextlib
import io
import json
import logging
from datetime import datetime
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit

import pytest
from conftest import API_KEY, load_fixture, set_api_key, set_secret_string

import app
import youtube
from config import ConfigError
from record import build_item

VIDEO_ID = "wCAM-K5E-Ec"
OTHER_VIDEO_ID = "aaaaaaaaaaa"
CHANNEL_ID = "UCdj0goPwahmOx77QJvvj2SQ"
VIDEO = load_fixture("videos_normal")["items"][0]
CHANNEL = load_fixture("channels_normal")["items"][0]
CATEGORY = load_fixture("video_categories")["items"][0]
SECRETS = (VIDEO["snippet"]["title"], VIDEO["snippet"]["description"], API_KEY)


class FakeApi:
    def __init__(self):
        self.requests = []
        self.results = {
            ("videos", VIDEO_ID): load_fixture("videos_normal"),
            ("channels", CHANNEL_ID): load_fixture("channels_normal"),
            ("videoCategories", "23"): load_fixture("video_categories"),
        }

    def urlopen(self, url, timeout):
        parts = urlsplit(url)
        resource = parts.path.rsplit("/", 1)[-1]
        key = (resource, dict(parse_qsl(parts.query))["id"])
        self.requests.append(key)
        result = self.results.get(key, load_fixture("videos_empty"))
        if isinstance(result, Exception):
            raise result
        body = json.dumps(result).encode()
        return contextlib.nullcontext(SimpleNamespace(status=200, read=lambda: body))


@pytest.fixture(autouse=True)
def api(monkeypatch):
    youtube.video_category.cache_clear()
    fake = FakeApi()
    monkeypatch.setattr("urllib.request.urlopen", fake.urlopen)
    return fake


@pytest.fixture(autouse=True)
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def job(event="upsert", video_id=VIDEO_ID, **fields):
    message = {"schema_version": 1, "source": "pubsubhubbub"}
    return message | {"event": event, "video_id": video_id} | fields


def invoke(*bodies):
    records = [
        {"messageId": f"m{i}", "body": b if isinstance(b, str) else json.dumps(b)}
        for i, b in enumerate(bodies)
    ]
    return app.lambda_handler({"Records": records}, None)


def failed(*ids):
    return {"batchItemFailures": [{"itemIdentifier": i} for i in ids]}


def get(table, video_id=VIDEO_ID):
    return table.get_item(Key={"video_id": video_id}).get("Item")


def app_logs(logs):
    return [r for r in logs.records if r.module == "app"]


def quota_error():
    body = {"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}]}}
    url = f"https://example.com/videos?key={API_KEY}"
    return HTTPError(url, 403, "Forbidden", {}, io.BytesIO(json.dumps(body).encode()))


def test_upsert_stores_item(table):
    assert invoke(job(channel_id=CHANNEL_ID)) == failed()
    item = get(table)
    fetched_at = datetime.fromisoformat(item["fetched_at"])
    assert item == build_item(
        VIDEO,
        CHANNEL,
        CATEGORY,
        source="pubsubhubbub",
        fetched_at=fetched_at,
        retention_days=28,
    )
    assert item["expires_at"] == int(fetched_at.timestamp()) + 28 * 86400
    assert {"channel_subscriber_count", "category_name"} <= item.keys()


def test_upsert_without_items_deletes(table, api, logs):
    table.put_item(Item={"video_id": OTHER_VIDEO_ID})
    assert invoke(job(video_id=OTHER_VIDEO_ID, source="manual")) == failed()
    assert get(table, OTHER_VIDEO_ID) is None
    assert api.requests == [("videos", OTHER_VIDEO_ID)]
    assert [r.levelname for r in app_logs(logs)] == ["INFO"]


@pytest.mark.parametrize("existing", [True, False])
def test_delete_removes_item(table, api, existing):
    if existing:
        table.put_item(Item={"video_id": VIDEO_ID})
    assert invoke(job("delete", deleted_at="2026-09-25T08:00:00+00:00")) == failed()
    assert get(table) is None
    assert api.requests == []


def test_channel_mismatch_warns_and_stores(table, logs):
    other = "UC" + "x" * 22
    assert invoke(job(channel_id=other)) == failed()
    assert get(table)
    [warning] = [r for r in app_logs(logs) if r.levelname == "WARNING"]
    assert warning.api_channel_id == CHANNEL_ID


def test_mixed_batch_reports_only_failures(table, api, logs):
    api.results[("videos", OTHER_VIDEO_ID)] = quota_error()
    assert invoke(job(), "not json", job(video_id=OTHER_VIDEO_ID)) == failed("m1", "m2")
    assert get(table)
    invalid, error = [r for r in app_logs(logs) if r.levelname == "ERROR"]
    assert "not JSON" in invalid.getMessage()
    assert error.exc_info and "quotaExceeded" in str(error.exc_info[1])


@pytest.mark.parametrize(
    "break_secret", [lambda: set_api_key(" "), lambda: set_secret_string("not json")]
)
def test_config_error_fails_batch_until_fixed(table, break_secret):
    break_secret()
    with pytest.raises(ConfigError):
        invoke(job())
    set_api_key(API_KEY)
    assert invoke(job()) == failed()
    assert get(table)


def test_deletes_do_not_need_api_key(table):
    set_api_key(" ")
    assert invoke(job("delete")) == failed()


def test_channel_cached_per_invocation(api):
    invoke(job(), job())
    invoke(job())
    resources = [resource for resource, _ in api.requests]
    assert resources.count("videos") == 3
    assert resources.count("channels") == 2
    assert resources.count("videoCategories") == 1


def test_logs_carry_ids_and_no_secrets(api, logs):
    api.results[("videos", OTHER_VIDEO_ID)] = quota_error()
    invoke(job(channel_id="UC" + "x" * 22), "{}", job(video_id=OTHER_VIDEO_ID))
    records = app_logs(logs)
    assert len(records) == 4
    for r in records:
        assert r.message_id.startswith("m")
    parsed = [r for r in records if r.message_id != "m1"]
    assert all(r.video_id and r.event == "upsert" for r in parsed)
    for secret in SECRETS:
        assert secret not in logs.text
