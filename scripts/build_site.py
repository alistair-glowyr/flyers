#!/usr/bin/env python3
"""Build the static site (docs/) from data/latest.json + data/history.jsonl."""

import html
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flyerlib as fl

STORE_COLORS = {
    "no frills": "#f2b705",
    "freshco": "#2e9e4f",
    "food basics": "#0e8577",
    "metro": "#c8102e",
    "loblaws": "#e57200",
    "walmart": "#0071ce",
    "costco": "#005daa",
    "green thumb": "#1a7f4b",
}
FALLBACK_COLORS = ["#6b5b95", "#88767c", "#3e7cb1", "#a05c7b", "#57707a"]


def esc(s):
    return html.escape(str(s or ""), quote=True)


def store_color(store, idx=0):
    return STORE_COLORS.get(fl.fold(store), FALLBACK_COLORS[idx % len(FALLBACK_COLORS)])


def money(v):
    if v is None:
        return "—"
    return f"${v:,.2f}"


def unit_label(unit):
    return {"kg": "/kg", "lb": "/lb", "L": "/L", "ea": " ea"}.get(unit, f"/{unit}")


def price_suffix(basis):
    """Suffix for the big printed price — must match the basis the price was printed in."""
    return {"per kg": "/kg", "per lb": "/lb", "per 100 g": "/100 g"}.get(basis, "")


def display_unit_price(value, source_unit, target_unit=None):
    """Convert a value for display, falling back when units are incompatible."""
    if target_unit:
        converted = fl.convert_unit_price(value, source_unit, target_unit)
        if converted is not None:
            return converted, target_unit
    return value, source_unit


def unit_price_text(d, target_unit=None):
    """Format a scalar unit price or a conservative parsed package-size range."""
    source_unit = d.get("unit", "ea")
    if d.get("unit_price") is not None:
        value, unit = display_unit_price(d["unit_price"], source_unit, target_unit)
        return f'{money(value)}{unit_label(unit)}'
    low, high = d.get("unit_price_low"), d.get("unit_price_high")
    if low is not None and high is not None:
        low, unit = display_unit_price(low, source_unit, target_unit)
        high, _ = display_unit_price(high, source_unit, target_unit)
        return f"{money(low)}–{money(high)}{unit_label(unit)}"
    return ""


def exact_unit_price(d, target_unit):
    """Return an exact comparable price in the requested display unit."""
    return fl.convert_unit_price(d.get("unit_price"), d.get("unit"), target_unit)


def baseline_comparison(d, baseline_price, target_unit, reference_name="baseline"):
    """Describe how an exact flyer unit price compares with its reference."""
    current = exact_unit_price(d, target_unit)
    if current is None or baseline_price is None:
        return "", ""
    difference = current - baseline_price
    if abs(difference) < 0.005:
        return f"matches {reference_name}", "same"
    direction = "below" if difference < 0 else "above"
    css_class = "good" if difference < 0 else "bad"
    return f"{money(abs(difference))} {direction} {reference_name}", css_class


def watchlist_sort_key(d, preferred_unit):
    """Prefer exact comparable prices, then conservative range upper bounds."""
    preferred = d.get("unit") == preferred_unit
    if d.get("unit_price") is not None:
        return (0 if preferred else 2, d["unit_price"])
    if d.get("unit_price_high") is not None:
        return (1 if preferred else 3, d["unit_price_high"])
    return (4, d.get("price") or 9e9)


def brand_prefix(d):
    """Show brand only when the name doesn't already contain it."""
    b = d.get("brand") or ""
    if b and fl.fold(b) not in fl.fold(d.get("name") or ""):
        return f"{esc(b)} · "
    return ""


def summary_category_label(cat, deal):
    """Add configured product detail to a category's weekly-summary label."""
    label = cat["label"]
    variants = cat.get("summary_variants") or []
    if not variants:
        return label
    name = deal.get("name") or ""
    folded_name = fl.fold(name)
    found = [
        (folded_name.find(fl.fold(variant)), variant)
        for variant in variants
        if fl.pattern_matches(name, variant)
    ]
    if not found:
        return label
    found.sort(key=lambda match: match[0])
    return f"{label} ({' / '.join(variant for _, variant in found)})"


CSS = """
:root{
  --bg:#f6f5f2; --card:#ffffff; --ink:#1d1c1a; --muted:#6f6c66;
  --line:#e6e3dc; --accent:#1a7f4b; --accent-ink:#ffffff;
  --best:#fff7e0; --best-line:#e8c96a; --baseline:#eef5ff; --baseline-line:#9dbce8;
  --good:#16713f; --bad:#a13b32; --shadow:0 1px 3px rgba(0,0,0,.07);
}
@media (prefers-color-scheme: dark){
  :root{ --bg:#161513; --card:#211f1c; --ink:#f0eee9; --muted:#a39f97;
         --line:#37342f; --best:#2c2718; --best-line:#7a6a33;
         --baseline:#182536; --baseline-line:#486b96; --good:#73c994; --bad:#ef9187;
         --shadow:none; }
}
*{box-sizing:border-box} html{-webkit-text-size-adjust:100%}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:var(--bg);color:var(--ink);font-size:16px;line-height:1.4}
a{color:inherit}
header{position:sticky;top:0;z-index:10;background:var(--bg);
       border-bottom:1px solid var(--line);padding:10px 14px 0}
h1{font-size:1.15rem;margin:0 0 2px}
.sub{color:var(--muted);font-size:.8rem;margin:0 0 8px}
nav{display:flex;gap:6px;margin-bottom:-1px}
nav a{flex:1;text-align:center;padding:9px 4px;text-decoration:none;font-weight:600;
      font-size:.95rem;color:var(--muted);border-bottom:3px solid transparent;border-radius:6px 6px 0 0}
nav a.on{color:var(--ink);border-bottom-color:var(--accent)}
main{padding:12px 14px 60px;max-width:900px;margin:0 auto}
.controls{display:flex;flex-direction:column;gap:8px;margin-bottom:14px}
input[type=search]{width:100%;padding:10px 12px;font-size:1rem;border:1px solid var(--line);
     border-radius:10px;background:var(--card);color:var(--ink)}
.chips{display:flex;gap:6px;overflow-x:auto;padding-bottom:4px;-webkit-overflow-scrolling:touch}
.chip{flex:0 0 auto;border:1px solid var(--line);background:var(--card);color:var(--ink);
      padding:6px 12px;border-radius:999px;font-size:.85rem;font-weight:600;cursor:pointer}
.chip.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.storehead{display:flex;align-items:center;gap:8px;margin:18px 0 8px}
.storehead .dot{width:12px;height:12px;border-radius:50%}
.storehead h2{font-size:1.02rem;margin:0}
.storehead .n{color:var(--muted);font-size:.8rem;font-weight:400}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
      padding:10px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:4px}
.card img{width:100%;height:92px;object-fit:contain;border-radius:6px;background:#fff}
.iname{font-size:.83rem;font-weight:600;line-height:1.25;
       display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.price{font-size:1.12rem;font-weight:800}
.uprice{color:var(--muted);font-size:.78rem}
.basis{color:var(--muted);font-size:.72rem}
.story{color:#b3541e;font-size:.72rem;font-weight:600}
.badge{display:inline-block;color:#fff;font-size:.68rem;font-weight:700;
       padding:2px 7px;border-radius:6px;letter-spacing:.02em}
.empty{color:var(--muted);text-align:center;padding:40px 0}
.summary{background:var(--card);border:1px solid var(--line);border-radius:14px;
         padding:14px;margin-bottom:18px;box-shadow:var(--shadow)}
.summary h2{margin:0 0 10px;font-size:1rem}
.sumrow{display:flex;align-items:center;gap:8px;padding:6px 0;border-top:1px solid var(--line);font-size:.9rem}
.sumrow:first-of-type{border-top:none}
.sumrow .cat{flex:1;font-weight:600}
.sumrow .p{font-weight:800}
.wl{background:var(--card);border:1px solid var(--line);border-radius:14px;
    padding:14px;margin-bottom:16px;box-shadow:var(--shadow)}
.wl h2{margin:0 0 2px;font-size:1.05rem}
.stats{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 10px}
.stat{background:var(--bg);border:1px solid var(--line);border-radius:10px;
      padding:7px 10px;text-align:center;min-width:74px}
.stat .v{font-weight:800;font-size:.95rem}
.stat .k{color:var(--muted);font-size:.68rem;text-transform:uppercase;letter-spacing:.04em}
.stat .u{color:var(--muted);font-size:.68rem}
.obs{color:var(--muted);font-size:.72rem;margin:-4px 0 10px}
.deal{display:flex;align-items:center;gap:10px;padding:8px;border-radius:10px;border:1px solid transparent}
.deal.best{background:var(--best);border-color:var(--best-line)}
.deal.baseline{background:var(--baseline);border-color:var(--baseline-line);margin:6px 0}
.deal img{width:44px;height:44px;object-fit:contain;border-radius:6px;background:#fff;flex:0 0 auto}
.deal .mid{flex:1;min-width:0}
.deal .nm{font-size:.85rem;font-weight:600;line-height:1.25}
.deal .meta{color:var(--muted);font-size:.75rem}
.deal .pr{text-align:right}
.deal .pr .p{font-weight:800;font-size:1rem}
.deal .pr .u{color:var(--muted);font-size:.72rem}
.deal .pr .cmp{font-size:.68rem;font-weight:700;white-space:nowrap}
.deal .pr .cmp.good{color:var(--good)}
.deal .pr .cmp.bad{color:var(--bad)}
.deal .pr .cmp.same{color:var(--muted)}
.baselinebadge{display:inline-block;background:var(--baseline-line);color:#142d4f;font-size:.62rem;
               font-weight:800;padding:1px 6px;border-radius:5px;margin-left:6px;vertical-align:middle}
.bestbadge{display:inline-block;background:var(--best-line);color:#3a2f0d;font-size:.62rem;
           font-weight:800;padding:1px 6px;border-radius:5px;margin-left:6px;vertical-align:middle}
.nodeal{color:var(--muted);font-size:.85rem;padding:4px 0}
footer{color:var(--muted);font-size:.72rem;text-align:center;padding:20px 14px 30px}
"""


def page(title, sub, active_tab, body, site_title):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{esc(title)} · {esc(site_title)}</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>{esc(site_title)}</h1>
  <p class="sub">{esc(sub)}</p>
  <nav>
    <a href="deals.html" class="{'on' if active_tab == 'all' else ''}">All Deals</a>
    <a href="index.html" class="{'on' if active_tab == 'wl' else ''}">My Items</a>
  </nav>
</header>
<main>
{body}
</main>
<footer>Prices from public store flyers via Flipp · for personal use ·
updated automatically by GitHub Actions</footer>
</body>
</html>"""


def deal_card(d):
    img = f'<img src="{esc(d["image"])}" loading="lazy" alt="" onerror="this.style.display=\'none\'">' if d.get("image") else ""
    up = ""
    if d.get("unit_price") is not None and d.get("unit") != "ea":
        up = f'<div class="uprice">{unit_price_text(d)}</div>'
    elif d.get("unit_price") is not None and d.get("price_basis", "").startswith("pkg"):
        up = f'<div class="uprice">{money(d["unit_price"])} each</div>'
    elif d.get("unit_price_low") is not None:
        up = f'<div class="uprice">{unit_price_text(d)}</div>'
    story = f'<div class="story">{esc(d["sale_story"])}</div>' if d.get("sale_story") else ""
    suffix = price_suffix(d.get("price_basis"))
    basis = ""
    if not suffix and d.get("price_basis") not in ("each", "package", "package range"):
        basis = f'<div class="basis">{esc(d["price_basis"])}</div>'
    if suffix == "/kg":
        up = ""  # big price already is the per-kg price
    search_text = fl.fold(f'{d.get("brand", "")} {d["name"]}')
    return f"""<div class="card" data-s="{esc(search_text)}">
{img}
  <div class="iname">{brand_prefix(d)}{esc(d["name"])}</div>
  <div class="price">{money(d["price"])}{'<span class="basis"> ' + suffix + '</span>' if suffix else ''}</div>
{up}{basis}{story}
</div>"""


def build_index(snapshot, cfg):
    deals = snapshot["deals"]
    stores = []
    for d in deals:
        if d["store"] not in stores:
            stores.append(d["store"])

    chips = '<div class="chips" id="chips"><button class="chip on" data-store="*">All</button>'
    for i, s in enumerate(stores):
        chips += f'<button class="chip" data-store="{esc(s)}">{esc(s)}</button>'
    chips += "</div>"

    sections = ""
    for i, s in enumerate(stores):
        sdeals = [d for d in deals if d["store"] == s]
        sdeals.sort(key=lambda d: fl.fold(f'{d.get("brand", "")} {d.get("name", "")}'))
        merchant = sdeals[0]["merchant"] if sdeals else s
        valid_to = sdeals[0].get("valid_to", "") if sdeals else ""
        cards = "".join(deal_card(d) for d in sdeals)
        sections += f"""<section class="storesec" data-store="{esc(s)}">
<div class="storehead"><span class="dot" style="background:{store_color(s, i)}"></span>
<h2>{esc(merchant)}</h2><span class="n">{len(sdeals)} deal{'s' if len(sdeals) != 1 else ''} · until {esc(valid_to)}</span></div>
<div class="grid">{cards}</div>
</section>"""

    missing = snapshot.get("stores_missing") or []
    missing_note = ""
    if missing:
        missing_note = f'<p class="sub">No current flyer found for: {esc(", ".join(missing))}</p>'

    body = f"""<div class="controls">
<input type="search" id="q" placeholder="Search deals… (e.g. yogurt, chicken)" autocomplete="off">
{chips}
</div>
{missing_note}
{sections}
<p class="empty" id="noresults" style="display:none">Nothing matches your search.</p>
<script>
(function(){{
  var q=document.getElementById('q'), chips=document.querySelectorAll('.chip'),
      secs=document.querySelectorAll('.storesec'), none=document.getElementById('noresults'),
      store='*';
  function norm(s){{return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();}}
  function apply(){{
    var term=norm(q.value.trim()); var any=false;
    secs.forEach(function(sec){{
      var okStore=(store==='*'||sec.dataset.store===store); var shown=0;
      sec.querySelectorAll('.card').forEach(function(c){{
        var ok=okStore&&(!term||c.dataset.s.indexOf(term)>-1);
        c.style.display=ok?'':'none'; if(ok)shown++;
      }});
      sec.style.display=(okStore&&shown>0)?'':'none'; if(okStore&&shown>0)any=true;
    }});
    none.style.display=any?'none':'';
  }}
  q.addEventListener('input',apply);
  chips.forEach(function(ch){{ch.addEventListener('click',function(){{
    chips.forEach(function(c){{c.classList.remove('on');}});
    ch.classList.add('on'); store=ch.dataset.store; apply();
  }});}});
}})();
</script>"""
    sub = f"Week of {snapshot['generated']} · {snapshot['postal_code']} · {len(deals)} deals across {len(stores)} stores"
    return page("All Deals", sub, "all", body, cfg["site_title"])


def build_watchlist(snapshot, history, cfg):
    deals = snapshot["deals"]
    stats = fl.category_stats(history, cfg["watchlist"], cfg.get("history_days", 365))

    # -- "where to go" summary: best store per category this week
    summary_rows, sections = "", ""
    for ci, cat in enumerate(cfg["watchlist"]):
        matches = [d for d in deals if cat["id"] in d.get("categories", [])]
        pref = cat.get("preferred_unit")
        display_unit = cat.get("display_unit")
        baseline = cat.get("baseline") or {}
        baseline_price = fl.baseline_unit_price(baseline, display_unit or "lb")
        baseline_store = baseline.get("store", "Baseline")

        matches.sort(key=lambda d: watchlist_sort_key(d, pref))
        best = matches[0] if matches else None
        best_price = exact_unit_price(best, display_unit or "lb") if best else None
        baseline_is_best = baseline_price is not None and (
            best is None or (best_price is not None and baseline_price <= best_price)
        )

        if baseline_is_best:
            bu = f"{money(baseline_price)}{unit_label(display_unit or 'lb')}"
            summary_rows += f"""<div class="sumrow"><span>{esc(cat.get('emoji', ''))}</span>
<span class="cat">{esc(cat['label'])}</span>
<span class="badge" style="background:{store_color(baseline_store)}">{esc(baseline_store)}</span>
<span class="p">{bu}</span></div>"""
        elif best:
            bu = unit_price_text(best, display_unit) or money(best["price"])
            summary_rows += f"""<div class="sumrow"><span>{esc(cat.get('emoji', ''))}</span>
<span class="cat">{esc(summary_category_label(cat, best))}</span>
<span class="badge" style="background:{store_color(best['store'])}">{esc(best['store'])}</span>
<span class="p">{bu}</span></div>"""

        # stats chips
        stat_html, obs_html = "", ""
        cat_stats = stats.get(cat["id"]) or []
        if cat_stats:
            unit, s = cat_stats[0]
            low, stat_unit = display_unit_price(s["low"], unit, display_unit)
            median, _ = display_unit_price(s["median"], unit, display_unit)
            high, _ = display_unit_price(s["high"], unit, display_unit)
            stat_html = f"""<div class="stats">
<div class="stat"><div class="k">1-yr low</div><div class="v">{money(low)}</div><div class="u">{unit_label(stat_unit)}</div></div>
<div class="stat"><div class="k">median</div><div class="v">{money(median)}</div><div class="u">{unit_label(stat_unit)}</div></div>
<div class="stat"><div class="k">1-yr high</div><div class="v">{money(high)}</div><div class="u">{unit_label(stat_unit)}</div></div>
</div>"""
            extra = []
            for u2, s2 in cat_stats[1:]:
                low2, shown_unit = display_unit_price(s2["low"], u2, display_unit)
                high2, _ = display_unit_price(s2["high"], u2, display_unit)
                extra.append(f"{money(low2)}–{money(high2)}{unit_label(shown_unit)} ({s2['n']} obs)")
            obs_html = f'<p class="obs">{s["n"]} price points over the last year' + \
                       (f' · also seen: {esc("; ".join(extra))}' if extra else "") + "</p>"
        else:
            obs_html = '<p class="obs">No history yet — stats build up as weekly runs accumulate.</p>'

        rows = ""
        if baseline and baseline_price is not None:
            baseline_suffix = "/lb" if baseline.get("unit") == "lb" else ""
            baseline_unit_text = "" if baseline_suffix and display_unit == "lb" else \
                f'<div class="u">{money(baseline_price)}{unit_label(display_unit or "lb")}</div>'
            rows += f"""<div class="deal baseline">
<div style="width:44px;text-align:center;font-size:1.35rem">{esc(baseline.get('emoji', '📌'))}</div>
<div class="mid"><div class="nm">{esc(baseline.get('label', cat['label']))}<span class="baselinebadge">{esc(baseline_store).upper()}</span>{'<span class="bestbadge">BEST</span>' if baseline_is_best else ''}</div>
<div class="meta">{esc(baseline.get('package_label', 'Reference price'))}</div></div>
<div class="pr"><div class="p">{money(baseline['price'])}{baseline_suffix}</div>{baseline_unit_text}</div>
</div>"""
        for d in matches[:8]:
            is_best = d is best and len(matches) > 1 and not baseline_is_best
            upx = unit_price_text(d, display_unit)
            comparison, comparison_class = baseline_comparison(
                d, baseline_price, display_unit or "lb", baseline_store)
            comparison_html = f'<div class="cmp {comparison_class}">{esc(comparison)}</div>' if comparison else ""
            img = f'<img src="{esc(d["image"])}" loading="lazy" alt="" onerror="this.style.display=\'none\'">' if d.get("image") else "<div style='width:44px'></div>"
            suffix = price_suffix(d.get("price_basis"))
            if (suffix == "/kg" and display_unit == "kg") or (suffix == "/lb" and display_unit == "lb"):
                upx = ""  # printed price already uses the requested display unit
            basis_meta = ""
            if not suffix and d.get("price_basis") not in ("each", "package", "package range"):
                basis_meta = " · " + esc(d["price_basis"])
            rows += f"""<div class="deal{' best' if is_best else ''}">
{img}
<div class="mid"><div class="nm">{brand_prefix(d)}{esc(d["name"])}{'<span class="bestbadge">BEST</span>' if is_best else ''}</div>
<div class="meta">{esc(d["store"])}{basis_meta}{' · ' + esc(d["sale_story"]) if d.get('sale_story') else ''}</div></div>
<div class="pr"><div class="p">{money(d["price"])}{suffix}</div><div class="u">{upx}</div>{comparison_html}</div>
</div>"""
        if not matches:
            rows += '<p class="nodeal">No deals on this in this week\'s flyers.</p>'

        sections += f"""<section class="wl">
<h2>{esc(cat.get('emoji', ''))} {esc(cat['label'])}</h2>
{stat_html}{obs_html}{rows}
</section>"""

    summary = ""
    if summary_rows:
        summary = f'<div class="summary"><h2>🛒 Where to go this week</h2>{summary_rows}</div>'

    body = summary + sections
    sub = f"Week of {snapshot['generated']} · your usual items, cheapest store first"
    return page("My Items", sub, "wl", body, cfg["site_title"])


def main():
    cfg = fl.load_config(sys.argv[1] if len(sys.argv) > 1 else None)
    latest = fl.DATA_DIR / "latest.json"
    if not latest.exists():
        print("data/latest.json missing — run fetch_flyers.py first")
        sys.exit(1)
    snapshot = json.loads(latest.read_text(encoding="utf-8"))
    history = fl.load_history()

    fl.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    watchlist_page = build_watchlist(snapshot, history, cfg)
    (fl.DOCS_DIR / "index.html").write_text(watchlist_page, encoding="utf-8")
    (fl.DOCS_DIR / "watchlist.html").write_text(watchlist_page, encoding="utf-8")
    (fl.DOCS_DIR / "deals.html").write_text(build_index(snapshot, cfg), encoding="utf-8")
    (fl.DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built docs/index.html + docs/deals.html "
          f"({len(snapshot['deals'])} deals, {len(history)} history rows)")


if __name__ == "__main__":
    main()
