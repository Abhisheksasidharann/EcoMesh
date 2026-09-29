import os
from typing import List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from verification_agent import verify, VERIFY_THRESHOLD, REJECT_THRESHOLD
from vision_agent import check_photo
from impact_agent import estimate
from gamification_agent import update_profile


class PipelineState(TypedDict, total=False):
    submission: dict
    school: Optional[dict]
    upload_dir: str
    existing_hashes: set
    status: str
    trust_score: float
    reasons: List[str]
    photo_hash: Optional[str]
    hard_reject: bool
    ai_check: Optional[dict]
    impact_kg_co2e: float
    impact_method: str
    student_profile: Optional[dict]
    updated_profile: dict
    points_awarded: int
    new_badges: List[str]


def rules_node(state: PipelineState):
    status, trust, reasons, photo_hash = verify(
        state["submission"],
        state["upload_dir"],
        state["existing_hashes"],
        state.get("school"),
    )
    # Hard rejects (missing photo, duplicate, future timestamp) return trust 0.0
    hard = status == "rejected" and trust == 0.0
    return {
        "status": status,
        "trust_score": trust,
        "reasons": reasons,
        "photo_hash": photo_hash,
        "hard_reject": hard,
    }


def vision_node(state: PipelineState):
    s = state["submission"]
    path = os.path.join(state["upload_dir"], s["photo_file"])
    delta, reason, details = check_photo(path, s["action_type"])
    trust = round(max(0.0, min(1.0, state["trust_score"] + delta)), 2)
    if trust >= VERIFY_THRESHOLD:
        status = "verified"
    elif trust < REJECT_THRESHOLD:
        status = "rejected"
    else:
        status = "needs_review"
    return {
        "trust_score": trust,
        "status": status,
        "reasons": state["reasons"] + [reason],
        "ai_check": details,
    }


def impact_node(state: PipelineState):
    s = state["submission"]
    kg, note = estimate(s["action_type"], s.get("quantity", 1.0))
    return {"impact_kg_co2e": kg, "impact_method": note}


def gamification_node(state: PipelineState):
    s = state["submission"]
    action_date = s["captured_at"].date().isoformat()
    profile, points, badges = update_profile(
        state.get("student_profile"), state["impact_kg_co2e"], action_date
    )
    return {"updated_profile": profile, "points_awarded": points, "new_badges": badges}


def route_after_rules(state: PipelineState):
    return "stop" if state["hard_reject"] else "vision"


def route_after_vision(state: PipelineState):
    return "impact" if state["status"] == "verified" else "stop"


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("rules", rules_node)
    g.add_node("vision", vision_node)
    g.add_node("impact", impact_node)
    g.add_node("gamification", gamification_node)
    g.set_entry_point("rules")
    g.add_conditional_edges("rules", route_after_rules, {"vision": "vision", "stop": END})
    g.add_conditional_edges("vision", route_after_vision, {"impact": "impact", "stop": END})
    g.add_edge("impact", "gamification")
    g.add_edge("gamification", END)
    return g.compile()


graph = build_graph()
