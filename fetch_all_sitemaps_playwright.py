#!/usr/bin/env python3
"""
bluecross_playwright_scraper.py

Fetches the rendered Blue Cross cat listing page using Playwright,
extracts all cat cards (<article class="m-pet-listing-item_wrapper">),
and saves available cats (non-reserved) to bluecross_cats.json.
"""

import os
import json
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUT_FILE = os.getenv("OUT_FILE", "bluecross_cats.json")
URL = os.getenv("URL", "https://www.bluecross.org.uk/rehome/cat")
HEADFUL = os.getenv("HEADFUL", "0") == "1"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"


def ts():
    return datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M:%S UTC]")


def log(*args):
    print(ts(), *args)


def extract_cats(html):
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("article.m-pet-listing-item_wrapper")
    cats = []

    for card in cards:
        link = card.select_one("a.m-pet-listing-item")
        if not link:
            continue
        url = "https://www.bluecross.org.uk" + link["href"]

        name_tag = card.select_one("h3.m-pet-listing-item__title")
        name = name_tag.get_text(strip=True) if name_tag else "Unknown"

        reserved = card.select_one("div.m-pet-listing-item_reserved") is not None
        if reserved:
            continue  # skip reserved cats

        cats.append({
            "id": url.rstrip("/"),
            "name": name,
            "url": url,
            "available": True,
        })

    return cats


def main():
    log("Starting Blue Cross Playwright scraper")
    log("Target URL:", URL)
    log("Headful:", HEADFUL)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADFUL)
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()

        log("Loading page…")
        page.goto(URL, wait_until="networkidle")
        html = page.content()
        browser.close()

    cats = extract_cats(html)
    log(f"Found {len(cats)} available cats")

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(cats, f, indent=2, ensure_ascii=False)

    log("Saved to", OUT_FILE)
    return 0


if __name__ == "__main__":
    main()