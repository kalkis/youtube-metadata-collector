# youtube-metadata-collector

AWS Lambda (container image) that consumes video jobs from an SQS queue, fetches each video's metadata from the [YouTube Data API v3](https://developers.google.com/youtube/v3) and stores it in DynamoDB with a TTL. Deleted, private and missing videos are removed from the table.

```
youtube-notification-callback ──▶ SNS ──▶ SQS ──▶ this Lambda ──HTTPS──▶ YouTube Data API v3
          aws sqs send-message (manual) ──▲  │                ──▶ DynamoDB <prefix>-video-metadata (TTL on expires_at)
                                             └──▶ DLQ (after max_receive_count attempts)
```

The producer is [`youtube-notification-callback`](https://github.com/kalkis/youtube-notification-callback), and the infrastructure (queue, DLQ, table, secret lookup, alarms) is in [`tf-youtube-cloud-backup`](https://github.com/kalkis/tf-youtube-cloud-backup).

Scope is metadata only. The collector never downloads videos, thumbnails or captions, and never scrapes YouTube.

## Usage

Replace the placeholders with the Terraform outputs `queue_url` and `table_name`.

```sh
# Manual job: fetch and store a video (use "event":"delete" to remove it)
aws sqs send-message --queue-url <queue_url> \
  --message-body '{"schema_version":1,"source":"manual","event":"upsert","video_id":"<id>"}'

# A channel's live items, newest first
aws dynamodb query --table-name <table_name> --index-name by_channel \
  --key-condition-expression 'channel_id = :c' --filter-expression 'expires_at > :now' \
  --expression-attribute-values '{":c":{"S":"<channel_id>"},":now":{"N":"'$(date +%s)'"}}' \
  --no-scan-index-forward
```

DynamoDB deletes expired items up to a few days late, so always filter on `expires_at > :now`. To see recent items across all channels, run a `scan` with the same filter.

## Configuration

Set by Terraform as environment variables. They are validated when the module loads, and the handler fails immediately if anything is missing or invalid.

| Variable               | Required | Default                                 | Description                                                                         |
| ---------------------- | -------- | --------------------------------------- | ----------------------------------------------------------------------------------- |
| `TABLE_NAME`           | yes      |                                         | DynamoDB table                                                                      |
| `API_KEY_SECRET_ID`    | yes      |                                         | Secrets Manager secret name or ARN. A key-value secret whose `API_KEY` field holds the YouTube API key. |
| `RETENTION_DAYS`       | no       | `28`                                    | Positive integer. `expires_at = fetched_at + RETENTION_DAYS × 86400`.               |
| `YOUTUBE_API_BASE_URL` | no       | `https://www.googleapis.com/youtube/v3` | Must be `https`. Overridable for tests.                                             |
| `HTTP_TIMEOUT_SECONDS` | no       | `10`                                    | Per API request                                                                     |
| `LOG_LEVEL`            | no       | `INFO`                                  | Python logging level                                                                |

The API key is read on first use and cached for the container's life. A missing or blank key is not cached, so fixing the secret takes effect without a redeploy. A rotated key reaches warm containers only after their next cold start; any configuration change (`aws lambda update-function-configuration`) forces one.

The function's role needs `sqs:ReceiveMessage`, `DeleteMessage`, `ChangeMessageVisibility` and `GetQueueAttributes` on the queue, `dynamodb:PutItem` and `DeleteItem` on the table, and `secretsmanager:GetSecretValue` on the secret.

## Development

Requires [uv](https://docs.astral.sh/uv/). Python 3.13 comes from `.python-version`.

```sh
uv sync --locked
uv run pytest
uv run ruff check && uv run ruff format --check
docker build --platform linux/amd64 -t youtube-metadata-collector .
```

There are no runtime dependencies: HTTP uses `urllib`, and boto3 is provided by the Lambda runtime (it is only in the dev group, with `moto` for tests). The API fixtures in `tests/fixtures` are described in their own [README](tests/fixtures/README.md).

## Behaviour

The event source mapping uses `ReportBatchItemFailures`, and each record is handled on its own:

| Message                                               | Result                                                                                 |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Invalid (fails the contract below)                    | Logged at `ERROR` and reported as failed, so it reaches the DLQ after repeated attempts |
| `delete`                                              | `DeleteItem` (idempotent)                                                              |
| `upsert`, video returned by `videos.list`             | `PutItem` of the whole item, which resets `expires_at`                                 |
| `upsert`, `videos.list` returns no items              | `DeleteItem`, counted as a success (the video is private, deleted or never existed)    |
| `upsert` where the API's channel differs from the message | Stored as normal, with a warning                                                   |
| Any other error (API, network, DynamoDB)              | Traceback logged, record reported as failed and retried after the visibility timeout   |
| API key secret missing, unreadable or blank           | The whole batch fails, which fires the `Errors` alarm                                  |

Each upsert costs at most 3 quota units (`videos.list`, `channels.list` cached per invocation, `videoCategories.list` cached for the container's life), against the default 10,000 per day. API errors are logged with the method, HTTP status and reason (for example `quotaExceeded`).

Logs are JSON lines (the function uses `log_format = "JSON"`) carrying `message_id`, `video_id` and `event`. They never contain titles, descriptions, request URLs or the API key.

## Message contract

This contract is shared with `youtube-notification-callback`. Every message is a UTF-8 JSON object, delivered to SQS with raw message delivery, so hub notifications and manual jobs look the same.

```json
{"schema_version": 1, "source": "pubsubhubbub", "event": "upsert", "video_id": "dQw4w9WgXcQ",
 "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw", "title": "Video title",
 "published": "2026-09-24T10:00:00+00:00", "updated": "2026-09-24T10:00:05+00:00"}

{"schema_version": 1, "source": "pubsubhubbub", "event": "delete", "video_id": "dQw4w9WgXcQ",
 "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw", "deleted_at": "2026-09-25T08:00:00+00:00"}
```

| Field                                         | Required | Validation                                                                   |
| --------------------------------------------- | -------- | ---------------------------------------------------------------------------- |
| `schema_version`                              | yes      | Integer, must equal `1`                                                      |
| `source`                                      | yes      | `"pubsubhubbub"` or `"manual"`                                               |
| `event`                                       | yes      | `"upsert"` (fetch and store) or `"delete"` (remove the item)                 |
| `video_id`                                    | yes      | `^[A-Za-z0-9_-]{11}$`                                                        |
| `channel_id`                                  | no       | `^UC[A-Za-z0-9_-]{22}$`                                                      |
| `title`, `published`, `updated`, `deleted_at` | no       | Strings, for debugging only. The collector stores only what the API returns. |

API requests are built only from the validated `video_id`; no URL from a message is ever followed.

## Stored item

One item per video, keyed on `video_id`. GSI `by_channel` (`channel_id` / `published_at`, projection `ALL`) lists a channel's videos. Absent values, empty lists and empty maps are left out.

| Group          | Attributes                                                                                                                                             |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Basics         | `title`, `description`, `tags`, `published_at`, `channel_id`, `channel_title`, `duration` (e.g. `PT4M13S`), `duration_seconds`, `live_broadcast_content` |
| Category       | `category_id`, `category_name`                                                                                                                         |
| Statistics     | `statistics`: `view_count`, `like_count`, `comment_count` (hidden or disabled counts are left out)                                                     |
| Official flags | `flags`: `license`, `embeddable`, `made_for_kids`, `contains_synthetic_media`, `licensed_content`, `region_restriction`, `content_rating`, `has_paid_product_placement` |
| Topics         | `topic_categories` (Wikipedia URLs)                                                                                                                    |
| Live           | `live`: `scheduled_start_time`, `scheduled_end_time`, `actual_start_time`, `actual_end_time` (streams and premieres only)                               |
| Channel        | `channel_subscriber_count` (rounded snapshot; left out if hidden)                                                                                      |
| Housekeeping   | `fetched_at` (ISO 8601 UTC), `expires_at` (TTL, epoch seconds), `source`, `schema_version`                                                             |

## Data handling and policies

The [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies) allow stored API data to be kept for at most 30 days before it is deleted or refreshed (§III.E.4.d), and require reasonable efforts to keep it current (§III.E.4.e). Downloading audiovisual content is not allowed (§III.E.1). Use of the API is also subject to the [YouTube API Services Terms of Service](https://developers.google.com/youtube/terms/api-services-terms-of-service) and the [Google Privacy Policy](https://policies.google.com/privacy).

- Each upsert re-fetches the video and resets the TTL, which is the refresh the policy allows.
- The default retention is 28 days rather than 30, leaving a margin for TTL deletion lag. Keep `RETENTION_DAYS` at or below that if the policy cap changes.
- Delete notifications and empty `videos.list` responses both remove the item.
- The table has no point-in-time recovery or backups.
- The queue holds messages (IDs and feed titles) for up to 4 days, the DLQ for 14 days, and CloudWatch Logs (IDs, events and error reasons only) for `log_retention_days` (14). If retention is ever set below 14 days, lower those to match.

## License

[MIT](LICENSE)
