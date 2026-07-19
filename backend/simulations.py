import os
import json
from datetime import datetime

SIMULATIONS_FILE = "simulated_actions_log.json"

def log_simulation(action_type, target, details):
    event = {
        "timestamp": datetime.now().isoformat(),
        "type": action_type,
        "target": target,
        "details": details
    }
    events = []
    if os.path.exists(SIMULATIONS_FILE):
        try:
            with open(SIMULATIONS_FILE, "r", encoding="utf-8") as f:
                events = json.load(f)
        except Exception:
            pass
    events.append(event)
    events = events[-50:] # Keep last 50 events
    try:
        with open(SIMULATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Failed to write simulation log:", e)
    return event

def get_simulations():
    if os.path.exists(SIMULATIONS_FILE):
        try:
            with open(SIMULATIONS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []
