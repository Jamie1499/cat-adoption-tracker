#!/usr/bin/env python3
import os
import json
import smtplib
import time
from email.mime.text import MIMEText
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Config
FILE = "bluecross_cats.json"
SITEMAP_URL = "https://www.bluecross.org.uk/sitemap.xml"
USER_AGENT = "bluecross-tracker/1.0 (+https://github.com/yourname)"
REQUEST_TIMEOUT = 15
DEBUG = os.getenv("DEBUG", "0") == "1"

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
    r.raise_for_status()
    return r


def parse_sitemap(xml_text):
    # Lightweight parse for <loc> entries
    from xml.etree import ElementTree as ET
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    root = ET.fromstring(xml_text)
    locs = [el.text for el in root.findall(".//ns:loc", ns)]
    return locs


def collect_pet_urls_from_sitemap(sitemap_url):
    """
    Follow sitemap index and nested sitemaps, return unique /pet/ URLs.
    """
    headers = {"User-Agent": USER_AGENT}
    pet_urls = set()
    try:
        r = requests.get(sitemap_url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        print("Failed to fetch sitemap:", e)
        return []

    locs = parse_sitemap(r.text)
    # If the sitemap is an index (contains sitemap entries), follow them
    # Heuristic: if any loc ends with .xml, treat as nested sitemap
    nested = [u for u in locs if u.endswith(".xml")]
    if nested:
        for ns_url in nested:
            try:
                log("Fetching nested sitemap:", ns_url)
                r2 = requests.get(ns_url, headers=headers, timeout=REQUEST_TIMEOUT)
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


def extract_pet_from_detail(html_text, url):
    """
    Parse a pet detail page and return dict with name, url, shelter, and availability flag.
    Heuristics:
      - Look for <h1> text (common for title)
      - Look for meta property og:title
      - Look for phrases like 'Available for adoption', 'Available', 'Adopt me'
      - If page contains 'This pet has been adopted' or 404-like content, mark unavailable
    """
    soup = BeautifulSoup(html_text, "lxml")

    # Try meta og:title first
    meta_title = soup.find("meta", property="og:title")
    if meta_title and meta_title.get("content"):
        name = meta_title["content"].strip()
    else:
        # Try H1
        h1 = soup.find("h1")
        name = h1.get_text(strip=True) if h1 else None

    # Fallback: title tag
    if not name:
        if soup.title and soup.title.string:
            name = soup.title.string.strip()
        else:
            # fallback to last path segment
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
    ]
    unavailable_phrases = [
        "has been adopted",
        "adopted",
        "no longer available",
        "reserved",
        "under assessment",
        "not available",
    ]

    is_unavailable = any(p in text for p in unavailable_phrases)
    is_available = any(p in text for p in available_phrases) and not is_unavailable

    # Extra check: some pages show a banner or status element
    # Look for common status classes or labels
    status_labels = soup.select(".status, .pet-status, .availability, .adoption-status")
    for lbl in status_labels:
        lbl_text = lbl.get_text(" ", strip=True).lower()
        if any(p in lbl_text for p in unavailable_phrases):
            is_unavailable = True
        if any(p in lbl_text for p in available_phrases):
            is_available = True

    return {
        "name": name,
        "url": url,
        "shelter": "Blue Cross",
        "available": bool(is_available and not is_unavailable)
    }


def scrape_bluecross():
    pet_urls = collect_pet_urls_from_sitemap(SITEMAP_URL)
    log("Found pet URLs in sitemap:", len(pet_urls))
    results = []

    for i, url in enumerate(pet_urls):
        try:
            log(f"[{i+1}/{len(pet_urls)}] Checking {url}")
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                log("404 skipping:", url)
                continue
            r.raise_for_status()
            pet = extract_pet_from_detail(r.text, url)
            if pet["available"]:
                results.append({"name": pet["name"], "url": pet["url"], "shelter": pet["shelter"]})
                log("Available:", pet["name"])
            else:
                log("Not available or filtered out:", pet["name"])
            # Be polite
            time.sleep(0.5)
        except Exception as e:
            log("Error fetching/parsing:", url, e)
            continue

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

    # First run: if previous empty, send all current
    if len(previous) == 0 and len(current) > 0:
        send_email(current)
    else:
        send_email(new_cats)

    save_current(current)


if __name__ == "__main__":
    main()
