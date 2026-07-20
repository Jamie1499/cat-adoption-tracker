#!/usr/bin/env python3
import os
import json
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# Save JSON next to this script
FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")

REQUEST_TIMEOUT = 30
DEBUG = os.getenv("DEBUG", "1") == "1"
SAVE_HTML_SAMPLES = int(os.getenv("SAVE_HTML_SAMPLES", "0"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))  # faster
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.02"))  # faster
USER_AGENT = os.getenv("USER_AGENT", "bluecross-tracker/1.0")


def ts():
    """Timestamp prefix for logs."""
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


# SCRAPER UTILITIES
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


def collect_pet_urls():
    log("Fetching Blue Cross sitemaps…")

    session = make_session()
    pet_urls = set()

    sitemap_pages = [
        "https://www.bluecross.org.uk/sitemap.xml?page=1",
        "https://www.bluecross.org.uk/sitemap.xml?page=2",
    ]

    all_locs = []

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {ex.submit(session.get, sm, timeout=REQUEST_TIMEOUT): sm for sm in sitemap_pages}
        for fut in as_completed(futures):
            sm = futures[fut]
            try:
                r = fut.result()
                r.raise_for_status()
                locs = parse_sitemap(r.text)
                log(f"Sitemap {sm} → {len(locs)} URLs")
                all_locs.extend(locs)
            except Exception as e:
                log(f"Failed sitemap {sm}: {e}")

    # Filter only cat pages
    for l in all_locs:
        if "/pet/" not in l:
            continue

        slug = l.split("/")[-1]
        id_part = slug.split("-")[-1]

        if not id_part.startswith("2"):
            continue

        pet_urls.add(l)

    log(f"Total cat URLs: {len(pet_urls)}")
    return sorted(pet_urls)


# PET PARSER
def extract_pet(html_text, url):
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
    try:
        for script in soup.find_all("script", type="application/ld+json"):
            import json as _json
            try:
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
    except Exception:
        pass

    # CTA buttons
    cta_texts = []
    for tag in soup.find_all(["a", "button"]):
        t = tag.get_text(" ", strip=True).lower()
        if any(k in t for k in ["enquire", "apply", "adopt", "rehome", "express interest"]):
            cta_texts.append(t)
    has_cta = bool(cta_texts)

    # Availability phrases
    has_phrase = any(p in text for p in ["available for adoption", "available now", "ready for adoption"])

    # Species detection
    species = "unknown"
    try:
        for use in soup.find_all("use"):
            href = use.get("xlink:href") or use.get("href")
            if not href:
                continue
            h = href.lower()
            if "#cat" in h or "#kitten" in h:
                species = "cat"
                break
            if any(k in h for k in ["#dog", "#rabbit", "#horse"]):
                species = "other"
                break
    except Exception:
        species = "unknown"

    # Unavailable phrases
    is_unavailable = any(p in text for p in ["has been adopted", "reserved", "not available"])

    final_available = False
    if species == "cat" and not is_unavailable and (is_available_jsonld or has_cta or has_phrase):
        final_available = True

    return {
        "id": url.rstrip("/"),
        "name": name,
        "url": url,
        "available": final_available,
        "species": species,
    }


# PARALLEL SCRAPER
def fetch_and_parse(session, idx, url):
    try:
        if REQUEST_DELAY > 0:
            time.sleep(REQUEST_DELAY)

        r = session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        pet = extract_pet(r.text, url)
        return ("ok", pet)
    except Exception as e:
        return ("error", url, str(e))


def scrape_bluecross():
    pet_urls = collect_pet_urls()
    session = make_session()
    results = []
    futures = {}

    log("Scraping Blue Cross cats…")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for idx, u in enumerate(pet_urls, start=1):
            fut = ex.submit(fetch_and_parse, session, idx, u)
            futures[fut] = u

        for fut in as_completed(futures):
            res = fut.result()
            if res[0] == "ok":
                pet = res[1]
                if pet["species"] == "cat":
                    results.append(pet)
                    log(f"Parsed {pet['name']} ({pet['url']}) available={pet['available']}")
            else:
                log("ERROR", res[1], res[2])

    session.close()
    return results


# MAIN
def main():
    print(ts(), "Starting Blue Cross tracker…")

    previous = load_previous()
    current = scrape_bluecross()

    cats_only = [
        c for c in current
        if c.get("species") == "cat" and c.get("available") is True
    ]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(ts(), f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    return added, removed