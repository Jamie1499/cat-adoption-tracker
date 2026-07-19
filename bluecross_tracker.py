#!/usr/bin/env python3
"""
Blue Cross tracker (rolled-back matching logic + modular)

Restored behaviour:
- Species detection via SVG sprite (#cat) EXACTLY as before
- Availability detection via JSON-LD, CTA, phrases EXACTLY as before
- Filtering to cats_only EXACTLY as before
"""

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

FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")
DEFAULT_SITEMAP_URL = "https://www.bluecross.org.uk/sitemap.xml"
REQUEST_TIMEOUT = 30

DEBUG = os.getenv("DEBUG", "1") == "1"
SAVE_HTML_SAMPLES = int(os.getenv("SAVE_HTML_SAMPLES", "2"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.25"))
USER_AGENT = os.getenv("USER_AGENT", "bluecross-tracker/1.0")

SITEMAP_FILES = [p.strip() for p in os.getenv("SITEMAP_FILES", "").split(",") if p.strip()]
SITEMAP_FILE = os.getenv("SITEMAP_FILE", "").strip()
SITEMAP_URL = os.getenv("SITEMAP_URL", DEFAULT_SITEMAP_URL)


def log(*args):
    if DEBUG:
        print(*args)


# ---------------------------------------------------------------------------
# JSON LOAD / SAVE
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# DIFF LOGIC (with ID fix)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# SCRAPER UTILITIES
# ---------------------------------------------------------------------------

def save_sample_html(index, url, html):
    os.makedirs("debug_html", exist_ok=True)
    safe_name = f"debug_{index:03d}.html"
    path = os.path.join("debug_html", safe_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"<!-- URL: {url} -->\n")
        f.write(html)
    return path


def make_session():
    s = requests.Session()
    retries = Retry(total=3, backoff_factor=0.6, status_forcelist=(429, 500, 502, 503, 504))
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
    session = make_session()
    pet_urls = set()

    # Blue Cross uses paginated sitemaps
    sitemap_pages = [
        "https://www.bluecross.org.uk/sitemap.xml?page=1",
        "https://www.bluecross.org.uk/sitemap.xml?page=2",
    ]

    all_locs = []

    for sm in sitemap_pages:
        try:
            r = session.get(sm, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                log(f"Skipping missing sitemap page: {sm}")
                continue

            r.raise_for_status()
            locs = parse_sitemap(r.text)
            all_locs.extend(locs)
            log(f"Loaded sitemap page: {sm} ({len(locs)} URLs)")
        except Exception as e:
            log(f"Failed to load sitemap page {sm}: {e}")

    # Filter pet URLs
    for l in all_locs:
        if "/pet/2" in l:
            pet_urls.add(l)

    log(f"Total pet URLs found: {len(pet_urls)}")
    return sorted(pet_urls)




# ---------------------------------------------------------------------------
# PET DETAIL PARSER (ROLLED BACK)
# ---------------------------------------------------------------------------

def extract_pet(html_text, url):
    soup = BeautifulSoup(html_text, "lxml")

    # Name
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else url.split("/")[-1].replace("-", " ").title()

    text = soup.get_text(" ", strip=True).lower()

    # JSON-LD availability (unchanged)
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
                    avail2 = it.get("availability")
                    if avail2 and ("instock" in str(avail2).lower() or "available" in str(avail2).lower()):
                        is_available_jsonld = True
    except Exception:
        pass

    # CTA buttons (unchanged)
    cta_texts = []
    for tag in soup.find_all(["a", "button"]):
        t = tag.get_text(" ", strip=True).lower()
        if any(k in t for k in ["enquire", "apply", "adopt", "rehome", "express interest"]):
            cta_texts.append(t)
    has_cta = bool(cta_texts)

    # Availability phrases (unchanged)
    has_phrase = any(p in text for p in ["available for adoption", "available now", "ready for adoption"])

    # SPECIES DETECTION (ROLLED BACK EXACTLY)
    species = "unknown"
    evidence = []
    try:
        for use in soup.find_all("use"):
            href = use.get("xlink:href") or use.get("href")
            if not href:
                continue
            h = href.lower()
            if "#cat" in h or "#kitten" in h:
                species = "cat"
                evidence.append("svg_sprite:#cat")
                break
            if any(k in h for k in ["#dog", "#rabbit", "#horse"]):
                species = "other"
                evidence.append(f"svg_sprite:{h}")
                break
    except Exception:
        species = "unknown"

    if species == "unknown":
        evidence.append("no_svg_sprite")

    # Unavailable phrases (unchanged)
    is_unavailable = any(p in text for p in ["has been adopted", "reserved", "not available"])

    # FINAL AVAILABILITY (ROLLED BACK EXACTLY)
    final_available = False
    reason = "filtered_out"

    if species == "cat" and not is_unavailable and (is_available_jsonld or has_cta or has_phrase):
        final_available = True
        if is_available_jsonld:
            reason = "jsonld_available"
        elif has_cta:
            reason = "cta_found"
        else:
            reason = "available_phrase_found"
    else:
        if species != "cat":
            reason = f"filtered_out_species:{species}"
        elif is_unavailable:
            reason = "unavailable_phrase_found"
        else:
            reason = "no_availability_evidence"

    return {
        "id": url.rstrip("/"),
        "name": name,
        "url": url,
        "available": final_available,
        "reason": reason,
        "species": species,
        "evidence": ";".join(evidence)
    }


# ---------------------------------------------------------------------------
# PARALLEL SCRAPER (unchanged)
# ---------------------------------------------------------------------------

def fetch_and_parse(session, idx, url):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return ("skip", url, "404")
        r.raise_for_status()

        if idx <= SAVE_HTML_SAMPLES:
            save_sample_html(idx, url, r.text)

        pet = extract_pet(r.text, url)
        return ("ok", pet)

    except Exception as e:
        return ("error", url, str(e))


def scrape_bluecross():
    pet_urls = collect_pet_urls()
    log("Found Blue Cross pet URLs:", len(pet_urls))

    session = make_session()
    results = []
    futures = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for idx, u in enumerate(pet_urls, start=1):
            fut = ex.submit(fetch_and_parse, session, idx, u)
            futures[fut] = u
            time.sleep(REQUEST_DELAY / max(1, MAX_WORKERS))

        for fut in as_completed(futures):
            res = fut.result()
            if res[0] == "ok":
                pet = res[1]
                if pet["available"] and pet["species"] == "cat":
                    print(f"KEEP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']}")
                    results.append(pet)
                else:
                    print(f"SKIP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']}")
            elif res[0] == "skip":
                pass
            else:
                print("ERROR fetching", res[1], res[2])

    session.close()
    return results


# ---------------------------------------------------------------------------
# MAIN ENTRYPOINT (returns added, removed)
# ---------------------------------------------------------------------------

def main():
    print("Starting Blue Cross tracker…")

    previous = load_previous()
    current = scrape_bluecross()

    # FILTER EXACTLY AS BEFORE
    cats_only = [c for c in current if c.get("species") == "cat" and c.get("available")]

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    return added, removed