import os
import json
import smtplib
from email.mime.text import MIMEText
import cloudscraper
from bs4 import BeautifulSoup

FILE = "bluecross_cats.json"

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")

URL = "https://www.bluecross.org.uk/adopt/cat"


def load_previous():
    if not os.path.exists(FILE):
        return []
    with open(FILE, "r") as f:
        return json.load(f)


def save_current(cats):
    with open(FILE, "w") as f:
        json.dump(cats, f, indent=2)


def scrape_bluecross():
    scraper = cloudscraper.create_scraper(
        browser={
            "browser": "chrome",
            "platform": "windows",
            "mobile": False
        }
    )

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml"
    }

    html = scraper.get(URL, headers=headers).text

    # Debugging: save raw HTML so you can inspect it in GitHub Actions
    with open("debug.html", "w", encoding="utf-8") as f:
        f.write(html)

    soup = BeautifulSoup(html, "html.parser")

    cats = []
    items = soup.select(".views-row")

    for item in items:
        name_el = item.select_one(".field--name-title")
        link_el = item.select_one("a")

        if not name_el or not link_el:
            continue

        name = name_el.get_text(strip=True)
        link = link_el["href"]

        # Ensure full URL
        if link.startswith("/"):
            link = "https://www.bluecross.org.uk" + link

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
    print("Starting Blue Cross tracker…")

    current = scrape_bluecross()
    previous = load_previous()

    prev_urls = {c["url"] for c in previous}
    new_cats = [c for c in current if c["url"] not in prev_urls]

    print(f"Total new cats: {len(new_cats)}")

    # First run → send all cats
    if len(previous) == 0:
        send_email(current)
    else:
        send_email(new_cats)

    save_current(current)


if __name__ == "__main__":
    main()
