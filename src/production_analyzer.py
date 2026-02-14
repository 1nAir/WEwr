import logging
from collections import defaultdict
from typing import Dict, List, Set

from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class CompanyAnalyzer:
    """
    Analyzes global company basing and movement statistics.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def get_best_regions_map(self, items: List[str]) -> Dict[str, Set[str]]:
        """
        Identifies 'Best Bonus' regions for each item based on specific rules.
        """
        best_regions = defaultdict(set)

        # Pre-fetch all regions for country lookups to avoid N+1 queries
        all_regions_map = self.client.get_regions()

        # Map country_id -> list of region_ids
        country_to_regions = defaultdict(list)
        for r_id, r_data in all_regions_map.items():
            c_id = r_data.get("country")
            if c_id:
                country_to_regions[c_id].append(r_id)

        for item in items:
            recs = self.client.get_recommended_regions(item)
            if not recs:
                continue

            # Find max bonus in the returned list
            max_bonus = max((r.get("bonus", 0) for r in recs), default=0)

            # Filter regions that have this max bonus
            top_regions = [r for r in recs if r.get("bonus", 0) == max_bonus]

            # Rule: If all 5 returned regions have equal bonus
            if len(recs) == 5 and len(top_regions) == 5:
                # a. Add regions with depositBonus > 0
                for r in top_regions:
                    if r.get("depositBonus", 0) > 0:
                        best_regions[item].add(r["regionId"])

                # b. For others (no deposit), add ALL regions of their country
                for r in top_regions:
                    if r.get("depositBonus", 0) <= 0:
                        r_id = r["regionId"]
                        region_obj = all_regions_map.get(r_id)
                        if region_obj:
                            c_id = region_obj.get("country")
                            if c_id:
                                # Add ALL regions of this country
                                for cr_id in country_to_regions[c_id]:
                                    best_regions[item].add(cr_id)
            else:
                # Standard case: just add the specific regions with max bonus
                for r in top_regions:
                    best_regions[item].add(r["regionId"])

        return best_regions

    def collect_company_stats(self, items: List[str]) -> Dict[str, Dict[str, int]]:
        """
        Scrapes all companies to aggregate basing stats.
        Returns a flattened dict of stats per item.
        """
        # 1. Prepare Best Regions Map
        best_regions_map = self.get_best_regions_map(items)

        # 2. Get All Users (via Countries)
        countries = self.client.get_countries()
        country_ids = [c["_id"] for c in countries]
        all_user_ids = set()

        logger.info(f"Fetching users from {len(country_ids)} countries...")

        # Batch fetch users (paginated)
        # We process countries in chunks to batch the initial requests
        # We use a queue to handle pagination (cursors).
        # The client's batch_call handles the HTTP batching limits automatically.

        queue = [(cid, None) for cid in country_ids]

        while queue:
            chunk = queue
            queue = []

            calls = []
            for cid, cursor in chunk:
                params = {"countryId": cid, "limit": 100}
                if cursor:
                    params["cursor"] = cursor
                calls.append(("user.getUsersByCountry", params))

            results = self.client.batch_call(calls, raise_on_error=True)

            for i, res in enumerate(results):
                cid = chunk[i][0]  # Map result back to country_id
                if "error" in res:
                    continue

                data = res.get("result", {}).get("data", {})
                if "json" in data:
                    data = data["json"]

                users = data.get("items", [])
                next_cursor = data.get("nextCursor")

                for u in users:
                    uid = u.get("_id") if isinstance(u, dict) else u
                    if uid:
                        all_user_ids.add(uid)

                if next_cursor:
                    queue.append((cid, next_cursor))

        logger.info(f"Found {len(all_user_ids)} users. Fetching companies...")

        # 3. Get Companies for all users
        all_company_ids = set()
        user_ids_list = list(all_user_ids)
        comp_queue = [(uid, None) for uid in user_ids_list]

        # Process users in batches
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
                uid = chunk[i][0]  # Map result back to user_id
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
        # Initialize stats structure
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
            }
        )

        # Pre-fill region counts
        for item in items:
            stats[item]["comp_best_regions_count"] = len(
                best_regions_map.get(item, set())
            )

        company_ids_list = list(all_company_ids)

        # Prepare all calls at once; client handles batching
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

            if not item_code or not region_id:
                continue

            # Only process items we care about
            if item_code not in items:
                continue

            # Metrics
            workers = c.get("workerCount", 0)
            upgrades = c.get("activeUpgradeLevels", {})
            ae = upgrades.get("automatedEngine", 0)

            # Classify (Best vs Others)
            is_best = region_id in best_regions_map.get(item_code, set())
            prefix = "comp_best" if is_best else "comp_others"

            # Update Stats
            stats[item_code][f"{prefix}_count"] += 1
            stats[item_code][f"{prefix}_workers"] += workers
            stats[item_code][f"{prefix}_ae"] += ae

            stats[item_code]["comp_total_count"] += 1
            stats[item_code]["comp_total_workers"] += workers
            stats[item_code]["comp_total_ae"] += ae

        return stats
