from datetime import date

# Badge rules: (id, label, condition on the updated profile)
BADGES = [
    ("first_action", "First Step", lambda p: p["total_actions"] >= 1),
    ("five_actions", "Getting Going", lambda p: p["total_actions"] >= 5),
    ("streak_3", "3-Day Streak", lambda p: p["streak_days"] >= 3),
    ("carbon_50", "50 kg Club", lambda p: p["total_kg_co2e"] >= 50),
]


def update_profile(profile, kg_co2e, action_date):
    """Returns (updated_profile, points_awarded, new_badge_ids).
    action_date is an ISO string like '2026-09-28'."""
    p = {
        "points": 0,
        "total_actions": 0,
        "total_kg_co2e": 0.0,
        "streak_days": 0,
        "last_action_date": None,
        "badges": [],
    }
    p.update(profile or {})
    p["badges"] = list(p["badges"])

    # Points: 10 per verified action + 1 per 5 kg CO2e
    points = 10 + int(kg_co2e // 5)
    p["points"] += points
    p["total_actions"] += 1
    p["total_kg_co2e"] = round(p["total_kg_co2e"] + kg_co2e, 3)

    # Streak
    today = date.fromisoformat(action_date)
    if p["last_action_date"] is None:
        p["streak_days"] = 1
    else:
        gap = (today - date.fromisoformat(p["last_action_date"])).days
        if gap == 1:
            p["streak_days"] += 1
        elif gap > 1:
            p["streak_days"] = 1
        # gap == 0 (same day): streak unchanged
    p["last_action_date"] = action_date

    # Badges
    new_badges = []
    for badge_id, _label, cond in BADGES:
        if badge_id not in p["badges"] and cond(p):
            p["badges"].append(badge_id)
            new_badges.append(badge_id)

    return p, points, new_badges
