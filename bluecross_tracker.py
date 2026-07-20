#!/usr/bin/env python3
import os
import json
import requests
from datetime import datetime, timezone
from bs4 import BeautifulSoup

# Save JSON next to this script
FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")

DEBUG = os.getenv("DEBUG", "1") == "1"
USER_AGENT = os.getenv("USER_AGENT", "bluecross-tracker/1.0")

BASE_URL = "https://www.bluecross.org.uk/rehome/cat"


def ts():
    return datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M:%S UTC]")


def log(*args):
    if DEBUG:
        print(ts(), *args)


# JSON LOAD / SAVE
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


# DIFF LOGIC
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


# SCRAPER
def fetch_page(url):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        r.raise_for_status()
        return r.text
    except Exception as e:
        log("ERROR fetching page:", url, e)
        return None


def extract_cats_from_page(html):
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select("article.m-pet-listing-item_wrapper")
    results = []

    for card in cards:
        link = card.select_one("a.m-pet-listing-item")
        if not link:
            continue

        url = "https://www.bluecross.org.uk" + link["href"]

        name_tag = card.select_one("h3.m-pet-listing-item__title")
        name = name_tag.get_text(strip=True) if name_tag else "Unknown"

        reserved = card.select_one("div.m-pet-listing-item_reserved") is not None

        # Only available cats (Option 1)
        if reserved:
            continue

        results.append({
            "id": url.rstrip("/"),
            "name": name,
            "url": url,
            "available": True,
        })

    return results


def scrape_bluecross():
    log("Fetching Blue Cross cat listing…")
    all_cats = []
    page = 0

    while True:
        url = f"{BASE_URL}?page={page}"
        html = fetch_page(url)
        if not html:
            break

        cats = extract_cats_from_page(html)
        if not cats:
            break

        all_cats.extend(cats)
        log(f"Page {page}: {len(cats)} available cats")
        page += 1

    log(f"Total available cats: {len(all_cats)}")
    return all_cats


# MAIN
def main():
    print(ts(), "Starting Blue Cross tracker…")

    previous = load_previous()
    current = scrape_bluecross()

    cats_only = current  # Option 1: only available cats

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(ts(), f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")
    return added, removed


if __name__ == "__main__":
    main()