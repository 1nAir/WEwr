import os

# --- Directory Paths ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_STORE_DIR = os.path.join(BASE_DIR, "data_store")
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
PUBLIC_DATA_DIR = os.path.join(PUBLIC_DIR, "data")
ASSETS_DIR = os.path.join(PUBLIC_DIR, "assets")

# --- Internal Cumulative Storage Files (data_store/) ---
LATEST_PROFITABILITY_FILE = os.path.join(DATA_STORE_DIR, "latest_profitability.json")
HISTORY_PROFITABILITY_FILE = os.path.join(DATA_STORE_DIR, "history_profitability.json")

LATEST_ORDERBOOK_FILE = os.path.join(DATA_STORE_DIR, "latest_orderbook.json")
HISTORY_ORDERBOOK_FILE = os.path.join(DATA_STORE_DIR, "history_orderbook.json")

LATEST_TRADES_FILE = os.path.join(DATA_STORE_DIR, "latest_trades.json")
HISTORY_TRADES_FILE = os.path.join(DATA_STORE_DIR, "history_trades.json")
DAILY_TRADER_STATS_FILE = os.path.join(DATA_STORE_DIR, "daily_trader_stats.json")

MARKET_LEADERBOARDS_FILE = os.path.join(DATA_STORE_DIR, "market_leaderboards.json")
KNOWN_PLAYERS_FILE = os.path.join(DATA_STORE_DIR, "known_players.json")
PLAYER_META_CACHE_FILE = os.path.join(DATA_STORE_DIR, "player_meta_cache.json")

# --- Frontend Static JSON Slices (public/data/) ---
FE_META_FILE = os.path.join(PUBLIC_DATA_DIR, "meta.json")
FE_PROFITABILITY_FILE = os.path.join(PUBLIC_DATA_DIR, "profitability.json")
FE_PROFITABILITY_HISTORY_FILE = os.path.join(PUBLIC_DATA_DIR, "profitability_history.json")
FE_ORDERBOOK_FILE = os.path.join(PUBLIC_DATA_DIR, "orderbook.json")
FE_ORDERBOOK_HISTORY_FILE = os.path.join(PUBLIC_DATA_DIR, "orderbook_history.json")
FE_TRADES_FILE = os.path.join(PUBLIC_DATA_DIR, "trades.json")
FE_TRADES_HISTORY_FILE = os.path.join(PUBLIC_DATA_DIR, "trades_history.json")
FE_LEADERBOARDS_FILE = os.path.join(PUBLIC_DATA_DIR, "leaderboards.json")

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

# --- History Retention & Spike Cleaner ---
MAX_HISTORY_POINTS = 12288
SPARKLINE_POINTS = 42  # ~7 days of 4-hour intervals or last 42 snapshots
THRESHOLD_MULTIPLIER = 1.3
GLOBAL_COEF_MIN = 0.45
GLOBAL_COEF_THRESH = 1.35

# --- Item Definitions (Manufactured & Raw Resources with PP > 0) ---
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

# --- Unmanufactured Market Items (0 PP) ---
MARKET_EXTRA_ITEMS = {
    "scraps": "Scraps",
    "case1": "Case",
    "case2": "Elite Case",
    "woodenCase": "Wooden Case",
}

ALL_MARKET_ITEMS = {
    **ITEM_PRETTY_NAMES,
    **MARKET_EXTRA_ITEMS,
}

ALL_ITEMS_PP = {
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

# Fallback production recipes (also dynamically fetched from gameConfig)
DEFAULT_RECIPES = {
    "lead": {},
    "iron": {},
    "limestone": {},
    "wood": {},
    "grain": {},
    "livestock": {},
    "fish": {},
    "coca": {},
    "petroleum": {},
    "cookedFish": {"fish": 1},
    "steak": {"livestock": 1},
    "bread": {"grain": 10},
    "cocain": {"coca": 200},
    "oil": {"petroleum": 1},
    "steel": {"iron": 10},
    "concrete": {"limestone": 10},
    "paper": {"wood": 1},
    "lightAmmo": {"lead": 1},
    "ammo": {"lead": 4},
    "heavyAmmo": {"lead": 16},
}

ITEM_COLORS = {
    "fish": "#3b82f6",
    "cookedFish": "#60a5fa",
    "livestock": "#ef4444",
    "steak": "#f87171",
    "grain": "#eab308",
    "bread": "#facc15",
    "coca": "#10b981",
    "cocain": "#34d399",
    "petroleum": "#8b5cf6",
    "oil": "#a78bfa",
    "lead": "#84cc16",
    "ammo": "#a3e635",
    "heavyAmmo": "#ca8a04",
    "lightAmmo": "#bef264",
    "iron": "#f97316",
    "steel": "#fb923c",
    "limestone": "#64748b",
    "concrete": "#94a3b8",
    "wood": "#06b6d4",
    "paper": "#22d3ee",
    "case1": "#ec4899",
    "case2": "#6366f1",
    "woodenCase": "#d97706",
    "scraps": "#cbd5e1",
}

PRODUCTION_LINES = {
    "Fishery": ["fish", "cookedFish"],
    "Ranch": ["livestock", "steak"],
    "Farm": ["grain", "bread"],
    "Plantation": ["coca", "cocain"],
    "Oil Rig": ["petroleum", "oil"],
    "Lead Works": ["lead", "lightAmmo", "ammo", "heavyAmmo"],
    "Iron Works": ["iron", "steel"],
    "Quarry": ["limestone", "concrete"],
    "Lumber Mill": ["wood", "paper"],
    "Cases & Scraps": ["case1", "case2", "woodenCase", "scraps"],
}

