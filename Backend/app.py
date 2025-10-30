"""
Combined FastAPI backend + AI microservice logic.
Run with: uvicorn app_combined:app --reload --port 8000
Environment:
 - GEMINI_API_KEY (optional)
 - GEMINI_MODEL (optional, default gemini-2.5-flash)
 - SERPAPI_API_KEY (optional)
 - SAVE_TO_FIRESTORE = "1" to enable Firestore (optional)
"""

import os, re, json, math, time, random, datetime, traceback, logging
from typing import Dict, Any, List, Optional
from functools import lru_cache

from fastapi import FastAPI, UploadFile, File, Body, Query, Depends, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

# === Logging ===
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("food-analysis")

# === Local cache ===
LOCAL_FOOD_CACHE = []

def _normalize_name(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", "", (s or "").lower())

def load_local_foods(path="foods_data.json"):
    global LOCAL_FOOD_CACHE
    LOCAL_FOOD_CACHE = []
    if not os.path.exists(path):
        logger.warning("No local foods file found at %s", path)
        return
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        name = item.get("food_name") or item.get("description") or ""
        if not name:
            continue
        nutrients = {}
        for k,v in item.items():
            kl = k.lower()
            if "energy" in kl or "calorie" in kl:
                nutrients["calories_kcal"] = float(v)
            elif "protein" in kl:
                nutrients["protein_g"] = float(v)
            elif "carbohydrate" in kl or "carbs" in kl:
                nutrients["total_carbohydrate_g"] = float(v)
            elif "fat" in kl and "saturated" not in kl:
                nutrients["total_fat_g"] = float(v)
        LOCAL_FOOD_CACHE.append({
            "name": name.strip(),
            "norm": _normalize_name(name),
            "nutrients": nutrients,
        })
    logger.info(f"✅ Loaded {len(LOCAL_FOOD_CACHE)} local food entries")

load_local_foods(os.path.join(os.path.dirname(__file__), "foods_data.json"))

@lru_cache(maxsize=2048)
def find_local_food(name: str, threshold: int = 75):
    if not name or not LOCAL_FOOD_CACHE:
        return None
    q = _normalize_name(name)
    best, best_score = None, 0
    for e in LOCAL_FOOD_CACHE:
        if e["norm"] == q:
            return {**e, "score": 100}
        if q in e["norm"] or e["norm"] in q:
            s = 85
            if s > best_score:
                best_score, best = s, e
    try:
        from rapidfuzz import fuzz
        for e in LOCAL_FOOD_CACHE:
            sc = int(fuzz.token_set_ratio(q, e["norm"]))
            if sc > best_score:
                best_score, best = sc, e
    except Exception:
        pass
    if best and best_score >= threshold:
        return {**best, "score": best_score}
    return None

# === AI optional ===
import requests
load_dotenv()
try:
    import google.generativeai as genai
except Exception:
    genai = None
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
if GEMINI_API_KEY and genai:
    genai.configure(api_key=GEMINI_API_KEY)
    logger.info("Gemini configured")
else:
    logger.warning("Gemini unavailable")

# === FastAPI ===
app = FastAPI(title="Food Analysis API (Offline + AI)")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def _is_number(v):
    try: float(v); return True
    except: return False

def json_error(msg, exc=None):
    payload = {"error": msg}
    if exc: payload["traceback"] = traceback.format_exc()
    return JSONResponse(status_code=500, content=payload)

# === Nutrient endpoint ===
# === Main nutrient endpoint (fixed order + closest-match fallback) ===
from typing import Tuple
try:
    from rapidfuzz import fuzz
except Exception:
    fuzz = None

def _closest_local_food(name: str, min_score: int = 60) -> Optional[Dict[str, Any]]:
    """Pick the best local match even if find_local_food() fails the threshold."""
    if not LOCAL_FOOD_CACHE:
        return None
    q = _normalize_name(name)
    best, best_score = None, 0
    # quick substring pass
    for e in LOCAL_FOOD_CACHE:
        if q in e["norm"] or e["norm"] in q:
            sc = 85
            if sc > best_score:
                best, best_score = e, sc
    # fuzzy pass if available
    if fuzz:
        for e in LOCAL_FOOD_CACHE:
            sc = int(fuzz.token_set_ratio(q, e["norm"]))
            if sc > best_score:
                best, best_score = e, sc
    if best and best_score >= min_score:
        return {**best, "score": best_score}
    return None

@app.post("/api/run_nutrients")
async def run_nutrients(payload: Dict[str, Any] = Body(...)):
    try:
        items = payload.get("items") or []
        results: List[Dict[str, Any]] = []
        totals: Dict[str, float] = {}

        for i, it in enumerate(items):
            # --- READ & SANITIZE INPUTS FIRST ---
            if isinstance(it, dict):
                name_raw = it.get("name", "")
                qty = it.get("quantity", 1)
                portion_mult = it.get("portion_mult", 1.0)
            else:
                name_raw = str(it)
                qty, portion_mult = 1, 1.0

            name_trim = (name_raw or "").strip()
            if not name_trim:
                continue

            try:
                mult = float(qty) * float(portion_mult)
            except Exception:
                mult = 1.0

            # --- 1) LOCAL EXACT/GOOD MATCH ---
            local = find_local_food(name_trim, threshold=40)  # your lowered threshold
            if not local:
                # --- 1b) CLOSEST MATCH (so carbs never 0 for real foods) ---
                local = _closest_local_food(name_trim, min_score=60)
                provenance = {"source": "closest_match", "score": local.get("score")} if local else None
            else:
                provenance = {"source": "local_cache", "score": local.get("score")}

            if local:
                base = local["nutrients"] or {}
                scaled = {k: float(v) * mult for k, v in base.items() if _is_number(v)}
                # accumulate totals
                for k, v in scaled.items():
                    totals[k] = totals.get(k, 0.0) + v
                results.append({
                    "id": f"item-{i}",
                    "item": name_trim,
                    "macros": scaled,
                    "calories": scaled.get("calories_kcal"),
                    "quantity": float(qty) if _is_number(qty) else 1.0,
                    "provenance": provenance or {"source": "local_cache"}
                })
                continue

            # --- 2) GEMINI LLM FALLBACK (if configured) ---
            if genai and GEMINI_API_KEY:
                prompt = (
                    f"Estimate calories and macros for: {name_trim}\n"
                    "Return JSON: {\"calories\": number, \"protein\": number, \"carbs\": number, \"fats\": number}"
                )
                try:
                    model = genai.GenerativeModel(GEMINI_MODEL)
                    resp = model.generate_content(prompt)
                    text = getattr(resp, "text", str(resp))
                    parsed = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
                except Exception:
                    parsed = {}

                if parsed:
                    est = {
                        "calories_kcal": float(parsed.get("calories", 0.0)) * mult,
                        "protein_g": float(parsed.get("protein", 0.0)) * mult,
                        # Avoid bogus zeros by clamping to >= 0 (some prompts can return null/negatives)
                        "total_carbohydrate_g": max(0.0, float(parsed.get("carbs", 0.0)) * mult),
                        "total_fat_g": max(0.0, float(parsed.get("fats", 0.0)) * mult),
                    }
                    for k, v in est.items():
                        totals[k] = totals.get(k, 0.0) + v
                    results.append({
                        "id": f"item-{i}",
                        "item": name_trim,
                        "macros": est,
                        "calories": est.get("calories_kcal"),
                        "quantity": float(qty) if _is_number(qty) else 1.0,
                        "provenance": {"source": "llm_fallback"}
                    })
                    continue

            # --- 3) HEURISTIC FALLBACK ---
            base = 350.0
            low = name_trim.lower()
            if "salad" in low:
                base = 220
            elif "biryani" in low:
                base = 420
            elif "pizza" in low:
                base = 700
            elif "paneer" in low:
                base = 450

            est = {
                "calories_kcal": base * mult,
                # rough macro shares; clamp ≥ 0
                "protein_g": max(0.0, (base * 0.12 / 4) * mult),
                "total_carbohydrate_g": max(0.0, (base * 0.45 / 4) * mult),
                "total_fat_g": max(0.0, (base * 0.43 / 9) * mult),
            }
            for k, v in est.items():
                totals[k] = totals.get(k, 0.0) + v
            results.append({
                "id": f"item-{i}",
                "item": name_trim,
                "macros": est,
                "calories": est.get("calories_kcal"),
                "quantity": float(qty) if _is_number(qty) else 1.0,
                "provenance": {"source": "heuristic"}
            })

        macros = {
            "total_calories": round(totals.get("calories_kcal", 0.0), 1),
            "total_protein": round(totals.get("protein_g", 0.0), 1),
            "total_carbs": round(totals.get("total_carbohydrate_g", 0.0), 1),
            "total_fat": round(totals.get("total_fat_g", 0.0), 1),
        }
        return JSONResponse(content={"results": results, "totals": totals, "macros": macros})

    except Exception as e:
        logger.exception("run_nutrients failed")
        return json_error("run_nutrients failed", e)

# === Local search ===
@app.get("/api/food/search_local")
def search_local_foods(q: str):
    qn = _normalize_name(q)
    matches = [f for f in LOCAL_FOOD_CACHE if qn in f["norm"]][:15]
    return [{"name": f["name"], **f["nutrients"]} for f in matches]

@app.get("/ping")
def ping():
    return {"ok": True}

# === DB ===
Base = declarative_base()
DB_PATH = os.getenv("FOOD_DB_PATH", "sqlite:///food_app.db")
engine = create_engine(DB_PATH, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)

class MealLog(Base):
    __tablename__ = "meal_logs"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer)
    item_name = Column(String)
    nutrients = Column(JSON)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

Base.metadata.create_all(bind=engine)

@app.get("/api/analytics/summary")
def summary(user_id: int, db: SessionLocal = Depends(SessionLocal)):
    logs = db.query(MealLog).filter(MealLog.user_id == user_id).all()
    total = {}
    for l in logs:
        for k,v in (l.nutrients or {}).items():
            if _is_number(v): total[k]=total.get(k,0)+float(v)
    macros = {
        "total_calories": total.get("calories_kcal",0),
        "total_protein": total.get("protein_g",0),
        "total_carbs": total.get("total_carbohydrate_g",0),
        "total_fat": total.get("total_fat_g",0),
    }
    return {"totals": total, "macros": macros}

# ============================================================
# ✅ NEW: AI-Summary compatible endpoint (dummy logic)
# ============================================================
# ============================================================
# ✅ Personalized, non-LLM Daily Summary
# ============================================================
_summary_jobs = {}

def _bmr_msj(sex: str, age: float, height_cm: float, weight_kg: float) -> float:
    # Mifflin–St Jeor
    s = 5 if (sex or "").lower().startswith("m") else -161
    return 10*weight_kg + 6.25*height_cm - 5*age + s

def _activity_mult(level: str) -> float:
    m = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "very": 1.725,
        "extra": 1.9,
    }
    return m.get((level or "light").lower(), 1.375)

def _targets_from_profile(p: dict) -> dict:
    # Sensible defaults if profile missing
    sex = p.get("sex", "male")
    age = float(p.get("age", 25))
    height_cm = float(p.get("height_cm", 170))
    weight_kg = float(p.get("weight_kg", 70))
    activity = p.get("activity_level", "light")  # sedentary/light/moderate/very/extra
    goal = (p.get("goal", "maintain") or "maintain").lower()  # cut/maintain/bulk

    bmr = _bmr_msj(sex, age, height_cm, weight_kg)
    tdee = bmr * _activity_mult(activity)

    # Calorie target from goal
    if goal in ("cut", "fatloss", "weight loss", "lose"):
        cal_target = tdee - 400
    elif goal in ("bulk", "gain", "muscle gain"):
        cal_target = tdee + 300
    else:
        cal_target = tdee

    # Macro targets: Protein 1.6 g/kg (cut: 1.8, bulk: 1.6), Fat 0.8 g/kg, rest carbs
    prot_per_kg = 1.8 if goal in ("cut", "fatloss", "weight loss", "lose") else 1.6
    protein_g = round(prot_per_kg * weight_kg, 0)
    fat_g = round(0.8 * weight_kg, 0)
    # kcal from P/F; carbs get the rest (4/4/9 rule)
    kcal_pf = protein_g*4 + fat_g*9
    carb_g = max(0, round((cal_target - kcal_pf) / 4, 0))

    return {
        "bmr": round(bmr),
        "tdee": round(tdee),
        "calorie_target": max(1200, round(cal_target)),
        "protein_target_g": protein_g,
        "fat_target_g": fat_g,
        "carb_target_g": carb_g,
        "goal": goal,
        "activity_level": activity,
        "weight_kg": weight_kg,
        "height_cm": height_cm,
        "age": age,
        "sex": sex,
    }

def _sum_logs(logs: list) -> dict:
    tot = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fats_g": 0.0}
    meals_out = []
    for l in logs or []:
        name = l.get("item") or l.get("name") or "Meal"
        cal = float(l.get("calories") or 0)
        # Allow logs to include a nested macros object or flat g values
        m = l.get("macros") or {}
        prot = float(m.get("protein_g") or l.get("protein_g") or 0)
        carbs = float(m.get("carbs_g") or m.get("total_carbohydrate_g") or l.get("carbs_g") or 0)
        fats = float(m.get("fats_g") or m.get("total_fat_g") or l.get("fats_g") or 0)

        tot["calories"] += cal
        tot["protein_g"] += prot
        tot["carbs_g"] += carbs
        tot["fats_g"] += fats
        meals_out.append({
            "item": name,
            "calories": round(cal),
            "protein_g": round(prot, 1),
            "carbs_g": round(carbs, 1),
            "fats_g": round(fats, 1),
        })
    # round totals
    for k in tot: tot[k] = round(tot[k], 1)
    return {"totals": tot, "meals": meals_out}

def _make_recommendations(tot: dict, targets: dict) -> list:
    recs = []
    # Calorie guidance
    cal_gap = round(tot["calories"] - targets["calorie_target"])
    if cal_gap > 150:
        recs.append(f"Calories {cal_gap} kcal over target — trim portion size at dinner or swap a sugary drink for water.")
    elif cal_gap < -150:
        recs.append(f"Calories {abs(cal_gap)} kcal under target — add a snack (e.g., yogurt + fruit) or increase carbs at lunch.")

    # Protein
    p_gap = round(targets["protein_target_g"] - tot["protein_g"])
    if p_gap > 15:
        recs.append(f"Protein is low by ~{p_gap} g — add eggs, paneer, dal, chicken, or Greek yogurt.")
    # Carbs/Fats soft checks
    if tot["carbs_g"] > targets["carb_target_g"] + 40:
        recs.append("Carbs were quite high — consider switching one refined-carb item to legumes/veggies.")
    if tot["fats_g"] > targets["fat_target_g"] + 20:
        recs.append("Fats were high — reduce fried/oily items; prefer nuts/seeds in measured portions.")

    if not recs:
        recs.append("Great balance today — keep portions steady and prioritize whole foods.")
    return recs

def _personalized_summary_job(user_id: str, date: str, logs: List[dict], profile: Optional[dict]):
    # 1) derive targets
    targets = _targets_from_profile(profile or {})
    # 2) sum the day
    agg = _sum_logs(logs)
    totals = agg["totals"]
    meals = agg["meals"]

    # 3) gaps
    gaps = {
        "calories_gap": round(totals["calories"] - targets["calorie_target"]),
        "protein_gap_g": round(totals["protein_g"] - targets["protein_target_g"]),
        "carb_gap_g": round(totals["carbs_g"] - targets["carb_target_g"]),
        "fat_gap_g": round(totals["fats_g"] - targets["fat_target_g"]),
    }

    # 4) simple ranking
    top_meals = sorted(meals, key=lambda x: x["calories"], reverse=True)[:3]

    # 5) recs
    recs = _make_recommendations(totals, targets)

    parsed = {
        "date": date,
        "profile_used": targets,
        "totals": totals,
        "gaps_vs_target": gaps,
        "top_meals_by_cal": top_meals,
        "recommendations": recs,
        "generated_at": datetime.datetime.utcnow().isoformat()+"Z"
    }

    _summary_jobs[(user_id, date)] = {
        "status": "complete",
        "summary": {
            "parsed": parsed,
            "totals": {"calories_kcal": totals["calories"]},
        },
    }

@app.post("/api/summarizeDaily")
def start_summary(data: dict, bg: BackgroundTasks):
    user = data.get("user_id")
    date = data.get("date") 
    logs = data.get("logs", [])
    profile = data.get("profile", {})  # <-- optional, but enables personalization
    if not user or not date:
        raise HTTPException(400, "user_id & date required")
    _summary_jobs[(user, date)] = {"status": "pending"}
    bg.add_task(_personalized_summary_job, user, date, logs, profile)
    return {"status": "queued"}

@app.get("/api/summarizeDaily/status")
def status_summary(user_id: str, date: str):
    job = _summary_jobs.get((user_id, date))
    if not job:
        return {"status": "pending"}
    return job
