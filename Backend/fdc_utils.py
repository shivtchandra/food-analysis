# backend/fdc_utils.py
import os
import requests
import json
import time
from pathlib import Path

API_KEY = os.environ.get("FDC_API_KEY")
if not API_KEY:
    print("Warning: FDC_API_KEY environment variable not set. FoodData Central lookups will be disabled.")

SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
FOOD_URL = "https://api.nal.usda.gov/fdc/v1/food/{}"

CACHE_PATH = Path("fdc_cache.json")


def _load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache):
    try:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print("Failed to write FDC cache:", e)


def _safe_get(url, params=None):
    if not API_KEY:
        return None
    params = dict(params or {})
    params["api_key"] = API_KEY
    for attempt in range(3):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status and 400 <= status < 500:
                print("FDC client error:", status, e)
                return None
            else:
                time.sleep(1 + attempt)
        except Exception:
            time.sleep(1 + attempt)
    return None


def search_food(query, page_size=5):
    if not API_KEY:
        return None
    params = {"query": query, "pageSize": page_size}
    return _safe_get(SEARCH_URL, params=params)


def get_food_by_fdcid(fdcId):
    if not API_KEY:
        return None
    url = FOOD_URL.format(fdcId)
    return _safe_get(url, params={})


# nutrient name mapping -> (key, expected_unit)
_NUTRIENT_MAPPING = {
    "Energy": ("calories_kcal", "kcal"),
    "Energy (kcal)": ("calories_kcal", "kcal"),
    "Protein": ("protein_g", "g"),
    "Total lipid (fat)": ("total_fat_g", "g"),
    "Fat": ("total_fat_g", "g"),
    "Fatty acids, total saturated": ("saturated_fat_g", "g"),
    "Carbohydrate, by difference": ("total_carbohydrate_g", "g"),
    "Carbohydrate": ("total_carbohydrate_g", "g"),
    "Fiber, total dietary": ("dietary_fiber_g", "g"),
    "Sugars, total including NLEA": ("sugars_g", "g"),
    "Sugars, total": ("sugars_g", "g"),
    "Calcium, Ca": ("calcium_mg", "mg"),
    "Iron, Fe": ("iron_mg", "mg"),
    "Magnesium, Mg": ("magnesium_mg", "mg"),
    "Phosphorus, P": ("phosphorus_mg", "mg"),
    "Potassium, K": ("potassium_mg", "mg"),
    "Sodium, Na": ("sodium_mg", "mg"),
    "Zinc, Zn": ("zinc_mg", "mg"),
    "Selenium, Se": ("selenium_mcg", "mcg"),
    "Vitamin C, total ascorbic acid": ("vitamin_C_mg", "mg"),
    "Vitamin D (D2 + D3)": ("vitamin_D_mcg", "mcg"),
    "Vitamin A, RAE": ("vitamin_A_mcg_RAE", "mcg"),
    "Vitamin E (alpha-tocopherol)": ("vitamin_E_mg", "mg"),
    "Vitamin K (phylloquinone)": ("vitamin_K_mcg", "mcg"),
    "Thiamin": ("thiamin_mg", "mg"),
    "Riboflavin": ("riboflavin_mg", "mg"),
    "Niacin": ("niacin_mg_NE", "mg"),
    "Vitamin B-6": ("vitamin_B6_mg", "mg"),
    "Folate, total": ("folate_mcg_DFE", "mcg"),
    "Folate, DFE": ("folate_mcg_DFE", "mcg"),
    "Vitamin B-12": ("vitamin_B12_mcg", "mcg"),
    "Biotin": ("biotin_mcg", "mcg"),
    "Pantothenic acid": ("pantothenic_acid_mg", "mg"),
    "Cholesterol": ("cholesterol_mg", "mg"),
    "Cholesterol, total": ("cholesterol_mg", "mg"),
    # add more as you discover them
}


def _as_float_safe(x):
    try:
        return float(x)
    except Exception:
        return None


def _convert_unit(value, from_unit, to_unit):
    if value is None:
        return None
    from_unit = (from_unit or "").lower()
    to_unit = (to_unit or "").lower()
    if from_unit == to_unit:
        return value
    if from_unit in ("mcg", "μg") and to_unit == "mg":
        return value / 1000.0
    if from_unit == "mg" and to_unit in ("mcg", "μg"):
        return value * 1000.0
    if from_unit == "g" and to_unit == "mg":
        return value * 1000.0
    if from_unit == "mg" and to_unit == "g":
        return value / 1000.0
    return value


def extract_nutrients_from_fdc(food_json):
    if not food_json:
        return {}

    out = {}

    nut_list = food_json.get("foodNutrients") or []
    for comp in nut_list:
        nutrient_obj = comp.get("nutrient") or {}
        name = nutrient_obj.get("name") or comp.get("nutrientName") or comp.get("name")
        amount = comp.get("amount") if comp.get("amount") is not None else comp.get("value")
        unit = nutrient_obj.get("unitName") or comp.get("unitName")
        if not name or amount is None:
            continue
        mapped = _NUTRIENT_MAPPING.get(name)
        if mapped:
            key, expected_unit = mapped
            amt = _as_float_safe(amount)
            normalized = amt
            if expected_unit and unit:
                # convert units: e.g. mg -> mcg etc.
                normalized = _convert_unit(amt, unit, expected_unit.replace("_mg", "mg").replace("_mcg", "mcg").replace("_g", "g"))
            out[key] = normalized if normalized is not None else amt

    # fallback for branded items
    if not out:
        label = food_json.get("labelNutrients") or {}
        label_map = {
            "calories": ("calories_kcal", None),
            "protein": ("protein_g", "g"),
            "fat": ("total_fat_g", "g"),
            "saturatedFat": ("saturated_fat_g", "g"),
            "transFat": ("trans_fat_g", "g"),
            "cholesterol": ("cholesterol_mg", "mg"),
            "sodium": ("sodium_mg", "mg"),
            "carbohydrates": ("total_carbohydrate_g", "g"),
            "fiber": ("dietary_fiber_g", "g"),
            "sugars": ("sugars_g", "g"),
            "calcium": ("calcium_mg", "mg"),
            "iron": ("iron_mg", "mg"),
        }
        for k, v in label.items():
            if k in label_map and isinstance(v, dict):
                key, expected_unit = label_map[k]
                amt = _as_float_safe(v.get("value"))
                if amt is None:
                    continue
                out[key] = amt

    return out


def lookup_food_nutrients(query):
    cache = _load_cache()
    key = query.lower().strip()
    if key in cache:
        entry = cache[key]
        return entry.get("nutrients", {}), entry.get("provenance", {})

    search_res = search_food(query, page_size=5)
    if not search_res:
        return None, {"source": "fdc_search_failed"}

    foods = search_res.get("foods") or []
    if not foods:
        return None, {"source": "no_results"}

    chosen = foods[0]
    fdcId = chosen.get("fdcId")
    detail = get_food_by_fdcid(fdcId)
    if not detail:
        return None, {"source": "fdc_detail_failed", "fdcId": fdcId}

    nutrients = extract_nutrients_from_fdc(detail)
    provenance = {
        "source": "fdc",
        "fdcId": fdcId,
        "description": chosen.get("description") or "",
        "servingSize": detail.get("servingSize"),
        "servingSizeUnit": detail.get("servingSizeUnit"),
        "householdServingFullText": detail.get("householdServingFullText")
    }

    cache[key] = {"nutrients": nutrients, "provenance": provenance, "timestamp": int(time.time())}
    _save_cache(cache)
    return nutrients, provenance
