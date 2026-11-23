#!/usr/bin/env python3
"""
Watch a Shopify collection for new and restocked products, and publish an RSS feed.

Each run:
  1. Downloads every product in the collection from Shopify's public products.json.
  2. Compares it with the snapshot saved last time (state.json).
  3. Records an event when a product is brand new and in stock, or when it comes
     back in stock. (This store removes sold-out games from the collection, so a
     restock usually looks like a product reappearing; seen.json remembers every
     product ever listed so those get labeled "Back in stock".)
  4. Rewrites feed.xml (RSS 2.0) from the most recent events (events.json).

The first run only saves a baseline, so you don't get flooded with every game
already in stock.
"""

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

# ---- Settings (can be overridden with environment variables) -----------------
STORE = os.environ.get("STORE_URL", "https://gamesunl.com").rstrip("/")
COLLECTION = os.environ.get("COLLECTION", "used-games")
FEED_TITLE = os.environ.get("FEED_TITLE", "Games Unlimited: used games in stock")
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "150"))

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "state.json")
EVENTS_FILE = os.path.join(HERE, "events.json")
FEED_FILE = os.path.join(HERE, "feed.xml")
SEEN_FILE = os.path.join(HERE, "seen.json")

USER_AGENT = "Mozilla/5.0 (personal restock watcher; checks a few times a day)"


def fetch_page(page):
    url = f"{STORE}/collections/{COLLECTION}/products.json?limit=250&page={page}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp).get("products", [])
        except Exception as exc:  # network hiccup or rate limit: back off and retry
            if attempt == 2:
                raise
            print(f"Page {page} failed ({exc}); retrying...", file=sys.stderr)
            time.sleep(10 * (attempt + 1))


def fetch_all_products():
    products = {}
    page = 1
    while True:
        batch = fetch_page(page)
        if not batch:
            break
        for p in batch:
            products[str(p["id"])] = summarize(p)
        if len(batch) < 250:
            break
        page += 1
        time.sleep(1)  # be polite
    return products


def summarize(p):
    variants = p.get("variants") or []
    prices = [float(v["price"]) for v in variants if v.get("price")]
    images = p.get("images") or []
    return {
        "title": p.get("title", "(untitled)"),
        "handle": p.get("handle", ""),
        "available": any(v.get("available") for v in variants),
        "price": f"${min(prices):.2f}" if prices else "",
        "image": images[0].get("src", "") if images else "",
    }


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


def find_events(previous, current, seen, now_iso):
    """Return a list of new events by comparing two snapshots."""
    events = []
    for pid, prod in current.items():
        if not prod["available"]:
            continue
        before = previous.get(pid)
        if before is None:
            kind = "Back in stock" if pid in seen else "New listing"
        elif not before["available"]:
            kind = "Back in stock"
        else:
            continue
        events.append({
            # Unique per occurrence, so a game restocked twice shows up twice.
            "guid": f"{pid}-{now_iso}",
            "kind": kind,
            "product_id": pid,
            "time": now_iso,
            **prod,
        })
    return events


def build_feed(events):
    channel_link = f"{STORE}/collections/{COLLECTION}"
    items = []
    for e in events:
        link = f"{STORE}/products/{e['handle']}"
        when = format_datetime(datetime.fromisoformat(e["time"]))
        desc = f"{e['kind']}: {e['title']}"
        if e.get("price"):
            desc += f" ({e['price']})"
        if e.get("image"):
            desc += f'<br/><img src="{escape(e["image"], {chr(34): "&quot;"})}" width="300"/>'
        items.append(
            "  <item>\n"
            f"   <title>{escape(e['kind'] + ': ' + e['title'])}</title>\n"
            f"   <link>{escape(link)}</link>\n"
            f"   <guid isPermaLink=\"false\">{escape(e['guid'])}</guid>\n"
            f"   <pubDate>{when}</pubDate>\n"
            f"   <description>{escape(desc)}</description>\n"
            "  </item>"
        )
    # Use the newest event's time (not "now") so the feed only changes when
    # there's something new, and the workflow only commits when stock changes.
    last_build = (f"  <lastBuildDate>{format_datetime(datetime.fromisoformat(events[0]['time']))}"
                  "</lastBuildDate>\n") if events else ""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        " <channel>\n"
        f"  <title>{escape(FEED_TITLE)}</title>\n"
        f"  <link>{escape(channel_link)}</link>\n"
        "  <description>New and restocked items, checked automatically.</description>\n"
        + last_build
        + ("\n".join(items) + "\n" if items else "")
        + " </channel>\n</rss>\n"
    )


def main():
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    previous = load_json(STATE_FILE, None)
    events = load_json(EVENTS_FILE, [])
    # Every product ID ever listed -> title. Seeded from the last snapshot.
    seen = load_json(SEEN_FILE, None)
    if seen is None:
        seen = {pid: p["title"] for pid, p in (previous or {}).items()}

    current = fetch_all_products()
    in_stock = sum(p["available"] for p in current.values())
    print(f"Fetched {len(current)} products ({in_stock} in stock).")

    # Safety net: if the fetch looks broken, don't overwrite good state,
    # or the next run would report everything as "new".
    if not current:
        sys.exit("Got zero products; leaving state alone.")
    if previous and len(current) < 0.5 * len(previous):
        sys.exit(f"Product count dropped from {len(previous)} to {len(current)}; "
                 "looks like a bad fetch, leaving state alone.")

    if previous is None:
        print("First run: saving baseline, no events recorded.")
    else:
        new_events = find_events(previous, current, seen, now_iso)
        for e in new_events:
            print(f"  {e['kind']}: {e['title']}")
        events = (new_events + events)[:MAX_EVENTS]
        print(f"{len(new_events)} new event(s).")

    seen.update({pid: p["title"] for pid, p in current.items()})
    save_json(STATE_FILE, current)
    save_json(SEEN_FILE, seen)
    save_json(EVENTS_FILE, events)
    with open(FEED_FILE, "w") as f:
        f.write(build_feed(events))


if __name__ == "__main__":
    main()
