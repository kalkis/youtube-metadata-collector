import json
import re
from dataclasses import dataclass

VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
CHANNEL_ID_PATTERN = re.compile(r"UC[A-Za-z0-9_-]{22}")
SOURCES = ("pubsubhubbub", "manual")
EVENTS = ("upsert", "delete")
OPTIONAL_STRINGS = ("title", "published", "updated", "deleted_at")
CURRENT_SCHEMA_VERSION = 1


class InvalidMessage(Exception):
    pass


@dataclass(frozen=True)
class Job:
    event: str
    video_id: str
    source: str
    channel_id: str | None = None


def parse_job(body: str) -> Job:
    try:
        message = json.loads(body)
    except ValueError as e:
        raise InvalidMessage(f"body is not JSON: {e}") from None
    if not isinstance(message, dict):
        raise InvalidMessage("body is not a JSON object")

    def one_of(name, allowed):
        value = message.get(name)
        if not (isinstance(value, str) and value in allowed):
            raise InvalidMessage(f"{name} must be one of {', '.join(allowed)}")
        return value

    def matching(name, pattern):
        value = message.get(name)
        if not (isinstance(value, str) and pattern.fullmatch(value)):
            raise InvalidMessage(f"{name} is not a valid {name.replace('_', ' ')}")
        return value

    version = message.get("schema_version")
    if not (type(version) is int and version == CURRENT_SCHEMA_VERSION):
        raise InvalidMessage(f"schema_version must be {CURRENT_SCHEMA_VERSION}")
    source = one_of("source", SOURCES)
    event = one_of("event", EVENTS)
    video_id = matching("video_id", VIDEO_ID_PATTERN)
    channel_id = message.get("channel_id")
    if channel_id is not None:
        matching("channel_id", CHANNEL_ID_PATTERN)
    for name in OPTIONAL_STRINGS:
        if not isinstance(message.get(name, ""), str | None):
            raise InvalidMessage(f"{name} must be a string")
    return Job(event, video_id, source, channel_id)
