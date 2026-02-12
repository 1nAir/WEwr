import os

# --- Paths ---
HISTORY_FILE = "history.json"
OUTPUT_HTML = "index.html"
ASSETS_DIR = "assets"

# --- API Configuration ---
# Explicit key separation
API_KEY_MAIN = os.environ.get("WARERA_API_KEY_MAIN")
API_KEY_COMPANY = os.environ.get("WARERA_API_KEY_COMPANY")
# --- Data Processing Settings ---
MAX_HISTORY_POINTS = 2016
THRESHOLD_MULTIPLIER = 1.3
GLOBAL_COEF_MIN = 0.45
GLOBAL_COEF_THRESH = 1.35

# --- Item Configuration ---
# Strictly from original file
ITEM_PRETTY_NAMES = {
    "lead": "Lead",
    "cookedFish": "Cooked Fish",
    "iron": "Iron",
    "lightAmmo": "Light Ammo",
    "limestone": "Limestone",
    "steel": "Steel",
    "livestock": "Livestock",
    "concrete": "Concrete",
    "fish": "Fish",
    "steak": "Steak",
    "petroleum": "Petroleum",
    "ammo": "Ammo",
    "oil": "Oil",
    "coca": "Mysterious Plant",
    "cocain": "Pill",
    "bread": "Bread",
    "heavyAmmo": "Heavy Ammo",
    "grain": "Grain",
}

# Colors for charts
ITEM_COLORS = {
    # Fish - Blue
    "fish": "#3182ce",
    "cookedFish": "#63b3ed",
    # Livestock - Red
    "livestock": "#c53030",
    "steak": "#f56565",
    # Grain - Yellow/Gold
    "grain": "#d69e2e",
    "bread": "#f6e05e",
    # Coca - Green
    "coca": "#2f855a",
    "cocain": "#68d391",
    # Petroleum - Purple
    "petroleum": "#44337a",
    "oil": "#805ad5",
    # Lead - Olive/Lime
    "lead": "#556B2F",
    "ammo": "#9ACD32",
    "heavyAmmo": "#9E9D24",
    "lightAmmo": "#D8E49C",
    # Iron - Rust/Orange
    "iron": "#dd6b20",
    "steel": "#f6ad55",
    # Limestone - Gray
    "limestone": "#4A5568",
    "concrete": "#A0AEC0",
}

# --- UI Configuration ---
METRIC_LABELS = {
    "min_pp": "Min Profit/PP",
    "avg_pp": "Avg Profit/PP",
    "max_pp": "Max Profit/PP",
}

PRODUCTION_LINES = {
    "Fishery": ["fish", "cookedFish"],
    "Ranch": ["livestock", "steak"],
    "Farm": ["grain", "bread"],
    "Plantation": ["coca", "cocain"],
    "Oil Rig": ["petroleum", "oil"],
    "Lead Works": ["lead", "ammo", "heavyAmmo", "lightAmmo"],
    "Iron Works": ["iron", "steel"],
    "Quarry": ["limestone", "concrete"],
}
