#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Save JSON next to this script
FILE = os.path.join(os.path.dirname(__file__), "catchat_cats.json")

REQUEST_TIMEOUT = 30
DEBUG = os.getenv("DEBUG", "1") == "1"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "16"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.0"))
USER_AGENT = os.getenv("USER_AGENT", "catchat-tracker/1.0")

# CatChat regions to scrape
REGIONS = [
    "https://catchat.org/adopt-a-cat/buckinghamshire",
    "https://catchat.org/adopt-a-cat/hertfordshire",
]

def log(*args):
    if DEBUG:
        print(*args)

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
    prev_map = {}
    for c in previous:
        cid = c.get("id") or c.get("url")
        c["id"] = cid
        prev_map[cid] = c

    curr_map = {c["id"]: c for c in current}

    added, removed, still_here = [], [], []
    now = datetime.utcnow().isoformat()

    for cid, cat in curr_map.items():
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
        if cid not in curr_map:
            removed.append(cat)

    return added, removed, still_here

# HTTP session
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s

# Parse region page
def parse_region(html, region_url):
    soup = BeautifulSoup(html, "lxml")

    # CatChat uses varied card classes across rescues
    cards = soup.select(".cat-card, .cat-listing, .cat, .listing")

    results = []

    for card in cards:
        # Name
        name_tag = card.find(["h3", "h2"])
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)

        # URL
        link = card.find("a")
        if not link or not link.get("href"):
            continue
        url = link["href"]
        if url.startswith("/"):
            url = "https://catchat.org" + url

        # Reserved via paw icon
        reserved = bool(card.select_one(".icon.reserved"))

        results.append({
            "id": url.rstrip("/"),
            "name": name,
            "url": url,
            "available": not reserved,
            "reason": "reserved" if reserved else "available",
            "species": "cat",
            "region": region_url,
        })

    return results

# Fetch region
def fetch_region(session, region_url):
    try:
        r = session.get(region_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return parse_region(r.text, region_url)
    except Exception as e:
        log("ERROR fetching region:", region_url, e)
        return []

# Main scrape
def scrape_catchat():
    session = make_session()
    results = []
    futures = {}

    log("Scraping CatChat regions…")

    with ThreadPoolExecutor(max_workers=len(REGIONS)) as ex:
        for region in REGIONS:
            fut = ex.submit(fetch_region, session, region)
            futures[fut] = region

        for fut in as_completed(futures):
            region = futures[fut]
            cats = fut.result()
            log(f"Region {region} → {len(cats)} cats")
            results.extend(cats)

    session.close()
    return results

# MAIN
def main():
    print("Starting CatChat tracker…")

    previous = load_previous()
    current = scrape_catchat()

    # Only AVAILABLE cats
    cats_only = [c for c in current if c["available"]]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    return added, removed