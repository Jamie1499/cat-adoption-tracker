import requests
import json
import os
import smtplib
from email.mime.text import MIMEText

# JSON memory files
FILES = {
    "bluecross": "bluecross_cats.json",
    "battersea": "battersea_cats.json",
    "catsprotection": "catsprotection_cats.json",
    "rspca": "rspca_cats.json"
}

# Email credentials
EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")


# -----------------------------
# API FETCHERS (ADOPTABLE ONLY)
# -----------------------------

def fetch_bluecross():
    """Blue Cross adoptable cats."""
    url = "https://www.bluecross.org.uk/api/pets"
    r = requests.get(url).json()

    cats = []
    for pet in r.get("pets", []):
        if pet.get("species") == "Cat" and pet.get("status") == "Available":
            cats.append({
                "name": pet.get("name"),
                "url": "https://www.bluecross.org.uk" + pet.get("path"),
                "shelter": "Blue Cross"
            })
    return cats


def fetch_battersea():
    """Battersea adoptable cats."""
    url = "https://www.battersea.org.uk/api/pets?species=cat"
    r = requests.get(url).json()

    cats = []
    for pet in r.get("data", []):
        if pet.get("status") == "Available":
            cats.append({
                "name": pet.get("title"),
                "url": "https://www.battersea.org.uk" + pet.get("url"),
                "shelter": "Battersea"
            })
    return cats


def fetch_catsprotection():
    """Cats Protection UK-wide adoptable cats."""
    url = "https://www.cats.org.uk/api/animals"
    r = requests.get(url).json()

    cats = []
    for pet in r.get("animals", []):
        if pet.get("species") == "Cat" and pet.get("availability") == "Available":
            cats.append({
                "name": pet.get("name"),
                "url": pet.get("url"),
                "shelter": "Cats Protection"
            })
    return cats


def fetch_rspca():
    """RSPCA UK-wide adoptable cats."""
    url = "https://www.rspca.org.uk/api/animals"
    r = requests.get(url).json()

    cats = []
    for pet in r.get("animals", []):
        if pet.get("species") == "Cat" and pet.get("available") is True:
            cats.append({
                "name": pet.get("name"),
                "url": pet.get("url"),
                "shelter": "RSPCA"
            })
    return cats


# -----------------------------
# JSON MEMORY HELPERS
# -----------------------------

def load_previous(path):
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        return json.load(f)


def save_current(path, cats):
    with open(path, "w") as f:
        json.dump(cats, f, indent=2)


# -----------------------------
# EMAIL
# -----------------------------

def send_email(new_cats):
    """Send one email listing all new cats grouped by shelter."""
    if not new_cats:
        print("No new cats — no email sent.")
        return

    body = "New Cats Available for Adoption\n\n"

    shelters = {}
    for cat in new_cats:
        shelters.setdefault(cat["shelter"], []).append(cat)

    for shelter, cats in shelters.items():
        body += f"{shelter}:\n"
        for c in cats:
            body += f"- {c['name']} → {c['url']}\n"
        body += "\n"

    msg = MIMEText(body)
    msg["Subject"] = "New Adoptable Cats Found"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join([EMAIL_TO_1, EMAIL_TO_2])

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_FROM, EMAIL_PASS)
        server.send_message(msg)

    print("Email sent.")


# -----------------------------
# MAIN
# -----------------------------

def main():
    print("Fetching cats…")

    current = {
        "bluecross": fetch_bluecross(),
        "battersea": fetch_battersea(),
        "catsprotection": fetch_catsprotection(),
        "rspca": fetch_rspca()
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

    # First run always sends email
    if all(len(load_previous(f)) == 0 for f in FILES.values()):
        print("First run — sending test email.")
        send_email(new_cats)
    else:
        send_email(new_cats)


if __name__ == "__main__":
    main()
