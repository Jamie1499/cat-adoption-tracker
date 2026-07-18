#!/usr/bin/env python3
"""
Blue Cross tracker (simplified)

- Relies on SVG sprite (#cat) to determine species (strict).
- Uses a requests.Session with retries and a ThreadPoolExecutor for parallel fetches.
- Supports multiple local sitemap files via SITEMAP_FILES env var.
- Saves a compact JSON file of detected cats only.
- Keeps debug HTML samples when requested.

Environment variables:
  SITEMAP_FILES    -> comma-separated local sitemap files (e.g., sitemap_page1.xml,sitemap_page2.xml)
  SITEMAP_FILE     -> single local sitemap file (fallback)
  SITEMAP_URL      -> remote sitemap URL (fallback)
  DEBUG            -> "1" for verbose logging (default 1)
  SAVE_HTML_SAMPLES-> number of HTML samples to save (default 2)
  NO_EMAIL         -> "1" to skip email sending (default 1)
  MAX_WORKERS      -> number of parallel workers (default 8)
  REQUEST_DELAY    -> small stagger delay in seconds between submissions (default 0.25)
  USER_AGENT       -> override User-Agent header
"""
import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from xml.etree import ElementTree as ET

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# --- Config ---
FILE = "bluecross_cats.json"
DEFAULT_SITEMAP_URL = "https://www.bluecross.org.uk/sitemap.xml"
REQUEST_TIMEOUT = 30

DEBUG = os.getenv("DEBUG", "1") == "1"
SAVE_HTML_SAMPLES = int(os.getenv("SAVE_HTML_SAMPLES", "2"))
NO_EMAIL = os.getenv("NO_EMAIL", "1") == "1"

SITEMAP_FILES = [p.strip() for p in os.getenv("SITEMAP_FILES", "").split(",") if p.strip()]
SITEMAP_FILE = os.getenv("SITEMAP_FILE", "").strip()
SITEMAP_URL = os.getenv("SITEMAP_URL", DEFAULT_SITEMAP_URL)
USER_AGENT = os.getenv("USER_AGENT", "bluecross-tracker/1.0 (+https://github.com/yourname)")

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.25"))


def log(*args):
    if DEBUG:
        print(*args)


def save_current(cats):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(cats, f, indent=2, ensure_ascii=False)


def save_sample_html(index, url, html):
    os.makedirs("debug_html", exist_ok=True)
    safe_name = f"debug_{index:03d}.html"
    path = os.path.join("debug_html", safe_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"<!-- URL: {url} -->\n")
        f.write(html)
    return path


def make_session_with_retries():
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
    locs = [el.text for el in root.findall(".//ns:loc", ns)]
    return locs


def collect_pet_urls_from_sitemap(sitemap_url):
    pet_urls = set()

    # Multiple local sitemaps
    if SITEMAP_FILES:
        log("Using local sitemap files:", ", ".join(SITEMAP_FILES))
        for local in SITEMAP_FILES:
            if not os.path.exists(local):
                log("Sitemap file not found:", local)
                continue
            try:
                with open(local, "r", encoding="utf-8") as f:
                    locs = parse_sitemap(f.read())
                for l in locs:
                    if l and "/pet/" in l:
                        pet_urls.add(l)
            except Exception as e:
                log("Failed to parse local sitemap", local, e)
        return sorted(pet_urls)

    # Single local sitemap
    if SITEMAP_FILE:
        if not os.path.exists(SITEMAP_FILE):
            log("SITEMAP_FILE set but not found:", SITEMAP_FILE)
            return []
        log("Using local sitemap file:", SITEMAP_FILE)
        with open(SITEMAP_FILE, "r", encoding="utf-8") as f:
            try:
                locs = parse_sitemap(f.read())
            except Exception as e:
                log("Failed to parse local sitemap:", e)
                return []
        for l in locs:
            if l and "/pet/" in l:
                pet_urls.add(l)
        return sorted(pet_urls)

    # Remote sitemap fallback
    try:
        session = make_session_with_retries()
        r = session.get(sitemap_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        locs = parse_sitemap(r.text)
    except Exception as e:
        log("Failed to fetch/parse remote sitemap:", e)
        return []

    nested = [u for u in locs if u and u.endswith(".xml")]
    if nested:
        for ns_url in nested:
            try:
                log("Fetching nested sitemap:", ns_url)
                r2 = session.get(ns_url, timeout=REQUEST_TIMEOUT)
                r2.raise_for_status()
                locs2 = parse_sitemap(r2.text)
                for l in locs2:
                    if l and "/pet/" in l:
                        pet_urls.add(l)
            except Exception as e:
                log("Nested sitemap fetch failed:", ns_url, e)
    else:
        for l in locs:
            if l and "/pet/" in l:
                pet_urls.add(l)

    return sorted(pet_urls)


def extract_pet_from_detail(html_text, url):
    """
    Strict species detection using SVG sprite only.
    Availability is determined by JSON-LD offers OR visible CTA/phrases.
    Returns a dict with keys: name, url, available, reason, species, evidence
    """
    soup = BeautifulSoup(html_text, "lxml")

    # name
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else url.rstrip("/").split("/")[-1].replace("-", " ").title()

    text = soup.get_text(" ", strip=True).lower()

    # --- availability detection (JSON-LD offers OR CTA phrases) ---
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
        is_available_jsonld = False

    cta_texts = []
    for tag in soup.find_all(["a", "button"]):
        t = tag.get_text(" ", strip=True).lower()
        if t and any(k in t for k in ["enquire", "apply", "adopt", "rehome", "express interest", "apply to adopt", "register interest", "complete the online adoption inquiry", "please adopt"]):
            cta_texts.append(t)
    has_cta = bool(cta_texts)
    has_phrase = any(p in text for p in ["available for adoption", "available to adopt", "available now", "ready for adoption"])

    # --- species detection: SVG sprite only ---
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
            if any(k in h for k in ["#dog", "#puppy", "#rabbit", "#horse", "#pig", "#bird", "#parrot"]):
                species = "other"
                evidence.append(f"svg_sprite:{h}")
                break
    except Exception:
        species = "unknown"

    if species == "unknown":
        evidence.append("no_svg_sprite")

    # final availability: require species == cat AND availability evidence
    is_unavailable = any(p in text for p in ["has been adopted", "has now been adopted", "adopted", "no longer available", "reserved", "not available"])
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
        "name": name,
        "url": url,
        "available": bool(final_available),
        "reason": reason,
        "species": species,
        "evidence": ";".join(evidence)
    }


def fetch_and_parse(session, idx, url, save_sample_limit):
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code == 404:
            return ("skip", url, "404")
        r.raise_for_status()
        if idx <= save_sample_limit:
            save_sample_html(idx, url, r.text)
        pet = extract_pet_from_detail(r.text, url)
        return ("ok", pet)
    except Exception as e:
        return ("error", url, str(e))


def scrape_bluecross_parallel():
    pet_urls = collect_pet_urls_from_sitemap(SITEMAP_URL)
    log("Found pet URLs in sitemap:", len(pet_urls))
    results = []

    session = make_session_with_retries()
    save_limit = SAVE_HTML_SAMPLES
    idx = 0
    futures = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        for u in pet_urls:
            idx += 1
            fut = ex.submit(fetch_and_parse, session, idx, u, save_limit)
            futures[fut] = u
            time.sleep(REQUEST_DELAY / max(1, MAX_WORKERS))

        for fut in as_completed(futures):
            res = fut.result()
            if res[0] == "ok":
                pet = res[1]
                if pet["available"]:
                    results.append(pet)
                    print(f"KEEP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']} evidence={pet.get('evidence','')}")
                else:
                    print(f"SKIP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']} evidence={pet.get('evidence','')}")
            elif res[0] == "skip":
                pass
            else:
                print("ERROR fetching", res[1], res[2])

    session.close()
    return results


def send_email(new_cats):
    # kept minimal; not used when NO_EMAIL=1
    if not new_cats:
        return
    print("Email sending is disabled in this simplified script.")


def main():
    print("Starting Blue Cross tracker… DEBUG=" + str(DEBUG))
    print("SITEMAP_FILES:", SITEMAP_FILES or "(none)", "SITEMAP_FILE:", SITEMAP_FILE or "(none)", "SITEMAP_URL:", SITEMAP_URL)
    current = scrape_bluecross_parallel()

    cats_only = [c for c in current if c.get("species", "").lower() == "cat" and c.get("available", False)]
    print(f"Filtered to {len(cats_only)} cats from {len(current)} available pets (sprite-only).")

    # Save results
    save_current(cats_only)

    if NO_EMAIL:
        print("NO_EMAIL=1 set — skipping email send.")
    else:
        send_email(cats_only)


if __name__ == "__main__":
    main()
