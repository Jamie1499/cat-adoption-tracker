#!/usr/bin/env python3
"""
Blue Cross tracker with change‑tracking + timestamps + diff‑based email.

All original scraping logic preserved.
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

MAX_WORKERS = int(os.getenv("MAX_WORKERS", "32"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.25"))

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")


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
# DIFF LOGIC
# ---------------------------------------------------------------------------

def diff_cats(previous, current):
    prev_map = {c["id"]: c for c in previous}
    curr_map = {c["id"]: c for c in current}

    added = []
    removed = []
    still_here = []

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
# EMAIL
# ---------------------------------------------------------------------------

def send_diff_email(added, removed):
    if not added and not removed:
        return

    import smtplib
    from email.mime.text import MIMEText

    body = f"""
Blue Cross Cat Tracker Update

New cats ({len(added)}):
{''.join(f"- {c['name']} ({c['url']})\n" for c in added)}

Removed cats ({len(removed)}):
{''.join(f"- {c['name']} ({c['url']})\n" for c in removed)}
"""

    msg = MIMEText(body)
    msg["Subject"] = "Blue Cross Cat Tracker – Updates"
    msg["From"] = EMAIL_USER
    msg["To"] = EMAIL_TO

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.send_message(msg)

    print("Email sent.")


# ---------------------------------------------------------------------------
# ORIGINAL SCRAPER (UNCHANGED)
# ---------------------------------------------------------------------------

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
    return [el.text for el in root.findall(".//ns:loc", ns)]


def collect_pet_urls_from_sitemap(sitemap_url):
    pet_urls = set()

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
    soup = BeautifulSoup(html_text, "lxml")

    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else url.rstrip("/").split("/")[-1].replace("-", " ").title()

    text = soup.get_text(" ", strip=True).lower()

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
        if t and any(k in t for k in ["enquire", "apply", "adopt", "rehome", "express interest"]):
            cta_texts.append(t)
    has_cta = bool(cta_texts)
    has_phrase = any(p in text for p in ["available for adoption", "available now", "ready for adoption"])

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

    is_unavailable = any(p in text for p in ["has been adopted", "reserved", "not available"])
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

        for fut in as_completed(futures):
            res = fut.result()
            if res[0] == "ok":
                pet = res[1]
                if pet["available"]:
                    results.append(pet)
                    print(f"KEEP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']}")
                else:
                    print(f"SKIP {pet['name']} ({pet['url']}) reason={pet['reason']} species={pet['species']}")
            elif res[0] == "skip":
                pass
            else:
                print("ERROR fetching", res[1], res[2])

    session.close()
    return results


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    print("Starting Blue Cross tracker… DEBUG=" + str(DEBUG))

    previous = load_previous()
    current = scrape_bluecross_parallel()

    cats_only = [c for c in current if c.get("species") == "cat" and c.get("available")]
    print(f"Filtered to {len(cats_only)} cats.")

    added, removed, still_here = diff_cats(previous, cats_only)

    final = added + still_here
    save_final(final)

    print(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    if NO_EMAIL:
        print("NO_EMAIL=1 — skipping email.")
    else:
        send_diff_email(added, removed)


if __name__ == "__main__":
    main()
