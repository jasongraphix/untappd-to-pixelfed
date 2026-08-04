# untappd-to-pixelfed

Cross-posts Untappd checkins to Pixelfed automatically. Runs on a GitHub Actions schedule.

## Why it's built this way

**Untappd side:** Untappd's public API has been closed to new developer applications for years, with no reopening in sight. Instead, this uses the RSS feed available under Untappd account settings (Settings → "View your RSS feed") — no API key required, just an unguessable feed URL.

**Pixelfed side:** Pixelfed has a convenience endpoint (`/api/v1.1/status/create`) built for single-request posting, but it's not part of the standard Mastodon-compatible API surface and is more prone to silently breaking. This uses the same two endpoints real Pixelfed/Mastodon clients use — `POST /api/v1/media` to upload, then `POST /api/v1/statuses` to publish — which is slower (two calls) but far more stable long-term.

## How it works

1. A GitHub Actions workflow runs on a cron schedule (every 20 min) and on manual trigger.
2. The script fetches the Untappd RSS feed and compares entries against `state.json`, which tracks which checkin IDs have already been posted.
3. For each new checkin: pulls the full-resolution photo (unwrapping Untappd's thumbnail-cropper URL to get the original file, not the 200×200 crop), uploads it to Pixelfed, then creates a status with a cleaned-up caption and a link back to the Untappd checkin.
4. Updates `state.json` and commits it back to the repo, so the next run knows what's already posted.

## Setup

1. Fork or clone this repo.
2. In repo **Settings → Secrets and variables → Actions**, add:
   | Secret | Value |
   |---|---|
   | `UNTAPPD_RSS_URL` | Your RSS feed URL from Untappd account settings (includes a private `key` param — treat it like a password) |
   | `PIXELFED_INSTANCE` | Your Pixelfed instance, e.g. `https://pixelfed.social` |
   | `PIXELFED_TOKEN` | A personal access token from Pixelfed Settings → Applications → Develop, with `write` scope |
3. Optionally set `PIXELFED_VISIBILITY` (defaults to `public`; other valid values are `unlisted` and `private`).
4. Trigger the workflow manually once (Actions tab → **Untappd to Pixelfed** → Run workflow) to confirm it posts correctly before letting the cron take over.

## Re-seeding state (avoiding a backfill flood)

If you ever need to reset which checkins have been posted — e.g. first-time setup, or recovering from a bad `state.json` — edit the `seen_ids` array directly. Entries must match the full checkin URL format used as the RSS `<guid>`:

```json
{
  "seen_ids": [
    "https://untappd.com/user/USERNAME/checkin/1234567890"
  ]
}
```

Any checkin ID *not* in that list will be treated as new and posted on the next run. To do a full backfill, seed the list with everything except the oldest entry, verify that first post looks right, then clear the list entirely (or remove ids one at a time) to release the rest.

## Known limitations

- Checkins with no photo in the RSS feed are skipped (Pixelfed requires an image per post) and marked seen so they're not retried indefinitely.
- Caption parsing assumes Untappd's standard title format (`"... is drinking a[n] {beer} by {brewery} at {location}"`). Beer or brewery names that happen to contain literal " by " or " at " will parse incorrectly; the script falls back to posting the raw title rather than failing.
- No rate-limit backoff — if a large batch (e.g. a backfill) triggers a 429 from Pixelfed partway through, only already-succeeded posts are marked seen. The remaining entries will simply be picked up on the next run.
- Image quality is capped by whatever Untappd stores after their own upload compression — this script always pulls the highest-resolution version Untappd has, but that may still be smaller/more compressed than the original camera photo.
