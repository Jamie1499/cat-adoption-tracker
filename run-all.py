import logging
from datetime import datetime

from scrapers.catchat import scrape_catchat
from scrapers.battersea import scrape_battersea
from scrapers.bluecross import scrape_bluecross

from database import load_previous, save_current
from emailer import send_combined_email

logging.basicConfig(
    filename="scraper.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

MIN_RESULTS = 10  # minimum acceptable listings per site

def log(msg):
    print(msg)
    logging.info(msg)

def safe_scrape(name, fn):
    log(f"{name}: Starting scrape…")

    try:
        results = fn()

        if results is None:
            log(f"{name}: Returned None — marking as unhealthy")
            return None

        if len(results) == 0:
            log(f"{name}: Returned 0 results — marking as unhealthy")
            return None

        if len(results) < MIN_RESULTS:
            log(f"{name}: Suspiciously low result ({len(results)}) — marking as unhealthy")
            return None

        log(f"{name}: Healthy — {len(results)} listings")
        return results

    except Exception as e:
        log(f"{name}: EXCEPTION — {e}")
        return None


def diff(previous, current):
    prev_ids = set(previous.keys())
    curr_ids = set(current.keys())

    added = curr_ids - prev_ids
    removed = prev_ids - curr_ids
    still_here = curr_ids & prev_ids

    return added, removed, still_here


def run():
    log("Starting parallel scrapers…")

    catchat = safe_scrape("CatChat", scrape_catchat)
    battersea = safe_scrape("Battersea", scrape_battersea)
    bluecross = safe_scrape("Blue Cross", scrape_bluecross)

    scrapers = {
        "catchat": catchat,
        "battersea": battersea,
        "bluecross": bluecross
    }

    # If ANY scraper is unhealthy → skip updates + skip email
    if any(v is None for v in scrapers.values()):
        log("One or more scrapers unhealthy — SKIPPING database update and email send")
        return

    previous = load_previous()

    combined_current = {
        **{f"catchat_{c['id']}": c for c in catchat},
        **{f"battersea_{c['id']}": c for c in battersea},
        **{f"bluecross_{c['id']}": c for c in bluecross},
    }

    added, removed, still_here = diff(previous, combined_current)

    log(f"Added: {len(added)}, Removed: {len(removed)}, Still here: {len(still_here)}")

    # MASS REMOVAL PROTECTION
    if len(removed) > 20:
        log("Mass removal detected — likely scraper failure — SKIPPING email + SKIPPING save")
        return

    save_current(combined_current)

    log("Sending email update…")
    send_combined_email(
        [combined_current[a] for a in added if a.startswith("bluecross_")],
        [combined_current[r] for r in removed if r.startswith("bluecross_")],
        [combined_current[a] for a in added if a.startswith("battersea_")],
        [combined_current[r] for r in removed if r.startswith("battersea_")],
        [combined_current[a] for a in added if a.startswith("catchat_")],
        [combined_current[r] for r in removed if r.startswith("catchat_")],
    )
    log("Combined email sent.")

if __name__ == "__main__":
    run()