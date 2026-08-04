#!/usr/bin/env python3
"""Poll an Untappd RSS feed and cross-post new checkins to Pixelfed."""
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import feedparser
import requests
from bs4 import BeautifulSoup

STATE_FILE = Path("state.json")
MAX_HISTORY = 100  # how many processed ids to remember, to avoid duplicate posts

UNTAPPD_RSS_URL = os.environ["UNTAPPD_RSS_URL"]
PIXELFED_INSTANCE = os.environ["PIXELFED_INSTANCE"].rstrip("/")
PIXELFED_TOKEN = os.environ["PIXELFED_TOKEN"]
VISIBILITY = os.environ.get("PIXELFED_VISIBILITY", "public")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"seen_ids": []}


def save_state(state):
    # cap history so the file doesn't grow forever
    state["seen_ids"] = state["seen_ids"][-MAX_HISTORY:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


def extract_image_url(entry):
    if "media_content" in entry and entry.media_content:
        return entry.media_content[0]["url"]
    if "enclosures" in entry and entry.enclosures:
        return entry.enclosures[0]["href"]

    soup = BeautifulSoup(entry.get("summary", ""), "html.parser")
    img = soup.find("img")
    if not img or not img.get("src"):
        return None

    thumb_url = img["src"]
    # Untappd wraps the full-res image in a thumbnail cropper's url= param — unwrap it
    parsed = urlparse(thumb_url)
    qs = parse_qs(parsed.query)
    if "url" in qs:
        return qs["url"][0]
    return thumb_url


def clean_text(entry):
    raw_title = entry.get("title", "")
    match = re.match(r"^.*?is drinking an? (.+?) by\s+(.+?)(?: at (.+))?$", raw_title)

    if match:
        beer, brewery, location = match.groups()
        line = f"{beer.strip()} by {brewery.strip()}"
        if location and location.strip() != "Untappd at Home":
            line += f" at {location.strip()}"
    else:
        line = raw_title.strip()  # fallback if the title doesn't match the usual pattern

    link = entry.get("link", "")
    parts = [line]
    if link:
        parts.append(link)
    parts.append("via Untappd")

    return "\n".join(parts)


def post_to_pixelfed(image_url, status_text):
    headers = {"Authorization": f"Bearer {PIXELFED_TOKEN}"}

    img_resp = requests.get(image_url, timeout=30)
    img_resp.raise_for_status()

    media_resp = requests.post(
        f"{PIXELFED_INSTANCE}/api/v1/media",
        headers=headers,
        files={"file": ("checkin.jpg", img_resp.content)},
        timeout=60,
    )
    media_resp.raise_for_status()
    media_id = media_resp.json()["id"]

    status_resp = requests.post(
        f"{PIXELFED_INSTANCE}/api/v1/statuses",
        headers=headers,
        data={
            "status": status_text,
            "media_ids[]": media_id,
            "visibility": VISIBILITY,
        },
        timeout=30,
    )
    status_resp.raise_for_status()
    return status_resp.json()


def main():
    state = load_state()
    seen = set(state["seen_ids"])

    feed = feedparser.parse(UNTAPPD_RSS_URL)
    if feed.bozo:
        print(f"Feed parse warning: {feed.bozo_exception}", file=sys.stderr)

    # process oldest-first so posts land on Pixelfed in the right order
    new_entries = [e for e in feed.entries if e.get("id", e.get("link")) not in seen]
    new_entries.reverse()

    if not new_entries:
        print("No new checkins.")
        return

    for entry in new_entries:
        entry_id = entry.get("id", entry.get("link"))
        image_url = extract_image_url(entry)
        text = clean_text(entry)

        if not image_url:
            print(f"Skipping (no image found): {text[:60]}")
            seen.add(entry_id)
            continue

        try:
            post_to_pixelfed(image_url, text)
            print(f"Posted: {text[:60]}")
        except requests.HTTPError as e:
            print(f"Failed to post '{text[:60]}': {e}", file=sys.stderr)
            continue  # leave it unmarked so we retry next run

        seen.add(entry_id)

    state["seen_ids"] = list(seen)
    save_state(state)


if __name__ == "__main__":
    main()
