import requests
from bs4 import BeautifulSoup
import json
import os
import smtplib
from email.mime.text import MIMEText

# URLs
BLUECROSS_URL = "https://www.bluecross.org.uk/pet/cat"
BATTERSEA_URL = "https://www.battersea.org.uk/cats/cat-rehoming-gallery"

# Data files
BLUECROSS_FILE = "bluecross_cats.json"
BATTERSEA_FILE = "battersea_cats.json"

# Email credentials (GitHub Actions secrets)
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")


def send_email(new_bluecross, new_battersea, forced=False):
    """Send a single email listing new cats from both shelters to two recipients."""
    body = ""

    if forced:
        body += "Test email: forced send to verify setup.\n\n"

    if new_bluecross:
        body += "New Blue Cross Cats:\n"
        for c in new_bluecross:
            body += f"- {c['name']} → {c['url']}\n"
        body += "\n"

    if new_battersea:
        body += "New Battersea Cats:\n"
        for c in new_battersea:
            body += f"- {c['name']} → {c['url']}\n"
        body += "\n"

    if not body.strip():
        body = "No new cats, but sending test email so you know it works."

    msg = MIMEText(body)
    msg["Subject"] = "New Cats Added (Blue Cross + Battersea)"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join([EMAIL_TO_1, EMAIL_TO_2])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)


# -----------------------------
# Scrapers (updated + working)
# -----------------------------

def fetch_bluecross():
    """Scrape Blue Cross cat listings."""
    print("Scraping Blue Cross…")
    response = requests.get(BLUECROSS_URL)
    soup = BeautifulSoup(response.text, "html.parser")

    cats = []
    cards = soup.select("article.pet-card")

    for card in cards:
        name_tag = card.select_one(".pet-card__title")
        link_tag = card.select_one("a")

        if not name_tag or not link_tag:
            continue

        cats.append({
            "name": name_tag.get_text(strip=True),
            "url": "https://www.bluecross.org.uk" + link_tag["href"]
        })

    print(f"Found {len(cats)} Blue Cross cats.")
    return cats


def fetch_battersea():
    """Scrape Battersea cat listings."""
    print("Scraping Battersea…")
    response = requests.get(BATTERSEA_URL)
    soup = BeautifulSoup(response.text, "html.parser")

    cats = []
    cards = soup.select("div.views-row")

    for card in cards:
        name_tag = card.select_one(".title")
        link_tag = card.select_one("a")

        if not name_tag or not link_tag:
            continue

        cats.append({
            "name": name_tag.get_text(strip=True),
            "url": "https://www.battersea.org.uk" + link_tag["href"]
        })

    print(f"Found {len(cats)} Battersea cats.")
    return cats


# -----------------------------
# Storage helpers
# -----------------------------

def load_previous(path):
    if not os.path.exists(path):
        print(f"{path} does not exist yet.")
        return []
    with open(path, "r") as f:
        return json.load(f)


def save_current(path, cats):
    with open(path, "w") as f:
        json.dump(cats, f, indent=2)
    print(f"Saved {len(cats)} cats to {path}")


# -----------------------------
# Main
# -----------------------------

def main():
    print("Starting cat scraper…")

    # Fetch current cats
    bc_current = fetch_bluecross()
    bt_current = fetch_battersea()

    # Load previous
    bc_previous = load_previous(BLUECROSS_FILE)
    bt_previous = load_previous(BATTERSEA_FILE)

    # Detect new cats
    bc_old_urls = {c["url"] for c in bc_previous}
    bt_old_urls = {c["url"] for c in bt_previous}

    new_bluecross = [c for c in bc_current if c["url"] not in bc_old_urls]
    new_battersea = [c for c in bt_current if c["url"] not in bt_old_urls]

    print(f"New Blue Cross cats: {len(new_bluecross)}")
    print(f"New Battersea cats: {len(new_battersea)}")

    # FORCE EMAIL ON FIRST RUN
    if not bc_previous and not bt_previous:
        print("First run detected — forcing test email.")
        send_email(new_bluecross, new_battersea, forced=True)
    else:
        if new_bluecross or new_battersea:
            print("Sending email with new cats.")
            send_email(new_bluecross, new_battersea)
        else:
            print("No new cats — no email sent.")

    # Save updated lists
    save_current(BLUECROSS_FILE, bc_current)
    save_current(BATTERSEA_FILE, bt_current)

    print("Done.")


if __name__ == "__main__":
    main()
