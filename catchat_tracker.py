#!/usr/bin/env python3
import os
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

FILE = os.path.join(os.path.dirname(__file__), "catchat_cats.json")

REQUEST_TIMEOUT = 30
DEBUG = os.getenv("DEBUG", "1") == "1"
MAX_WORKERS = 4
USER_AGENT = os.getenv("USER_AGENT", "catchat-tracker/1.0")

MIN_RESULTS = 10  # minimum acceptable listings per site

REGIONS = [
    "https://catchat.org/adopt-a-cat/buckinghamshire",
    "https://catchat.org/adopt-a-cat/hertfordshire",
]

def log(*args):
    if DEBUG:
        print("CatChat:", *args)

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
    prev_map = {c["id"]: c for c in previous}
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

def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s

def normalize_url(href):
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        href = "https://catchat.org" + href
    return href

def parse_region(html, region_url):
    soup = BeautifulSoup(html, "lxml")

    # Detect maintenance or error pages
    if "maintenance" in html.lower() or "temporarily unavailable" in html.lower():
        log(region_url, "→ Maintenance page detected")
        return []

    cards = soup.select("div#cat")
    results = []

    for card in cards:
        link_tag = card.select_one("a#articleLink")
        name_tag = card.select_one("h3#articleTitle")
        img_tag = card.select_one("img")
        reserved_icon = card.select_one(".icon.reserved")

        if not link_tag or not name_tag:
            continue

        url = normalize_url(link_tag.get("href"))
        name = name_tag.get_text(strip=True)
        img = normalize_url(img_tag.get("src")) if img_tag else None
        reserved = bool(reserved_icon)

        results.append({
            "id": url.rstrip("/") if url else name,
            "name": name,
            "url": url,
            "image": img,
            "available": not reserved,
            "reason": "reserved" if reserved else "available",
            "species": "cat",
            "region": region_url,
        })

    log(region_url, f"→ parsed {len(results)} cats")
    return results

def fetch_region(session, region_url):
    try:
        r = session.get(region_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        r.raise_for_status()

        html = r.text
        log(region_url, f"HTML length: {len(html)}")

        return parse_region(html, region_url)

    except Exception as e:
        log("ERROR fetching region:", region_url, e)
        return []

def scrape_catchat():
    session = make_session()
    results = []
    futures = {}

    log("Scraping CatChat regions…")

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(REGIONS))) as ex:
        for region in REGIONS:
            fut = ex.submit(fetch_region, session, region)
            futures[fut] = region

        for fut in as_completed(futures):
            cats = fut.result()
            results.extend(cats)

    session.close()

    # Deduplicate
    unique = {c["id"]: c for c in results}
    total = len(unique)

    log("CatChat total unique cats:", total)

    # HEALTH CHECK — prevent false “all removed”
    if total < MIN_RESULTS:
        log(f"CatChat: Suspiciously low total ({total}) — marking scraper unhealthy")
        return []

    return list(unique.values())

def main():
    print("Starting CatChat tracker…")

    previous = load_previous()
    current = scrape_catchat()

    cats_only = [c for c in current if c.get("available")]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    return added, removed

if __name__ == "__main__":
    main()