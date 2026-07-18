import os
import json
import smtplib
from email.mime.text import MIMEText
import requests
import xml.etree.ElementTree as ET

FILE = "bluecross_cats.json"

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")


def load_previous():
    if not os.path.exists(FILE):
        return []
    with open(FILE, "r") as f:
        return json.load(f)


def save_current(cats):
    with open(FILE, "w") as f:
        json.dump(cats, f, indent=2)


def scrape_bluecross_sitemap():
    url = "https://www.bluecross.org.uk/sitemap.xml"
    r = requests.get(url)
    r.raise_for_status()

    root = ET.fromstring(r.text)

    cats = []
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

    for loc in root.findall(".//ns:loc", ns):
        link = loc.text

        # Only pet pages
        if "/pet/" not in link:
            continue

        # Only cats (Blue Cross uses /pet/<name>-<id>)
        # We detect cats by checking the page content later if needed,
        # but for now we include all pet pages.
        name = link.split("/")[-1].replace("-", " ").title()

        cats.append({
            "name": name,
            "url": link,
            "shelter": "Blue Cross"
        })

    return cats


def send_email(new_cats):
    if not new_cats:
        print("No new cats — no email sent.")
        return

    body = "New Blue Cross Cats Detected\n\n"

    for c in new_cats:
        body += f"- {c['name']} → {c['url']}\n"

    msg = MIMEText(body)
    msg["Subject"] = "New Blue Cross Cats"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join([EMAIL_TO_1, EMAIL_TO_2])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)

    print("Email sent.")


def main():
    print("Starting Blue Cross tracker…")

    current = scrape_bluecross_sitemap()
    previous = load_previous()

    prev_urls = {c["url"] for c in previous}
    new_cats = [c for c in current if c["url"] not in prev_urls]

    print(f"Scraped {len(current)} pet pages.")
    print(f"New cats detected: {len(new_cats)}")

    # First run → send all cats
    if len(previous) == 0:
        send_email(current)
    else:
        send_email(new_cats)

    save_current(current)


if __name__ == "__main__":
    main()
