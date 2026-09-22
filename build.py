#!/usr/bin/env python3
"""Rebuild the embedded catalog in index.html.

Fetches BRIDGE research dumps (https://github.com/sierra-moxon/bridge-research),
including the BASALT dump used as the drop-target schema, slims them, and
rewrites the <script id="catalog"> block so the page stays a single file://-able
HTML document. Standard library only.

    python3 build.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HTML = ROOT / "index.html"
CACHE = ROOT / ".cache/bridge-dumps"
MARKER = '<script id="catalog" type="application/json">'
BRIDGE_RAW = "https://raw.githubusercontent.com/sierra-moxon/bridge-research/main"

# Dump key, short label, longer title. BASALT is the target, not a source.
SCHEMAS = [
    ("nmdc", "NMDC", "NMDC Schema"),
    ("nmdc_lakehouse", "NMDC Lakehouse", "NMDC lakehouse (flattened)"),
    ("lambda", "LAMBDA-BER", "LAMBDA-BER Schema"),
    ("aims_leaf", "AIMS-LEAF", "AIMS-LEAF Schema"),
    ("cdm", "KBase CDM", "KBase Common Data Model"),
    ("cdm_credit", "KBase Credit", "KBase credit / CRediT schema"),
    ("basin3d", "BASIN-3D", "BASIN-3D (dschristianson)"),
    ("basin3d_cmungall", "BASIN-3D cmungall", "BASIN-3D (cmungall rendering)"),
    ("bertron", "BERtron", "BERtron Schema"),
    ("brc", "BRC", "BRC Schema"),
    ("osti", "OSTI", "OSTI E-Link schema"),
    ("kg_registry", "KG Registry", "Knowledge Graph Registry"),
    ("standards", "Standards", "Bridge2AI standards-schemas"),
    ("data_sheets", "Data Sheets", "Data-sheets schema"),
    ("model_card", "Model Card", "Model-card schema"),
    ("geochem_rf", "Geochem RF", "ESS-DIVE geochem RF (LinkML)"),
    ("miappe", "MIAPPE", "MIAPPE LinkML"),
    ("linkml_test", "linkml-test", "linkml-test (MIAPPE derivative)"),
    ("pathogen", "Pathogen WW", "Pathogen genomics wastewater package"),
]


def _trim(text, n=280):
    text = (text or "").strip()
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _slim_slots(raw_slots, cap=80):
    out = []
    for s in raw_slots or []:
        if not isinstance(s, dict) or "error" in s or not s.get("name"):
            continue
        out.append({
            "name": s["name"],
            "range": s.get("range") or "",
            "required": bool(s.get("required")),
        })
        if len(out) >= cap:
            break
    n = len([s for s in (raw_slots or []) if isinstance(s, dict) and s.get("name")])
    return out, n


def slim_foreign_class(name, c):
    slots, n_slots = _slim_slots(c.get("induced_slots"))
    return {
        "name": name,
        "desc": _trim(c.get("description")),
        "is_a": c.get("is_a"),
        "abstract": bool(c.get("abstract")),
        "mixin": bool(c.get("mixin")),
        "n_slots": n_slots,
        "slots": slots,
    }


def fetch_dump(key: str) -> dict:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"_dump_{key}.json"
    url = f"{BRIDGE_RAW}/_dump_{key}.json"
    if path.exists() and path.stat().st_size > 100:
        return json.loads(path.read_text())
    req = urllib.request.Request(url, headers={"User-Agent": "BASALT-schema-mapper/1.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read()
    path.write_bytes(data)
    return json.loads(data.decode("utf-8"))


def build_basalt():
    dump = fetch_dump("basalt")
    classes = dump.get("classes") or {}

    def anc_set(name):
        out = set()
        cur = name
        seen = set()
        while cur and cur not in seen:
            seen.add(cur)
            out.add(cur)
            cur = (classes.get(cur) or {}).get("is_a")
        return out

    def bucket_of(name):
        a = anc_set(name)
        if name == "Site":
            return "site_meta"
        if "ProcessedSample" in a:
            return "processed"
        if "DataProduct" in a or "PlateProduct" in a or name in ("MAOMProduct", "WEOMProduct"):
            return "products"
        if "DataProcessingActivity" in a:
            return "dataproc"
        if "DataGenerationActivity" in a:
            return "datagen"
        if "SampleProcessing" in a or "LabProcessingActivity" in a or "PurchasedMaterial" in a:
            return "processing"
        if "SamplingActivity" in a:
            return "sampling"
        if "Sample" in a:
            return "samples"
        return None

    children = {}
    for name, c in classes.items():
        parent = c.get("is_a")
        if parent:
            children.setdefault(parent, []).append(name)

    out = {}
    for name, c in classes.items():
        slots, n_slots = _slim_slots(c.get("induced_slots"))
        out[name] = {
            "name": name,
            "desc": _trim(c.get("description")),
            "is_a": c.get("is_a"),
            "abstract": bool(c.get("abstract")),
            "mixin": bool(c.get("mixin")),
            "bucket": bucket_of(name),
            "n_slots": n_slots,
            "slots": slots,
            "children": sorted(children.get(name, [])),
        }
    return out


def build_catalog():
    print("  basalt dump…")
    basalt = build_basalt()
    schemas = {}
    errors = []

    def one(key, short, title):
        dump = fetch_dump(key)
        meta = dump.get("schema") or {}
        classes = {
            name: slim_foreign_class(name, c)
            for name, c in (dump.get("classes") or {}).items()
        }
        return key, {
            "key": key,
            "short": short,
            "title": meta.get("title") or title,
            "name": meta.get("name") or short,
            "desc": _trim(meta.get("description"), 420),
            "n_classes": len(classes),
            "classes": classes,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(one, key, short, title): key for key, short, title in SCHEMAS}
        for fut in as_completed(futs):
            key = futs[fut]
            try:
                k, payload = fut.result()
                schemas[k] = payload
                print(f"  {k}: {payload['n_classes']} classes")
            except Exception as e:
                errors.append((key, str(e)))
                print(f"  {key}: FAILED — {e}", file=sys.stderr)

    if errors and len(schemas) < 5:
        raise SystemExit(f"Too many dump fetch failures: {errors}")

    order = [k for k, _, _ in SCHEMAS if k in schemas]
    return {
        "source": "https://github.com/sierra-moxon/bridge-research",
        "basalt": {"classes": basalt},
        "schema_order": order,
        "schemas": schemas,
    }


def main():
    if not HTML.exists():
        raise SystemExit(f"missing {HTML}")
    print("Building BASALT buckets + fetching BRIDGE dumps…")
    catalog = build_catalog()
    html = HTML.read_text()
    start = html.index(MARKER) + len(MARKER)
    end = html.index("</script>", start)
    payload = json.dumps(catalog, separators=(",", ":")).replace("</", "<\\/")
    HTML.write_text(html[:start] + payload + html[end:])

    n_src = sum(s["n_classes"] for s in catalog["schemas"].values())
    buckets = {}
    for c in catalog["basalt"]["classes"].values():
        if c["bucket"]:
            buckets[c["bucket"]] = buckets.get(c["bucket"], 0) + 1
    print(f"✓ {HTML.name} updated — {n_src} source classes, "
          f"{len(catalog['basalt']['classes'])} BASALT classes")
    print("  BASALT buckets:", ", ".join(f"{k}={v}" for k, v in sorted(buckets.items())))
    print(f"  catalog payload {len(payload)/1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
