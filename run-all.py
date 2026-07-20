#!/usr/bin/env python3
import os
import time
import concurrent.futures
from datetime import datetime

from bluecross_tracker import main as bc_main
from battersea_tracker import main as bt_main
from catchat_tracker import main as cc_main
from email_utils import send_combined_email


def ts():
    """Return a timestamp prefix for logs."""
    return datetime.utcnow().strftime("[%Y-%m-%d %H:%M:%S UTC]")


def run_all():
    # --- Startup diagnostics visible in GitHub Actions ---
    print(f"{ts()} ::group::[Run‑All] Workflow startup")
    print(f"{ts()} [Run‑All] UTC time: {datetime.utcnow().isoformat()}")
    print(f"{ts()} [Run‑All] Working directory: {os.getcwd()}")
    print(f"{ts()} [Run‑All] Files in workspace:")
    for f in os.listdir("."):
        print(f"{ts()}    {f}")
    print(f"{ts()} ::endgroup::")

    start_time = time.time()
    print(f"{ts()} [Run‑All] Starting parallel scrapers…")

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        print(f"{ts()} [Run‑All] Submitting Blue Cross scraper…")
        future_bc = ex.submit(bc_main)

        print(f"{ts()} [Run‑All] Submitting Battersea scraper…")
        future_bt = ex.submit(bt_main)

        print(f"{ts()} [Run‑All] Submitting CatChat scraper…")
        future_cc = ex.submit(cc_main)

        print(f"{ts()} [Run‑All] Waiting for scraper results…")
        bc_added, bc_removed = future_bc.result()
        bt_added, bt_removed = future_bt.result()
        cc_added, cc_removed = future_cc.result()

    elapsed = round(time.time() - start_time, 2)
    print(f"{ts()} [Run‑All] All scrapers finished in {elapsed}s")

    print(f"{ts()} [Run‑All] Blue Cross added={len(bc_added)} removed={len(bc_removed)}")
    print(f"{ts()} [Run‑All] Battersea added={len(bt_added)} removed={len(bt_removed)}")
    print(f"{ts()} [Run‑All] CatChat added={len(cc_added)} removed={len(cc_removed)}")

    if bc_added or bc_removed or bt_added or bt_removed or cc_added or cc_removed:
        print(f"{ts()} [Run‑All] Sending email update…")
        send_combined_email(
            bc_added, bc_removed,
            bt_added, bt_removed,
            cc_added, cc_removed
        )
        print(f"{ts()} [Run‑All] Email sent.")
    else:
        print(f"{ts()} [Run‑All] No changes detected — no email sent.")


if __name__ == "__main__":
    run_all()