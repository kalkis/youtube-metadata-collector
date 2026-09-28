import logging
from datetime import UTC, datetime

import record
import store
import youtube
from config import CONFIG, ConfigError
from messages import InvalidMessage, parse_job

logger = logging.getLogger()


def _upsert(job, log):
    video = youtube.video(job.video_id)
    if video is None:
        store.delete(job.video_id)
        logger.info("Video unavailable, deleted item", extra=log)
        return
    snippet = video.get("snippet", {})
    channel_id, category_id = snippet.get("channelId"), snippet.get("categoryId")
    if job.channel_id and channel_id != job.channel_id:
        logger.warning(
            "Channel differs from message", extra=log | {"api_channel_id": channel_id}
        )
    item = record.build_item(
        video,
        youtube.channel(channel_id) if channel_id else None,
        youtube.video_category(category_id) if category_id else None,
        source=job.source,
        fetched_at=datetime.now(UTC),
        retention_days=CONFIG.retention_days,
    )
    store.put(item)
    logger.info("Stored item", extra=log)


def _process(job, log):
    if job.event == "delete":
        store.delete(job.video_id)
        logger.info("Deleted item", extra=log)
    else:
        _upsert(job, log)


def lambda_handler(event, context):
    youtube.channel.cache_clear()
    failures = []
    for message in event["Records"]:
        log = {"message_id": message["messageId"]}
        try:
            job = parse_job(message["body"])
            log |= {"video_id": job.video_id, "event": job.event}
            _process(job, log)
        except InvalidMessage as e:
            logger.error("Invalid message: %s", e, extra=log)
        except ConfigError:
            raise
        except Exception:
            logger.exception("Processing failed", extra=log)
        else:
            continue
        failures.append({"itemIdentifier": log["message_id"]})
    return {"batchItemFailures": failures}
