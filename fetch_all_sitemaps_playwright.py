#!/usr/bin/env python3
"""
fetch_all_sitemaps_playwright.py

Robust sitemap index fetcher using Playwright. Behavior:
  - Fetches a root sitemap URL (default https://www.bluecross.org.uk/sitemap.xml).
  - Parses all <loc> entries from the root sitemap.
  - Fetches every nested sitemap URL found (including query strings like ?page=1).
  - Saves each fetched sitemap into OUT_DIR with a safe filename that includes query info.
  - Uses Playwright's browser to solve JS challenges; falls back to request.get() when appropriate.
  - Emits clear logs and returns nonzero exit codes on failure.

Usage:
  python fetch_all_sitemaps_playwright.py

Environment variables:
  URL            -> override default sitemap URL
  OUT_DIR        -> output directory (default "sitemaps")
  HEADFUL        -> "1" to run browser headful for debugging (default headless)
  NAV_TIMEOUT_MS -> navigation timeout in milliseconds (default 180000)
  REQUEST_TIMEOUT_MS -> request.get() timeout in ms (default 60000)
"""
import os
import sys
import time
import re
import json
from urllib.parse import urlparse, quote_plus
import xml.etree.ElementTree as ET

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except Exception as e:
    print("Playwright is not installed or not available in this environment.")
    print("Install with: pip install playwright && python -m playwright install")
    raise

URL = os.getenv("URL", "https://www.bluecross.org.uk/sitemap.xml")
OUT_DIR = os.getenv("OUT_DIR", "sitemaps")
HEADFUL = os.getenv("HEADFUL", "0") == "1"
NAV_TIMEOUT_MS = int(os.getenv("NAV_TIMEOUT_MS", str(180000)))
REQUEST_TIMEOUT_MS = int(os.getenv("REQUEST_TIMEOUT_MS", str(60000)))

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"

os.makedirs(OUT_DIR, exist_ok=True)

def safe_filename_from_url(u: str) -> str:
    """
    Create a filesystem-safe filename for a URL, preserving query info to avoid collisions.
    Examples:
      https://.../sitemap.xml?page=1 -> sitemap.xml_page=1
      https://.../nested/sitemap-index.xml -> sitemap-index.xml
    """
    p = urlparse(u)
    base = os.path.basename(p.path) or "sitemap"
    # sanitize base
    base = re.sub(r'[^A-Za-z0-9._-]', '_', base)
    if p.query:
        q = p.query.replace("=", "_").replace("&", "_")
        q = re.sub(r'[^A-Za-z0-9._-]', '_', q)
        return f"{base}__{q}"
    return base

def looks_like_xml(text: str) -> bool:
    t = text.lstrip()
    return t.startswith("<?xml") or t.startswith("<urlset") or t.startswith("<sitemapindex")

def parse_locs_from_xml_bytes(b: bytes):
    try:
        root = ET.fromstring(b)
    except Exception:
        # try decode and parse
        try:
            root = ET.fromstring(b.decode("utf-8", errors="replace"))
        except Exception:
            return []
    ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = []
    for el in root.findall(".//ns:loc", ns):
        if el is not None and el.text:
            locs.append(el.text.strip())
    # fallback: any <loc> without namespace
    if not locs:
        for el in root.findall(".//loc"):
            if el is not None and el.text:
                locs.append(el.text.strip())
    return locs

def save_bytes(path: str, data: bytes):
    with open(path, "wb") as f:
        f.write(data)

def save_text(path: str, text: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

def fetch_with_playwright(page, target_url: str, out_path: str) -> dict:
    """
    Try to fetch target_url using Playwright page/request APIs.
    Returns dict with keys: ok (bool), status (int|None), saved_as (path), reason (str)
    """
    print(f"[fetch] {target_url} -> {out_path}")
    # Try request.get first (faster, doesn't render)
    try:
        resp = page.request.get(target_url, timeout=REQUEST_TIMEOUT_MS)
        if resp.ok:
            body = resp.body()
            save_bytes(out_path, body)
            print(f"[fetch] saved (request.get) {len(body)} bytes")
            return {"ok": True, "status": resp.status, "saved_as": out_path, "method": "request.get"}
        else:
            print(f"[fetch] request.get returned status {resp.status}; falling back to navigation")
    except Exception as e:
        print(f"[fetch] request.get failed: {e}; falling back to navigation")

    # Fallback: navigate (handles JS challenges)
    try:
        resp_nav = None
        try:
            resp_nav = page.goto(target_url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            print("[fetch] navigation (networkidle) returned")
        except PWTimeout:
            print("[fetch] networkidle timed out; trying domcontentloaded")
            try:
                resp_nav = page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                print("[fetch] navigation (domcontentloaded) returned")
            except PWTimeout:
                print("[fetch] domcontentloaded timed out; will capture page.content()")
        except Exception as e:
            print("[fetch] navigation raised:", repr(e))

        if resp_nav:
            try:
                body = resp_nav.body()
                save_bytes(out_path, body)
                print(f"[fetch] saved (nav response.body) {len(body)} bytes")
                return {"ok": True, "status": getattr(resp_nav, "status", None), "saved_as": out_path, "method": "navigation"}
            except Exception as e:
                print("[fetch] failed to read resp_nav.body():", e)
                content = page.content()
                save_text(out_path, content)
                print("[fetch] saved page.content() fallback")
                return {"ok": True, "status": getattr(resp_nav, "status", None), "saved_as": out_path, "method": "navigation_fallback"}
        else:
            # No response object: save page content and return failure
            content = page.content()
            save_text(out_path, content)
            print("[fetch] no response object; saved page.content()")
            return {"ok": False, "status": None, "saved_as": out_path, "method": "no_response"}
    except Exception as e:
        print("[fetch] navigation fallback failed:", repr(e))
        return {"ok": False, "status": None, "saved_as": None, "reason": str(e)}

def main():
    print("Starting sitemap fetcher")
    print("Root URL:", URL)
    print("Output dir:", OUT_DIR)
    print("Headful:", HEADFUL)
    print("Nav timeout (ms):", NAV_TIMEOUT_MS)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=not HEADFUL)
            context = browser.new_context(user_agent=USER_AGENT)
            page = context.new_page()

            # 1) Fetch root sitemap
            root_fname = safe_filename_from_url(URL)
            root_out = os.path.join(OUT_DIR, root_fname)
            result = fetch_with_playwright(page, URL, root_out)
            if not result.get("ok"):
                print("Failed to fetch root sitemap; inspect", root_out)
                # still attempt to parse whatever was saved
            # 2) Parse root sitemap for locs
            try:
                with open(root_out, "rb") as f:
                    data = f.read()
            except FileNotFoundError:
                print("Root sitemap file not found; aborting.")
                browser.close()
                return 2

            locs = parse_locs_from_xml_bytes(data)
            print(f"Found {len(locs)} <loc> entries in root sitemap.")
            # Deduplicate and keep order
            seen = set()
            locs_unique = []
            for u in locs:
                if u not in seen:
                    seen.add(u)
                    locs_unique.append(u)

            # 3) For each loc that looks like a sitemap (endswith .xml or contains ?page=), fetch it
            nested_to_fetch = []
            for u in locs_unique:
                if u.lower().endswith(".xml") or ("?page=" in u) or ("/sitemap" in u.lower()):
                    nested_to_fetch.append(u)
            print(f"Will fetch {len(nested_to_fetch)} nested sitemap URLs (candidates).")

            fetched = []
            for u in nested_to_fetch:
                fname = safe_filename_from_url(u)
                out_path = os.path.join(OUT_DIR, fname)
                # If file exists and looks like XML, skip (idempotent)
                if os.path.exists(out_path):
                    try:
                        with open(out_path, "rb") as f:
                            sample = f.read(512)
                        if looks_like_xml(sample.decode("utf-8", errors="replace")):
                            print(f"[skip] {u} -> {out_path} (already exists and looks like XML)")
                            fetched.append({"url": u, "saved_as": out_path, "skipped": True})
                            continue
                    except Exception:
                        pass
                res = fetch_with_playwright(page, u, out_path)
                fetched.append({"url": u, **res})
                # small polite pause
                time.sleep(0.5)

            # 4) Optionally, parse nested sitemaps for further nested .xml links and fetch them too
            # (two-level deep)
            extra = []
            for item in fetched:
                path = item.get("saved_as")
                if not path or not os.path.exists(path):
                    continue
                try:
                    with open(path, "rb") as f:
                        b = f.read()
                    locs2 = parse_locs_from_xml_bytes(b)
                    for u2 in locs2:
                        if u2 not in seen and (u2.lower().endswith(".xml") or ("?page=" in u2) or ("/sitemap" in u2.lower())):
                            seen.add(u2)
                            extra.append(u2)
                except Exception:
                    continue

            if extra:
                print(f"Found {len(extra)} additional nested sitemap URLs; fetching them.")
                for u in extra:
                    fname = safe_filename_from_url(u)
                    out_path = os.path.join(OUT_DIR, fname)
                    if os.path.exists(out_path):
                        try:
                            with open(out_path, "rb") as f:
                                sample = f.read(512)
                            if looks_like_xml(sample.decode("utf-8", errors="replace")):
                                print(f"[skip] {u} -> {out_path} (already exists and looks like XML)")
                                continue
                        except Exception:
                            pass
                    res = fetch_with_playwright(page, u, out_path)
                    time.sleep(0.5)

            # 5) Summary
            print("Fetch summary:")
            print(json.dumps(fetched, indent=2, ensure_ascii=False))
            browser.close()
            return 0
    except Exception as exc:
        print("Fatal error:", repr(exc))
        return 10

if __name__ == "__main__":
    rc = main()
    sys.exit(rc)