#!/usr/bin/env python3
"""Fetch current grocery flyers via the Flipp API, normalize deals, update history.

Usage:
    python scripts/fetch_flyers.py                 # live fetch (postal code from config.json)
    python scripts/fetch_flyers.py --fixtures DIR  # offline run against fixture JSON files
    python scripts/fetch_flyers.py --no-details    # skip per-item detail requests (faster, less unit info)

Outputs:
    data/latest.json     full snapshot of this week's deals (used by build_site.py)
    data/history.jsonl   one row per (week, store, item) — accumulates for price stats
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flyerlib as fl


def make_fixture_fetcher(fix_dir):
    """Map API URLs onto fixture files: flyers.json, flyer_<id>.json, item_<id>.json."""
    fix = Path(fix_dir)

    def fetch(url):
        if "/flyers?" in url:
            name = "flyers.json"
        elif "/flyers/" in url:
            fid = url.split("/flyers/")[1].split("?")[0]
            name = f"flyer_{fid}.json"
        elif "/items/" in url:
            iid = url.split("/items/")[1].split("?")[0]
            name = f"item_{iid}.json"
        else:
            raise ValueError(f"no fixture mapping for {url}")
        p = fix / name
        if not p.exists():
            raise FileNotFoundError(p)
        return json.loads(p.read_text(encoding="utf-8"))

    return fetch


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=None)
    ap.add_argument("--fixtures", default=None, help="directory of fixture JSON (offline test mode)")
    ap.add_argument("--no-details", action="store_true", help="skip per-item detail fetches")
    ap.add_argument("--detail-scope", choices=("all", "watchlist_candidates", "none"),
                    default=None, help="override which items receive detail requests")
    ap.add_argument("--postal-code", default=None, help="override config postal code")
    args = ap.parse_args()

    cfg = fl.load_config(args.config)
    postal = args.postal_code or cfg["postal_code"]
    fetcher = make_fixture_fetcher(args.fixtures) if args.fixtures else None
    delay = 0 if args.fixtures else cfg.get("request_delay_seconds", 0.15)
    client = fl.FlippClient(postal, cfg.get("locale", "en-ca"), delay=delay, fetch_json=fetcher)

    print(f"Fetching flyers for {postal} ...")
    all_flyers = client.flyers()
    matched, flyer_audit = fl.evaluate_flyers(
        all_flyers,
        cfg["stores"],
        cfg.get("exclude_merchants", []),
        cfg.get("flyer_rules", {}),
        cfg.get("flyer_max_days"),
    )
    print(f"  {len(all_flyers)} flyers available; {len(matched)} match configured stores")
    for candidate in flyer_audit:
        marker = "using" if candidate["selected"] else "skip"
        print(f"  {marker}: {candidate['store']} — {candidate['name']} ({candidate['reason']})")

    found_stores = {s for s, _ in matched}
    missing = [s for s in cfg["stores"] if s not in found_stores]
    if missing:
        print(f"  no current flyer for: {', '.join(missing)}")

    detail_scope = args.detail_scope or cfg.get("item_detail_scope", "watchlist_candidates")
    if args.no_details or not cfg.get("fetch_item_details", True):
        detail_scope = "none"
    today = date.today().isoformat()
    deals, history_rows, errors, detail_requests = [], [], 0, 0

    for store, flyer in matched:
        merchant = flyer.get("merchant") or store
        fid = flyer.get("id")
        try:
            detail = client.flyer_with_items(fid)
        except Exception as e:
            print(f"  !! failed flyer {merchant} ({fid}): {e}")
            errors += 1
            continue
        items = detail.get("items") or []
        print(f"  {merchant}: {len(items)} items (flyer {fid})")

        for it in items:
            merged = dict(it)
            should_fetch_detail = (
                detail_scope == "all"
                or (detail_scope == "watchlist_candidates" and fl.could_match_watchlist(
                    cfg["watchlist"], it.get("name") or "", it.get("brand") or ""))
            )
            if should_fetch_detail and it.get("id"):
                try:
                    detail_requests += 1
                    merged.update({k: v for k, v in client.item_detail(it["id"]).items()
                                   if v not in (None, "", [])})
                except Exception:
                    errors += 1  # detail is enrichment only; keep going
            norm = fl.normalize_item(merged)
            if not norm["name"] or norm["price"] is None:
                continue  # page decorations / non-priced blocks
            cats = fl.categorize(cfg["watchlist"], norm["name"], norm["brand"])
            deal = {
                **norm,
                "store": store,
                "merchant": merchant,
                "flyer_id": fid,
                "item_id": it.get("id"),
                "image": (it.get("cutout_image_url") or merged.get("cutout_image_url")
                          or merged.get("image_url") or ""),
                "valid_from": (it.get("valid_from") or flyer.get("valid_from") or "")[:10],
                "valid_to": (it.get("valid_to") or flyer.get("valid_to") or "")[:10],
                "categories": cats,
                "discount": merged.get("percent_off") or it.get("discount"),
            }
            deals.append(deal)
            history_rows.append({
                "date": today,
                "week": deal["valid_from"],
                "store": store,
                "merchant": merchant,
                "flyer_id": fid,
                "item_id": it.get("id"),
                "name": norm["name"],
                "brand": norm["brand"],
                "price": norm["price"],
                "unit_price": norm["unit_price"],
                "unit_price_low": norm["unit_price_low"],
                "unit_price_high": norm["unit_price_high"],
                "unit": norm["unit"],
                "price_basis": norm["price_basis"],
                "categories": cats,
            })

    before_dedupe = len(deals)
    deals = fl.dedupe_deals(deals)
    duplicates = before_dedupe - len(deals)

    fl.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (fl.DATA_DIR / "flyer_audit.json").write_text(
        json.dumps({
            "generated": today,
            "postal_code": postal,
            "candidates": flyer_audit,
        }, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    snapshot = {
        "generated": today,
        "postal_code": postal,
        "stores_configured": cfg["stores"],
        "stores_missing": missing,
        "deals": deals,
    }
    (fl.DATA_DIR / "latest.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")

    added, total = fl.append_history(history_rows, cfg.get("history_keep_days", 730))
    print(f"Done: {len(deals)} deals ({duplicates} duplicates removed); "
          f"{detail_requests} item detail requests; history +{added} rows "
          f"(total {total}); {errors} fetch errors")
    if not deals:
        print("WARNING: no deals fetched — leaving previous site untouched")
        sys.exit(2)


if __name__ == "__main__":
    main()
