import smtplib
from email.mime.text import MIMEText
import os

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")

def format_section(title, added, removed):
    body = f"=== {title} ===\n"

    # Added
    body += f"Added ({len(added)}):\n"
    if added:
        body += "".join(f"- {c['name']} {c['url']}\n" for c in added)
    else:
        body += "None\n"

    # Removed
    body += f"\nRemoved ({len(removed)}):\n"
    if removed:
        body += "".join(f"- {c['name']} {c['url']}\n" for c in removed)
    else:
        body += "None\n"

    return body + "\n\n"

def send_combined_email(bc_added, bc_removed, bt_added, bt_removed, cc_added, cc_removed):
    recipients = [r for r in [EMAIL_TO_1, EMAIL_TO_2] if r]

    if not recipients:
        print("No email recipients configured.")
        return

    body = "Cat Adoption Tracker Update\n\n"

    body += format_section("Blue Cross", bc_added, bc_removed)
    body += format_section("Battersea", bt_added, bt_removed)
    body += format_section("CatChat", cc_added, cc_removed)

    msg = MIMEText(body)
    msg["Subject"] = "Cat Adoption Tracker – Updates"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASS)
        smtp.sendmail(EMAIL_FROM, recipients, msg.as_string())

    print("Combined email sent.")