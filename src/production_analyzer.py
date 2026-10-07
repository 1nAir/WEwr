from __future__ import annotations

from collections import defaultdict
import logging
from typing import Any

from src.api_client import TRPCClient
from src.region_analyzer import RegionBonusAnalyzer

logger = logging.getLogger(__name__)


class CompanyAnalyzer:
    """
    Analyzes global company basing and movement statistics.
    """

    def __init__(
        self, client: TRPCClient, region_analyzer: RegionBonusAnalyzer | None = None
    ):
        self.client = client
        self.region_analyzer = region_analyzer or RegionBonusAnalyzer(client)

    def get_best_regions_map(
        self, items: list[str], bonuses_data: dict | None = None
    ) -> tuple[dict[str, set[str]], dict]:
        """
        Identifies 'Best Bonus' regions for each item using RegionBonusAnalyzer.
        A region is considered 'Best' if and only if it has the maximum production bonus %
        for that item in the world. (Taxes and other criteria are not considered).
        """
        if not bonuses_data:
            bonuses_data = self.region_analyzer.collect_all_bonuses()

        by_region = bonuses_data.get("by_region", {})
        best_regions = defaultdict(set)

        for item in items:
            max_bonus = max(
                (r_info["bonuses"][item]["total_bonus"] for r_info in by_region.values() if item in r_info.get("bonuses", {})),
                default=0.0,
            )
            if max_bonus > 0:
                for r_id, r_info in by_region.items():
                    item_bonuses = r_info.get("bonuses", {}).get(item, {})
                    if item_bonuses.get("total_bonus", 0.0) == max_bonus:
                        best_regions[item].add(r_id)

        return best_regions, bonuses_data

    def collect_company_stats(self, items: list[str]) -> dict[str, dict[str, Any]]:
        """
        Scrapes all companies to aggregate basing stats and region breakdowns.
        Returns a dict of stats per item.
        """
        # 1. Prepare Best Regions Map & World State using RegionBonusAnalyzer
        best_regions_map, bonuses_data = self.get_best_regions_map(items)
        by_region = bonuses_data.get("by_region", {})

        # 2. Get Eligible Users (Level >= 20 via userLevel Ranking)
        logger.info("Fetching global user ranking to filter active business owners (Level >= 20)...")
        MIN_LEVEL_XP = 12600  # XP threshold for Level 20
        ranking_items = self.client.get_users_ranking("userLevel")
        if not ranking_items:
            raise RuntimeError("Failed to fetch user ranking or received empty ranking items.")

        all_user_ids = {
            it["user"]
            for it in ranking_items
            if it.get("user") and it.get("value", 0) >= MIN_LEVEL_XP
        }

        logger.info(
            f"Found {len(ranking_items)} players in ranking. Filtered to {len(all_user_ids)} eligible players (Level >= 20). Fetching companies..."
        )

        # 3. Get Companies for all users
        all_company_ids = set()
        user_ids_list = list(all_user_ids)
        comp_queue = [(uid, None) for uid in user_ids_list]

        while comp_queue:
            chunk = comp_queue
            comp_queue = []

            calls = []
            for uid, cursor in chunk:
                params = {"userId": uid, "perPage": 100}
                if cursor:
                    params["cursor"] = cursor
                calls.append(("company.getCompanies", params))

            results = self.client.batch_call(calls, raise_on_error=True)

            for i, res in enumerate(results):
                uid = chunk[i][0]
                if "error" in res:
                    continue

                data = res.get("result", {}).get("data", {})
                if "json" in data:
                    data = data["json"]

                comps = data.get("items", [])
                next_cursor = data.get("nextCursor")

                for c in comps:
                    cid = c.get("_id") if isinstance(c, dict) else c
                    if cid:
                        all_company_ids.add(cid)

                if next_cursor:
                    comp_queue.append((uid, next_cursor))

        logger.info(f"Found {len(all_company_ids)} companies. Fetching details...")

        # 4. Get Company Details & Aggregate
        stats = defaultdict(
            lambda: {
                "comp_best_count": 0,
                "comp_best_workers": 0,
                "comp_best_ae": 0,
                "comp_others_count": 0,
                "comp_others_workers": 0,
                "comp_others_ae": 0,
                "comp_total_count": 0,
                "comp_total_workers": 0,
                "comp_total_ae": 0,
                "comp_best_regions_count": 0,
                "locations": [],
            }
        )

        for item in items:
            stats[item]["comp_best_regions_count"] = len(
                best_regions_map.get(item, set())
            )

        # Track per-region company counts and workers
        item_region_stats = defaultdict(lambda: defaultdict(lambda: {"count": 0, "workers": 0}))

        company_ids_list = list(all_company_ids)
        calls = [("company.getById", {"companyId": cid}) for cid in company_ids_list]
        results = self.client.batch_call(calls, raise_on_error=False)

        for res in results:
            if "error" in res:
                continue

            c = res.get("result", {}).get("data", {})
            if "json" in c:
                c = c["json"]

            # Ignore disabled companies
            if c.get("disabledAt"):
                continue

            item_code = c.get("itemCode")
            region_id = c.get("region")

            if not item_code or not region_id or item_code not in items:
                continue

            workers = c.get("workerCount", 0)
            upgrades = c.get("activeUpgradeLevels", {})
            ae = upgrades.get("automatedEngine", 0)

            is_best = region_id in best_regions_map.get(item_code, set())
            prefix = "comp_best" if is_best else "comp_others"

            stats[item_code][f"{prefix}_count"] += 1
            stats[item_code][f"{prefix}_workers"] += workers
            stats[item_code][f"{prefix}_ae"] += ae

            stats[item_code]["comp_total_count"] += 1
            stats[item_code]["comp_total_workers"] += workers
            stats[item_code]["comp_total_ae"] += ae

            item_region_stats[item_code][region_id]["count"] += 1
            item_region_stats[item_code][region_id]["workers"] += workers

        # 5. Build detailed locations distribution for each item
        for item in items:
            loc_groups = defaultdict(lambda: {"company_count": 0, "worker_count": 0})

            for r_id, r_counts in item_region_stats[item].items():
                if r_counts["count"] <= 0 and r_counts["workers"] <= 0:
                    continue
                r_info = by_region.get(r_id)
                if not r_info:
                    continue
                b_info = r_info.get("bonuses", {}).get(item, {})
                has_dep = b_info.get("has_deposit", False)
                gkey = (r_info["country_id"], r_id if has_dep else None)

                entry = loc_groups[gkey]
                entry["country_name"] = r_info.get("country_name", "Unknown")
                entry["region_name"] = r_info.get("region_name", "Unknown") if has_dep else "All regions"
                entry["total_bonus"] = b_info.get("total_bonus", 0.0)
                entry["has_deposit"] = has_dep
                entry["tax_percent"] = r_info.get("tax_percent", 0)
                entry["company_count"] += r_counts["count"]
                entry["worker_count"] += r_counts["workers"]

            bonus_locs = []
            zero_comps = 0
            zero_workers = 0

            for loc in loc_groups.values():
                if loc["total_bonus"] > 0:
                    bonus_locs.append(loc)
                else:
                    zero_comps += loc["company_count"]
                    zero_workers += loc["worker_count"]

            # Sort bonus locations: highest production bonus first; secondary sort by company_count desc
            bonus_locs.sort(key=lambda x: (x["total_bonus"], x["company_count"]), reverse=True)

            # Assign rank tiers: same bonus gets same rank number
            current_rank = 0
            prev_bonus = None
            for loc in bonus_locs:
                if loc["total_bonus"] != prev_bonus:
                    current_rank += 1
                    prev_bonus = loc["total_bonus"]
                loc["rank"] = current_rank

            locations_list = list(bonus_locs)
            if zero_comps > 0 or zero_workers > 0:
                locations_list.append({
                    "rank": None,
                    "country_name": "Other regions (0% bonus)",
                    "region_name": "",
                    "total_bonus": 0.0,
                    "has_deposit": False,
                    "tax_percent": None,
                    "company_count": zero_comps,
                    "worker_count": zero_workers,
                    "is_zero_group": True,
                })

            stats[item]["locations"] = locations_list

        return stats
