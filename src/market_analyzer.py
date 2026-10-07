from typing import Any

from src.api_client import TRPCClient
from src.region_analyzer import RegionBonusAnalyzer


class MarketAnalyzer:
    """
    Encapsulates business logic for calculating item profitability,
    considering production costs, regional bonuses, and deposits.
    """

    def __init__(self, client: TRPCClient):
        self.client = client
        self.region_analyzer = RegionBonusAnalyzer(client)
        self.last_bonuses_data = None

    def _get_best_production_options(
        self, items: list[str]
    ) -> dict[str, dict[str, Any]]:
        """
        Uses RegionBonusAnalyzer to find best locations based on
        bonuses, taxes, and deposit duration.
        Returns a dict of item_code -> {bonus, region_data...}.
        """
        self.last_bonuses_data = self.region_analyzer.collect_all_bonuses()
        by_item = self.last_bonuses_data.get("by_item", {})

        best_options = {}

        for item in items:
            locs = by_item.get(item, [])
            if not locs:
                best_options[item] = {
                    "total_bonus": 0,
                    "region_bonus": 0,
                    "country_bonus": 0,
                    "ethic_bonus": 0,
                    "region": "None",
                    "country": "None",
                    "deposit_ends_at": None,
                    "tax_percent": 0,
                }
                continue

            top_loc = locs[0]
            b_down = top_loc.get("breakdown", {})
            ethic_bonus = b_down.get("ethic_specialization_bonus", 0) + b_down.get(
                "ethic_deposit_bonus", 0
            )

            regions_list = top_loc.get("regions", [])
            if top_loc.get("has_deposit") and regions_list:
                region_name = regions_list[0].get("name", "Unknown")
            else:
                region_name = "All regions"

            tax = top_loc.get("tax_percent", 0)
            if isinstance(tax, float) and tax.is_integer():
                tax = int(tax)
            elif isinstance(tax, float):
                tax = round(tax, 2)

            best_options[item] = {
                "total_bonus": top_loc.get("total_bonus", 0),
                "region_bonus": b_down.get("deposit_bonus", 0),
                "country_bonus": b_down.get("country_strategic_bonus", 0),
                "ethic_bonus": ethic_bonus,
                "region": region_name,
                "country": top_loc.get("country_name", "Unknown"),
                "deposit_ends_at": top_loc.get("deposit_ends_at"),
                "tax_percent": tax,
            }

        return best_options

    def calculate_snapshot(self) -> dict[str, Any]:
        """
        Main logic: Fetch prices, stats, and calculate Profit/PP (min/avg/max).
        Subtracts production costs recursively (inputs).
        """
        prices_resp = self.client.get_item_prices()
        raw_prices = prices_resp.get("result", {}).get("data", {})
        items = list(raw_prices.keys())

        # Heavy operation: fetch detailed stats for all items
        stats = self.client.get_item_stats(items)
        best_options = self._get_best_production_options(items)

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
                "ethic_bonus": best_opt.get("ethic_bonus", 0),
                "deposit_ends_at": best_opt.get("deposit_ends_at"),
                "tax_percent": best_opt.get("tax_percent", 0),
            }

        return snapshot
