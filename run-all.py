#!/usr/bin/env python3
import concurrent.futures

from bluecross_tracker import main as bc_main
from battersea_tracker import main as bt_main
from catchat_tracker import main as cc_main
from email_utils import send_combined_email

def run_all():
    print("[Run-All] Starting parallel scrapers…")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        print("[Run-All] Starting Blue Cross…")
        future_bc = ex.submit(bc_main)

        print("[Run-All] Starting Battersea…")
        future_bt = ex.submit(bt_main)

        print("[Run-All] Starting CatChat…")
        future_cc = ex.submit(cc_main)

        bc_added, bc_removed = future_bc.result()
        bt_added, bt_removed = future_bt.result()
        cc_added, cc_removed = future_cc.result()

    print(f"[Run-All] Blue Cross added={len(bc_added)} removed={len(bc_removed)}")
    print(f"[Run-All] Battersea added={len(bt_added)} removed={len(bt_removed)}")
    print(f"[Run-All] CatChat added={len(cc_added)} removed={len(cc_removed)}")

    if bc_added or bc_removed or bt_added or bt_removed or cc_added or cc_removed:
        print("[Run-All] Sending email update…")
        send_combined_email(
            bc_added, bc_removed,
            bt_added, bt_removed,
            cc_added, cc_removed
        )
        print("[Run-All] Email sent.")
    else:
        print("[Run-All] No changes detected — no email sent.")

if __name__ == "__main__":
    run_all()
