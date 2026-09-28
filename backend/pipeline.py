from typing import List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from verification_agent import verify
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
    impact_kg_co2e: float
    impact_method: str
    student_profile: Optional[dict]
    updated_profile: dict
    points_awarded: int
    new_badges: List[str]


def verification_node(state: PipelineState):
    status, trust, reasons, photo_hash = verify(
        state["submission"],
        state["upload_dir"],
        state["existing_hashes"],
        state.get("school"),
    )
    return {
        "status": status,
        "trust_score": trust,
        "reasons": reasons,
        "photo_hash": photo_hash,
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


def route_after_verification(state: PipelineState):
    return "impact" if state["status"] == "verified" else "stop"


def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("verification", verification_node)
    g.add_node("impact", impact_node)
    g.add_node("gamification", gamification_node)
    g.set_entry_point("verification")
    g.add_conditional_edges(
        "verification",
        route_after_verification,
        {"impact": "impact", "stop": END},
    )
    g.add_edge("impact", "gamification")
    g.add_edge("gamification", END)
    return g.compile()


graph = build_graph()
