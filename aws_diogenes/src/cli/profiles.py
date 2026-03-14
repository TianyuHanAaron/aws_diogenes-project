import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "user_profiles.json"

def load_profiles():
    
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            return json.load(f)
    return []

def save_profiles(profiles):
    
    DATA_PATH.parent.mkdir(parents=True, exist_ok = True)
    
    with open(DATA_PATH, "w") as f:
        json.dump(profiles, f, indent=2)

def find_user(user_id):
    profiles = load_profiles()
    
    for p in profiles:
        if p["user_id"] == user_id:
            return p
    return None
        
    
