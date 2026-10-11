"""Shared library: Flipp API client, price normalization, watchlist matching, history stats."""

import json
import re
import statistics
import time
import unicodedata
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

API_BASE = "https://backflipp.wishabi.com/flipp"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"

LB_TO_KG = 0.45359237
OZ_TO_KG = 0.0283495


# ---------------------------------------------------------------- utilities

def load_config(path=None):
    p = Path(path) if path else ROOT / "config.json"
    return json.loads(p.read_text(encoding="utf-8"))


def fold(s):
    """Lowercase and strip accents for robust matching (Liberté -> liberte)."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def convert_unit_price(value, from_unit, to_unit):
    """Convert a comparable unit price while leaving incompatible units alone."""
    if value is None:
        return None
    if from_unit == to_unit:
        return value
    if from_unit == "kg" and to_unit == "lb":
        return value * LB_TO_KG
    if from_unit == "lb" and to_unit == "kg":
        return value / LB_TO_KG
    return None


def baseline_unit_price(baseline, target_unit="lb"):
    """Return a configured baseline as a comparable unit price."""
    if not baseline or baseline.get("price") is None:
        return None
    price = float(baseline["price"])
    weight_lb = baseline.get("weight_lb")
    if weight_lb is not None:
        weight_lb = float(weight_lb)
        if weight_lb <= 0:
            return None
        per_lb = price / weight_lb
    elif baseline.get("unit") == "lb":
        per_lb = price
    else:
        return None
    return convert_unit_price(per_lb, "lb", target_unit)


def http_get_json(url, retries=3, delay=1.5):
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_err}")


# ---------------------------------------------------------------- Flipp API

class FlippClient:
    """Thin client over Flipp's public backend API (the one flipp.com itself uses)."""

    def __init__(self, postal_code, locale="en-ca", delay=0.15, fetch_json=None):
        self.postal_code = postal_code.replace(" ", "").upper()
        self.locale = locale
        self.delay = delay
        # injectable fetcher so tests can run offline against fixtures
        self._fetch = fetch_json or http_get_json

    def flyers(self):
        url = f"{API_BASE}/flyers?locale={self.locale}&postal_code={self.postal_code}"
        data = self._fetch(url)
        return data if isinstance(data, list) else data.get("flyers", [])

    def flyer_with_items(self, flyer_id):
        url = f"{API_BASE}/flyers/{flyer_id}?locale={self.locale}"
        time.sleep(self.delay)
        return self._fetch(url)

    def item_detail(self, item_id):
        url = f"{API_BASE}/items/{item_id}"
        time.sleep(self.delay)
        data = self._fetch(url)
        return data.get("item", data)


def _flyer_days(flyer):
    """Return the inclusive validity window, or None for incomplete metadata."""
    try:
        start = datetime.fromisoformat((flyer.get("valid_from") or "").replace("Z", "+00:00"))
        end = datetime.fromisoformat((flyer.get("valid_to") or "").replace("Z", "+00:00"))
        return (end.date() - start.date()).days + 1
    except (TypeError, ValueError):
        return None


def evaluate_flyers(all_flyers, store_names, exclude_merchants=(), flyer_rules=None,
                    max_days=None):
    """Select configured weekly flyers and return an audit of every store candidate.

    Merchant matching is exact by default. Alternate merchant labels must be declared
    in ``flyer_rules[store].merchant_aliases``; this prevents FreshCo from silently
    matching Chalo FreshCo. Flyer titles are allow-listed per store so seasonal and
    department catalogues do not become grocery deals.
    """
    rules = flyer_rules or {}
    excluded = {fold(x) for x in exclude_merchants}
    selected, audit = [], []

    for flyer in all_flyers:
        merchant = flyer.get("merchant") or ""
        merchant_folded = fold(merchant).strip()
        store = None
        for configured in store_names:
            rule = rules.get(configured) or {}
            aliases = [configured, *(rule.get("merchant_aliases") or [])]
            if merchant_folded in {fold(alias).strip() for alias in aliases}:
                store = configured
                break
        if store is None:
            continue

        rule = rules.get(store) or {}
        title = flyer.get("name") or ""
        title_folded = fold(title)
        reason = "selected"
        keep = True

        if merchant_folded in excluded:
            keep, reason = False, "excluded merchant"

        include = rule.get("include_name_any") or []
        if keep and include and not any(fold(term) in title_folded for term in include):
            keep, reason = False, "flyer name is not allow-listed"

        exclude = rule.get("exclude_name_any") or []
        if keep and any(fold(term) in title_folded for term in exclude):
            keep, reason = False, "flyer name is explicitly excluded"

        days = _flyer_days(flyer)
        allowed_days = rule.get("max_days", max_days)
        if keep and allowed_days and days and days > allowed_days:
            keep, reason = False, f"validity window is {days} days (max {allowed_days})"

        audit.append({
            "store": store,
            "merchant": merchant,
            "flyer_id": flyer.get("id"),
            "name": title,
            "valid_from": (flyer.get("valid_from") or "")[:10],
            "valid_to": (flyer.get("valid_to") or "")[:10],
            "days": days,
            "selected": keep,
            "reason": reason,
        })
        if keep:
            selected.append((store, flyer))

    return selected, audit


def select_flyers(all_flyers, store_names, exclude_merchants=(), flyer_rules=None,
                  max_days=None):
    """Compatibility wrapper returning only selected ``(store, flyer)`` pairs."""
    selected, _ = evaluate_flyers(
        all_flyers, store_names, exclude_merchants, flyer_rules, max_days)
    return selected


# ------------------------------------------------------- price normalization

_MULTI_RANGE_RE = re.compile(
    r"(\d+)\s*[xX×=]\s*(\d+(?:[.,]\d+)?)\s*(?:-|–|—|/)\s*"
    r"(\d+(?:[.,]\d+)?)\s*,?\s*(kg|g|l|ml|lb|oz)\b", re.IGNORECASE)
_MULTI_SIZE_RE = re.compile(
    r"(\d+)\s*[xX×=]\s*(\d+(?:[.,]\d+)?)\s*,?\s*(kg|g|l|ml|lb|oz)\b", re.IGNORECASE)
_SIZE_RANGE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(?:-|–|—|/|\bto\b)\s*"
    r"(\d+(?:[.,]\d+)?)\s*,?\s*(kg|g|l|ml|lb|oz)\b", re.IGNORECASE)
_SIZE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*,?\s*(kg|g|l|ml|lb|oz)\b", re.IGNORECASE)
_PKG_COUNT_RE = re.compile(
    r"(?:pkg?\.?\s*of\s*(\d+)|(\d+)\s*(?:pack|pk\b|ct\b|count|un\b|'s\b))", re.IGNORECASE)
_PER_LB_RE = re.compile(r"(?:/\s*lb|per\s*lb|\blb\.?\s*$|\ba\s*lb\b)", re.IGNORECASE)
_PER_KG_RE = re.compile(r"(?:/\s*kg|per\s*kg)", re.IGNORECASE)
_PER_100G_RE = re.compile(r"(?:/\s*100\s*g|per\s*100\s*g)", re.IGNORECASE)
_MULTIBUY_RE = re.compile(r"(\d+)\s*(?:for|/)\s*\$?\s*(\d+(?:[.,]\d+)?)?", re.IGNORECASE)
_KG_EQUIV_RE = re.compile(r"\$?\s*(\d+(?:[.,]\d+)?)\s*/\s*kg", re.IGNORECASE)


def _num(s):
    try:
        return float(str(s).replace(",", ".").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


def _to_kg(qty, unit):
    unit = unit.lower()
    if unit == "kg":
        return qty, "kg"
    if unit == "g":
        return qty / 1000.0, "kg"
    if unit == "lb":
        return qty * LB_TO_KG, "kg"
    if unit == "oz":
        return qty * OZ_TO_KG, "kg"
    if unit == "l":
        return qty, "L"
    if unit == "ml":
        return qty / 1000.0, "L"
    return None, None


def _overlaps(span, spans):
    return any(span[0] < other[1] and other[0] < span[1] for other in spans)


def _package_size(name):
    """Return (kind, quantities, unit, source) for an unambiguous package size.

    ``kind`` is ``exact`` or ``range``. Listings with multiple independent sizes
    are intentionally left unparsed rather than assigning one product's size to
    every product in a combined flyer tile.
    """
    multi_ranges = list(_MULTI_RANGE_RE.finditer(name))
    multi = [m for m in _MULTI_SIZE_RE.finditer(name)
             if not _overlaps(m.span(), [r.span() for r in multi_ranges])]
    ranges = list(_SIZE_RANGE_RE.finditer(name))
    ranges = [m for m in ranges
              if not _overlaps(m.span(), [r.span() for r in multi_ranges])]
    occupied = [m.span() for m in multi_ranges + multi + ranges]
    singles = [m for m in _SIZE_RE.finditer(name) if not _overlaps(m.span(), occupied)]

    candidates = len(multi_ranges) + len(multi) + len(ranges) + len(singles)
    if candidates > 1:
        return "ambiguous", (), None, ""
    if candidates == 0:
        return None
    if multi_ranges:
        match = multi_ranges[0]
        count = int(match.group(1))
        first, unit = _to_kg(count * _num(match.group(2)), match.group(4))
        second, second_unit = _to_kg(count * _num(match.group(3)), match.group(4))
        if first and second and unit == second_unit:
            return "range", tuple(sorted((first, second))), unit, match.group(0)
        return None
    if multi:
        match = multi[0]
        count, each = int(match.group(1)), _num(match.group(2))
        quantity, unit = _to_kg(count * each, match.group(3))
        return ("exact", (quantity,), unit, match.group(0)) if quantity else None
    if ranges:
        match = ranges[0]
        first, unit = _to_kg(_num(match.group(1)), match.group(3))
        second, second_unit = _to_kg(_num(match.group(2)), match.group(3))
        if first and second and unit == second_unit:
            return "range", tuple(sorted((first, second))), unit, match.group(0)
        return None
    match = singles[0]
    quantity, unit = _to_kg(_num(match.group(1)), match.group(2))
    return ("exact", (quantity,), unit, match.group(0)) if quantity else None


def normalize_item(raw):
    """Turn a merged Flipp item into a normalized deal record.

    Returns dict with: name, brand, price (each/effective), unit_price, unit
    ('kg' | 'L' | 'ea'), size_text, price_basis, plus passthrough display fields.
    Conservative: when unsure, falls back to per-each and never invents a unit price.
    """
    name = (raw.get("name") or "").strip()
    brand = (raw.get("brand") or "").strip()
    price = _num(raw.get("current_price") or raw.get("price"))
    pre = (raw.get("pre_price_text") or "").strip()
    ptext = (raw.get("price_text") or "").strip()
    story = (raw.get("sale_story") or "").strip()
    desc = (raw.get("description") or "").strip()

    hint_text = " ".join([pre, ptext, story])          # price-qualifier fields
    result = {
        "name": name,
        "brand": brand,
        "price": price,
        "unit_price": None,
        "unit_price_low": None,
        "unit_price_high": None,
        "unit": "ea",
        "size_text": "",
        "price_basis": "each",
        "pre_price_text": pre,
        "price_text": ptext,
        "sale_story": story,
        "description": desc.split("\n")[0][:120],
    }
    if price is None:
        return result

    package = _package_size(name)
    if package and package[0] == "ambiguous":
        # A single tile may advertise several products and sizes. Its price text
        # cannot safely be assigned to any one package or watchlist category.
        result["price_basis"] = "ambiguous package"
        return result

    # -- multi-buy: "2 FOR" / "2/$5" => effective each price
    m = _MULTIBUY_RE.search(pre) or _MULTIBUY_RE.search(ptext)
    if m:
        n = int(m.group(1))
        total = _num(m.group(2)) if m.group(2) else None
        if n > 1:
            if total:                      # "2/$5" style: total given in the text
                price = total / n
            elif price and price > 0:      # "2 FOR" + price holds the total
                price = price / n
            result["price"] = round(price, 2)
            result["price_basis"] = f"{n} for"

    # -- weight-priced items (produce/meat): "/lb", "/kg", "/100 g"
    if _PER_KG_RE.search(hint_text):
        result.update(unit_price=round(price, 2), unit="kg", price_basis="per kg")
        return result
    if _PER_LB_RE.search(hint_text):
        result.update(unit_price=round(price / LB_TO_KG, 2), unit="kg", price_basis="per lb")
        return result
    if _PER_100G_RE.search(hint_text):
        result.update(unit_price=round(price * 10, 2), unit="kg", price_basis="per 100 g")
        return result

    # description sometimes carries the metric equivalent, e.g. "4.39/kg"
    m = (_KG_EQUIV_RE.search(desc) or _KG_EQUIV_RE.search(story)
         or _KG_EQUIV_RE.search(name))
    if m:
        kg_price = _num(m.group(1))
        if kg_price:
            result.update(unit_price=round(kg_price, 2), unit="kg", price_basis="per kg (equiv)")
            return result

    # -- package size in the name: exact or one parseable range
    if package:
        kind, quantities, unit, source = package
        if kind == "exact" and quantities[0] > 0:
            result.update(unit_price=round(price / quantities[0], 2), unit=unit,
                          size_text=source, price_basis="package")
            return result
        if kind == "range" and quantities[0] > 0:
            # Larger packages have the lower unit price.
            low = round(price / quantities[1], 2)
            high = round(price / quantities[0], 2)
            result.update(unit_price_low=low, unit_price_high=high, unit=unit,
                          size_text=source, price_basis="package range")
            return result

    # -- count-based package: "PKG OF 5", "6 pack"
    m = _PKG_COUNT_RE.search(name)
    if m:
        n = int(m.group(1) or m.group(2))
        if n > 1:
            result.update(unit_price=round(price / n, 2), unit="ea",
                          size_text=m.group(0), price_basis=f"pkg of {n}")
            return result

    # -- fallback: each
    result["unit_price"] = round(price, 2)
    return result


# ----------------------------------------------------------- watchlist match

def pattern_matches(text, pattern):
    """Match a normalized whole word/phrase, or a word-prefix ending in ``*``."""
    text = fold(text)
    pattern = fold(pattern).strip()
    prefix = pattern.endswith("*")
    if prefix:
        pattern = pattern[:-1]
    if not pattern:
        return False
    start = r"(?<![a-z0-9])"
    end = "" if prefix else r"(?![a-z0-9])"
    return re.search(start + re.escape(pattern) + end, text) is not None


def _matches_any(text, patterns):
    return any(pattern_matches(text, pattern) for pattern in patterns)


def could_match_watchlist(watchlist, name, brand=""):
    """Cheap pre-detail test used to avoid unnecessary item API requests."""
    text = f"{brand} {name}"
    return any(_matches_any(text, cat.get("match_any", [])) for cat in watchlist)


def matches_category(cat, name, brand=""):
    text = f"{brand} {name}"
    if not _matches_any(text, cat.get("match_any", [])):
        return False
    req = cat.get("require_any") or []
    if req and not _matches_any(text, req):
        return False
    if _matches_any(text, cat.get("exclude_any", [])):
        return False
    return True


def categorize(watchlist, name, brand=""):
    return [c["id"] for c in watchlist if matches_category(c, name, brand)]


def deal_key(row):
    """Stable logical identity for duplicate flyer tiles and history rows."""
    return (
        row.get("week") or row.get("valid_from") or "",
        fold(row.get("store") or ""),
        fold(row.get("name") or ""),
        row.get("price"),
        row.get("unit_price"),
        row.get("unit_price_low"),
        row.get("unit_price_high"),
        row.get("unit"),
    )


def dedupe_deals(rows):
    """Collapse repeated visual tiles while preserving the richest record."""
    unique = {}
    for row in rows:
        key = deal_key(row)
        current = unique.get(key)
        if current is None:
            unique[key] = row
        elif not current.get("image") and row.get("image"):
            unique[key] = row
    return list(unique.values())


# ----------------------------------------------------------------- history

def history_path():
    return DATA_DIR / "history.jsonl"


def load_history():
    p = history_path()
    rows = []
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return rows


def save_history(rows):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with history_path().open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_history(new_rows, keep_days=730, today=None):
    """Merge new rows into history, deduplicate logical deals, and prune old rows."""
    today = today or date.today()
    rows = dedupe_deals(load_history())
    seen = {deal_key(r) for r in rows}
    added = 0
    for r in new_rows:
        key = deal_key(r)
        if key in seen:
            continue
        seen.add(key)
        rows.append(r)
        added += 1
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    rows = [r for r in rows if (r.get("date") or "9999") >= cutoff]
    rows.sort(key=lambda r: (r.get("date") or "", r.get("store") or "", r.get("name") or ""))
    save_history(rows)
    return added, len(rows)


def category_stats(history_rows, watchlist, window_days=365, today=None):
    """1-year low/median/high of unit_price per (category, unit)."""
    today = today or date.today()
    cutoff = (today - timedelta(days=window_days)).isoformat()
    stats = {}
    for cat in watchlist:
        buckets = {}
        for r in history_rows:
            if (r.get("date") or "") < cutoff or r.get("unit_price") is None:
                continue
            if cat["id"] not in (r.get("categories") or []):
                continue
            buckets.setdefault(r.get("unit", "ea"), []).append(r["unit_price"])
        per_unit = {}
        for unit, vals in buckets.items():
            per_unit[unit] = {
                "low": min(vals),
                "median": round(statistics.median(vals), 2),
                "high": max(vals),
                "n": len(vals),
            }
        # order: preferred unit first, then by observation count
        pref = cat.get("preferred_unit")
        ordered = sorted(per_unit.items(),
                         key=lambda kv: (kv[0] != pref, -kv[1]["n"]))
        stats[cat["id"]] = ordered
    return stats
