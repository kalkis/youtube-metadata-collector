# API response fixtures

Response bodies from the YouTube Data API v3, recorded on 2026-09-28 with the parameters the collector uses, unless marked hand-built.

The recorded responses are anonymised so that no YouTube API data is kept past the 30-day limit in the YouTube API Services Developer Policies (§III.E.4). None of the IDs belongs to a real video or channel:

- Titles, descriptions, tags and channel titles (including `snippet.localized`) are placeholders.
- Video and channel IDs and etags are permutations of the originals. Video and channel IDs keep their last character, which YouTube restricts; `activeLiveChatId` is re-encoded with the new IDs.
- Non-zero counts are changed by up to 15% (the subscriber count stays rounded to three significant figures), and timestamps are shifted by a few seconds.

| File                               | Call                   | Case                                                                           |
| ---------------------------------- | ---------------------- | ------------------------------------------------------------------------------ |
| `videos_normal.json`               | `videos.list`          | Normal upload; no `topicDetails`, empty `contentRating`                        |
| `videos_upcoming_premiere.json`    | `videos.list`          | `upcoming`, duration `P0D`, `scheduledStartTime` only                          |
| `videos_live_completed.json`       | `videos.list`          | Finished stream with scheduled and actual times, `regionRestriction.blocked`   |
| `videos_hidden_likes.json`         | `videos.list`          | No `likeCount`                                                                 |
| `videos_comments_disabled.json`    | `videos.list`          | Made for kids, no `commentCount`                                               |
| `videos_empty.json`                | `videos.list`          | Unknown ID: empty `items`                                                      |
| `channels_normal.json`             | `channels.list`        | Channel of `videos_normal.json`                                                |
| `channels_hidden_subscribers.json` | `channels.list`        | **Hand-built**: `hiddenSubscriberCount` true, `subscriberCount` left out       |
| `video_categories.json`            | `videoCategories.list` | Category of `videos_normal.json`                                               |
| `error_key_invalid.json`           | any                    | HTTP 400, reason `badRequest`                                                  |
| `error_quota_exceeded.json`        | any                    | **Hand-built** from the documented format: HTTP 403, reason `quotaExceeded`    |
