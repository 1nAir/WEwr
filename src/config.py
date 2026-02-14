import os

# --- Paths ---
HISTORY_FILE = "history.json"
HISTORY_COMPANIES_FILE = "history_companies.json"
OUTPUT_HTML = "index.html"
ASSETS_DIR = "assets"

# --- API Configuration ---
API_KEYS = [
    key
    for key in [
        os.environ.get("WEALTHRATE1"),
        os.environ.get("WEALTHRATE2"),
        os.environ.get("WEALTHRATE3"),
    ]
    if key
]

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

ITEM_SHORT_NAMES = {
    "coca": "Myst. Plant",
    "heavyAmmo": "H. Ammo",
    "lightAmmo": "L. Ammo",
    "cookedFish": "C. Fish",
    "limestone": "Limest.",
    "petroleum": "Petrol.",
    "concrete": "Concr.",
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

# --- History Configuration ---
PROFITABILITY_METRICS = ["min_pp", "avg_pp", "max_pp"]

COMPANY_METRICS = [
    "comp_best_count",
    "comp_best_workers",
    "comp_best_ae",
    "comp_others_count",
    "comp_others_workers",
    "comp_others_ae",
    "comp_total_count",
    "comp_total_workers",
    "comp_total_ae",
]
