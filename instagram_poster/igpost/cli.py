"""Command line entry point:  python -m igpost <command>

  check          verify the token, show the account and today's publishing quota
  post           publish one image, reel or carousel right now
  run-queue      publish every queued post whose publish_after time has passed
  refresh-token  extend the access token another ~60 days (and save it to .env)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .client import InstagramAPIError, InstagramClient
from .config import DEFAULT_ENV_FILE, PROJECT_ROOT, Settings, update_env_value
from .hosting import make_host, resolve_media
from .posts import Post, load_queue, mark_failed, mark_published

DEFAULT_QUEUE = PROJECT_ROOT / "queue"


def build_client(settings: Settings) -> InstagramClient:
    settings.require_api()
    return InstagramClient(settings.access_token, settings.ig_user_id,
                           api_version=settings.api_version, host=settings.host)


def publish_post(post: Post, client: InstagramClient | None, host, dry_run: bool = False) -> dict:
    media = [resolve_media(ref, host, post.base_dir) for ref in post.media]
    label = "with AI label" if post.ai_generated else "without AI label"
    if dry_run:
        print(f"  [dry run] would publish {post.type} {label}:")
        for url, is_video in media:
            print(f"    {'video' if is_video else 'image'}: {url}")
        print(f"    caption: {post.caption[:80]!r}{'…' if len(post.caption) > 80 else ''}")
        return {"dry_run": True}
    assert client is not None
    if post.type == "image":
        return client.post_image(media[0][0], post.caption, post.ai_generated)
    if post.type == "reel":
        return client.post_reel(media[0][0], post.caption, post.ai_generated,
                                share_to_feed=post.share_to_feed)
    return client.post_carousel(media, post.caption, post.ai_generated)


def quota_left(client: InstagramClient) -> int | None:
    try:
        limit = client.publishing_limit()
    except InstagramAPIError:
        return None
    total = (limit.get("config") or {}).get("quota_total")
    used = limit.get("quota_usage", 0)
    return None if total is None else total - used


# ----------------------------------------------------------------- commands
def cmd_check(args, settings: Settings) -> int:
    client = build_client(settings)
    me = client.me()
    print(f"Account: @{me.get('username')}  ({me.get('account_type')}, id {me.get('user_id')})")
    if str(me.get("user_id")) != str(settings.ig_user_id):
        print(f"  note: IG_USER_ID in .env is {settings.ig_user_id}; the token belongs to {me.get('user_id')}")
    limit = client.publishing_limit()
    cfg = limit.get("config") or {}
    print(f"Posts published via API in the last 24h: {limit.get('quota_usage', 0)} of {cfg.get('quota_total', '?')}")
    print(f"Media hosting: {'configured (' + settings.public_base_url + ')' if settings.hosting_configured else 'not configured — only public URLs will work'}")
    return 0


def cmd_post(args, settings: Settings) -> int:
    post = Post.from_dict({
        "type": args.type, "media": args.media, "caption": args.caption or "",
        "ai_generated": not args.no_ai_label, "share_to_feed": not args.reels_tab_only,
    })
    client = None if args.dry_run else build_client(settings)
    result = publish_post(post, client, make_host(settings, args.dry_run), args.dry_run)
    if not args.dry_run:
        print(f"Published: {result.get('permalink') or result['media_id']}")
    return 0


def cmd_run_queue(args, settings: Settings) -> int:
    queue_dir = Path(args.queue_dir).resolve()
    posts, errors = load_queue(queue_dir)
    for path, err in errors:
        print(f"Skipping invalid file {path.name}: {err}", file=sys.stderr)
    due = [p for p in posts if p.is_due()]
    print(f"{len(posts)} queued, {len(due)} due" + (f", {len(errors)} invalid" if errors else ""))
    if not due:
        return 1 if errors else 0

    client = None if args.dry_run else build_client(settings)
    host = make_host(settings, args.dry_run)
    failures = 0
    for post in due[: args.max]:
        print(f"→ {post.source.name}")
        if client is not None:
            left = quota_left(client)
            if left is not None and left <= 0:
                print("Publishing quota for the last 24h is used up; stopping.")
                break
        try:
            result = publish_post(post, client, host, args.dry_run)
        except Exception as exc:
            failures += 1
            print(f"  failed: {exc}", file=sys.stderr)
            if not args.dry_run:
                print(f"  moved to {mark_failed(post, str(exc)).relative_to(queue_dir)}")
            continue
        if not args.dry_run:
            dest = mark_published(post, result)
            print(f"  published: {result.get('permalink') or result['media_id']}  ({dest.relative_to(queue_dir)})")
    return 1 if failures or errors else 0


def cmd_refresh_token(args, settings: Settings) -> int:
    client = build_client(settings)
    body = client.refresh_token()
    token, days = body["access_token"], int(body.get("expires_in", 0)) // 86400
    if args.no_save:
        print(json.dumps(body, indent=2))
    else:
        update_env_value("IG_ACCESS_TOKEN", token, Path(args.env_file))
        print(f"Token refreshed and saved to {args.env_file}; valid for about {days} days.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="igpost", description="Publish AI-generated posts to Instagram.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="path to .env (default: project .env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify credentials and show quota")

    p = sub.add_parser("post", help="publish one post now")
    p.add_argument("type", choices=["image", "reel", "carousel"])
    p.add_argument("media", nargs="+", help="local .jpg/.mp4/.mov files or public URLs")
    p.add_argument("-c", "--caption", default="")
    p.add_argument("--no-ai-label", action="store_true", help="don't add Instagram's AI info label")
    p.add_argument("--reels-tab-only", action="store_true", help="reel: don't also show it in the feed")
    p.add_argument("--dry-run", action="store_true", help="validate and show what would happen")

    q = sub.add_parser("run-queue", help="publish due posts from the queue folder")
    q.add_argument("--queue-dir", default=str(DEFAULT_QUEUE))
    q.add_argument("--max", type=int, default=5, help="most posts to publish in one run (default 5)")
    q.add_argument("--dry-run", action="store_true")

    r = sub.add_parser("refresh-token", help="extend the long-lived access token")
    r.add_argument("--no-save", action="store_true", help="print the new token instead of saving it")

    args = parser.parse_args(argv)
    settings = Settings.from_env(Path(args.env_file))
    commands = {"check": cmd_check, "post": cmd_post, "run-queue": cmd_run_queue,
                "refresh-token": cmd_refresh_token}
    try:
        return commands[args.command](args, settings)
    except InstagramAPIError as exc:
        print(f"Instagram API error: {exc}", file=sys.stderr)
        if exc.payload:
            print(json.dumps(exc.payload, indent=2), file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
