import os
import uuid
from datetime import datetime, timezone
from typing import Literal

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pymongo import MongoClient

from gamification_agent import update_profile
from impact_agent import estimate
from pipeline import graph

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"), serverSelectionTimeoutMS=5000)
db = client[os.getenv("DB_NAME", "ecomesh")]
submissions = db["submissions"]
students = db["students"]
schools = db["schools"]

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Seed one demo school the first time (does nothing if it already exists)
try:
    schools.update_one(
        {"_id": "SCH001"},
        {"$setOnInsert": {"name": "Demo School", "lat": 8.5241, "lng": 76.9366, "radius_m": 300}},
        upsert=True,
    )
except Exception:
    pass

app = FastAPI(title="EcoMesh API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Photos are viewable at http://127.0.0.1:8000/uploads/<photo_file>
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

ActionType = Literal[
    "plantation",
    "waste_segregation",
    "sustainable_transport",
    "solar_adoption",
    "water_conservation",
]


class SchoolIn(BaseModel):
    school_id: str
    name: str
    lat: float
    lng: float
    radius_m: float = 300


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    reviewer: str
    note: str = ""


def clean(d):
    d["id"] = str(d.pop("_id"))
    if d.get("photo_file"):
        d["photo_url"] = f"/uploads/{d['photo_file']}"
    return d


@app.get("/")
def root():
    return {"status": "EcoMesh API is running"}


@app.get("/health/db")
def health_db():
    try:
        client.admin.command("ping")
        return {"database": "connected"}
    except Exception as e:
        return {"database": "error", "detail": str(e)}


# ---------- Schools ----------
@app.post("/schools")
def upsert_school(body: SchoolIn):
    schools.update_one(
        {"_id": body.school_id},
        {"$set": {"name": body.name, "lat": body.lat, "lng": body.lng, "radius_m": body.radius_m}},
        upsert=True,
    )
    return {"school_id": body.school_id, "saved": True}


@app.get("/schools")
def list_schools():
    out = []
    for s in schools.find():
        s["school_id"] = s.pop("_id")
        out.append(s)
    return out


# ---------- Submissions ----------
@app.post("/submissions")
def create_submission(
    student_id: str = Form(...),
    school_id: str = Form(...),
    action_type: ActionType = Form(...),
    context: Literal["school", "home"] = Form("school"),
    latitude: float = Form(...),
    longitude: float = Form(...),
    captured_at: datetime = Form(...),
    quantity: float = Form(1.0),
    photo: UploadFile = File(...),
):
    if photo.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(status_code=400, detail="Photo must be JPEG or PNG")

    ext = ".png" if photo.content_type == "image/png" else ".jpg"
    filename = uuid.uuid4().hex + ext
    with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
        f.write(photo.file.read())

    doc = {
        "student_id": student_id,
        "school_id": school_id,
        "action_type": action_type,
        "context": context,
        "location": {"lat": latitude, "lng": longitude},
        "captured_at": captured_at,
        "quantity": quantity,
        "photo_file": filename,
        "status": "pending",
        "created_at": datetime.now(timezone.utc),
    }
    result = submissions.insert_one(doc)
    return {"id": str(result.inserted_id), "status": "pending"}


@app.get("/submissions")
def list_submissions(limit: int = 20, status: str | None = None):
    query = {"status": status} if status else {}
    return [clean(d) for d in submissions.find(query).sort("created_at", -1).limit(limit)]


# ---------- Pipeline ----------
@app.post("/pipeline/run")
def run_pipeline():
    existing = {
        d["photo_hash"]
        for d in submissions.find({"photo_hash": {"$exists": True}}, {"photo_hash": 1})
    }
    results = []
    for s in list(submissions.find({"status": "pending"})):
        out = graph.invoke({
            "submission": s,
            "school": schools.find_one({"_id": s["school_id"]}),
            "upload_dir": UPLOAD_DIR,
            "existing_hashes": existing,
            "student_profile": students.find_one({"_id": s["student_id"]}),
        })
        update = {
            "status": out["status"],
            "trust_score": out["trust_score"],
            "verification_reasons": out["reasons"],
            "photo_hash": out["photo_hash"],
            "ai_check": out.get("ai_check"),
            "verified_at": datetime.now(timezone.utc),
        }
        if "impact_kg_co2e" in out:
            update["impact_kg_co2e"] = out["impact_kg_co2e"]
            update["impact_method"] = out["impact_method"]
            update["points_awarded"] = out["points_awarded"]
        submissions.update_one({"_id": s["_id"]}, {"$set": update})
        if "updated_profile" in out:
            students.update_one(
                {"_id": s["student_id"]}, {"$set": out["updated_profile"]}, upsert=True
            )
        if out["photo_hash"] and out["status"] != "rejected":
            existing.add(out["photo_hash"])
        results.append({
            "id": str(s["_id"]),
            "status": out["status"],
            "trust_score": out["trust_score"],
            "kg_co2e": out.get("impact_kg_co2e"),
            "points_awarded": out.get("points_awarded"),
            "new_badges": out.get("new_badges"),
            "reasons": out["reasons"],
        })
    return {"processed": len(results), "results": results}


# ---------- Review queue (human in the loop) ----------
@app.get("/review/queue")
def review_queue():
    return [clean(d) for d in submissions.find({"status": "needs_review"}).sort("created_at", 1)]


@app.post("/review/{submission_id}")
def review_submission(submission_id: str, body: ReviewIn):
    try:
        oid = ObjectId(submission_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid submission id")
    s = submissions.find_one({"_id": oid})
    if s is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    if s["status"] != "needs_review":
        raise HTTPException(status_code=409, detail=f"Submission is already {s['status']}")

    update = {
        "reviewed_by": body.reviewer,
        "review_note": body.note,
        "reviewed_at": datetime.now(timezone.utc),
    }
    if body.decision == "reject":
        update["status"] = "rejected"
        submissions.update_one({"_id": oid}, {"$set": update})
        return {"id": submission_id, "status": "rejected"}

    kg, method = estimate(s["action_type"], s.get("quantity", 1.0))
    profile, points, badges = update_profile(
        students.find_one({"_id": s["student_id"]}),
        kg,
        s["captured_at"].date().isoformat(),
    )
    update.update({
        "status": "verified",
        "impact_kg_co2e": kg,
        "impact_method": method,
        "points_awarded": points,
    })
    submissions.update_one({"_id": oid}, {"$set": update})
    students.update_one({"_id": s["student_id"]}, {"$set": profile}, upsert=True)
    return {
        "id": submission_id,
        "status": "verified",
        "kg_co2e": kg,
        "points_awarded": points,
        "new_badges": badges,
    }


# ---------- Reports ----------
@app.get("/impact/school/{school_id}")
def school_impact(school_id: str):
    pipeline = [
        {"$match": {"school_id": school_id, "impact_kg_co2e": {"$exists": True}}},
        {"$group": {
            "_id": "$action_type",
            "actions": {"$sum": 1},
            "kg_co2e": {"$sum": "$impact_kg_co2e"},
        }},
    ]
    rows = list(submissions.aggregate(pipeline))
    breakdown = {r["_id"]: {"actions": r["actions"], "kg_co2e": round(r["kg_co2e"], 3)} for r in rows}
    total = round(sum(r["kg_co2e"] for r in rows), 3)
    return {"school_id": school_id, "total_kg_co2e": total, "by_action": breakdown}


@app.get("/students/{student_id}")
def get_student(student_id: str):
    p = students.find_one({"_id": student_id})
    if p is None:
        raise HTTPException(status_code=404, detail="No activity yet for this student")
    p["student_id"] = p.pop("_id")
    return p

