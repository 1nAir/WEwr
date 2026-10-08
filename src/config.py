import os

# --- Paths ---
HISTORY_FILE = "history.json"
HISTORY_COMPANIES_FILE = "history_companies.json"
HISTORY_WORKERS_FILE = "history_workers.json"
HISTORY_MARKET_DEPTH_FILE = "history_market_depth.json"
LATEST_MARKET_FILE = "latest_market.json"
LATEST_COMPANIES_FILE = "latest_companies.json"
LATEST_WORKERS_FILE = "latest_workers.json"
LATEST_MARKET_DEPTH_FILE = "latest_market_depth.json"
KNOWN_PLAYERS_FILE = "known_players.json"
PUBLIC_DIR = "public"
OUTPUT_HTML = os.path.join(PUBLIC_DIR, "index.html")
ASSETS_DIR = os.path.join(PUBLIC_DIR, "assets")

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
MAX_HISTORY_POINTS = 12288
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
    "wood": "Wood",
    "paper": "Paper",
}

ITEM_PRODUCTION_POINTS = {
    "lead": 1,
    "cookedFish": 40,
    "iron": 1,
    "lightAmmo": 1,
    "limestone": 1,
    "steel": 10,
    "livestock": 20,
    "concrete": 10,
    "fish": 40,
    "steak": 20,
    "petroleum": 1,
    "ammo": 4,
    "oil": 1,
    "coca": 1,
    "cocain": 200,
    "bread": 10,
    "heavyAmmo": 16,
    "grain": 1,
    "wood": 1,
    "paper": 1,
}

# --- Market Depth Extra Items (Unmanufactured tradables with 0 PP) ---
MARKET_DEPTH_EXTRA_ITEMS = {
    "scraps": "Scraps",
    "case1": "Case",
    "case2": "Elite Case",
    "woodenCase": "Wooden Case",
}

# All items displayed in Market Depth tab
MARKET_DEPTH_ITEMS = {
    **ITEM_PRETTY_NAMES,
    **MARKET_DEPTH_EXTRA_ITEMS,
}

MARKET_DEPTH_PP = {
    **ITEM_PRODUCTION_POINTS,
    "scraps": 0,
    "case1": 0,
    "case2": 0,
    "woodenCase": 0,
}

ITEM_SHORT_NAMES = {
    "coca": "Plant",
    "heavyAmmo": "H. Ammo",
    "lightAmmo": "L. Ammo",
    "cookedFish": "C. Fish",
    "limestone": "Limest.",
    "petroleum": "Petrol.",
    "concrete": "Concr.",
    "livestock": "L.stock",
    "woodenCase": "W. Case",
    "case2": "Elite C.",
}

# --- Ethics & Item Categories ---
# Resources where active deposits receive bonus from Agrarian ethics (+10% / +30%)
AGRARIAN_ITEMS = {"coca", "grain", "livestock", "fish"}

# Goods where specialization receives bonus from Industrialist ethics (+10% / +30%)
INDUSTRIAL_ITEMS = {
    "ammo",
    "lightAmmo",
    "heavyAmmo",
    "iron",
    "steel",
    "limestone",
    "concrete",
    "wood",
    "paper",
    "lead",
    "oil",
    "petroleum",
}

# Items unaffected by production ethics bonuses
NO_ETHIC_ITEMS = {"cookedFish", "steak", "bread", "cocain"}

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
    # Wood/Paper - Cyan
    "wood": "#00838f",
    "paper": "#4dd0e1",
    # Market Depth Items: Cases & Scraps
    "case1": "#ec4899",
    "case2": "#6366f1",
    "woodenCase": "#a27b5c",
    "scraps": "#e2e8f0",
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
    "Lumber Mill": ["wood", "paper"],
    "Cases & Scraps": ["case1", "case2", "woodenCase", "scraps"],
}

# --- History Configuration ---
PROFITABILITY_METRICS = ["min_pp", "avg_pp", "max_pp"]

WORKER_METRICS = [
    "min_pp",
    "avg_pp",
    "max_pp",
    "min_pp_f5",
    "avg_pp_f5",
    "max_pp_f5",
    "min_pp_f10",
    "avg_pp_f10",
    "max_pp_f10",
]

WORKER_PLAYER_STATS = {
    "energy": 130,
    "production": 40,
    "level": 50,
}

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

MARKET_DEPTH_METRICS = [
    "total_units",
    "total_pp",
]

