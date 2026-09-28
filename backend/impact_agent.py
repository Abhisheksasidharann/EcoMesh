# Emission factors: kg CO2e per unit.
# PLACEHOLDER VALUES. Before your final review, replace each one with a
# figure from a cited source (IPCC AR6, India CEA grid factor, etc.)
# and fill in the "source" field.
FACTORS = {
    "plantation": {"unit": "sapling", "factor": 10.0, "source": "TODO cite"},
    "waste_segregation": {"unit": "kg waste", "factor": 0.5, "source": "TODO cite"},
    "sustainable_transport": {"unit": "km", "factor": 0.17, "source": "TODO cite"},
    "solar_adoption": {"unit": "kWh", "factor": 0.71, "source": "TODO cite"},
    "water_conservation": {"unit": "litre", "factor": 0.0003, "source": "TODO cite"},
}


def estimate(action_type, quantity):
    """Returns (kg_co2e, method_note)."""
    f = FACTORS.get(action_type)
    if f is None:
        return 0.0, "Unknown action type"
    kg = round(max(quantity, 0) * f["factor"], 3)
    note = f"{quantity} {f['unit']} x {f['factor']} kg CO2e/{f['unit']}"
    return kg, note
