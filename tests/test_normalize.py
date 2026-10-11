#!/usr/bin/env python3
"""Unit tests for price normalization + watchlist matching. Run: python tests/test_normalize.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import flyerlib as fl
import build_site as site

PASS = FAIL = 0


def check(desc, got, want, tol=0.01):
    global PASS, FAIL
    ok = (abs(got - want) <= tol) if isinstance(want, float) else (got == want)
    if ok:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL {desc}: got {got!r}, want {want!r}")


def norm(**kw):
    return fl.normalize_item(kw)


# --- package sizes in name
r = norm(name="BLACK DIAMOND CHEESE, 410 g", current_price="2.97")
check("410g unit", r["unit"], "kg")
check("410g unit_price", r["unit_price"], 2.97 / 0.410)

r = norm(name="APPLE JUICE, 1.36 L", current_price="1.99")
check("1.36L unit", r["unit"], "L")
check("1.36L unit_price", r["unit_price"], 1.99 / 1.36)

r = norm(name="YOGURT TUBES, 8x60 g", current_price="2.99")
check("8x60g unit_price", r["unit_price"], 2.99 / 0.48)

r = norm(name="PC SHRIMP, 340-454 G", current_price="11.00")
check("size range has no scalar unit price", r["unit_price"], None)
check("size range low", r["unit_price_low"], 11.00 / 0.454)
check("size range high", r["unit_price_high"], 11.00 / 0.340)
check("size range unit", r["unit"], "kg")

r = norm(name="CHEDDAR, 250/280 G", current_price="6.00")
check("slash range low", r["unit_price_low"], 6.00 / 0.280)
check("slash range high", r["unit_price_high"], 6.00 / 0.250)

r = norm(name="LARABAR, 16X45/48 G", current_price="21.00")
check("multi-pack range low", r["unit_price_low"], 21.00 / (16 * 0.048))
check("multi-pack range high", r["unit_price_high"], 21.00 / (16 * 0.045))

r = norm(name="CHEESE 170/200 G OR SAUSAGE 250-375 G", current_price="6.00")
check("multiple size ranges omitted", r["unit_price"], None)
check("multiple size ranges have no low", r["unit_price_low"], None)
check("multiple size ranges basis", r["price_basis"], "ambiguous package")

r = norm(name="GRAPES 1 LB OR BLUEBERRIES 340 G", current_price="3.99", price_text="/lb")
check("ambiguous tile ignores shared per-lb qualifier", r["unit_price"], None)

r = norm(name="CHOCOLATE, 80-200 G OR BARS, 138, G", current_price="11.00")
check("comma-separated second size makes tile ambiguous", r["unit_price_low"], None)

r = norm(name="FROZEN TURKEY 5-11 kg 5.49/kg", current_price="2.49")
check("metric equivalent in name wins over package range", r["unit_price"], 5.49)

r = norm(name="GALA APPLES, 5 LB BAG", current_price="5.99")
check("5lb bag kg price", r["unit_price"], 5.99 / (5 * fl.LB_TO_KG))

r = norm(name="AVOCADOS, PKG OF 5", current_price="3.99")
check("pkg of 5 unit", r["unit"], "ea")
check("pkg of 5 each", r["unit_price"], 3.99 / 5)

# --- weight-priced
r = norm(name="BANANAS", current_price="0.63", price_text="lb.")
check("bananas /lb basis", r["price_basis"], "per lb")
check("bananas per-kg", r["unit_price"], 0.63 / fl.LB_TO_KG)

r = norm(name="ROYAL GALA APPLES", current_price="1.99", price_text="/lb")
check("apples /lb per-kg", r["unit_price"], 1.99 / fl.LB_TO_KG)

r = norm(name="BANANAS", current_price="1.49", price_text="/kg")
check("bananas /kg", r["unit_price"], 1.49)

r = norm(name="DELI TURKEY", current_price="2.99", price_text="/100 g")
check("per 100g -> per kg", r["unit_price"], 29.90)

# description carries metric equivalent, no size in name
r = norm(name="CHICKEN DRUMSTICKS", current_price="2.49", description="5.49/kg")
check("desc kg equiv", r["unit_price"], 5.49)

# --- multi-buy
r = norm(name="RASPBERRIES, 170 g", current_price="5.00", pre_price_text="2 FOR")
check("2-for each price", r["price"], 2.50)
check("2-for per kg", r["unit_price"], 2.50 / 0.170)

r = norm(name="SODA, 2 L", current_price="1.99", price_text="2/$5")
check("2/$5 each", r["price"], 2.50)

# --- fallbacks / guards
r = norm(name="BLUEBERRIES, 1 PINT", current_price="2.99")
check("pint falls back to each", r["unit"], "ea")
check("pint each price", r["unit_price"], 2.99)

r = norm(name="MYSTERY ITEM", current_price=None)
check("no price -> no unit_price", r["unit_price"], None)

# --- display-unit conversions and non-flyer baselines
check("kg price converts to per lb", fl.convert_unit_price(10.00, "kg", "lb"),
      10.00 * fl.LB_TO_KG)
check("per-lb price converts to kg", fl.convert_unit_price(2.00, "lb", "kg"),
      2.00 / fl.LB_TO_KG)
check("incompatible unit conversion", fl.convert_unit_price(3.00, "ea", "lb"), None)
check("six-ounce tray baseline per lb", fl.baseline_unit_price({
    "price": 3.00, "weight_lb": 6 / 16,
}), 8.00)
check("one-pound tray baseline per lb", fl.baseline_unit_price({
    "price": 5.00, "weight_lb": 1,
}), 5.00)
check("per-lb baseline", fl.baseline_unit_price({
    "price": 2.00, "unit": "lb",
}), 2.00)
check("My Items unit-price text uses lb", site.unit_price_text({
    "unit_price": 10.00, "unit_price_low": None, "unit_price_high": None, "unit": "kg",
}, "lb"), "$4.54/lb")
baseline_only_html = site.build_watchlist(
    {"deals": [], "generated": "2026-10-10", "postal_code": "TEST"},
    [],
    {"site_title": "Test", "history_days": 365, "watchlist": [{
        "id": "blackberries", "label": "Blackberries", "emoji": "🍇",
        "preferred_unit": "kg", "display_unit": "lb",
        "baseline": {"store": "Green Thumb", "label": "Organic blackberries", "price": 3.00,
                     "unit": "tray", "weight_lb": 0.375,
                     "package_label": "6 oz tray"},
    }]},
)
check("baseline remains visible without flyer deals",
      "Organic blackberries" in baseline_only_html, True)
check("baseline-only category reports no flyer deal",
      "No deals on this in this week's flyers." in baseline_only_html, True)
check("Green Thumb replaces the baseline label",
      "GREEN THUMB" in baseline_only_html and "BASELINE" not in baseline_only_html, True)
check("blackberries appear in the weekly quick list",
      '<span class="cat">Blackberries</span>' in baseline_only_html, True)
check("Green Thumb baseline is the quick-list choice",
      '>Green Thumb</span>\n<span class="p">$8.00/lb</span>' in baseline_only_html, True)

green_thumb_wins_html = site.build_watchlist(
    {"deals": [{
        "name": "Strawberries, 1 lb", "brand": "", "store": "Loblaws",
        "price": 6.00, "unit_price": 6.00 / fl.LB_TO_KG,
        "unit_price_low": None, "unit_price_high": None, "unit": "kg",
        "price_basis": "package", "categories": ["strawberries"],
    }], "generated": "2026-10-10", "postal_code": "TEST"},
    [],
    {"site_title": "Test", "history_days": 365, "watchlist": [{
        "id": "strawberries", "label": "Strawberries", "emoji": "🍓",
        "preferred_unit": "kg", "display_unit": "lb",
        "baseline": {"store": "Green Thumb", "label": "Strawberries",
                     "price": 5.00, "unit": "tray", "weight_lb": 1.0},
    }]},
)
check("Green Thumb wins the quick list when cheaper than a flyer",
      '>Green Thumb</span>\n<span class="p">$5.00/lb</span>' in green_thumb_wins_html, True)
check("flyer comparison names Green Thumb",
      "$1.00 above Green Thumb" in green_thumb_wins_html, True)

apple_summary_html = site.build_watchlist(
    {"deals": [{
        "name": "Bulk Gala apples", "brand": "", "store": "Walmart",
        "price": 0.98, "unit_price": 2.16, "unit_price_low": None,
        "unit_price_high": None, "unit": "kg", "price_basis": "per lb",
        "categories": ["apples"],
    }], "generated": "2026-10-10", "postal_code": "TEST"},
    [],
    {"site_title": "Test", "history_days": 365, "watchlist": [{
        "id": "apples", "label": "Apples", "emoji": "🍎",
        "preferred_unit": "kg", "display_unit": "lb",
        "summary_variants": ["Gala", "McIntosh"],
    }]},
)
check("apple summary names the cheapest variety",
      '<span class="cat">Apples (Gala)</span>' in apple_summary_html, True)
check("apple summary includes its display price",
      '<span class="p">$0.98/lb</span>' in apple_summary_html, True)

# --- watchlist matching
cfg = fl.load_config()
wl = cfg["watchlist"]


def cats(name, brand=""):
    return fl.categorize(wl, name, brand)


check("krema yogurt matches", cats("KREMA GREEK YOGURT, 500 g", "Krema"), ["yogurt"])
check("liberte accent matches", cats("LIBERTÉ MÉDITERRANÉE YOGURT, 650 g", "Liberté"), ["yogurt"])
check("other yogurt brand no match", cats("SELECTION YOGURT TUBES, 8x60 g", "Selection"), [])
check("gerber excluded", cats("Gerber Apple Banana Blueberry Yogurt Purée", "Gerber"), [])
check("blueberries match", cats("BLUEBERRIES, 1 PINT"), ["blueberries"])
check("blueberry muffin excluded", cats("BLUEBERRY MUFFINS, PKG OF 6"), [])
check("apples match", cats("ROYAL GALA APPLES"), ["apples"])
check("honeycrisp has its own category", cats("HONEYCRISP APPLES"), ["honeycrisp"])
check("spaced honeycrisp has its own category", cats("HONEY CRISP APPLES"), ["honeycrisp"])
check("pineapple not apples", cats("GOLDEN PINEAPPLE"), [])
check("apple juice excluded", cats("APPLE JUICE, 1.36 L"), [])
check("applewood is not an apple", cats("APPLEWOOD SMOKED CHEDDAR"), [])
check("apple watch excluded", cats("Apple Watch Ultra 3"), [])
check("apple cider plural excluded", cats("STRONG BOW APPLE CIDERS"), [])
check("oranges match", cats("NAVEL ORANGES, 3 LB BAG"), ["oranges"])
check("orange juice excluded", cats("ORANGE JUICE, 1.54 L", "Tropicana"), [])
check("orange energy drink excluded", cats("ENERGY DRINK ORANGE KISS"), [])
check("bananas match", cats("BANANAS"), ["bananas"])
check("banana bread excluded", cats("BANANA BREAD, 450 g"), [])
check("banana republic excluded", cats("BANANA REPUBLIC MEN'S VEST"), [])
check("raspberries match", cats("RASPBERRIES, 170 g"), ["raspberries"])
check("blackberries match", cats("BLACKBERRIES, 170 g"), ["blackberries"])
check("blueberry chocolate excluded", cats("DARK CHOCOLATE BLUEBERRY FLAVOURS"), [])
check("strawberry tomatoes excluded", cats("STRAWBERRY-TYPE TOMATOES, 340 G"), [])

# --- strict flyer selection + audit trail
flyers = [
    {"id": 1, "merchant": "Walmart", "name": "Flyer",
     "valid_from": "2026-10-08", "valid_to": "2026-10-14"},
    {"id": 2, "merchant": "Walmart", "name": "The Halloween Hub",
     "valid_from": "2026-10-01", "valid_to": "2026-10-31"},
    {"id": 3, "merchant": "Costco", "name": "Costco Grocery",
     "valid_from": "2026-10-05", "valid_to": "2026-10-11"},
    {"id": 4, "merchant": "Chalo FreshCo", "name": "Weekly Flyer",
     "valid_from": "2026-10-08", "valid_to": "2026-10-14"},
]
selected, audit = fl.evaluate_flyers(
    flyers, cfg["stores"], cfg.get("exclude_merchants", []),
    cfg.get("flyer_rules", {}), cfg.get("flyer_max_days"))
check("strict flyers selected", [f["id"] for _, f in selected], [1, 3])
check("seasonal flyer audited", next(a["selected"] for a in audit if a["flyer_id"] == 2), False)

# --- logical duplicate tiles collapse
duplicate = {
    "store": "Walmart", "name": "Liberté yogurt", "price": 3.47,
    "unit_price": None, "unit_price_low": None, "unit_price_high": None,
    "unit": "ea", "valid_from": "2026-10-08", "image": "",
}
richer = {**duplicate, "item_id": 2, "image": "https://example.test/yogurt.png"}
deduped = fl.dedupe_deals([{**duplicate, "item_id": 1}, richer])
check("duplicate deals collapse", len(deduped), 1)
check("duplicate keeps image", deduped[0]["image"], richer["image"])

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
