# instagram_poster

Publish AI-generated images, Reels and carousels to Instagram from the command
line or on a schedule, using Meta's official **Instagram API with Instagram Login**.
Every post gets Instagram's **AI info** label by default (`is_ai_generated`).

```
python -m igpost check                                   # verify token + quota
python -m igpost post reel media/clip.mp4 -c "caption"   # publish now
python -m igpost run-queue                               # publish whatever is due
python -m igpost refresh-token                           # extend the token ~60 days
```

Add `--dry-run` to `post` or `run-queue` to validate everything without uploading or publishing.

## How it works

1. A local file is uploaded to your public bucket (Meta only fetches media from a URL).
2. `POST /{ig-user-id}/media` creates a container (with the AI label).
3. For video, the container is polled until `status_code` is `FINISHED`.
4. `POST /{ig-user-id}/media_publish` publishes it, and the permalink is printed.

## One-time setup

### 1. Instagram account
Switch the account to a **professional account** (Creator or Business) in the
Instagram app: Settings → Account type and tools.

### 2. Meta app and token
1. Go to <https://developers.facebook.com/apps>, create an app (use case: *Manage messaging & content on Instagram*).
2. In the app dashboard open **Instagram → API setup with Instagram login**.
3. Under **Generate access tokens**, add your Instagram account and generate a token.
   It needs `instagram_business_basic` and `instagram_business_content_publish`.
4. Copy the token and the account ID into `.env` (`cp .env.example .env`).

While the app is in development mode it can post to accounts that have a role on
the app (your own), so you don't need App Review just to post to your account.
The token lasts about 60 days. Run `python -m igpost refresh-token` before it
expires; it saves the new token to `.env`.

### 3. Media hosting
Create a bucket with public read access. **Cloudflare R2** is a good fit: free tier,
no egress fees, and a public `r2.dev` URL. Fill in the `S3_*` values and
`PUBLIC_BASE_URL` in `.env`. Any S3-compatible service works. If your media is
already at public URLs, you can skip this and pass the URLs directly.

### 4. Python
```
cd instagram_poster
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m igpost check
python -m pytest
```

## The queue

Put one JSON file per post in `queue/` (see `examples/`). Media paths are relative to the JSON file.

```json
{
  "type": "reel",
  "media": ["../media/beach_morning.mp4"],
  "caption": "Slow mornings by the pool ☀️ #beachhotel",
  "publish_after": "2026-10-20T18:00:00-05:00",
  "ai_generated": true
}
```

`run-queue` publishes every post whose `publish_after` has passed (no time = now),
oldest first, at most `--max` per run (default 5). Published posts move to
`queue/published/` with their media ID and permalink, and failures move to
`queue/failed/` with the error. It stops early if the 24-hour publishing quota is used up.

To run it automatically, schedule `python -m igpost run-queue` every 15–30 minutes
with cron or a systemd timer. The VeraSynth accounts use systemd timers on the
Raspberry Pi; see `vera_synth/scheduler/install.sh`.

## Limits and media rules

- **Images:** JPEG only (`.jpg`). Convert PNG/WebP first.
- **Reels:** `.mp4` or `.mov`, vertical 9:16 recommended (e.g. 1080×1920, H.264 + AAC).
- **Carousels:** 2–10 items. The AI label goes on the carousel itself.
- **Captions:** up to 2,200 characters and 30 hashtags.
- **Quota:** Meta's docs give 100 API-published posts per 24 hours (one section says 50).
  `check` shows your actual quota.
- Containers expire if not published within 24 hours.

## Files

```
igpost/client.py    Graph API calls: containers, status polling, publish, token refresh
igpost/hosting.py   local file → public URL (S3/R2), media type checks
igpost/posts.py     post definition, validation, file-based queue
igpost/cli.py       command line
tests/              unit tests with a fake HTTP session (no network needed)
```

Reference: [Instagram content publishing docs](https://developers.facebook.com/docs/instagram-platform/content-publishing)
