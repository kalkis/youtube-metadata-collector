import re
from datetime import UTC, datetime

SCHEMA_VERSION = 1
SECONDS_PER_DAY = 86400
DURATION_PATTERN = re.compile(
    r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?"
)
DURATION_UNITS = (7 * SECONDS_PER_DAY, SECONDS_PER_DAY, 3600, 60, 1)
EMPTY = (None, "", [], {})


def duration_seconds(duration) -> int | None:
    match = isinstance(duration, str) and DURATION_PATTERN.fullmatch(duration)
    if not match or not any(match.groups()):
        return None
    return sum(int(n or 0) * unit for n, unit in zip(match.groups(), DURATION_UNITS))


def _count(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _prune(value):
    if isinstance(value, dict):
        pairs = ((k, _prune(v)) for k, v in value.items())
        return {k: v for k, v in pairs if v not in EMPTY}
    if isinstance(value, list):
        return [v for v in map(_prune, value) if v not in EMPTY]
    return value


def build_item(
    video: dict,
    channel: dict | None,
    category: dict | None,
    *,
    source: str,
    fetched_at: datetime,
    retention_days: int,
) -> dict:
    snippet = video.get("snippet", {})
    details = video.get("contentDetails", {})
    status = video.get("status", {})
    stats = video.get("statistics", {})
    live = video.get("liveStreamingDetails", {})
    channel_stats = (channel or {}).get("statistics", {})
    fetched_at = fetched_at.astimezone(UTC).replace(microsecond=0)
    return _prune(
        {
            "video_id": video["id"],
            "title": snippet.get("title"),
            "description": snippet.get("description"),
            "tags": snippet.get("tags"),
            "published_at": snippet.get("publishedAt"),
            "channel_id": snippet.get("channelId"),
            "channel_title": snippet.get("channelTitle"),
            "duration": details.get("duration"),
            "duration_seconds": duration_seconds(details.get("duration")),
            "live_broadcast_content": snippet.get("liveBroadcastContent"),
            "category_id": snippet.get("categoryId"),
            "category_name": (category or {}).get("snippet", {}).get("title"),
            "statistics": {
                "view_count": _count(stats.get("viewCount")),
                "like_count": _count(stats.get("likeCount")),
                "comment_count": _count(stats.get("commentCount")),
            },
            "flags": {
                "license": status.get("license"),
                "embeddable": status.get("embeddable"),
                "made_for_kids": status.get("madeForKids"),
                "contains_synthetic_media": status.get("containsSyntheticMedia"),
                "licensed_content": details.get("licensedContent"),
                "region_restriction": details.get("regionRestriction"),
                "content_rating": details.get("contentRating"),
                "has_paid_product_placement": video.get(
                    "paidProductPlacementDetails", {}
                ).get("hasPaidProductPlacement"),
            },
            "topic_categories": video.get("topicDetails", {}).get("topicCategories"),
            "live": {
                "scheduled_start_time": live.get("scheduledStartTime"),
                "scheduled_end_time": live.get("scheduledEndTime"),
                "actual_start_time": live.get("actualStartTime"),
                "actual_end_time": live.get("actualEndTime"),
            },
            "channel_subscriber_count": None
            if channel_stats.get("hiddenSubscriberCount")
            else _count(channel_stats.get("subscriberCount")),
            "fetched_at": fetched_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": int(fetched_at.timestamp())
            + retention_days * SECONDS_PER_DAY,
            "source": source,
            "schema_version": SCHEMA_VERSION,
        }
    )
