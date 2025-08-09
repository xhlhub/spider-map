import argparse
import csv
import logging
import random
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape Google Maps business info (name, address, phone) using Playwright.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--region", required=True, help="Region text, e.g. 洛杉矶 or Los Angeles")
    parser.add_argument("--category", required=True, help="Business category, e.g. 修车店 or car repair")
    parser.add_argument("--out", default="output.csv", help="Output CSV file path")
    parser.add_argument("--max-results", type=int, default=150, help="Max places to visit from the list")
    parser.add_argument("--headless", type=lambda v: v.lower() != "false", default=True, help="Run headless browser (true/false)")
    parser.add_argument("--proxy", default="", help="Proxy server, e.g. http://user:pass@host:port or socks5://host:port")
    parser.add_argument("--lang", default="zh-CN,zh;q=0.9,en;q=0.8", help="Accept-Language header value")
    parser.add_argument("--include-without-phone", action="store_true", help="Include rows without phone numbers")
    parser.add_argument("--slowmo", type=int, default=0, help="Slow down actions (ms) for debug")
    parser.add_argument("--log-level", default="INFO", help="Logging level: DEBUG/INFO/WARNING/ERROR")
    return parser.parse_args()


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(message)s",
    )


def random_human_delay(min_s: float = 0.4, max_s: float = 1.2) -> None:
    time.sleep(random.uniform(min_s, max_s))


def normalize_phone_candidates(text: str) -> List[str]:
    # Extract phone-like sequences; then clean and filter by length
    # This aims to catch: +1 310-555-1212, (310) 555-1212, 310 555 1212, +86 10 88888888, etc.
    candidates = re.findall(r"\+?\d[\d\-\s\(\)]{6,}\d", text)
    cleaned: List[str] = []
    for raw in candidates:
        digits = re.sub(r"[^\d+]", "", raw)
        if len(re.sub(r"[^\d]", "", digits)) < 7:
            continue
        cleaned.append(re.sub(r"\s+", " ", raw).strip())
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for num in cleaned:
        key = re.sub(r"[^\d]", "", num)
        if key in seen:
            continue
        seen.add(key)
        unique.append(num)
    return unique


def try_accept_consent(page) -> None:
    # Try multiple strategies including iframes
    try:
        # Common selectors
        for sel in [
            "button:has-text('I agree')",
            "button:has-text('I Agree')",
            "button:has-text('Accept all')",
            "button:has-text('Accept All')",
            "button:has-text('同意')",
            "button:has-text('同意并继续')",
            "button:has-text('接受全部')",
        ]:
            btn = page.locator(sel)
            try:
                if btn.count() > 0:
                    btn.first.wait_for(state="visible", timeout=1000)
                    btn.first.click()
                    random_human_delay(0.5, 1.0)
                    return
            except Exception:
                pass
    except Exception:
        pass
    # Check frames (consent sometimes in an iframe)
    try:
        for frame in page.frames:
            for sel in [
                "button:has-text('I agree')",
                "button:has-text('Accept all')",
                "button:has-text('同意')",
            ]:
                el = frame.locator(sel)
                try:
                    if el.count() > 0:
                        el.first.wait_for(state="visible", timeout=1000)
                        el.first.click()
                        random_human_delay(0.5, 1.0)
                        return
                except Exception:
                    pass
    except Exception:
        pass


def wait_for_search_results(page, timeout_ms: int = 20000) -> None:
    # Wait for the left result list or any result cards to appear
    candidates = [
        "div[role='feed']",
        "div[aria-label$='results']",
        "div[aria-label$='结果']",
        "div.Nv2PK",  # individual cards
        "div[role='article']",
    ]
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for sel in candidates:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.wait_for(state="visible", timeout=5000)
                        return
                    except Exception:
                        pass
            except Exception:
                pass
        time.sleep(0.3)
    raise PlaywrightTimeoutError("Search results did not appear in time")


def perform_search(page, query: str) -> None:
    # Common input selectors on Google Maps
    selectors = [
        "input#searchboxinput",
        "input[aria-label='Search Google Maps']",
        "input[aria-label='在 Google 地图中搜索']",
    ]
    for sel in selectors:
        try:
            box = page.locator(sel)
            if box.count() > 0:
                try:
                    box.first.wait_for(state="visible", timeout=3000)
                except Exception:
                    continue
                box.first.fill("")
                random_human_delay(0.2, 0.5)
                box.first.type(query, delay=random.randint(50, 120))
                random_human_delay(0.2, 0.5)
                box.first.press("Enter")
                wait_for_search_results(page)
                return
        except Exception:
            continue
    raise RuntimeError("Search box not found on Google Maps page")


def get_result_cards(page):
    # Try multiple selectors; union them
    selectors = [
        "div.Nv2PK",
        "div[role='article']",
    ]
    locators = [page.locator(s) for s in selectors]
    return locators


def scroll_results_container(page, max_scrolls: int = 60) -> None:
    # Attempt to find the scrollable results container, then scroll to load more
    candidate_selectors = [
        "div[role='feed']",
        "div.m6QErb[aria-label]",
    ]
    container = None
    for sel in candidate_selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                try:
                    loc.first.wait_for(state="visible", timeout=1000)
                    container = loc.first
                    break
                except Exception:
                    pass
        except Exception:
            continue
    if container is None:
        # fallback: try to scroll the page itself
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 2000)
            random_human_delay(0.3, 0.8)
        return

    last_height = 0
    same_count = 0
    for _ in range(max_scrolls):
        try:
            container.evaluate("el => el.scrollBy(0, el.scrollHeight)")
        except Exception:
            # fallback: wheel
            page.mouse.wheel(0, 1500)
        random_human_delay(0.35, 0.9)
        try:
            height = container.evaluate("el => el.scrollTop")
        except Exception:
            height = 0
        if abs(height - last_height) < 50:
            same_count += 1
        else:
            same_count = 0
        last_height = height
        if same_count >= 5:
            break


def wait_for_place_details_loaded(page, timeout_ms: int = 15000) -> None:
    # Consider details loaded if the title appears or the right panel info is visible
    candidates = [
        "h1.DUwDvf",  # place title
        "div[role='main']",  # main details container
        "div.m6QErb",  # common details pane container
    ]
    start = time.time()
    while (time.time() - start) * 1000 < timeout_ms:
        for sel in candidates:
            try:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.wait_for(state="visible", timeout=2000)
                        # minor delay to let content render
                        random_human_delay(0.15, 0.35)
                        return
                    except Exception:
                        pass
            except Exception:
                pass
        time.sleep(0.2)
    raise PlaywrightTimeoutError("Place details did not load in time")


def extract_text_from_details(page) -> str:
    # Aggregate visible text from common containers for robust regex search
    texts: List[str] = []
    selectors = [
        "div[role='main']",
        "div.m6QErb",
        "body",
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel)
            if loc.count() > 0:
                texts.append(loc.first.inner_text(timeout=2000))
        except Exception:
            continue
    return "\n".join(texts)


def try_get_phone_direct(page) -> List[str]:
    # Prefer tel: links if present
    phones: List[str] = []
    try:
        tel_links = page.locator("a[href^='tel:']")
        count = tel_links.count()
        for i in range(min(count, 5)):
            href = tel_links.nth(i).get_attribute("href") or ""
            href_phone = href.replace("tel:", "").strip()
            if href_phone:
                phones.append(href_phone)
    except Exception:
        pass
    # Also try copying visible text associated with a phone icon/button
    try:
        # Buttons sometimes hold phone number in aria-label
        btns = page.locator("button[aria-label*='Phone'], button[aria-label*='电话']")
        count = btns.count()
        for i in range(min(count, 5)):
            label = btns.nth(i).get_attribute("aria-label") or ""
            phones.extend(normalize_phone_candidates(label))
    except Exception:
        pass
    # Deduplicate
    dedup = []
    seen = set()
    for p in phones:
        key = re.sub(r"[^\d]", "", p)
        if key and key not in seen:
            seen.add(key)
            dedup.append(p)
    return dedup


def extract_lat_lng_from_url(url: str) -> Tuple[Optional[float], Optional[float]]:
    # URLs can contain @lat,lng,zoomz
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if not m:
        return None, None
    try:
        return float(m.group(1)), float(m.group(2))
    except Exception:
        return None, None


def extract_place_details(page) -> Dict[str, Optional[str]]:
    data: Dict[str, Optional[str]] = {
        "name": None,
        "address": None,
        "phone": None,
        "website": None,
        "category": None,
        "rating": None,
        "reviews_count": None,
        "latitude": None,
        "longitude": None,
        "gmaps_url": page.url,
    }

    # Title (name)
    try:
        name_loc = page.locator("h1.DUwDvf")
        if name_loc.count() > 0:
            data["name"] = name_loc.first.inner_text(timeout=2000).strip()
    except Exception:
        pass

    # Address
    try:
        addr_btn = page.locator("button[data-item-id^='address']")
        if addr_btn.count() > 0:
            txt = addr_btn.first.inner_text(timeout=1500).strip()
            if txt and len(txt) > 4:
                data["address"] = txt
    except Exception:
        pass

    # Website
    try:
        site = page.locator("a[data-item-id^='authority']")
        if site.count() > 0:
            href = site.first.get_attribute("href")
            if href:
                data["website"] = href.strip()
    except Exception:
        pass

    # Category
    try:
        cat = page.locator("button[jsaction*='pane.rating.category']")
        if cat.count() > 0:
            data["category"] = cat.first.inner_text(timeout=1500).strip()
    except Exception:
        pass

    # Rating and reviews
    try:
        rating = page.locator("div.F7nice span[aria-hidden='true']").first
        try:
            rating.wait_for(state="visible", timeout=1000)
            data["rating"] = rating.inner_text().strip()
        except Exception:
            pass
    except Exception:
        pass
    try:
        reviews = page.locator("button[jsaction*='pane.reviewChart.moreReviews']").first
        try:
            reviews.wait_for(state="visible", timeout=1000)
            rc = normalize_phone_candidates(reviews.inner_text())  # quick numeric grab
            # Not ideal; more robust parse
            txt = reviews.inner_text().strip()
            m = re.search(r"\d+[\,\d]*", txt)
            if m:
                data["reviews_count"] = m.group(0).replace(",", "")
        except Exception:
            pass
    except Exception:
        pass

    # Phones
    phones = try_get_phone_direct(page)
    if not phones:
        all_text = extract_text_from_details(page)
        phones = normalize_phone_candidates(all_text)
    if phones:
        data["phone"] = "; ".join(phones)

    # Lat/Lng
    lat, lng = extract_lat_lng_from_url(page.url)
    if lat is not None:
        data["latitude"] = f"{lat:.6f}"
    if lng is not None:
        data["longitude"] = f"{lng:.6f}"

    return data


def write_csv_header(writer: csv.DictWriter) -> None:
    writer.writeheader()


def main() -> None:
    args = parse_args()
    setup_logging(args.log_level)

    query = f"{args.region} {args.category}".strip()
    fields = [
        "name",
        "address",
        "phone",
        "website",
        "category",
        "rating",
        "reviews_count",
        "latitude",
        "longitude",
        "gmaps_url",
    ]

    launch_kwargs = {
        "headless": args.headless,
        "slow_mo": args.slowmo,
        "args": [
            f"--lang={args.lang}",
            "--disable-blink-features=AutomationControlled",
            "--no-default-browser-check",
            "--disable-site-isolation-trials",
        ],
    }
    if args.proxy:
        launch_kwargs["proxy"] = {"server": args.proxy}

    user_agent = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_5_2) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    rows: List[Dict[str, Optional[str]]] = []
    visited_keys = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=user_agent,
            locale="zh-CN",
            extra_http_headers={"Accept-Language": args.lang},
            viewport={"width": 1380, "height": 900},
        )
        page = context.new_page()

        logging.info("Opening Google Maps...")
        page.goto("https://www.google.com/maps", wait_until="domcontentloaded", timeout=60000)
        try_accept_consent(page)
        random_human_delay()

        logging.info("Searching: %s", query)
        perform_search(page, query)
        random_human_delay()

        # Progressive load and iterate cards
        # We will scroll in batches and iterate newly visible cards each time
        total_target = args.max_results
        attempts = 0
        while len(rows) < total_target and attempts < 80:
            attempts += 1
            scroll_results_container(page, max_scrolls=4)
            locators = get_result_cards(page)
            # Gather indices to attempt clicking
            candidate_elements = []
            for loc in locators:
                count = loc.count()
                for i in range(count):
                    candidate_elements.append(loc.nth(i))

            logging.info("Found %d candidate cards on screen", len(candidate_elements))

            for card in candidate_elements:
                if len(rows) >= total_target:
                    break
                try:
                    # Compute a simple key from card text to avoid re-clicking
                    text_preview = card.inner_text(timeout=1000)[:120]
                    key = re.sub(r"\s+", " ", text_preview)
                    if key in visited_keys:
                        continue
                    visited_keys.add(key)

                    card.scroll_into_view_if_needed(timeout=3000)
                    random_human_delay(0.2, 0.6)
                    # Prefer clicking a link or the main clickable area
                    clickable = card.locator("a, div, button").first
                    clickable.click(timeout=5000)
                    wait_for_place_details_loaded(page)
                    random_human_delay(0.4, 1.1)

                    place = extract_place_details(page)
                    if place.get("name"):
                        has_phone = bool(place.get("phone"))
                        if has_phone or args.include_without_phone:
                            rows.append(place)
                            logging.info(
                                "Captured: %s | phone=%s", place.get("name"), place.get("phone") or "-"
                            )
                    # Go back to results list view (fallbacks)
                    try:
                        page.keyboard.press("Escape")
                        random_human_delay(0.2, 0.5)
                    except Exception:
                        pass
                    # Try clicking the back button in the left panel if present
                    try:
                        back_btn = page.locator("button[aria-label*='Back'], button[aria-label*='返回']").first
                        back_btn.click(timeout=1500)
                        random_human_delay(0.2, 0.6)
                    except Exception:
                        pass
                    # As a last resort, use browser back
                    try:
                        page.go_back(wait_until="domcontentloaded", timeout=5000)
                        random_human_delay(0.3, 0.8)
                    except Exception:
                        pass
                except PlaywrightTimeoutError:
                    logging.warning("Timeout on a card; skipping...")
                    continue
                except Exception as e:
                    logging.debug("Error while processing a card: %s", e)
                    continue

            # small human-like pause between batches
            random_human_delay(0.8, 1.6)

        logging.info("Collected %d rows", len(rows))

        context.close()
        browser.close()

    # Deduplicate final rows by name+address
    final: List[Dict[str, Optional[str]]] = []
    seen_key = set()
    for r in rows:
        key = (r.get("name") or "") + "|" + (r.get("address") or "")
        if key in seen_key:
            continue
        seen_key.add(key)
        final.append(r)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        write_csv_header(writer)
        for r in final:
            writer.writerow({k: r.get(k, "") or "" for k in fields})

    logging.info("Saved to %s (rows=%d)", args.out, len(final))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted by user", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logging.exception("Fatal error: %s", e)
        sys.exit(1)

