from datetime import datetime, timezone
from typing import Any, Dict

from src.api_client import TRPCClient


class MarketAnalyzer:
    """
    Encapsulates business logic for calculating item profitability,
    considering production costs, regional bonuses, and deposits.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def _get_best_production_options(self) -> Dict[str, Dict[str, Any]]:
        """
        Reconstructs the logic to find the best production location (Country + Region/Deposit).
        Returns a dict of item_code -> {bonus, region_data...}.
        """
        countries = self.client.get_countries()
        regions = self.client.get_regions()

        # 1. Map country bonuses
        country_info = {}
        item_to_country = {}
        country_id_to_name = {}

        for c in countries:
            c_id = c.get("_id")
            c_name = c.get("name", "Unknown")
            bonuses = c.get("strategicResources", {}).get("bonuses", {})
            prod_bonus = bonuses.get("productionPercent", 0)
            spec_item = c.get("specializedItem")

            country_info[c_id] = {
                "bonus": prod_bonus,
                "spec_item": spec_item,
                "name": c_name,
            }
            country_id_to_name[c_id] = c_name

            if spec_item:
                if spec_item not in item_to_country:
                    item_to_country[spec_item] = []
                item_to_country[spec_item].append(
                    {"c_id": c_id, "bonus": prod_bonus, "c_name": c_name}
                )

        # 2. Analyze Regions (Deposits)
        item_options = {}

        for r_id, region in regions.items():
            deposit = region.get("deposit")
            if not deposit:
                continue

            item_type = deposit.get("type")
            if not item_type:
                continue

            deposit_ends = None
            # Check expiration
            if "endsAt" in deposit:
                try:
                    ends_at = deposit["endsAt"].replace("Z", "+00:00")
                    if datetime.fromisoformat(ends_at) < datetime.now(timezone.utc):
                        continue
                    deposit_ends = deposit["endsAt"]
                except ValueError:
                    pass

            region_bonus = deposit.get("bonusPercent", 0)
            region_name = region.get("name", region.get("code", r_id))
            c_id = region.get("country")
            c_data = country_info.get(
                c_id, {"bonus": 0, "spec_item": None, "name": "Unknown"}
            )

            # Country bonus applies if it specializes in this item
            c_bonus = c_data["bonus"] if item_type == c_data["spec_item"] else 0
            total = region_bonus + c_bonus

            if item_type not in item_options:
                item_options[item_type] = []

            item_options[item_type].append(
                {
                    "total_bonus": total,
                    "region_bonus": region_bonus,
                    "country_bonus": c_bonus,
                    "region": region_name,
                    "country": c_data["name"],
                    "deposit_ends_at": deposit_ends,
                }
            )

        # 3. Add Country Capital options (no deposit, just country bonus)
        for item, opts in item_to_country.items():
            best_c = max(opts, key=lambda x: x["bonus"])

            # Try to find capital name
            capital_name = "Unknown"
            # Simple search for capital or any region in that country
            for r in regions.values():
                if r.get("country") == best_c["c_id"]:
                    capital_name = r.get("name", r.get("code", "Unknown"))
                    if r.get("isCapital"):
                        break

            if item not in item_options:
                item_options[item] = []

            item_options[item].append(
                {
                    "total_bonus": best_c["bonus"],
                    "region_bonus": 0,
                    "country_bonus": best_c["bonus"],
                    "region": capital_name,
                    "country": best_c["c_name"],
                    "deposit_ends_at": None,
                }
            )

        # 4. Find best option per item
        best_options = {}
        for item, options in item_options.items():
            if not options:
                continue

            def sort_key(opt):
                bonus = opt["total_bonus"]
                ends_at = opt["deposit_ends_at"]
                if ends_at is None:
                    ts = float("inf")
                else:
                    try:
                        ts = datetime.fromisoformat(
                            ends_at.replace("Z", "+00:00")
                        ).timestamp()
                    except ValueError:
                        ts = 0
                return (bonus, ts)

            best_opt = max(options, key=sort_key)
            best_options[item] = best_opt

        return best_options

    def calculate_snapshot(self) -> Dict[str, Any]:
        """
        Main logic: Fetch prices, stats, and calculate Profit/PP (min/avg/max).
        Subtracts production costs recursively (inputs).
        """
        prices_resp = self.client.get_item_prices()
        raw_prices = prices_resp.get("result", {}).get("data", {})
        items = list(raw_prices.keys())

        # Heavy operation: fetch detailed stats for all items
        stats = self.client.get_item_stats(items)
        best_options = self._get_best_production_options()

        snapshot = {}

        for item in items:
            prod_info = self.client.get_item_production_info(item)
            pp = prod_info.get("productionPoints", 0)
            if pp <= 0:
                continue

            item_stats = stats.get(item, {})
            # Starting prices (Revenue)
            min_price = item_stats.get("min", 0)
            avg_price = item_stats.get("avg", 0)
            max_price = item_stats.get("max", 0)

            min_p = min_price
            avg_p = avg_price
            max_p = max_price

            # Subtract Production Costs
            # Logic:
            # Conservative Profit: Sell Low, Buy Ingredients High (Max)
            # Optimistic Profit: Sell High, Buy Ingredients Low (Min)
            needs = prod_info.get("productionNeeds", {})
            resource_details = []

            for res, qty in needs.items():
                res_stats = stats.get(res, {})
                min_p -= res_stats.get("max", 0) * qty  # Worst case cost
                avg_p -= res_stats.get("avg", 0) * qty
                max_p -= res_stats.get("min", 0) * qty  # Best case cost

                resource_details.append(
                    {
                        "item": res,
                        "quantity": qty,
                        "min": res_stats.get("min", 0),
                        "avg": res_stats.get("avg", 0),
                        "max": res_stats.get("max", 0),
                    }
                )

            # Apply Bonus Multiplier
            best_opt = best_options.get(item, {})
            total_bonus = best_opt.get("total_bonus", 0)
            multiplier = 1 + (total_bonus / 100)

            # Profit Per Point
            snapshot[item] = {
                "min_pp": round((min_p * multiplier) / pp, 3),
                "avg_pp": round((avg_p * multiplier) / pp, 3),
                "max_pp": round((max_p * multiplier) / pp, 3),
                "market_avg": round(item_stats.get("avg", 0), 2),
                # Rich data for report
                "base_min_price": round(min_price, 3),
                "base_avg_price": round(avg_price, 3),
                "base_max_price": round(max_price, 3),
                "min_price": round(min_p, 3),  # Net profit before bonus
                "avg_price": round(avg_p, 3),
                "max_price": round(max_p, 3),
                "production_points": pp,
                "bonus_multiplier": multiplier,
                "total_bonus": total_bonus,
                "resources": resource_details,
                "region_name": best_opt.get("region", "Unknown"),
                "country_name": best_opt.get("country", "Unknown"),
                "region_bonus": best_opt.get("region_bonus", 0),
                "country_bonus": best_opt.get("country_bonus", 0),
                "deposit_ends_at": best_opt.get("deposit_ends_at"),
            }

        return snapshot
