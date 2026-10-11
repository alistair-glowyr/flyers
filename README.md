# Runnymede Grocery Deals

A self-updating, mobile-friendly static site for local grocery flyer deals. It has:

- **All Deals** — searchable weekly grocery deals grouped by store.
- **My Items** — the default page, with stricter matches for frequently purchased
  items, configurable baseline prices, and one-year low/median/high history.

The implementation uses only the Python standard library. GitHub Actions fetches the
weekly data, runs regression tests, builds the static pages, preserves price history,
and deploys directly to GitHub Pages.

## GitHub setup

1. Push this repository's `main` branch to the intended GitHub account.
2. In **Settings → Pages**, choose **GitHub Actions** as the deployment source.
3. In **Actions**, run **Update and deploy grocery deals** manually if the initial
   push did not already start it.
4. After the successful run, use the Pages URL shown in the deployment job and add
   it to the phone's home screen.

The workflow declares only the token permissions it needs; repository-wide
read/write workflow permissions are not required. It runs every Thursday at 12:00
UTC (8am Toronto during daylight-saving time) and can be run manually at any time.

GitHub Pages sites are public. The generated pages expose the configured postal code
and watchlist, so do not put private information in `config.json`.

## Configuration

`config.json` controls all local behaviour:

| Key | Purpose |
|---|---|
| `postal_code` | Postal code used to localize Flipp results. |
| `stores` | Store labels shown on the site. Merchant matching is exact. |
| `flyer_rules` | Per-store allow-list for weekly flyer names. Seasonal, beauty, clothing, and other catalogues are rejected. |
| `flyer_max_days` | Rejects unusually long catalogue validity windows. |
| `watchlist` | Strict whole-word or phrase matching rules. A pattern ending in `*` is a word-prefix, such as `blueberr*`. |
| `watchlist[].display_unit` | Unit used on My Items. Weight-based items are displayed per pound. |
| `watchlist[].baseline` | Optional non-flyer reference price. Tray prices include a weight so they can be compared per pound. |
| `watchlist[].baseline.store` | Store name shown for the reference price and used when it wins the weekly summary. |
| `item_detail_scope` | `watchlist_candidates` enriches only plausible watchlist items; `all` and `none` are available for debugging. |
| `history_days` | Window used for low/median/high statistics. |
| `history_keep_days` | Retention window for committed history rows. |

Each run writes `data/flyer_audit.json`. It records every flyer belonging to a
configured merchant, whether it was selected, and why. Review this file or the
workflow log before changing an allow-list when a merchant renames its weekly flyer.
Do not automatically accept every new title: a rejected title may be a seasonal or
department catalogue.

## Price normalization

Prices are normalized internally to dollars per kg, litre, or item when the listing is clear.
Supported examples include package sizes (`650 g`), multi-packs (`12x310 mL`),
per-pound produce, and multi-buy prices.

My Items converts comparable weight prices and historical statistics to dollars per
pound. Configured baselines retain their original tray or per-pound price and show the
equivalent per-pound value beside current flyer deals.

A single parseable size range such as `340–454 g` is displayed as a unit-price range.
Listings containing several unrelated sizes are labelled as ambiguous and are not
used for unit-price comparisons or historical statistics.

## Running locally

```bash
python3 tests/test_normalize.py
python3 scripts/fetch_flyers.py
python3 scripts/build_site.py
open docs/index.html
```

Useful lower-cost fetch modes:

```bash
python3 scripts/fetch_flyers.py --no-details
python3 scripts/fetch_flyers.py --detail-scope watchlist_candidates
python3 scripts/fetch_flyers.py --fixtures tests/fixtures
```

## Project layout

```text
config.json                   location, flyer rules, stores, and watchlist
scripts/flyerlib.py           API client, filtering, matching, normalization, stats
scripts/fetch_flyers.py       fetch -> latest snapshot, history, and flyer audit
scripts/build_site.py         data -> responsive static pages in docs/
.github/workflows/update.yml  weekly test, update, commit, and Pages deployment
data/                         generated snapshot, audit, and accumulated history
docs/                         generated GitHub Pages site
tests/                        offline fixtures and regression tests
```

Data comes from the public API used by Flipp. Requests are sequential and throttled;
the default detail scope limits enrichment requests to potential watchlist matches.
