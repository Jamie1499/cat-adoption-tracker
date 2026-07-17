import os
import json
import smtplib
from email.mime.text import MIMEText
import requests
from playwright.sync_api import sync_playwright

FILES = {
    "bluecross": "bluecross_cats.json",
    "battersea": "battersea_cats.json",
    "catsprotection": "catsprotection_cats.json",
    "rspca": "rspca_cats.json",
}

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")


def load_previous(path):
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def save_current(path, cats):
    with open(path, "w") as f:
        json.dump(cats, f, indent=2)


# -------------------------
# BLUE CROSS (JSON API)
# -------------------------

def scrape_bluecross_json():
    url = "https://www.bluecross.org.uk/api/pets?species=cat"
    try:
        r = requests.get(url).json()
    except:
        return []

    cats = []
    for pet in r.get("pets", []):
        cats.append({
            "name": pet.get("name"),
            "url": "https://www.bluecross.org.uk" + pet.get("path"),
            "shelter": "Blue Cross"
        })
    return cats


# -------------------------
# PLAYWRIGHT SCRAPERS
# -------------------------

def scrape_battersea(page):
    page.goto("https://www.battersea.org.uk/cats/cat-rehoming-gallery", wait_until="networkidle")
    page.wait_for_timeout(3000)

    cats = []
    cards = page.query_selector_all("article, .views-row, .cat-card")

    for card in cards:
        name_el = card.query_selector("h3, .title, .field--name-title")
        link_el = card.query_selector("a")

        if not name_el or not link_el:
            continue

        name = name_el.inner_text().strip()
        url = link_el.get_attribute("href")

        if not url.startswith("http"):
            url = "https://www.battersea.org.uk" + url

        cats.append({"name": name, "url": url, "shelter": "Battersea"})

    return cats


def scrape_catsprotection(page):
    page.goto("https://www.cats.org.uk/adopt-a-cat", wait_until="networkidle")
    page.wait_for_timeout(3000)

    cats = []
    cards = page.query_selector_all(".animal-card, article, .card")

    for card in cards:
        name_el = card.query_selector("h3, .animal-name")
        link_el = card.query_selector("a")

        if not name_el or not link_el:
            continue

        name = name_el.inner_text().strip()
        url = link_el.get_attribute("href")

        if not url.startswith("http"):
            url = "https://www.cats.org.uk" + url

        cats.append({"name": name, "url": url, "shelter": "Cats Protection"})

    return cats


def scrape_rspca(page):
    page.goto("https://www.rspca.org.uk/findapet", wait_until="networkidle")
    page.wait_for_timeout(3000)

    cats = []
    cards = page.query_selector_all(".animal-card, .result, article")

    for card in cards:
        species_el = card.query_selector(".species, .animal-type")
        if species_el and "cat" not in species_el.inner_text().lower():
            continue

        name_el = card.query_selector("h3, .animal-name")
        link_el = card.query_selector("a")

        if not name_el or not link_el:
            continue

        name = name_el.inner_text().strip()
        url = link_el.get_attribute("href")

        if not url.startswith("http"):
            url = "https://www.rspca.org.uk" + url

        cats.append({"name": name, "url": url, "shelter": "RSPCA"})

    return cats


# -------------------------
# EMAIL (FLAT LIST)
# -------------------------

def send_email(new_cats):
    if not new_cats:
        print("No new cats — no email sent.")
        return

    body = "New Cats Available for Adoption\n\n"

    for c in new_cats:
        body += f"- {c['name']} ({c['shelter']}) → {c['url']}\n"

    msg = MIMEText(body)
    msg["Subject"] = "New Cats Found"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join([EMAIL_TO_1, EMAIL_TO_2])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)

    print("Email sent.")


# -------------------------
# MAIN
# -------------------------

def main():
    print("Starting cat tracker…")

    # Blue Cross via JSON
    bluecross = scrape_bluecross_json()

    # Playwright for the rest
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        battersea = scrape_battersea(page)
        catsprotection = scrape_catsprotection(page)
        rspca = scrape_rspca(page)

        browser.close()

    current = {
        "bluecross": bluecross,
        "battersea": battersea,
        "catsprotection": catsprotection,
        "rspca": rspca,
    }

    new_cats = []

    for shelter, cats in current.items():
        prev = load_previous(FILES[shelter])
        prev_urls = {c["url"] for c in prev}

        for cat in cats:
            if cat["url"] not in prev_urls:
                new_cats.append(cat)

        save_current(FILES[shelter], cats)

    print(f"Total new cats: {len(new_cats)}")

    # First run: send all cats
    if all(len(load_previous(f)) == 0 for f in FILES.values()):
        send_email(sum(current.values(), []))
    else:
        send_email(new_cats)


if __name__ == "__main__":
    main()
