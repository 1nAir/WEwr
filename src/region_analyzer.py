import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from src import config
from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class RegionBonusAnalyzer:
    """Calculates production bonuses across all countries and regions based on

    strategic resources, government ethics, and active deposits.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def _fetch_world_state(self) -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
        """Fetches all countries, regions, and batch-loads ruling parties (5-6

        HTTP requests).
        """
        logger.info("Fetching world state (countries, regions, parties)...")
        countries = {c["_id"]: c for c in self.client.get_countries()}
        regions = self.client.get_regions()

        party_ids = list({c.get("rulingParty") for c in countries.values() if c.get("rulingParty")})
        party_results = self.client.batch_call([("party.getById", {"partyId": pid}) for pid in party_ids])
        parties = {
            r["result"]["data"]["_id"]: r["result"]["data"]
            for r in party_results
            if r.get("result", {}).get("data", {}).get("_id")
        }
        logger.info(f"Loaded {len(countries)} countries, {len(regions)} regions, {len(parties)} parties.")
        return countries, regions, parties

    def collect_all_bonuses(self) -> dict[str, Any]:
        """Calculates production bonuses across all countries and regions.

        Returns:
          - "by_region": dict of region_id -> metadata + bonuses per item for fast O(1) lookup
          - "by_item": dict of item_code -> list of ranked production locations (bonus desc, tax asc)
        """
        countries, regions, parties = self._fetch_world_state()
        now = datetime.now(timezone.utc)
        items = list(config.ITEM_PRETTY_NAMES.keys())

        # 1. Build by_region map (O(1) lookup per region)
        by_region: dict[str, dict[str, Any]] = {}
        for r_id, r in regions.items():
            c_id = r.get("country")
            c = countries.get(c_id) or {}
            party = parties.get(c.get("rulingParty")) or {}
            ind = (party.get("ethics") or {}).get("industrialism", 0)
            spec_item = c.get("specializedItem")
            tax = (c.get("taxes") or {}).get("income") or 0

            # Check active deposit in this region
            r_dep = r.get("deposit")
            active_dep = None
            if r_dep and r_dep.get("endsAt"):
                try:
                    ends_at = datetime.fromisoformat(r_dep["endsAt"].replace("Z", "+00:00"))
                    if ends_at > now:
                        remaining_sec = max(0, int((ends_at - now).total_seconds()))
                        active_dep = {
                            "type": r_dep.get("type"),
                            "bonus": float(r_dep.get("bonusPercent", 0)),
                            "ends_at": r_dep["endsAt"],
                            "ends_at_timestamp": ends_at.timestamp(),
                            "remaining_seconds": remaining_sec,
                        }
                except (ValueError, TypeError):
                    pass

            bonuses = {}
            for item in items:
                # Country Specialization (ind == -2 Fanatic Agrarian disables specialization)
                strat_bonuses = (c.get("strategicResources") or {}).get("bonuses") or {}
                strat = (
                    float(strat_bonuses.get("productionPercent", 0))
                    if (spec_item == item and ind != -2)
                    else 0.0
                )
                ethic_spec = (
                    10.0 if ind == 1 else (30.0 if ind == 2 else 0.0)
                ) if (spec_item == item and item in config.INDUSTRIAL_ITEMS) else 0.0

                # Regional Deposit (ind == 2 Fanatic Industrialist disables deposits)
                dep_bonus = 0.0
                ethic_dep = 0.0
                if ind != 2 and active_dep and active_dep["type"] == item:
                    dep_bonus = active_dep["bonus"]
                    if item in config.AGRARIAN_ITEMS:
                        ethic_dep = 10.0 if ind == -1 else (30.0 if ind == -2 else 0.0)

                total = strat + ethic_spec + dep_bonus + ethic_dep
                bonuses[item] = {
                    "total_bonus": total,
                    "breakdown": {
                        "country_strategic_bonus": strat,
                        "ethic_specialization_bonus": ethic_spec,
                        "deposit_bonus": dep_bonus,
                        "ethic_deposit_bonus": ethic_dep,
                    },
                    "has_deposit": (dep_bonus > 0 or ethic_dep > 0),
                    "deposit": active_dep if active_dep and active_dep["type"] == item else None,
                    "deposit_ends_at": active_dep["ends_at"] if active_dep and active_dep["type"] == item else None,
                    "remaining_seconds": active_dep["remaining_seconds"] if active_dep and active_dep["type"] == item else None,
                }

            by_region[r_id] = {
                "region_id": r_id,
                "region_name": r.get("name", r.get("code", "Unknown")),
                "country_id": c_id,
                "country_name": c.get("name", "Unknown"),
                "tax_percent": tax,
                "specialized_item": spec_item,
                "bonuses": bonuses,
            }

        # 2. Build by_item by grouping non-deposit regions of the same country
        by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            grouped: dict[tuple, dict[str, Any]] = defaultdict(lambda: {"regions": []})
            for r_id, r_info in by_region.items():
                b = r_info["bonuses"][item]
                if b["total_bonus"] <= 0:
                    continue
                # Deposit regions get their own entry; non-deposit regions group together
                gkey = (r_info["country_id"], r_id if b["has_deposit"] else None)
                entry = grouped[gkey]
                entry["country_id"] = r_info["country_id"]
                entry["country_name"] = r_info["country_name"]
                entry["tax_percent"] = r_info["tax_percent"]
                entry["specialized_item"] = r_info["specialized_item"]
                entry["has_deposit"] = b["has_deposit"]
                entry["total_bonus"] = b["total_bonus"]
                entry["breakdown"] = b["breakdown"]
                entry["deposit"] = b["deposit"]
                entry["deposit_ends_at"] = b["deposit_ends_at"]
                entry["remaining_seconds"] = b["remaining_seconds"]
                entry["regions"].append({"id": r_id, "name": r_info["region_name"]})

            # Priority sort order:
            # 1. Total bonus (desc: higher is better)
            # 2. Tax percent (asc: lower is better)
            # 3. Permanent country specialization > deposits (inf > timestamp)
            # 4. Longest remaining deposit (desc: latest ends_at timestamp)
            def loc_sort_key(loc):
                bonus = loc["total_bonus"]
                tax = loc["tax_percent"]
                ts = loc["deposit"]["ends_at_timestamp"] if (loc["has_deposit"] and loc["deposit"]) else float("inf")
                return (-bonus, tax, -ts)

            locations = list(grouped.values())
            locations.sort(key=loc_sort_key)
            by_item[item] = locations

        return {
            "by_item": dict(by_item),
            "by_region": by_region,
        }
