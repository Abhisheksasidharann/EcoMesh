import json
import os

from dotenv import load_dotenv

load_dotenv()

ACTION_DESCRIPTIONS = {
    "plantation": "a person planting a sapling or tree, or a freshly planted sapling in soil",
    "waste_segregation": "waste being sorted into separate bins or categories (e.g. plastic, paper, organic)",
    "sustainable_transport": "cycling, walking, or using public transport such as a bus or train",
    "solar_adoption": "solar panels, a solar water heater, or other solar equipment",
    "water_conservation": "rainwater harvesting, fixing a leak, reusing water, or a water-saving setup",
}

PROMPT = """You are verifying a student's climate-action photo.
Claimed action: {action} - expected to show {desc}.
Look at the image and answer ONLY with JSON in this form:
{{"matches": true or false, "confidence": number from 0 to 1, "description": "one short sentence of what the image shows"}}
Set matches to false if the image is a screenshot, a picture of a screen, clearly downloaded stock art, or unrelated to the action."""


def check_photo(path, action_type):
    """Returns (trust_delta, reason, details_dict)."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return 0.0, "AI check skipped (no API key)", None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        mime = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        with open(path, "rb") as f:
            image_bytes = f.read()

        resp = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
                PROMPT.format(action=action_type, desc=ACTION_DESCRIPTIONS.get(action_type, action_type)),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0,
            ),
        )
        result = json.loads(resp.text)
        matches = bool(result.get("matches"))
        conf = float(result.get("confidence", 0))
        desc = result.get("description", "")

        if matches and conf >= 0.6:
            return 0.2, f"AI: photo matches action ({conf:.2f}) - {desc}", result
        if matches:
            return 0.0, f"AI: weak match ({conf:.2f}) - {desc}", result
        return -0.4, f"AI: photo does not match action - {desc}", result
    except Exception as e:
        return 0.0, f"AI check unavailable ({type(e).__name__})", None