# app_enhanced.py — extended API: food search, user, meals, analytics, recipes, recommendations
from fastapi import FastAPI, HTTPException, Depends, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import datetime
from db import SessionLocal, engine, Base
from models import Food, User, MealLog, Recipe, Badge
from sqlalchemy.orm import Session
import math
import os

# create DB tables if not present
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Food Analysis - Extended API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- simple fuzzy matching using rapidfuzz if installed, fallback substring search ----
try:
    from rapidfuzz import process, fuzz
    RAPID = True
except Exception:
    RAPID = False

def search_food_db(q: str, db: Session, limit: int = 8):
    q = (q or "").strip()
    if not q:
        return []
    choices = db.query(Food).all()
    items = []
    if RAPID:
        names = [c.name for c in choices]
        results = process.extract(q, names, scorer=fuzz.token_set_ratio, limit=limit)
        for name, score, idx in results:
            f = choices[idx]
            items.append({"id": f.id, "name": f.name, "score": int(score), "variants": f.variants or [], "nutrients": f.nutrients or {}})
        return items
    else:
        # basic substring search
        for f in choices:
            score = 100 if q.lower() in (f.name or "").lower() else (50 if (f.name or "").split()[0].lower() in q.lower() else 0)
            if score > 0:
                items.append({"id": f.id, "name": f.name, "score": score, "variants": f.variants or [], "nutrients": f.nutrients or {}})
        items = sorted(items, key=lambda x: x["score"], reverse=True)[:limit]
        return items

# ---- endpoints ----
class SearchResp(BaseModel):
    id: int
    name: str
    score: int
    variants: Optional[list] = []
    nutrients: Optional[dict] = {}

@app.get("/api/food/search", response_model=List[SearchResp])
def api_food_search(q: str = Query(...), limit: int = Query(8), db: Session = Depends(get_db)):
    return search_food_db(q, db, limit)

@app.get("/api/food/{food_id}")
def api_food_detail(food_id: int, db: Session = Depends(get_db)):
    f = db.query(Food).get(food_id)
    if not f:
        raise HTTPException(404, "food not found")
    return {
        "id": f.id,
        "name": f.name,
        "serving_size": f.serving_size,
        "serving_unit": f.serving_unit,
        "nutrients": f.nutrients or {},
        "variants": f.variants or []
    }

# --- user profile (simple) ---
class ProfileIn(BaseModel):
    email: Optional[str]
    display_name: Optional[str]
    age: Optional[int]
    sex: Optional[str]
    height_cm: Optional[float]
    weight_kg: Optional[float]
    activity_level: Optional[str]

@app.post("/api/user/profile")
def create_or_update_profile(p: ProfileIn, db: Session = Depends(get_db)):
    # simplistic: find or create first user by email if given, else create a new anonymous user
    if p.email:
        user = db.query(User).filter(User.email == p.email).first()
    else:
        user = None
    if not user:
        user = User(email=p.email, display_name=p.display_name, age=p.age, sex=p.sex, height_cm=p.height_cm, weight_kg=p.weight_kg, activity_level=p.activity_level)
        db.add(user)
    else:
        for k,v in p.dict().items():
            if v is not None:
                setattr(user, k, v)
    db.commit()
    return {"ok": True, "user_id": user.id, "profile": {
        "email": user.email, "display_name": user.display_name, "age": user.age, "height_cm": user.height_cm, "weight_kg": user.weight_kg, "goals": user.goals
    }}

@app.post("/api/user/goals")
def set_goals(payload: dict = Body(...), user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    # user_id optional (local dev), else first user
    user = None
    if user_id:
        user = db.query(User).get(user_id)
    if not user:
        user = db.query(User).first()
    if not user:
        user = User()
        db.add(user)
    user.goals = payload
    db.commit()
    return {"ok": True, "goals": user.goals}

# --- log meal entry ---
class MealIn(BaseModel):
    user_id: Optional[int]
    food_id: Optional[int]
    item_name: str
    quantity: float = 1.0
    portion_mult: float = 1.0
    manual_calories: Optional[float] = None
    timestamp: Optional[datetime.datetime] = None
    source: Optional[str] = "manual"

@app.post("/api/meals/log")
def log_meal(m: MealIn, db: Session = Depends(get_db)):
    t = m.timestamp or datetime.datetime.utcnow()
    nutrients_snapshot = {}
    if m.food_id:
        f = db.query(Food).get(m.food_id)
        if f and f.nutrients:
            # scale nutrients by quantity * portion_mult
            mult = float(m.quantity) * float(m.portion_mult)
            for k,v in (f.nutrients or {}).items():
                try:
                    nutrients_snapshot[k] = float(v) * mult
                except Exception:
                    pass
    if m.manual_calories is not None and not nutrients_snapshot:
        nutrients_snapshot["calories_kcal"] = float(m.manual_calories) * float(m.quantity) * float(m.portion_mult)
    log = MealLog(
        user_id = m.user_id,
        food_id = m.food_id,
        item_name = m.item_name,
        quantity = m.quantity,
        portion_mult = m.portion_mult,
        manual_calories = m.manual_calories,
        nutrients_snapshot = nutrients_snapshot,
        source = m.source,
        timestamp = t
    )
    db.add(log)
    db.commit()
    # optional: update badges/streaks here (basic)
    return {"ok": True, "meal_id": log.id, "nutrients_snapshot": nutrients_snapshot}

# get history aggregated per day
@app.get("/api/meals/history")
def meals_history(start: Optional[str] = Query(None), end: Optional[str] = Query(None), db: Session = Depends(get_db)):
    # returns list of days with aggregated macros
    s = datetime.datetime.strptime(start, "%Y-%m-%d") if start else (datetime.datetime.utcnow() - datetime.timedelta(days=7))
    e = datetime.datetime.strptime(end, "%Y-%m-%d") if end else datetime.datetime.utcnow()
    e = e + datetime.timedelta(days=1)
    logs = db.query(MealLog).filter(MealLog.timestamp >= s, MealLog.timestamp < e).order_by(MealLog.timestamp.asc()).all()
    day_map = {}
    for l in logs:
        day = l.timestamp.date().isoformat()
        if day not in day_map:
            day_map[day] = {"calories":0,"protein_g":0,"carbs_g":0,"fat_g":0,"fiber_g":0,"items":[]}
        ns = l.nutrients_snapshot or {}
        day_map[day]["calories"] += ns.get("calories_kcal", 0)
        day_map[day]["protein_g"] += ns.get("protein_g", 0)
        day_map[day]["carbs_g"] += ns.get("total_carbohydrate_g", 0) or ns.get("carbs",0)
        day_map[day]["fat_g"] += ns.get("total_fat_g", 0) or ns.get("fat",0)
        day_map[day]["fiber_g"] += ns.get("dietary_fiber_g", 0) or ns.get("fiber_g", 0)
        day_map[day]["items"].append({"id": l.id, "item": l.item_name, "quantity": l.quantity})
    # return as list sorted by day asc
    out = [{"day":d, **day_map[d]} for d in sorted(day_map.keys())]
    return {"days": out}

# analytics summary for a range
@app.get("/api/analytics/summary")
def analytics_summary(range_days: int = Query(7), db: Session = Depends(get_db)):
    end = datetime.datetime.utcnow()
    start = end - datetime.timedelta(days=range_days)
    resp = meals_history(start=start.date().isoformat(), end=end.date().isoformat(), db=db)
    # simple aggregates
    total = {"calories":0,"protein_g":0,"carbs_g":0,"fat_g":0,"fiber_g":0}
    for d in resp["days"]:
        total["calories"] += d["calories"]
        total["protein_g"] += d["protein_g"]
        total["carbs_g"] += d["carbs_g"]
        total["fat_g"] += d["fat_g"]
        total["fiber_g"] += d["fiber_g"]
    avg = {k: (total[k] / max(1, len(resp["days"]))) for k in total}
    return {"days": resp["days"], "total": total, "avg_per_day": avg}

# recipe endpoints (CRUD)
from pydantic import Json

class RecipeIn(BaseModel):
    user_id: Optional[int]
    title: str
    items: List[dict]  # {food_id or name, qty, portion_mult}

@app.post("/api/recipes")
def create_recipe(r: RecipeIn, db: Session = Depends(get_db)):
    rec = Recipe(user_id=r.user_id, title=r.title, items=r.items)
    db.add(rec)
    db.commit()
    return {"ok": True, "recipe_id": rec.id}

@app.get("/api/recipes")
def list_recipes(user_id: Optional[int] = Query(None), db: Session = Depends(get_db)):
    q = db.query(Recipe)
    if user_id:
        q = q.filter(Recipe.user_id == user_id)
    items = []
    for rec in q.all():
        items.append({"id": rec.id, "title": rec.title, "items": rec.items})
    return {"recipes": items}

# --- recommendations (simple) ---
@app.post("/api/recommendations")
def recommendations(payload: dict = Body(...), db: Session = Depends(get_db)):
    # payload: { "date": "2025-10-05", "user_id": 1 }
    date = payload.get("date") or datetime.date.today().isoformat()
    user_id = payload.get("user_id")
    # compute day's totals
    res = meals_history(start=date, end=date, db=db)
    day_totals = res["days"][0] if res["days"] else {"calories":0,"protein_g":0,"carbs_g":0,"fat_g":0,"fiber_g":0}
    # load user goals if present
    user = db.query(User).get(user_id) if user_id else db.query(User).first()
    goals = user.goals if user and user.goals else {}
    recs = []
    # simple rules:
    if goals.get("protein_g") and day_totals.get("protein_g",0) < goals["protein_g"] * 0.8:
        # suggest high-protein items from DB by tag 'protein' or known foods
        results = db.query(Food).filter(Food.tags.like("%protein%")).limit(5).all()
        recs.append({"reason":"protein_deficit","suggestions":[{"id":r.id,"name":r.name} for r in results]})
    # fiber
    if goals.get("dietary_fiber_g") and day_totals.get("fiber_g",0) < goals["dietary_fiber_g"] * 0.8:
        results = db.query(Food).filter(Food.tags.like("%fiber%")).limit(5).all()
        recs.append({"reason":"fiber_deficit","suggestions":[{"id":r.id,"name":r.name} for r in results]})
    # if no specific deficits, suggest balanced items
    if not recs:
        results = db.query(Food).limit(6).all()
        recs.append({"reason":"general","suggestions":[{"id":r.id,"name":r.name} for r in results]})
    return {"ok": True, "recommendations": recs}

# badges endpoint (basic)
@app.get("/api/badges/{user_id}")
def get_badges(user_id: int, db: Session = Depends(get_db)):
    # compute basic streak / total logged days
    logs = db.query(MealLog).filter(MealLog.user_id == user_id).all()
    days = set([l.timestamp.date().isoformat() for l in logs])
    streak = 0
    d = datetime.date.today()
    while d.isoformat() in days:
        streak += 1
        d = d - datetime.timedelta(days=1)
    earned = db.query(Badge).filter(Badge.user_id == user_id).all()
    badge_keys = [b.badge_key for b in earned]
    # easy badges: first_log, streak_7, streak_30
    new = []
    if "first_log" not in badge_keys and len(logs) > 0:
        nb = Badge(user_id=user_id, badge_key="first_log")
        db.add(nb); new.append("first_log")
    if "streak_7" not in badge_keys and streak >= 7:
        nb = Badge(user_id=user_id, badge_key="streak_7"); db.add(nb); new.append("streak_7")
    if "streak_30" not in badge_keys and streak >= 30:
        nb = Badge(user_id=user_id, badge_key="streak_30"); db.add(nb); new.append("streak_30")
    db.commit()
    earned = db.query(Badge).filter(Badge.user_id == user_id).all()
    return {"streak": streak, "badges": [b.badge_key for b in earned], "new": new}
