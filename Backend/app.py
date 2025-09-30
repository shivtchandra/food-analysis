# backend/app.py
import os
import shutil
import traceback
import logging
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
from fastapi import FastAPI, UploadFile, File, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# local modules (must exist)
from fdc_utils import lookup_food_nutrients, search_food, get_food_by_fdcid
from image_utils import map_items_from_image_bytes
from fda_daily_values import FDA_DV

# optional CSV analyzer
try:
    from nutrition_utils import analyze_orders
except Exception:
    analyze_orders = None

# config
DEBUG = True
DATA_DIR = os.path.dirname(__file__) or "."
INDIAN_DB_PATH = os.path.join(DATA_DIR, 'indian_food_db.csv')

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("food-analysis")

app = FastAPI(title="Food Analysis API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"] if DEBUG else ["https://your.prod.domain"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# JSON sanitizer
import math
import numpy as _np

def _sanitize_value(v):
    if isinstance(v, (_np.integer,)):
        return int(v)
    if isinstance(v, (_np.floating,)):
        fv = float(v)
        if not math.isfinite(fv):
            return None
        return fv
    if isinstance(v, _np.ndarray):
        return [_sanitize_value(x) for x in v.tolist()]
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return v
    if isinstance(v, (int, str, bool, type(None))):
        return v
    try:
        if hasattr(v, "item"):
            item = v.item()
            return _sanitize_value(item)
    except Exception:
        pass
    return None

def sanitize_for_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_for_json(x) for x in obj]
    return _sanitize_value(obj)

def json_error(msg, exc=None):
    payload = {"error": msg}
    if DEBUG and exc is not None:
        payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=500, content=payload)


@app.get("/sample/")
def sample():
    return {"status":"ok","msg":"Use POST /analyze/ or /analyze_image_with_micronutrients/ to analyze."}


# -----------------------
# Micronutrient helpers
# -----------------------
def _as_float(x) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None

def scale_nutrients(nutrients: Dict[str, Any], multiplier: float) -> Dict[str, float]:
    out = {}
    for k, v in (nutrients or {}).items():
        fv = _as_float(v)
        if fv is None:
            continue
        out[k] = fv * multiplier
    return out

def merge_totals(agg: Dict[str, float], add: Dict[str, float]) -> Dict[str, float]:
    for k, v in (add or {}).items():
        if v is None:
            continue
        try:
            agg[k] = agg.get(k, 0.0) + float(v)
        except Exception:
            pass
    return agg

def compute_item_macros(nutrients: Dict[str, Any]) -> Dict[str, Optional[float]]:
    get = lambda key: _as_float(nutrients.get(key)) if nutrients else None
    calories = get("calories_kcal")
    protein = get("protein_g")
    carbs = get("total_carbohydrate_g") or get("total_carbohydrate")
    fat = get("total_fat_g") or get("fat") or get("fat_g")
    fiber = get("dietary_fiber_g") or get("fiber_g") or get("fiber")
    sugars = get("sugars_g") or get("sugars") or get("sugar_g")

    if calories is None and any(x is not None for x in (protein, carbs, fat)):
        p = protein or 0.0
        c = carbs or 0.0
        f = fat or 0.0
        calories = p * 4.0 + c * 4.0 + f * 9.0

    return {
        "calories_kcal": calories,
        "protein_g": protein,
        "total_carbohydrate_g": carbs,
        "total_fat_g": fat,
        "dietary_fiber_g": fiber,
        "sugars_g": sugars
    }

def build_macros_summary_from_totals(micronutrient_totals: Dict[str, float]) -> Dict[str, Optional[int]]:
    def to_int(x):
        try:
            if x is None:
                return None
            return int(round(float(x)))
        except Exception:
            return None
    return {
        "total_calories": to_int(micronutrient_totals.get("calories_kcal")),
        "total_protein": to_int(micronutrient_totals.get("protein_g")),
        "total_carbs": to_int(micronutrient_totals.get("total_carbohydrate_g")),
        "total_fat": to_int(micronutrient_totals.get("total_fat_g")),
        "total_fiber": to_int(micronutrient_totals.get("dietary_fiber_g")),
        "total_sugar": to_int(micronutrient_totals.get("sugars_g") or micronutrient_totals.get("sugar_g"))
    }

# --- NEW: smarter key-finding & unit conversion for %DV computation ---
def _unit_to_base(unit_str: Optional[str]) -> Optional[str]:
    if not unit_str:
        return None
    u = unit_str.lower()
    if u in ("g","gram","grams"):
        return "g"
    if u in ("mg","milligram","milligrams"):
        return "mg"
    if u in ("mcg","μg","microgram","micrograms"):
        return "mcg"
    if u in ("kcal","calories","cal"):
        return "kcal"
    return u

def _convert_value_to_target(value: float, from_unit: Optional[str], to_unit: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    fu = _unit_to_base(from_unit)
    tu = _unit_to_base(to_unit)
    try:
        if fu == tu or tu is None or fu is None:
            return float(value)
        # mcg <-> mg
        if fu in ("mcg", "μg") and tu == "mg":
            return float(value) / 1000.0
        if fu == "mg" and tu in ("mcg", "μg"):
            return float(value) * 1000.0
        # g <-> mg
        if fu == "g" and tu == "mg":
            return float(value) * 1000.0
        if fu == "mg" and tu == "g":
            return float(value) / 1000.0
        return float(value)
    except Exception:
        return None

def find_best_nutrient_key(target_key: str, available: Dict[str, float]) -> Optional[Tuple[str, float]]:
    if not available:
        return None
    if target_key in available:
        return target_key, available[target_key]

    base = target_key
    for suffix in ("_mg", "_mcg", "_g", "_kcal", "_RAE", "_NE"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = base.lower()

    for k in available.keys():
        k_lower = k.lower()
        if k_lower == base:
            return k, available[k]
        if k_lower.startswith(base + "_"):
            return k, available[k]
    for k in available.keys():
        if base in k.lower():
            return k, available[k]
    return None

def compute_percent_dv(micronutrient_totals: Dict[str, float]) -> Dict[str, Optional[float]]:
    out = {}
    if not isinstance(micronutrient_totals, dict):
        return out

    for dv_key, dv_value in (FDA_DV or {}).items():
        try:
            match = find_best_nutrient_key(dv_key, micronutrient_totals)
            if match:
                found_key, found_val = match
                from_unit = None
                if found_key.endswith("_mg"):
                    from_unit = "mg"
                elif found_key.endswith("_mcg"):
                    from_unit = "mcg"
                elif found_key.endswith("_g"):
                    from_unit = "g"
                elif found_key.endswith("_kcal"):
                    from_unit = "kcal"

                target_unit = None
                if dv_key.endswith("_mg"):
                    target_unit = "mg"
                elif dv_key.endswith("_mcg"):
                    target_unit = "mcg"
                elif dv_key.endswith("_g"):
                    target_unit = "g"
                elif dv_key.endswith("_kcal"):
                    target_unit = "kcal"

                val_converted = _convert_value_to_target(_as_float(found_val), from_unit, target_unit)
                if val_converted is None:
                    out[dv_key] = None
                else:
                    pct = (float(val_converted) / float(dv_value)) * 100.0 if dv_value else None
                    out[dv_key] = None if pct is None else round(pct, 1)
            else:
                out[dv_key] = None
        except Exception:
            out[dv_key] = None
    return out

# Friendly DV classification for UI
def classify_percent_dv(pct: Optional[float]):
    if pct is None:
        return {"pct": None, "category": "unknown", "label": "No data", "advice": "No data available."}
    if pct >= 20:
        return {"pct": pct, "category": "high", "label": "High (good source)", "advice": "This food is a significant source — useful to meet daily needs."}
    if pct >= 5:
        return {"pct": pct, "category": "moderate", "label": "Moderate", "advice": "Contributes to daily needs; combine with other foods."}
    return {"pct": pct, "category": "low", "label": "Low", "advice": "Low — consider adding foods rich in this nutrient."}

# Debug endpoints to test FDC connectivity
@app.get("/debug_fdc_raw/")
async def debug_fdc_raw(q: str = "chicken"):
    apikey = os.environ.get("FDC_API_KEY")
    if not apikey:
        return {"ok": False, "error": "FDC_API_KEY not set in this process (env missing).", "env": None}
    try:
        res = search_food(q, page_size=1)
        return {"ok": True, "has_key": True, "result_preview": res if res else None}
    except Exception as e:
        return {"ok": False, "error": repr(e)}

@app.get("/debug_fdc_detail/")
async def debug_fdc_detail(fdcId: int = Query(...)):
    apikey = os.environ.get("FDC_API_KEY")
    if not apikey:
        return {"ok": False, "error": "FDC_API_KEY not set in this process (env: None)."}
    try:
        res = get_food_by_fdcid(fdcId)
        return {"ok": True, "fdcId": fdcId, "detail_snippet": res}
    except Exception as e:
        return {"ok": False, "error": repr(e)}

# -------------------
# Routes (CSV / image / items)
# -------------------
@app.post("/analyze/")
async def analyze(file: UploadFile = File(...)):
    try:
        if analyze_orders is None:
            raise RuntimeError("analyze_orders function not available (check nutrition_utils.py)")
        file_location = f"/tmp/{file.filename}"
        with open(file_location, "wb+") as f:
            shutil.copyfileobj(file.file, f)
        logger.info("analyze: saved uploaded file to %s", file_location)
        result = analyze_orders(file_location)
        return JSONResponse(content=sanitize_for_json(result))
    except Exception as e:
        logger.exception("analyze() failed")
        return json_error("analyze() failed: " + str(e), exc=e)


@app.post("/analyze_image/")
async def analyze_image(file: UploadFile = File(...)):
    try:
        img_bytes = await file.read()
        logger.info("analyze_image: received file %s (%d bytes)", getattr(file, "filename", "<no name>"), len(img_bytes))
        result = map_items_from_image_bytes(img_bytes, confidence_threshold=80)
        return JSONResponse(content=sanitize_for_json(result))
    except Exception as e:
        logger.exception("analyze_image() failed")
        return json_error("analyze_image() failed: " + str(e), exc=e)


@app.post('/analyze_image_with_micronutrients/')
async def analyze_image_with_micronutrients(file: UploadFile = File(...),
                                            include_low_confidence: bool = False,
                                            dedupe: bool = Query(False)):
    """
    Main image -> OCR -> mapping -> FDC lookups -> aggregate micronutrients & macros.
    Query param dedupe=true will deduplicate identical extracted_text entries before lookup.
    """
    try:
        img_bytes = await file.read()
        mapping_result = map_items_from_image_bytes(img_bytes, confidence_threshold=80)
        mapped_items = mapping_result.get("mapped_items", []) or []

        # optional dedupe by normalized extracted_text
        if dedupe:
            seen = set()
            unique = []
            for m in mapped_items:
                k = (m.get("extracted_text") or m.get("raw_text") or "").strip().lower()
                if not k:
                    continue
                if k in seen:
                    continue
                seen.add(k)
                unique.append(m)
            mapped_items = unique

        micronutrient_totals: Dict[str, float] = {}
        per_item_provenance: List[Dict[str, Any]] = []

        for m in mapped_items:
            raw_text = m.get("raw_text") or m.get("extracted_text") or ""
            chosen_name = None
            provenance = None

            if m.get("best_score", 0) >= 80 and m.get("candidates"):
                chosen = m["candidates"][0]
                chosen_name = chosen.get("db_item")
            else:
                if include_low_confidence:
                    chosen_name = m.get("extracted_text")

            if not chosen_name:
                per_item_provenance.append({"raw": raw_text, "mapped_to": None, "quantity": m.get("quantity", 1), "provenance": {"source": "low_confidence_not_lookup"}})
                continue

            qty = float(m.get("quantity", 1) or 1)
            portion_mult = float(m.get("portion_mult", 1.0) or 1.0)
            multiplier = qty * portion_mult

            nutrients, prov = lookup_food_nutrients(chosen_name)
            provenance = prov or {"source": "fdc_no_provenance"}

            if not nutrients:
                per_item_provenance.append({"raw": raw_text, "mapped_to": chosen_name, "quantity": qty, "provenance": provenance})
                continue

            # canonical macros and scaled nutrients
            item_macros = compute_item_macros(nutrients)
            scaled_full = scale_nutrients(nutrients, multiplier)
            merge_totals(micronutrient_totals, scaled_full)
            scaled_macros = scale_nutrients(item_macros, multiplier)
            merge_totals(micronutrient_totals, scaled_macros)

            # attach serving info to provenance if available
            prov_with_serving = dict(provenance)
            if provenance and provenance.get("servingSize"):
                prov_with_serving["servingSize"] = provenance.get("servingSize")
                prov_with_serving["servingSizeUnit"] = provenance.get("servingSizeUnit")
                prov_with_serving["householdServingFullText"] = provenance.get("householdServingFullText")

            per_item_provenance.append({
                "raw": raw_text,
                "mapped_to": chosen_name,
                "quantity": qty,
                "portion_mult": portion_mult,
                "provenance": prov_with_serving
            })

        macros_summary = build_macros_summary_from_totals(micronutrient_totals)
        percent_dv = compute_percent_dv(micronutrient_totals)
        percent_dv_friendly = {k: classify_percent_dv(v) for k, v in (percent_dv or {}).items()}
        # top_lacking: nutrients with numeric %DV, sorted ascending (lowest first)
        top_lacking = sorted([(k, v) for k, v in (percent_dv or {}).items() if v is not None], key=lambda x: x[1])[:8]

        resp = {
            "mapping_result": mapping_result,
            "per_item_provenance": per_item_provenance,
            "micronutrient_totals": micronutrient_totals,
            "percent_dv": percent_dv,
            "percent_dv_friendly": percent_dv_friendly,
            "top_lacking": top_lacking,
            "macros_summary": macros_summary,
            "macros_source": "fdc_aggregated"
        }
        return JSONResponse(content=sanitize_for_json(resp))
    except Exception as e:
        logger.exception("analyze_image_with_micronutrients() failed")
        return json_error("analyze_image_with_micronutrients() failed: " + str(e), exc=e)


@app.post("/analyze_items/")
async def analyze_items(payload: Dict[str, Any] = Body(...)):
    """
    Accepts confirmed items from the UI and returns FDC-based aggregation.
      payload: {"confirmed": [{"item": <name>, "quantity": <float>, "portion_mult": <float?>, "calories": <manual?>}, ...]}
    Manual calories are honored when FDC data is missing.
    """
    try:
        confirmed = payload.get("confirmed", []) or []
        micronutrient_totals: Dict[str, float] = {}
        per_item_provenance: List[Dict[str, Any]] = []

        for c in confirmed:
            name = (c.get("item") or "").strip()
            if not name:
                continue
            qty = float(c.get("quantity", 1.0) or 1.0)
            portion_mult = float(c.get("portion_mult", 1.0) or 1.0)
            multiplier = qty * portion_mult
            manual_cal = c.get("calories") or c.get("manual_calories")

            nutrients, provenance = lookup_food_nutrients(name)

            if not nutrients and manual_cal is None:
                per_item_provenance.append({"raw": name, "mapped_to": None, "quantity": qty, "provenance": {"source": "fdc_no_data"}})
                continue

            if nutrients:
                scaled_full = scale_nutrients(nutrients, multiplier)
                merge_totals(micronutrient_totals, scaled_full)
                item_macros = compute_item_macros(nutrients)
                scaled_macros = scale_nutrients(item_macros, multiplier)
                merge_totals(micronutrient_totals, scaled_macros)
                prov = dict(provenance or {})
                if prov.get("servingSize"):
                    prov["servingSize"] = prov.get("servingSize")
                    prov["servingSizeUnit"] = prov.get("servingSizeUnit")
                    prov["householdServingFullText"] = prov.get("householdServingFullText")
                per_item_provenance.append({"raw": name, "mapped_to": name, "quantity": qty, "portion_mult": portion_mult, "provenance": prov})
            else:
                try:
                    v = float(manual_cal)
                    micronutrient_totals["calories_kcal"] = micronutrient_totals.get("calories_kcal", 0.0) + v * multiplier
                except Exception:
                    pass
                per_item_provenance.append({"raw": name, "mapped_to": name, "quantity": qty, "provenance": {"source": "manual_calories"}})

        macros_summary = build_macros_summary_from_totals(micronutrient_totals)
        percent_dv = compute_percent_dv(micronutrient_totals)
        percent_dv_friendly = {k: classify_percent_dv(v) for k, v in (percent_dv or {}).items()}
        top_lacking = sorted([(k, v) for k, v in (percent_dv or {}).items() if v is not None], key=lambda x: x[1])[:8]

        resp = {
            "per_item_provenance": per_item_provenance,
            "micronutrient_totals": micronutrient_totals,
            "macros_summary": macros_summary,
            "percent_dv": percent_dv,
            "percent_dv_friendly": percent_dv_friendly,
            "top_lacking": top_lacking
        }
        return JSONResponse(content=sanitize_for_json(resp))
    except Exception as e:
        logger.exception("analyze_items() failed")
        return json_error("analyze_items() failed: " + str(e), exc=e)


# small ping
@app.get('/ping/')
async def ping():
    return {"ok": True, "msg": "pong"}
