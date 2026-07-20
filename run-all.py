#!/usr/bin/env python3
import os
import time
import concurrent.futures
from datetime import datetime

from bluecross_tracker import main as bc_main
from battersea_tracker import main as bt_main
from catchat_tracker import main as cc_main
from email_utils import send_combined_email


def run_all():
    # --- Startup diagnostics visible in GitHub Actions ---
    print("::group::[Run‑All] Workflow startup")
    print(f"[Run‑All] UTC time: {datetime.utcnow().isoformat()}")
    print(f"[Run‑All] Working directory: {os.getcwd()}")
    print("[Run‑All] Files in workspace:")
    for f in os.listdir("."):
        print("   ", f)
    print("::endgroup::")

    start_time = time.time()
    print("[Run‑All] Starting parallel scrapers…")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        print("[Run‑All] Submitting Blue Cross scraper…")
        future_bc = ex.submit(bc_main)

        print("[Run‑All] Submitting Battersea scraper…")
        future_bt = ex.submit(bt_main)

        print("[Run‑All] Submitting CatChat scraper…")
        future_cc = ex.submit(cc_main)

        bc_added, bc_removed = future_bc.result()
        bt_added, bt_removed = future_bt.result()
        cc_added, cc_removed = future_cc.result()

    elapsed = round(time.time() - start_time, 2)
    print(f"[Run‑All] All scrapers finished in {elapsed}s")

    print(f"[Run‑All] Blue Cross added={len(bc_added)} removed={len(bc_removed)}")
    print(f"[Run‑All] Battersea added={len(bt_added)} removed={len(bt_removed)}")
    print(f"[Run‑All] CatChat added={len(cc_added)} removed={len(cc_removed)}")

    if bc_added or bc_removed or bt_added or bt_removed or cc_added or cc_removed:
        print("[Run‑All] Sending email update…")
        send_combined_email(
            bc_added, bc_removed,
            bt_added, bt_removed,
            cc_added, cc_removed
        )
        print("[Run‑All] Email sent.")
    else:
        print("[Run‑All] No changes detected — no email sent.")


if __name__ == "__main__":
    run_all()