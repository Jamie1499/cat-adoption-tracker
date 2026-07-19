import smtplib
from email.mime.text import MIMEText
import os

EMAIL_FROM = os.getenv("EMAIL_FROM")
EMAIL_PASS = os.getenv("EMAIL_PASS")
EMAIL_TO_1 = os.getenv("EMAIL_TO_1")
EMAIL_TO_2 = os.getenv("EMAIL_TO_2")

def send_combined_email(bc_added, bc_removed, bt_added, bt_removed):
    recipients = [r for r in [EMAIL_TO_1, EMAIL_TO_2] if r]

    if not recipients:
        print("No email recipients configured.")
        return

    # Always include both shelters, even if one has no changes
    body = "Cat Adoption Tracker Update\n\n"

    body += "=== Blue Cross ===\n"
    body += f"Added ({len(bc_added)}):\n"
    body += "".join(f"- {c['name']} ({c['url']})\n" for c in bc_added) or "None\n"
    body += f"Removed ({len(bc_removed)}):\n"
    body += "".join(f"- {c['name']} ({c['url']})\n" for c in bc_removed) or "None\n"

    body += "\n\n=== Battersea ===\n"
    body += f"Added ({len(bt_added)}):\n"
    body += "".join(f"- {c['name']} ({c['url']})\n" for c in bt_added) or "None\n"
    body += f"Removed ({len(bt_removed)}):\n"
    body += "".join(f"- {c['name']} ({c['url']})\n" for c in bt_removed) or "None\n"

    msg = MIMEText(body)
    msg["Subject"] = "Cat Adoption Tracker – Updates"
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(recipients)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(EMAIL_FROM, EMAIL_PASS)
        smtp.sendmail(EMAIL_FROM, recipients, msg.as_string())

    print("Combined email sent.")
