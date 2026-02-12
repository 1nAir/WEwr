from datetime import datetime
from typing import Any, Dict, List

from src.api_client import TRPCClient


class MarketAnalyzer:
    """
    Encapsulates business logic for calculating item profitability,
    considering production costs, regional bonuses, and deposits.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def _get_best_production_options(
        self, items: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        """
        Uses company.getRecommendedRegionIdsByItemCode to find best locations.
        Returns a dict of item_code -> {bonus, region_data...}.
        """
        countries = self.client.get_countries()
        regions = self.client.get_regions()

        # Map IDs to Names
        country_id_to_name = {c.get("_id"): c.get("name", "Unknown") for c in countries}
        region_id_to_obj = regions  # regions is Dict[id, region]

        best_options = {}

        for item in items:
            try:
                recs = self.client.get_recommended_regions(item)
            except Exception:
                continue

            if not recs:
                continue

            # Sort logic:
            # 1. Bonus (desc)
            # 2. Duration (desc/latest)
            def sort_key(r):
                bonus = r.get("bonus", 0)
                deposit_bonus = r.get("depositBonus", 0)
                end_at = r.get("depositEndAt")
                ts = 0.0
                if deposit_bonus > 0 and end_at:
                    try:
                        dt = datetime.fromisoformat(end_at.replace("Z", "+00:00"))
                        ts = dt.timestamp()
                    except ValueError:
                        pass
                return (bonus, ts)

            best_rec = max(recs, key=sort_key)

            # Resolve names
            r_id = best_rec.get("regionId")
            region_obj = region_id_to_obj.get(r_id, {})
            region_name = region_obj.get("name", region_obj.get("code", r_id))
            c_id = region_obj.get("country")
            country_name = country_id_to_name.get(c_id, "Unknown")

            # Calculate components
            ethic_bonus = best_rec.get("ethicDepositBonus", 0) + best_rec.get(
                "ethicSpecializationBonus", 0
            )

            deposit_bonus = best_rec.get("depositBonus", 0)
            deposit_ends_at = (
                best_rec.get("depositEndAt") if deposit_bonus > 0 else None
            )

            best_options[item] = {
                "total_bonus": best_rec.get("bonus", 0),
                "region_bonus": deposit_bonus,
                "country_bonus": best_rec.get("strategicBonus", 0),
                "ethic_bonus": ethic_bonus,
                "region": region_name,
                "country": country_name,
                "deposit_ends_at": deposit_ends_at,
            }

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
            }

        return snapshot
