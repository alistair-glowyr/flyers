#!/usr/bin/env python3
"""Generate offline test fixtures shaped like real Flipp API responses.

Item fields mirror the live API (verified 2026-07-11). Prices are synthetic —
fixtures are for testing parsing/rendering only and are never committed to data/.
Also synthesizes ~1 year of history rows so watchlist stats can be eyeballed.
"""

import json
import random
from datetime import date, timedelta
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"
FIX.mkdir(exist_ok=True)

WEEK_FROM = "2026-07-09T00:00:00-04:00"
WEEK_TO = "2026-07-15T23:59:59-04:00"


def flyer_stub(fid, merchant):
    return {
        "id": fid, "merchant": merchant, "merchant_id": fid, "name": "Weekly Flyer",
        "valid_from": WEEK_FROM, "valid_to": WEEK_TO, "categories": ["Groceries"],
        "postal_code": "M6S1N3", "locale": "en-ca",
    }


def item(iid, fid, name, price, brand=None, pre=None, ptext=None, story=None, desc=None):
    base = {
        "id": iid, "flyer_id": fid, "name": name, "display_type": 1, "brand": brand,
        "cutout_image_url": "", "valid_from": WEEK_FROM, "valid_to": WEEK_TO,
        "discount": None, "price": str(price) if price is not None else None,
        "print_id": f"SKU{iid}", "short_name": None, "text_areas": [],
    }
    detail = {"item": {**base, "pre_price_text": pre, "price_text": ptext,
                       "sale_story": story, "description": desc,
                       "current_price": str(price) if price is not None else None,
                       "merchant_id": fid, "sku": f"SKU{iid}"}}
    return base, detail


STORES = {
    9001: ("No Frills", [
        ("BLUEBERRIES, 1 PINT", 2.99, None, None, None, None, "product of Ontario"),
        ("BANANAS", 0.63, None, None, "lb.", None, "1.39/kg"),
        ("KREMA GREEK YOGURT, 500 g", 4.49, "Krema", None, None, "SAVE $1.50", "selected varieties"),
        ("ROYAL GALA APPLES", 1.99, None, None, "/lb", None, "product of Ontario, 4.39/kg"),
        ("NAVEL ORANGES, 3 LB BAG", 4.99, None, None, None, None, None),
        ("BLACK DIAMOND CHEESE SLICES, 410 g", 2.97, "Black Diamond", None, None, "SAVE UP TO 30%", "selected varieties"),
        ("RASPBERRIES, 170 g", 2.50, None, "2 FOR", None, None, None),
        ("APPLE JUICE, 1.36 L", 1.99, "Allen's", None, None, None, "from concentrate"),
    ]),
    9002: ("FreshCo", [
        ("BLUEBERRIES, 510 g", 4.99, None, None, None, None, "product of B.C."),
        ("LIBERTÉ MÉDITERRANÉE YOGURT, 650 g", 5.49, "Liberté", None, None, None, "selected varieties"),
        ("BLACKBERRIES, 170 g", 2.99, None, None, None, None, None),
        ("BANANAS", 1.49, None, None, "/kg", None, None),
        ("MANDARIN ORANGES, 2 LB BAG", 3.99, None, None, None, None, None),
        ("CHICKEN DRUMSTICKS", 2.49, None, None, "/lb", None, "5.49/kg"),
    ]),
    9003: ("Food Basics", [
        ("RASPBERRIES, 340 g", 3.99, None, None, None, None, None),
        ("SELECTION YOGURT TUBES, 8x60 g", 2.99, "Selection", None, None, None, None),
        ("GALA APPLES, 5 LB BAG", 5.99, None, None, None, None, None),
        ("AVOCADOS, PKG OF 5", 3.99, None, None, None, None, None),
    ]),
    9004: ("Loblaws", [
        ("LIBERTÉ GREEK YOGURT, 750 g", 6.99, "Liberté", None, None, None, "selected varieties"),
        ("STRAWBERRIES, 1 LB CLAMSHELL", 3.99, None, None, None, None, "product of Ontario"),
        ("ORANGE JUICE, 1.54 L", 4.99, "Tropicana", None, None, None, None),
    ]),
    9005: ("Costco", [
        ("KIRKLAND SIGNATURE BLUEBERRIES, 2 kg", 9.99, "Kirkland Signature", None, None, "$3 OFF", "frozen"),
    ]),
}


def main():
    random.seed(42)
    flyers = []
    iid = 500000
    for fid, (merchant, items) in STORES.items():
        flyers.append(flyer_stub(fid, merchant))
        flyer_items = []
        for (name, price, brand, pre, ptext, story, desc) in items:
            iid += 1
            base, detail = item(iid, fid, name, price, brand, pre, ptext, story, desc)
            flyer_items.append(base)
            (FIX / f"item_{iid}.json").write_text(json.dumps(detail, ensure_ascii=False, indent=1))
        flyer = flyer_stub(fid, merchant)
        flyer["items"] = flyer_items
        (FIX / f"flyer_{fid}.json").write_text(json.dumps(flyer, ensure_ascii=False, indent=1))
    # some non-matching merchants to exercise store filtering
    flyers.append(flyer_stub(9100, "Chalo FreshCo"))
    flyers.append(flyer_stub(9101, "Dollarama"))
    (FIX / "flyers.json").write_text(json.dumps({"flyers": flyers}, ensure_ascii=False, indent=1))

    # ---- synthetic 1-year history for stats demo (written to fixtures, NOT data/)
    cats = {
        "yogurt": ("kg", 7.0, 12.0), "blueberries": ("kg", 4.5, 18.0),
        "blackberries": ("kg", 10.0, 24.0), "raspberries": ("kg", 9.0, 26.0),
        "strawberries": ("kg", 4.0, 13.0), "apples": ("kg", 2.5, 7.5),
        "oranges": ("kg", 2.0, 6.5), "bananas": ("kg", 1.25, 1.9),
    }
    rows = []
    d0 = date(2026, 7, 9)
    for wk in range(52):
        day = (d0 - timedelta(weeks=wk)).isoformat()
        for cat, (unit, lo, hi) in cats.items():
            for store in random.sample(["No Frills", "FreshCo", "Food Basics", "Loblaws"], k=random.randint(1, 3)):
                up = round(random.uniform(lo, hi), 2)
                rows.append({
                    "date": day, "week": day, "store": store, "merchant": store,
                    "flyer_id": 8000 + wk, "item_id": 100000 + len(rows),
                    "name": f"{cat.upper()} (history sample)", "brand": "",
                    "price": up, "unit_price": up, "unit": unit,
                    "price_basis": "per kg", "categories": [cat],
                })
    with (FIX / "history_sample.jsonl").open("w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"fixtures written to {FIX} ({len(flyers)} flyers, {len(rows)} history rows)")


if __name__ == "__main__":
    main()
