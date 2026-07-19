#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime
from xml.etree import ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

FILE = os.path.join(os.path.dirname(__file__), "battersea_cats.json")

SITEMAP_URL = "https://www.battersea.org.uk/sitemap.xml"
REQUEST_TIMEOUT = 30

DEBUG = os.getenv("DEBUG", "1") == "1"
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "16"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.0"))
USER_AGENT = os.getenv("USER_AGENT", "battersea-tracker/1.0")

def log(*args):
    if DEBUG:
        print(*args)

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

def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s

def parse_sitemap(xml_text):
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)
    return [el.text for el in root.findall(".//ns:loc", ns)]

def collect_cat_urls():
    log("Fetching Battersea sitemap…")

    session = make_session()
    try:
        r = session.get(SITEMAP_URL, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        locs = parse_sitemap(r.text)
        log(f"Sitemap → {len(locs)} URLs")
    except Exception as e:
        log("Failed to fetch Battersea sitemap:", e)
        return []

    cats = [u for u in locs if "/cats/cat-rehoming-gallery/" in u]
    log(f"Total cat URLs: {len(cats)}")
    return sorted(cats)

def extract_cat(html_text, url):
    soup = BeautifulSoup(html_text, "lxml")

    h1 = soup.find("h1")
    name = h1.get_text(strip=True) if h1 else url.split("/")[-1].replace("-", " ").title()

    text = soup.get_text(" ", strip=True).lower()

    if name.strip().lower() == "do something extraordinary":
        is_reserved = True
        reason = "removed_banner"
    else:
        is_reserved = "reserved" in text.split()
        reason = "reserved" if is_reserved else "available"

    return {
        "id": url.rstrip("/"),
        "name": name,
        "url": url,
        "available": not is_reserved,
        "reason": reason,
        "species": "cat",
    }

def fetch_and_parse(session, idx, url):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        cat = extract_cat(r.text, url)
        return ("ok", cat)
    except Exception as e:
        return ("error", url, str(e))

def scrape_battersea():
    urls = collect_cat_urls()
    session = make_session()
    results = []
    futures = {}

    log("Scraping Battersea cats…")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for idx, u in enumerate(urls, start=1):
            fut = ex.submit(fetch_and_parse, session, idx, u)
            futures[fut] = u

        for fut in as_completed(futures):
            res = fut.result()
            if res[0] == "ok":
                cat = res[1]
                log(f"Parsed {cat['name']} ({cat['url']}) available={cat['available']}")
                results.append(cat)
            else:
                log("ERROR", res[1], res[2])

    session.close()
    return results

def main():
    print("Starting Battersea tracker…")

    previous = load_previous()
    current = scrape_battersea()

    cats_only = [
        c for c in current
        if c.get("species") == "cat" and c.get("available") is True
    ]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    return added, removed