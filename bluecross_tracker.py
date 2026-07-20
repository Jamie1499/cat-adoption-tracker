#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timezone

FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")
DEBUG = os.getenv("DEBUG", "1") == "1"

BASE_URL = "https://www.bluecross.org.uk/pet/listing/cat"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.bluecross.org.uk/rehome/cat",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}

def ts():
    return datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M:%S UTC]")

def log(*args):
    if DEBUG:
        print(ts(), *args)

def load_previous():
    if not os.path.exists(FILE):
        return []
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_final(cats):
    cats_sorted = sorted(cats, key=lambda c: c["id"])
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(cats_sorted, f, indent=2, ensure_ascii=False)

def diff_cats(previous, current):
    prev_map = {(c.get("id") or c.get("url")): c for c in previous}
    now = datetime.now(timezone.utc).isoformat()

    added, removed, still_here = [], [], []

    for cat in current:
        cid = cat["id"]
        if cid not in prev_map:
            cat["added"] = now
            cat["lastSeen"] = now
            added.append(cat)
        else:
            old = prev_map[cid]
            cat["added"] = old.get("added", now)
            cat["lastSeen"] = now
            still_here.append(cat)

    for cid, cat in prev_map.items():
        if cid not in {c["id"] for c in current}:
            removed.append(cat)

    return added, removed, still_here

def scrape_bluecross():
    log("Fetching Blue Cross JSON API…")

    r = requests.get(BASE_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    data = r.json()
    pets = data.get("results", [])

    results = []
    for pet in pets:
        # Only keep cats that are NOT reserved
        if pet.get("field_reserved", "").lower() == "yes":
            continue

        url = "https://www.bluecross.org.uk" + pet["view_node"]

        results.append({
            "id": url.rstrip("/"),
            "name": pet.get("title", "Unknown"),
            "url": url,
            "available": True,
        })

    log(f"Total available cats: {len(results)}")
    return results

def main():
    print(ts(), "Starting Blue Cross tracker…")

    previous = load_previous()
    current = scrape_bluecross()

    added, removed, still_here = diff_cats(previous, current)
    final = added + still_here
    save_final(final)

    print(ts(), f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")
    return added, removed

if __name__ == "__main__":
    main()
