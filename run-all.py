#!/usr/bin/env python3
import concurrent.futures
from bluecross_tracker import main as bc_main
from battersea_tracker import main as bt_main
from email_utils import send_combined_email

def run_all():
    print("Starting parallel scrapers…")

    # Run Blue Cross + Battersea at the same time
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        future_bc = ex.submit(bc_main)
        future_bt = ex.submit(bt_main)

        bc_added, bc_removed = future_bc.result()
        bt_added, bt_removed = future_bt.result()

    print(f"Blue Cross added: {len(bc_added)} removed: {len(bc_removed)}")
    print(f"Battersea added: {len(bt_added)} removed: {len(bt_removed)}")

    # Only send email if there are actual changes
    if bc_added or bc_removed or bt_added or bt_removed:
        print("Sending email update…")
        send_combined_email(bc_added, bc_removed, bt_added, bt_removed)
    else:
        print("No changes detected — no email sent.")

if __name__ == "__main__":
    run_all()