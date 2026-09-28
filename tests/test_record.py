from datetime import UTC, datetime, timedelta, timezone

import pytest
from boto3.dynamodb.types import TypeSerializer
from conftest import load_fixture

from record import build_item, duration_seconds


def first_item(name):
    return load_fixture(name)["items"][0]


VIDEO = first_item("videos_normal")
CHANNEL = first_item("channels_normal")
CATEGORY = first_item("video_categories")
VIDEO_FIXTURES = (
    "videos_normal",
    "videos_upcoming_premiere",
    "videos_live_completed",
    "videos_hidden_likes",
    "videos_comments_disabled",
)
FETCHED_AT = datetime(2026, 9, 28, 12, 0, 0, 750000, tzinfo=UTC)
FETCHED_EPOCH = 1790596800


def build(video=VIDEO, channel=CHANNEL, category=CATEGORY, **kwargs):
    options = {"source": "pubsubhubbub", "fetched_at": FETCHED_AT, "retention_days": 28}
    return build_item(video, channel, category, **options | kwargs)


def build_fixture(name, **kwargs):
    return build(first_item(name), **kwargs)


def test_normal_video():
    snippet = VIDEO["snippet"]
    assert build() == {
        "video_id": "wCAM-K5E-Ec",
        "title": snippet["title"],
        "description": snippet["description"],
        "tags": snippet["tags"],
        "published_at": "2026-09-22T00:00:08Z",
        "channel_id": "UCdj0goPwahmOx77QJvvj2SQ",
        "channel_title": snippet["channelTitle"],
        "duration": "PT1M27S",
        "duration_seconds": 87,
        "live_broadcast_content": "none",
        "category_id": "23",
        "category_name": "Comedy",
        "statistics": {
            "view_count": 447446,
            "like_count": 16740,
            "comment_count": 1481,
        },
        "flags": {
            "license": "youtube",
            "embeddable": True,
            "made_for_kids": False,
            "licensed_content": True,
            "has_paid_product_placement": False,
        },
        "channel_subscriber_count": 1030000,
        "fetched_at": "2026-09-28T12:00:00Z",
        "expires_at": FETCHED_EPOCH + 28 * 86400,
        "source": "pubsubhubbub",
        "schema_version": 1,
    }


@pytest.mark.parametrize("name", VIDEO_FIXTURES)
def test_item_is_writable_to_dynamodb(name):
    TypeSerializer().serialize(build_fixture(name))


@pytest.mark.parametrize(
    "fetched_at, retention_days, expected",
    [
        (FETCHED_AT, 28, FETCHED_EPOCH + 28 * 86400),
        (FETCHED_AT, 1, FETCHED_EPOCH + 86400),
        (
            FETCHED_AT.astimezone(timezone(timedelta(hours=2))),
            30,
            FETCHED_EPOCH + 30 * 86400,
        ),
    ],
)
def test_fetched_at_and_expires_at(fetched_at, retention_days, expected):
    item = build(fetched_at=fetched_at, retention_days=retention_days)
    assert item["fetched_at"] == "2026-09-28T12:00:00Z"
    assert item["expires_at"] == expected


def test_manual_source():
    assert build(source="manual")["source"] == "manual"


def test_upcoming_premiere():
    item = build_fixture("videos_upcoming_premiere")
    assert item["live_broadcast_content"] == "upcoming"
    assert item["duration"] == "P0D"
    assert item["duration_seconds"] == 0
    assert item["statistics"] == {"view_count": 0, "like_count": 8, "comment_count": 0}
    assert item["live"] == {"scheduled_start_time": "2026-09-30T23:29:51Z"}
    assert "tags" not in item


def test_finished_live_stream():
    item = build_fixture("videos_live_completed")
    assert item["live_broadcast_content"] == "none"
    assert item["duration_seconds"] == 11810
    assert item["flags"]["region_restriction"] == {"blocked": ["RU"]}
    assert item["live"] == {
        "scheduled_start_time": "2026-09-26T03:30:07Z",
        "actual_start_time": "2026-09-26T03:16:12Z",
        "actual_end_time": "2026-09-26T06:32:46Z",
    }


def test_hidden_likes():
    item = build_fixture("videos_hidden_likes")
    assert item["statistics"] == {"view_count": 292565, "comment_count": 34}
    assert "description" not in item
    assert "tags" not in item


def test_comments_disabled():
    item = build_fixture("videos_comments_disabled")
    assert item["statistics"] == {"view_count": 418100840, "like_count": 871263}
    assert item["flags"]["made_for_kids"] is True


def test_hidden_subscriber_count():
    channel = first_item("channels_hidden_subscribers")
    assert "channel_subscriber_count" not in build(channel=channel)


def test_missing_channel_and_category():
    item = build(channel=None, category=None)
    assert "channel_subscriber_count" not in item
    assert "category_name" not in item
    assert item["category_id"] == "23"


def test_empty_values_are_left_out():
    video = VIDEO | {
        "snippet": VIDEO["snippet"] | {"tags": [], "channelTitle": None},
        "contentDetails": {"duration": "PT10S", "regionRestriction": {"allowed": []}},
        "statistics": {},
        "topicDetails": {"topicCategories": []},
        "liveStreamingDetails": {},
        "paidProductPlacementDetails": {},
    }
    item = build(video, channel={}, category={})
    for name in ("tags", "channel_title", "statistics", "topic_categories", "live"):
        assert name not in item
    assert item["flags"] == {
        "license": "youtube",
        "embeddable": True,
        "made_for_kids": False,
    }
    assert "category_name" not in item
    assert "channel_subscriber_count" not in item


def test_values_missing_from_recordings_are_kept():
    video = VIDEO | {
        "contentDetails": VIDEO["contentDetails"]
        | {"contentRating": {"ytRating": "ytAgeRestricted"}},
        "status": VIDEO["status"] | {"containsSyntheticMedia": True},
    }
    flags = build(video)["flags"]
    assert flags["content_rating"] == {"ytRating": "ytAgeRestricted"}
    assert flags["contains_synthetic_media"] is True


def test_unparseable_counts_are_left_out():
    item = build(VIDEO | {"statistics": {"viewCount": "many", "likeCount": None}})
    assert "statistics" not in item


@pytest.mark.parametrize(
    "duration, seconds",
    [
        ("PT4M13S", 253),
        ("PT45S", 45),
        ("PT1H", 3600),
        ("PT1H0M5S", 3605),
        ("P1DT2H3M4S", 93784),
        ("P1W", 604800),
        ("P0D", 0),
        ("PT0S", 0),
        ("P", None),
        ("PT", None),
        ("", None),
        ("4M13S", None),
        ("PT1.5S", None),
        ("PT4M13S ", None),
        (None, None),
        (253, None),
    ],
)
def test_duration_seconds(duration, seconds):
    assert duration_seconds(duration) == seconds


def test_unparseable_duration_keeps_the_raw_value():
    item = build(VIDEO | {"contentDetails": {"duration": "P1Y"}})
    assert item["duration"] == "P1Y"
    assert "duration_seconds" not in item
