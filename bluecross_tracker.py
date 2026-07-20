#!/usr/bin/env python3
import os
import json
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

FILE = os.path.join(os.path.dirname(__file__), "bluecross_cats.json")
DEBUG = os.getenv("DEBUG", "1") == "1"

# Real Chrome user agent
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BASE_URL = "https://www.bluecross.org.uk/rehome/cat"


def ts():
    return datetime.now(timezone.utc).strftime("[%Y-%m-%d %H:%M:%S UTC]")


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
    prev_map = {(c.get("id") or c.get("url")): c for c in previous}
    now = datetime.now(timezone.utc).isoformat()

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

def fetch_rendered_html(url):
    log("Launching Playwright (headful, anti‑bot)…")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins",
                "--disable-site-isolation-trials",
                "--disable-infobars",
                "--window-size=1280,800",
            ]
        )

        context = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
        )

        page = context.new_page()

        log("Loading Blue Cross page…")
        page.goto(url, wait_until="networkidle", timeout=60000)

        # Hydrated DOM (the real one)
        html = page.evaluate("() => document.documentElement.outerHTML")

        browser.close()
        return html


def extract_cats_from_html(html):
    soup = BeautifulSoup(html, "lxml")

    # Correct selector
    cards = soup.select("article.m-pet-listing-item__wrapper")
    results = []

    for card in cards:
        # Correct link selector
        link = card.select_one("a.m-pet-listing-item")
        if not link:
            continue

        url = "https://www.bluecross.org.uk" + link["href"]

        # Correct name selector
        name_tag = card.select_one("h4.m-pet-listing-item__content--title")
        name = name_tag.get_text(strip=True) if name_tag else "Unknown"

        # Reserved cats are not marked in the listing grid
        reserved = False

        results.append({
            "id": url.rstrip("/"),
            "name": name,
            "url": url,
            "available": not reserved,
        })

    return results



def scrape_bluecross():
    log("Fetching rendered Blue Cross cat listing…")
    html = fetch_rendered_html(BASE_URL)
    cats = extract_cats_from_html(html)
    log(f"Total available cats: {len(cats)}")
    return cats


# MAIN
def main():
    print(ts(), "Starting Blue Cross tracker…")

    previous = load_previous()
    current = scrape_bluecross()

    cats_only = current  # Only available cats

    added, removed, still_here = diff_cats(previous, cats_only)
    final = added + still_here
    save_final(final)

    print(ts(), f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")
    return added, removed


if __name__ == "__main__":
    main()
