#!/usr/bin/env python3
import os
import json
import asyncio
import aiohttp
from datetime import datetime
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

# Save JSON next to this script
FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")

REQUEST_TIMEOUT = 30
DEBUG = os.getenv("DEBUG", "1") == "1"
USER_AGENT = os.getenv("USER_AGENT", "bluecross-tracker/1.0")

# Batch size (B2 = 40)
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "40"))


def ts():
    return datetime.utcnow().strftime("[%Y-%m-%d %H:%M:%S UTC]")


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
    prev_map = { (c.get("id") or c.get("url")): c for c in previous }
    now = datetime.utcnow().isoformat()

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


def parse_sitemap(text):
    # Try XML first
    try:
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        root = ET.fromstring(text)
        return [el.text for el in root.findall(".//ns:loc", ns)]
    except Exception:
        pass

    # Fallback: parse as HTML
    try:
        soup = BeautifulSoup(text, "lxml")
        locs = [loc_tag.get_text(strip=True) for loc_tag in soup.find_all("loc")]
        if locs:
            return locs
    except Exception:
        pass

    log("WARNING: Sitemap contained no <loc> entries.")
    return []


async def fetch(session, url):
    try:
        async with session.get(url, timeout=REQUEST_TIMEOUT) as r:
            return await r.text(errors="ignore")
    except Exception:
        return None


async def collect_pet_urls():
    log("Fetching Blue Cross sitemaps…")

    sitemap_pages = [
        "https://www.bluecross.org.uk/sitemap.xml?page=1",
        "https://www.bluecross.org.uk/sitemap.xml?page=2",
    ]

    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        texts = await asyncio.gather(*(fetch(session, sm) for sm in sitemap_pages))

    all_locs = []
    for sm, text in zip(sitemap_pages, texts):
        if text:
            locs = parse_sitemap(text)
            log(f"Sitemap {sm} → {len(locs)} URLs")
            all_locs.extend(locs)

    pet_urls = []
    for l in all_locs:
        if "/pet/" not in l:
            continue
        slug = l.split("/")[-1]
        id_part = slug.split("-")[-1]
        if id_part.startswith("2"):
            pet_urls.append(l)

    log(f"Total cat URLs: {len(pet_urls)}")
    return pet_urls


def extract_pet(html_text, url):
    if not html_text:
        return None

    soup = BeautifulSoup(html_text, "lxml")

    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else url.split("/")[-1].replace("-", " ").title()

    text = soup.get_text(" ", strip=True).lower()

    # JSON-LD availability
    is_available_jsonld = False
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            import json as _json
            data = _json.loads(script.string or "{}")
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]
        for it in items:
            if isinstance(it, dict):
                offers = it.get("offers")
                if isinstance(offers, dict):
                    avail = offers.get("availability") or offers.get("availabilityStatus")
                    if avail and ("instock" in str(avail).lower() or "available" in str(avail).lower()):
                        is_available_jsonld = True

    unavailable = any(p in text for p in ["reserved", "has been adopted", "not available"])

    final_available = is_available_jsonld and not unavailable

    return {
        "id": url.rstrip("/"),
        "name": name,
        "url": url,
        "available": final_available,
    }


async def fetch_and_parse(session, url):
    html = await fetch(session, url)
    return extract_pet(html, url)


async def scrape_bluecross_async():
    pet_urls = await collect_pet_urls()

    log("Scraping Blue Cross cats…")
    log("Batch size =", BATCH_SIZE)

    connector = aiohttp.TCPConnector(limit=BATCH_SIZE)
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT},
                                     connector=connector) as session:

        results = []
        for i in range(0, len(pet_urls), BATCH_SIZE):
            batch = pet_urls[i:i + BATCH_SIZE]
            log(f"Fetching batch {i//BATCH_SIZE + 1} ({len(batch)} cats)…")

            tasks = [fetch_and_parse(session, url) for url in batch]
            batch_results = await asyncio.gather(*tasks)

            results.extend([r for r in batch_results if r])

    return results


def main():
    print(ts(), "Starting Blue Cross tracker…")

    previous = load_previous()
    current = asyncio.run(scrape_bluecross_async())

    cats_only = [c for c in current if c.get("available")]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(ts(), f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")
    return added, removed


if __name__ == "__main__":
    main()