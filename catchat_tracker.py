#!/usr/bin/env python3
import os
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# File locations
FILE = os.path.join(os.path.dirname(__file__), "catchat_cats.json")
DEBUG_HTML_DIR = os.path.join(os.path.dirname(__file__), "catchat_debug_html")

# Config
REQUEST_TIMEOUT = 30
DEBUG = os.getenv("DEBUG", "1") == "1"
MAX_WORKERS = int(os.getenv("CATCHAT_MAX_WORKERS", "4"))
USER_AGENT = os.getenv("USER_AGENT", "catchat-tracker/1.0")
SAVE_DEBUG_HTML = int(os.getenv("SAVE_DEBUG_HTML", "1"))  # saves HTML for inspection (set 0 to disable)

# Regions to scrape
REGIONS = [
    "https://catchat.org/adopt-a-cat/buckinghamshire",
    "https://catchat.org/adopt-a-cat/hertfordshire",
]

def log(*args):
    if DEBUG:
        print(*args)

# JSON helpers
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

# Diff logic
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

# HTTP session
def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s

# Helpers
def ensure_debug_dir():
    if SAVE_DEBUG_HTML and not os.path.exists(DEBUG_HTML_DIR):
        os.makedirs(DEBUG_HTML_DIR, exist_ok=True)

def save_debug_html(region_url, html):
    if not SAVE_DEBUG_HTML:
        return
    ensure_debug_dir()
    name = region_url.rstrip("/").split("/")[-1] or "region"
    path = os.path.join(DEBUG_HTML_DIR, f"catchat_debug_{name}.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        log("Saved debug HTML:", path)
    except Exception as e:
        log("Failed to save debug HTML:", e)

def normalize_url(href):
    if not href:
        return None
    href = href.strip()
    if href.startswith("//"):
        href = "https:" + href
    if href.startswith("/"):
        href = "https://catchat.org" + href
    return href

# Parsing strategies
def parse_region(html, region_url):
    soup = BeautifulSoup(html, "lxml")
    results = []
    seen = set()

    # Strategy A: rescue -> .cat elements (explicit)
    rescues = soup.select(".rescue")
    if rescues:
        for rescue in rescues:
            cards = rescue.select(".cat")
            for card in cards:
                item = parse_card_element(card, region_url)
                if item and item["id"] not in seen:
                    results.append(item); seen.add(item["id"])

    # Strategy B: common card classes
    if not results:
        for sel in (".cat-listing", ".cat-card", ".listing", ".pet-card"):
            cards = soup.select(sel)
            if cards:
                for card in cards:
                    item = parse_card_element(card, region_url)
                    if item and item["id"] not in seen:
                        results.append(item); seen.add(item["id"])
                if results:
                    break

    # Strategy C: fallback — find anchors that link to adopt-a-cat pages
    if not results:
        anchors = soup.find_all("a", href=True)
        for a in anchors:
            href = a["href"]
            if "/adopt-a-cat/" in href:
                url = normalize_url(href)
                if not url:
                    continue
                # Try to get a name: anchor text or nearby heading
                name = a.get_text(strip=True)
                if not name:
                    # look for sibling or parent headings
                    parent = a.parent
                    name_tag = None
                    for depth in range(3):
                        if parent is None:
                            break
                        name_tag = parent.find(["h3", "h2", "h4"])
                        if name_tag:
                            break
                        parent = parent.parent
                    name = name_tag.get_text(strip=True) if name_tag else url.split("/")[-1].replace("-", " ").title()
                # reserved detection: check nearby for .icon.reserved or "Reserved" text
                parent = a.parent
                reserved = False
                # check up to 3 ancestor levels for reserved icon or text
                ancestor = a
                for _ in range(4):
                    if ancestor is None:
                        break
                    if ancestor.select_one(".icon.reserved"):
                        reserved = True
                        break
                    if "reserved" in ancestor.get_text(" ", strip=True).lower():
                        reserved = True
                        break
                    ancestor = ancestor.parent
                item = {
                    "id": url.rstrip("/"),
                    "name": name,
                    "url": url,
                    "available": not reserved,
                    "reason": "reserved" if reserved else "available",
                    "species": "cat",
                    "region": region_url,
                }
                if item["id"] not in seen:
                    results.append(item); seen.add(item["id"])

    # Final log of what we found
    return results

def parse_card_element(card, region_url):
    # name
    name_tag = card.select_one(".cat-name") or card.find(["h3", "h2", "h4"])
    if not name_tag:
        # sometimes name is inside an <a>
        name_tag = card.find("a")
    if not name_tag:
        return None
    name = name_tag.get_text(" ", strip=True)

    # url
    link = card.select_one(".cat-link") or card.find("a", href=True)
    if not link or not link.get("href"):
        return None
    url = normalize_url(link["href"])
    if not url:
        return None

    # reserved detection: icon or nearby text
    reserved = False
    if card.select_one(".icon.reserved"):
        reserved = True
    else:
        # check for the word reserved in the card text
        if "reserved" in card.get_text(" ", strip=True).lower():
            reserved = True

    return {
        "id": url.rstrip("/"),
        "name": name,
        "url": url,
        "available": not reserved,
        "reason": "reserved" if reserved else "available",
        "species": "cat",
        "region": region_url,
    }

# Fetch region
def fetch_region(session, region_url):
    try:
        r = session.get(region_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        status = r.status_code
        length = len(r.text or "")
        log(f"Fetched {region_url} status={status} bytes={length}")
        if status != 200:
            log("Non-200 status for region:", region_url, status)
        if SAVE_DEBUG_HTML:
            save_debug_html(region_url, r.text or "")
        cats = parse_region(r.text or "", region_url)
        log(f"{region_url} → {len(cats)} cats parsed")
        return cats
    except Exception as e:
        log("ERROR fetching region:", region_url, e)
        return []

# Main scrape
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
    # dedupe by id
    unique = {}
    for c in results:
        unique[c["id"]] = c
    return list(unique.values())

# MAIN
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