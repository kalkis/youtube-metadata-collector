from datetime import UTC, datetime

from conftest import load_fixture

import store
from record import build_item

VIDEO_ID = "wCAM-K5E-Ec"
ITEM = build_item(
    load_fixture("videos_normal")["items"][0],
    load_fixture("channels_normal")["items"][0],
    load_fixture("video_categories")["items"][0],
    source="pubsubhubbub",
    fetched_at=datetime(2026, 9, 28, 12, tzinfo=UTC),
    retention_days=28,
)


def get(table, video_id=VIDEO_ID):
    return table.get_item(Key={"video_id": video_id}).get("Item")


def test_put_round_trips_item(table):
    store.put(ITEM)
    assert get(table) == ITEM


def test_put_overwrites_whole_item(table):
    store.put(ITEM)
    store.put({"video_id": VIDEO_ID, "source": "manual"})
    assert get(table) == {"video_id": VIDEO_ID, "source": "manual"}


def test_delete_removes_item(table):
    store.put(ITEM)
    store.delete(VIDEO_ID)
    assert get(table) is None


def test_delete_missing_item_is_a_no_op(table):
    store.delete("aaaaaaaaaaa")
    assert get(table, "aaaaaaaaaaa") is None
