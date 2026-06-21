#!/usr/bin/env python3
"""
explore_product.py — Constructor.io product detail explorer for jumbo.cl
READ-ONLY: no DB writes, no changes to existing pipeline files.

NOTE: The classic VTEX catalog API (catalog_system/pub/...) returns HTTP 410
      for ALL endpoints — Jumbo.cl has fully migrated to Constructor.io.
      This script targets the live Constructor.io API (ac.cnstrc.com).

Single-product mode — search, pretty-print all fields, save full JSON:
    python explore_product.py "Mantequilla Soprole"
    python explore_product.py --id 6797

Bulk collection mode — crawl categories, collect N unique products, save CSV:
    python explore_product.py --bulk                    # default 2000
    python explore_product.py --bulk --limit 2000
    python explore_product.py --bulk --limit 2000 --output exploration/out.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ── Configuration (mirrors jumbo_scraper/config.py — standalone copy) ─────────
CNSTRC_API_KEY  = "key_JopvNXKS61kwGkBe"
CNSTRC_SECTION  = "Products"
CNSTRC_BASE     = "https://ac.cnstrc.com"
GROUPS_URL      = f"{CNSTRC_BASE}/browse/groups"
BROWSE_URL      = f"{CNSTRC_BASE}/browse/group_id"
SEARCH_URL      = f"{CNSTRC_BASE}/search"

PAGE_SIZE       = 50       # results per page (Constructor.io allows up to 100)
REQUEST_TIMEOUT = 30.0
MIN_DELAY       = 0.4      # courtesy delay between requests (seconds)
MAX_DELAY       = 0.9
MAX_RETRIES     = 2

EXPLORATION_DIR = Path("exploration")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Spec arrays we give individual columns in the CSV
SPEC_COLS = [
    "Envase", "Tipo de Producto", "Origen", "Pais de Origen",
    "Evento", "Producto Nuevo", "Id Grupo", "Id Subrubro",
    "Vendido por", "SellerVSS",
]

# ── HTTP client ────────────────────────────────────────────────────────────────

def _build_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept":     "application/json",
    })
    return s


_last_request_ts: float = 0.0


def _throttle() -> None:
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    delay   = random.uniform(MIN_DELAY, MAX_DELAY)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_request_ts = time.monotonic()


def _get(session: requests.Session, url: str,
         params: dict | None = None) -> tuple[Any, int]:
    """Throttled GET with retry. Returns (json_or_None, http_status)."""
    _throttle()
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            print(f"  [ERROR] {url}: {exc}", file=sys.stderr)
            return None, 0

        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt + random.uniform(0, 1))
                continue
            return None, resp.status_code

        try:
            resp.raise_for_status()
        except requests.HTTPError:
            return None, resp.status_code

        return (resp.json() if resp.content else None), resp.status_code

    return None, 0


# ── EAN fetcher (product page JSON-LD) ────────────────────────────────────────

def fetch_ean(session: requests.Session, product_url: str) -> str:
    """
    Fetch the product page and extract the EAN barcode from the JSON-LD @graph.

    VTEX product pages embed a <script type="application/ld+json"> block whose
    @graph contains a Product node with "gtin": "7802107000937".

    Falls back to a raw regex scan if the JSON-LD parse fails.
    Returns "" when not found.
    """
    if not product_url:
        return ""
    _throttle()
    try:
        resp = session.get(product_url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    html = resp.text

    # Primary: parse JSON-LD @graph blocks
    for block in re.findall(
        r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>',
        html, re.DOTALL
    ):
        try:
            obj = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        for item in obj.get("@graph", [obj]):
            if not isinstance(item, dict):
                continue
            gtin = (item.get("gtin") or item.get("gtin13")
                    or item.get("gtin8") or item.get("gtin14") or "")
            if gtin:
                return str(gtin)

    # Fallback: raw regex on the full HTML
    m = re.search(r'"gtin(?:13)?"\s*:\s*"(\d{8,14})"', html)
    return m.group(1) if m else ""


# ── Field helpers ──────────────────────────────────────────────────────────────

def _category_path(product: dict) -> str:
    """Parse 'ProductCategories' JSON + 'ProductCategoryIds' path."""
    raw = product.get("ProductCategories") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            raw = {}
    id_path = product.get("ProductCategoryIds", "")
    ids = [x for x in id_path.strip("/").split("/") if x]
    if ids and raw:
        return " > ".join(raw.get(i, i) for i in ids)
    return " > ".join(raw.values()) if raw else ""


def _decode_json_list_field(product: dict, key: str) -> dict:
    """
    Constructor.io stores some fields as a list whose single element is a
    JSON string, e.g. SkuData = ['{"6885": {...}}'].  Decode and return the
    inner dict (or {} on failure).
    """
    raw = product.get(key, "{}")
    if isinstance(raw, list):
        raw = raw[0] if raw else "{}"
    if not isinstance(raw, str):
        return raw if isinstance(raw, dict) else {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {}


def _first_image(product: dict) -> str:
    imgs = product.get("images") or []
    return imgs[0] if imgs else product.get("image_url", "")


def _array_to_str(val: Any) -> str:
    if isinstance(val, list):
        return "; ".join(str(v) for v in val if v != "")
    return str(val) if val is not None else ""


def _extract_sku_data(product: dict) -> dict:
    """
    Parse the SkuData field (a JSON-encoded blob keyed by skuId).
    Returns the inner SKU dict, or {}.

    Example SkuData value for SKU 6885:
    {
      "measurement_unit":     "un",
      "unit_multiplier":      1,
      "measurement_unit_un":  "kg",   <- base unit (kg, l, ...)
      "unit_multiplier_un":   0.25,   <- how much in that base unit (0.25 kg = 250 g)
      "cart_limit":           "24",
      "allow_substitute":     false,
      "measurement_unit_selector": false
    }
    """
    sku_id  = str(product.get("id", ""))
    raw_map = _decode_json_list_field(product, "SkuData")
    return raw_map.get(sku_id, {})


def _flatten_product(product: dict) -> dict:
    """Convert one Constructor.io result.data dict to a flat CSV row."""
    scraped_at = datetime.now(timezone.utc).isoformat()

    pd  = _decode_json_list_field(product, "ProductData")
    sd  = _extract_sku_data(product)

    measurement_unit = (
        sd.get("measurement_unit")
        or pd.get("measurement_unit")
        or product.get("MeasurementUnit", "")
    )
    unit_multiplier = (
        sd.get("unit_multiplier")
        or pd.get("unit_multiplier")
        or product.get("UnitMultiplier")
    )

    row: dict = {
        # --- identity ---
        "productId":       product.get("ProductId") or product.get("productId", ""),
        "skuId":           product.get("id", ""),
        "productName":     product.get("ProductName") or product.get("value", ""),
        "brand":           product.get("BrandName") or _array_to_str(product.get("brands", "")),
        "brandId":         product.get("BrandId", ""),
        "refId":           product.get("RefId", "") or product.get("ProductRefId", ""),
        "ean":             "",   # populated later by fetch_ean() — not in Constructor.io index
        # --- category ---
        "categoryPath":        _category_path(product),
        "ProductCategoryIds":  product.get("ProductCategoryIds", ""),
        # --- url / image ---
        "productUrl":      product.get("url", ""),
        "imageUrl":        _first_image(product),
        # --- unit / pack info (top-level) ---
        "MeasurementUnit": measurement_unit,
        "UnitMultiplier":  unit_multiplier,
        # --- unit / pack info (from SkuData — more detailed) ---
        "sku_measurement_unit":    sd.get("measurement_unit", ""),
        "sku_unit_multiplier":     sd.get("unit_multiplier", ""),
        "sku_measurement_unit_un": sd.get("measurement_unit_un", ""),   # e.g. "kg", "l"
        "sku_unit_multiplier_un":  sd.get("unit_multiplier_un", ""),    # e.g. 0.25 (= 250 g)
        "sku_cart_limit":          sd.get("cart_limit", ""),
        "sku_allow_substitute":    sd.get("allow_substitute", ""),
        # --- pricing / availability ---
        "price":           product.get("price") or product.get("sellingPrice", ""),
        "listPrice":       product.get("listPrice") or product.get("originalPrice", ""),
        "outOfStock":      product.get("outOfStock", ""),
        "stockLevel":      product.get("stockLevel", ""),
        # --- seller ---
        "storeId":         product.get("storeId", ""),
        "sellerName":      _array_to_str(product.get("Vendido por", "")),
        "allSellersCount": len(product.get("SellerVSS") or []),
        # --- raw JSON blobs for deep inspection ---
        "raw_SkuData_json":     json.dumps(sd, ensure_ascii=False),
        "raw_ProductData_json": json.dumps(pd, ensure_ascii=False),
        "scrapedAt":            scraped_at,
    }

    # Individual spec columns
    for col in SPEC_COLS:
        row[f"spec_{col}"] = _array_to_str(product.get(col, ""))

    return row


# CSV column order (stable)
CSV_FIELDNAMES = [
    "productId", "skuId", "productName", "brand", "brandId", "refId", "ean",
    "categoryPath", "ProductCategoryIds",
    "productUrl", "imageUrl",
    "MeasurementUnit", "UnitMultiplier",
    "sku_measurement_unit", "sku_unit_multiplier",
    "sku_measurement_unit_un", "sku_unit_multiplier_un",
    "sku_cart_limit", "sku_allow_substitute",
    "price", "listPrice", "outOfStock", "stockLevel",
    "storeId", "sellerName", "allSellersCount",
    "raw_SkuData_json", "raw_ProductData_json",
    "scrapedAt",
] + [f"spec_{c}" for c in SPEC_COLS]


# ── Single-product exploration ─────────────────────────────────────────────────

def explore_single(session: requests.Session, query: str) -> None:
    """Search Constructor.io for `query`, print all fields, save full JSON."""
    EXPLORATION_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    url    = f"{SEARCH_URL}/{requests.utils.quote(query, safe='')}"
    params = {"key": CNSTRC_API_KEY, "section": CNSTRC_SECTION,
              "num_results_per_page": 3}

    print(f"\n{'='*70}")
    print(f"  Constructor.io search: {query!r}")
    print(f"  URL: {url}")
    print(f"{'='*70}")

    data, status = _get(session, url, params)
    if not data:
        print(f"  No data (HTTP {status})")
        return

    results = (data.get("response") or {}).get("results") or []
    if not results:
        print("  No results found.")
        return

    # Save full JSON
    out_path = EXPLORATION_DIR / f"{ts}_search_{query[:30].replace(' ', '_')}.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  HTTP {status} — {len(results)} result(s)  ->  saved {out_path}\n")

    for i, result in enumerate(results):
        product = result.get("data") or {}
        print(f"\n--- Result [{i+1}] ---")
        print(f"  productId:    {product.get('ProductId') or product.get('productId')}")
        print(f"  skuId:        {product.get('id')}")
        print(f"  productName:  {product.get('ProductName') or product.get('value')}")
        print(f"  brand:        {product.get('BrandName')}")
        print(f"  category:     {_category_path(product)}")
        print(f"  url:          {product.get('url', '')}")

        print(f"\n  -- Unit / pack fields --")
        print(f"  MeasurementUnit:  {product.get('MeasurementUnit')}")
        print(f"  UnitMultiplier:   {product.get('UnitMultiplier')}")

        sd = _extract_sku_data(product)
        if sd:
            print(f"  SkuData for SKU {product.get('id')}:")
            for k, v in sd.items():
                print(f"    {k}: {v}")
        else:
            print(f"  SkuData: (empty / not parsed)")

        pd = _decode_json_list_field(product, "ProductData")
        if pd:
            print(f"  ProductData:")
            for k, v in pd.items():
                print(f"    {k}: {v}")

        print(f"\n  -- Spec arrays --")
        for col in SPEC_COLS + ["KeyWords", "Evento", "Regalos"]:
            val = product.get(col)
            if val is not None and val != "" and val != [""]:
                print(f"  {col}: {val}")

        print(f"\n  -- Pricing --")
        print(f"  price:      {product.get('price') or product.get('sellingPrice')}")
        print(f"  listPrice:  {product.get('listPrice') or product.get('originalPrice')}")
        print(f"  outOfStock: {product.get('outOfStock')}  stockLevel: {product.get('stockLevel')}")

        # Print all remaining keys not yet covered
        covered = {
            "id", "url", "ProductId", "productId", "ProductName", "value",
            "BrandName", "brands", "BrandId", "ProductCategories",
            "ProductCategoryIds", "MeasurementUnit", "UnitMultiplier",
            "SkuData", "ProductData", "price", "sellingPrice", "listPrice",
            "originalPrice", "outOfStock", "stockLevel", "image_url", "images",
            "storeId", "variation_id", "RefId", "ProductRefId",
        } | set(SPEC_COLS) | {"KeyWords", "Evento", "Regalos"}
        extra = {k: v for k, v in product.items() if k not in covered and v}
        if extra:
            print(f"\n  -- Other fields --")
            for k, v in extra.items():
                print(f"  {k}: {v}")

    print(f"\n{'='*70}\n")


# ── Bulk collection ────────────────────────────────────────────────────────────

def _collect_leaf_groups(groups: list, out: list | None = None) -> list:
    if out is None:
        out = []
    for g in groups:
        children = g.get("children") or []
        if children:
            _collect_leaf_groups(children, out)
        else:
            out.append({"id": str(g["group_id"]), "name": g.get("display_name", "")})
    return out


def bulk_collect(session: requests.Session, limit: int, out_path: Path) -> None:
    EXPLORATION_DIR.mkdir(exist_ok=True)

    # -- 1. Groups ---------------------------------------------------------
    print("[1/3] Fetching Constructor.io group tree ...")
    grp_data, status = _get(session, GROUPS_URL,
                            {"key": CNSTRC_API_KEY, "section": CNSTRC_SECTION})
    if not grp_data:
        sys.exit(f"  Failed to fetch groups (HTTP {status}). Aborting.")

    groups = (grp_data.get("response") or {}).get("groups") or []
    leaves = _collect_leaf_groups(groups)
    print(f"  {len(groups)} root groups, {len(leaves)} leaf categories found.")

    # Per-category cap: spread the budget across all categories so we get variety.
    # At minimum 20 per category; at most PAGE_SIZE per pass.
    per_cat_quota = max(20, math.ceil(limit / len(leaves))) if leaves else limit
    print(f"  Per-category quota: {per_cat_quota} products  (guarantees >= {len(leaves)} categories)\n")

    # -- 2. Collect products -----------------------------------------------
    print(f"[2/3] Collecting up to {limit} unique products across categories ...")
    print(f"  Output -> {out_path}\n")

    seen_ids: set[str] = set()
    total_rows = 0

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()

        for cat_idx, cat in enumerate(leaves):
            if len(seen_ids) >= limit:
                break

            cat_id   = cat["id"]
            cat_name = cat["name"]
            page     = 1
            last_pg  = None
            cat_new  = 0

            while len(seen_ids) < limit and cat_new < per_cat_quota:
                raw, status = _get(
                    session,
                    f"{BROWSE_URL}/{cat_id}",
                    params={
                        "key":                  CNSTRC_API_KEY,
                        "section":              CNSTRC_SECTION,
                        "num_results_per_page": PAGE_SIZE,
                        "page":                 page,
                    },
                )

                if not raw:
                    break

                resp    = raw.get("response") or {}
                results = resp.get("results") or []

                if last_pg is None:
                    total_in_cat = resp.get("total_num_results") or 0
                    last_pg = max(1, math.ceil(total_in_cat / PAGE_SIZE))

                for result in results:
                    if cat_new >= per_cat_quota or len(seen_ids) >= limit:
                        break
                    product = result.get("data") or {}
                    pid = str(product.get("ProductId") or product.get("productId") or "")
                    if not pid or pid in seen_ids:
                        continue
                    seen_ids.add(pid)
                    cat_new += 1
                    total_rows += 1
                    writer.writerow(_flatten_product(product))

                print(
                    f"  [{cat_idx+1:3d}/{len(leaves)}] {cat_name[:36]:36s} | "
                    f"page={page:3d}/{last_pg} | cat_new={cat_new:4d} | "
                    f"total={len(seen_ids):5d}",
                    end="\r",
                )

                if page >= last_pg or len(results) < PAGE_SIZE or cat_new >= per_cat_quota:
                    break
                page += 1

            print(
                f"  [{cat_idx+1:3d}/{len(leaves)}] {cat_name[:36]:36s} | "
                f"pages={last_pg or '?'} | new={cat_new:4d} | total={len(seen_ids):5d}     "
            )

    # -- 3. Summary --------------------------------------------------------
    print(f"\n[3/3] Done.")
    print(f"  Unique products collected : {len(seen_ids)}")
    print(f"  CSV rows written          : {total_rows}")
    print(f"  File                      : {out_path}")


# ── Brand filter collection ────────────────────────────────────────────────────

def collect_by_brand(session: requests.Session, brand: str, out_path: Path,
                     fetch_ean_flag: bool = False) -> None:
    """Fetch ALL products for a specific brand using Constructor.io search + brand filter."""
    EXPLORATION_DIR.mkdir(exist_ok=True)

    print(f"\n[brand filter] Fetching all products for brand: {brand!r}")
    if fetch_ean_flag:
        print(f"  EAN enrichment ON (1 extra page request per product)")
    print(f"  Output -> {out_path}\n")

    seen_ids: set[str] = set()
    total_rows = 0
    page = 1
    last_pg: int | None = None

    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()

        while True:
            raw, status = _get(
                session,
                f"{SEARCH_URL}/{requests.utils.quote(brand, safe='')}",
                params={
                    "key":                    CNSTRC_API_KEY,
                    "section":                CNSTRC_SECTION,
                    "num_results_per_page":   PAGE_SIZE,
                    "page":                   page,
                    "filters[BrandName]":     brand,
                },
            )

            if not raw:
                print(f"  No response (HTTP {status}). Stopping.")
                break

            resp    = raw.get("response") or {}
            results = resp.get("results") or []

            if last_pg is None:
                total = resp.get("total_num_results") or 0
                last_pg = max(1, math.ceil(total / PAGE_SIZE))
                print(f"  {total} products found across {last_pg} page(s)\n")

            for result in results:
                product = result.get("data") or {}
                pid = str(product.get("ProductId") or product.get("productId") or "")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)
                total_rows += 1
                row = _flatten_product(product)
                if fetch_ean_flag:
                    row["ean"] = fetch_ean(session, row.get("productUrl", ""))
                    print(f"  [{total_rows}] EAN={row['ean'] or '(not found)':14s}  {row['productName'][:50]}")
                writer.writerow(row)

            print(f"  page {page}/{last_pg} — collected so far: {len(seen_ids)}", end="\r")

            if page >= last_pg or len(results) < PAGE_SIZE:
                break
            page += 1

    print(f"\n  Done. {len(seen_ids)} unique products -> {out_path}")


# ── EAN enrichment of an existing CSV ─────────────────────────────────────────

def enrich_ean(session: requests.Session, input_csv: Path, output_csv: Path) -> None:
    """
    Read an existing CSV produced by this script, fetch the EAN barcode for
    every row that has a productUrl, and write a new CSV with the ean column
    populated.

    Skips rows that already have an EAN. Reuses the same throttle so we stay
    polite to the server (0.4–0.9 s between requests).
    """
    # utf-8-sig: tolera el BOM que escribe el Storage del scraper
    with open(input_csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        in_fields = list(reader.fieldnames or [])

    # Ensure ean column exists in output
    out_fields = in_fields if "ean" in in_fields else (
        in_fields[:in_fields.index("refId") + 1] + ["ean"] + in_fields[in_fields.index("refId") + 1:]
        if "refId" in in_fields else in_fields + ["ean"]
    )

    need_fetch = [r for r in rows if not r.get("ean") and r.get("productUrl")]
    already    = len(rows) - len(need_fetch)

    print(f"\n[enrich-ean] {input_csv.name}")
    print(f"  Total rows : {len(rows)}")
    print(f"  Already have EAN : {already}")
    print(f"  To fetch         : {len(need_fetch)}")
    print(f"  Output -> {output_csv}\n")

    fetched = 0
    failed  = 0
    for i, row in enumerate(rows):
        if row.get("ean") or not row.get("productUrl"):
            continue
        ean = fetch_ean(session, row["productUrl"])
        row["ean"] = ean
        if ean:
            fetched += 1
        else:
            failed += 1
        print(f"  [{i+1:4d}/{len(rows)}] EAN={ean or '(not found)':14s}  {row.get('productName','')[:50]}", end="\r")

    print(f"\n  Fetched: {fetched}   Not found: {failed}")

    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"  Saved -> {output_csv}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Constructor.io product detail explorer for jumbo.cl — read-only"
    )
    ap.add_argument("query", nargs="?",
                    help="Search query or product name for single-product mode")
    ap.add_argument("--id", dest="product_id",
                    help="Search by VTEX product ID (single mode)")
    ap.add_argument("--brand",
                    help="Fetch all products for a specific brand (e.g. 'Volcanes del Sur')")
    ap.add_argument("--fetch-ean", action="store_true",
                    help="Fetch EAN from each product page during --brand or --bulk collection")
    ap.add_argument("--enrich-ean", dest="enrich_csv", metavar="CSV",
                    help="Read an existing CSV and add EAN barcodes to it, saving a new file")
    ap.add_argument("--bulk", action="store_true",
                    help="Bulk collection mode")
    ap.add_argument("--limit", type=int, default=2000,
                    help="Max unique products in bulk mode (default: 2000)")
    ap.add_argument("--output", default=None,
                    help="Output CSV path for bulk/brand/enrich mode")
    args = ap.parse_args()

    session = _build_session()
    try:
        if args.enrich_csv:
            inp = Path(args.enrich_csv)
            if not inp.exists():
                sys.exit(f"File not found: {inp}")
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = (Path(args.output) if args.output
                   else inp.parent / f"{inp.stem}_ean_{ts}.csv")
            enrich_ean(session, inp, out)

        elif args.bulk:
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = (Path(args.output) if args.output
                   else EXPLORATION_DIR / f"products_detail_{ts}.csv")
            bulk_collect(session, args.limit, out)

        elif args.brand:
            ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug = args.brand.replace(" ", "_")[:30]
            out = (Path(args.output) if args.output
                   else EXPLORATION_DIR / f"brand_{slug}_{ts}.csv")
            collect_by_brand(session, args.brand, out, fetch_ean_flag=args.fetch_ean)

        else:
            query = args.query or (str(args.product_id) if args.product_id else "Mantequilla Soprole")
            explore_single(session, query)

    finally:
        session.close()


if __name__ == "__main__":
    main()
