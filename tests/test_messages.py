import json
from dataclasses import FrozenInstanceError

import pytest

from messages import InvalidMessage, Job, parse_job

VIDEO_ID = "dQw4w9WgXcQ"
CHANNEL_ID = "UCPdaxSov0mgwh77JvjQO2jQ"
UPSERT = {
    "schema_version": 1,
    "source": "pubsubhubbub",
    "event": "upsert",
    "video_id": VIDEO_ID,
    "channel_id": CHANNEL_ID,
    "title": "Video title",
    "published": "2026-09-24T10:00:00+00:00",
    "updated": "2026-09-24T10:00:05+00:00",
}
MISSING = object()


def body(**overrides):
    message = UPSERT | overrides
    return json.dumps({k: v for k, v in message.items() if v is not MISSING})


def test_callback_upsert():
    assert parse_job(body()) == Job("upsert", VIDEO_ID, "pubsubhubbub", CHANNEL_ID)


def test_manual_upsert_without_channel():
    message = {"schema_version": 1, "source": "manual", "event": "upsert"}
    job = parse_job(json.dumps(message | {"video_id": VIDEO_ID}))
    assert job == Job("upsert", VIDEO_ID, "manual")
    assert job.channel_id is None


def test_delete():
    job = parse_job(
        body(
            event="delete",
            title=MISSING,
            published=MISSING,
            updated=MISSING,
            deleted_at="2026-09-25T08:00:00+00:00",
        )
    )
    assert job == Job("delete", VIDEO_ID, "pubsubhubbub", CHANNEL_ID)


def test_null_optional_fields_are_absent():
    assert parse_job(body(channel_id=None, title=None)).channel_id is None


def test_unknown_fields_are_ignored():
    assert parse_job(body(extra={"a": 1})).video_id == VIDEO_ID


def test_job_is_frozen():
    with pytest.raises(FrozenInstanceError):
        parse_job(body()).video_id = "x"


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "{",
        "[]",
        '"x"',
        body(schema_version=MISSING),
        body(schema_version=2),
        body(schema_version="1"),
        body(schema_version=True),
        body(schema_version=1.0),
        body(source=MISSING),
        body(source="sns"),
        body(source=["manual"]),
        body(event=MISSING),
        body(event="update"),
        body(video_id=MISSING),
        body(video_id=VIDEO_ID[:10]),
        body(video_id=VIDEO_ID + "x"),
        body(video_id="dQw4w9WgXc!"),
        body(video_id=12345678901),
        body(channel_id="UX" + CHANNEL_ID[2:]),
        body(channel_id=CHANNEL_ID[:-1]),
        body(channel_id=1),
        body(title=1),
    ],
)
def test_invalid_message(raw):
    with pytest.raises(InvalidMessage):
        parse_job(raw)


def test_reason_does_not_repeat_values():
    with pytest.raises(InvalidMessage) as error:
        parse_job(body(video_id="secret-ish-id", title="A distinctive title"))
    assert "secret-ish-id" not in str(error.value)
    assert "distinctive" not in str(error.value)
