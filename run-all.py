#!/usr/bin/env python3
import os

from bluecross_tracker import main as run_bluecross
from battersea_tracker import main as run_battersea
from email_utils import send_combined_email

NO_EMAIL = os.getenv("NO_EMAIL", "1") == "1"

def main():
    print("Running Blue Cross scraper…")
    bc_added, bc_removed = run_bluecross()

    print("Running Battersea scraper…")
    bt_added, bt_removed = run_battersea()

    print("Blue Cross added:", len(bc_added), "removed:", len(bc_removed))
    print("Battersea added:", len(bt_added), "removed:", len(bt_removed))

    if NO_EMAIL:
        print("NO_EMAIL=1 — skipping combined email.")
        return

    send_combined_email(bc_added, bc_removed, bt_added, bt_removed)

if __name__ == "__main__":
    main()
