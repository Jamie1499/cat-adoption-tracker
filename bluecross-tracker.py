#!/usr/bin/env python3
import os
import json
import smtplib
import time
from email.mime.text import MIMEText
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET

# Config
FILE = "bluecross_cats.json"
SITEMAP_URL = "https://www.bluecross.org.uk/sitemap.xml"
USER_AGENT = "bluecross-tracker/1.0 (+https://github.com/yourname)"
REQUEST_TIMEOUT = 15
DEBUG = os.getenv("DEBUG", "1") == "1"   # default ON for debug runs
SAVE_HTML_SAMPLES = int(os.getenv("SAVE_HTML_SAMPLES", "10"))  # how many HTML files to save
FORCE_TEST = os.getenv("FORCE_TEST", "0") == "1"  # set to 1 to force a test new-cat email

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")


def log(*args):
    if DEBUG:
        print(*args)


def load_previous():
    if not os.path.exists(FILE):
        return []
    with open(FILE, "r") as f:
        return json.load(f)


def save_current(cats):
    with open(FILE, "w") as f:
        json.dump(cats, f, indent=2)


def fetch_url(url):
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    return r


def parse_sitemap(xml_text):
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)
    locs = [el.text for el in root.findall(".//ns:loc", ns)]
    return locs


def collect_pet_urls_from_sitemap(sitemap_url):
    pet_urls = set()
    try:
        r = fetch_url(sitemap_url)
        r.raise_for_status()
    except Exception as e:
        print("Failed to fetch sitemap:", e)
        return []

    locs = parse_sitemap(r.text)
    nested = [u for u in locs if u.endswith(".xml")]
    if nested:
        for ns_url in nested:
            try:
                log("Fetching nested sitemap:", ns_url)
                r2 = fetch_url(ns_url)
                r2.raise_for_status()
                locs2 = parse_sitemap(r2.text)
                for l in locs2:
                    if "/pet/" in l:
                        pet_urls.add(l)
            except Exception as e:
                log("Nested sitemap fetch failed:", ns_url, e)
    else:
        for l in locs:
            if "/pet/" in l:
                pet_urls.add(l)

    return sorted(pet_urls)


def save_sample_html(index, url, html):
    os.makedirs("debug_html", exist_ok=True)
    safe_name = f"debug_{index:03d}.html"
    path = os.path.join("debug_html", safe_name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"<!-- URL: {url} -->\n")
        f.write(html)
    return path


def extract_pet_from_detail(html_text, url):
    soup = BeautifulSoup(html_text, "lxml")

    # Name heuristics
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else None

    if not name:
        if soup.title and soup.title.string:
            name = soup.title.string.strip()
        else:
            name = url.rstrip("/").split("/")[-1].replace("-", " ").title()

    text = soup.get_text(separator=" ").lower()

    # Availability heuristics
    available_phrases = [
        "available for adoption",
        "available to adopt",
        "available to rehome",
        "available to re-home",
        "available",
        "ready for adoption",
        "ready to be rehomed",
        "available to rehome",
    ]
    unavailable_phrases = [
        "has been adopted",
        "has now been adopted",
        "adopted",
        "no longer available",
        "reserved",
        "under assessment",
        "not available",
        "this pet has been adopted",
    ]

    # Check explicit status labels
    status_labels = soup.select(".status, .pet-status, .availability, .adoption-status, .pet__status, .status-banner")
    label_texts = " ".join(lbl.get_text(" ", strip=True).lower() for lbl in status_labels) if status_labels else ""

    is_unavailable = any(p in text for p in unavailable_phrases) or any(p in label_texts for p in unavailable_phrases)
    is_available = any(p in text for p in available_phrases) or any(p in label_texts for p in available_phrases)

    # If both flags ambiguous, prefer explicit label presence
    if label_texts:
        if any(p in label_texts for p in unavailable_phrases):
            is_available = False
        if any(p in label_texts for p in available_phrases):
            is_available = True

    reason = "unknown"
    if is_unavailable:
        reason = "unavailable_phrase_found"
    elif is_available:
        reason = "available_phrase_found"
    else:
        reason = "no_availability_phrase"

    return {
        "name": name,
        "url": url,
        "shelter": "Blue Cross",
        "available": bool(is_available and not is_unavailable),
        "reason": reason,
        "label_texts": label_texts[:200]
    }


def scrape_bluecross():
    pet_urls = collect_pet_urls_from_sitemap(SITEMAP_URL)
    log("Found pet URLs in sitemap:", len(pet_urls))
    results = []
    saved = 0

    for i, url in enumerate(pet_urls):
        try:
            log(f"[{i+1}/{len(pet_urls)}] Fetching {url}")
            r = fetch_url(url)
            if r.status_code == 404:
                print(f"[{i+1}] SKIP 404 {url}")
                continue
            r.raise_for_status()
            if saved < SAVE_HTML_SAMPLES:
                sample_path = save_sample_html(i+1, url, r.text)
                log(f"Saved sample HTML to {sample_path}")
                saved += 1
            pet = extract_pet_from_detail(r.text, url)
            if pet["available"]:
                results.append({"name": pet["name"], "url": pet["url"], "shelter": pet["shelter"]})
                print(f"[{i+1}] KEEP {pet['name']} ({pet['url']}) reason={pet['reason']}")
            else:
                print(f"[{i+1}] SKIP {pet['name']} ({url}) reason={pet['reason']}")
            time.sleep(0.4)
        except Exception as e:
            print(f"[{i+1}] ERROR {url} -> {e}")
            continue

    # Force test mode: simulate a new cat for testing email
    if FORCE_TEST:
        fake = {"name": "TEST CAT (force)", "url": "https://www.bluecross.org.uk/pet/test-cat-000", "shelter": "Blue Cross"}
        results.append(fake)
        print("FORCE_TEST enabled: added fake cat for email testing.")

    return results


def send_email(new_cats):
    if not new_cats:
        print("No new cats — no email sent.")
        return

    body = "New Blue Cross Cats Available for Adoption\n\n"
    for c in new_cats:
        body += f"- {c['name']} → {c['url']}\n"

    msg = MIMEText(body)
    msg["Subject"] = "New Blue Cross Cats Found"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join([EMAIL_TO_1, EMAIL_TO_2])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)

    print("Email sent.")


def main():
    print("Starting Blue Cross tracker… DEBUG=" + str(DEBUG))
    current = scrape_bluecross()
    previous = load_previous()
    prev_urls = {c["url"] for c in previous}
    new_cats = [c for c in current if c["url"] not in prev_urls]

    print(f"Scraped {len(current)} available cats.")
    print(f"New cats detected: {len(new_cats)}")

    if len(previous) == 0 and len(current) > 0:
        send_email(current)
    else:
        send_email(new_cats)

    save_current(current)


if __name__ == "__main__":
    main()
