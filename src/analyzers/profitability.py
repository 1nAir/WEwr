import logging
from typing import Any

from src import config
from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class ProfitabilityAnalyzer:
    """
    Calculates dry 1 Production Point (PP) value relative to current market Bid/Ask prices,
    without country, regional, deposit, ethic, or fidelity bonuses.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def calculate_snapshot(self) -> dict[str, Any]:
        """
        Fetches current Bid/Ask/Avg prices and gameConfig recipes, then calculates:
        - Conservative scenario (Min ₿/PP): Sell output @ Bid, Buy ingredients @ Ask
        - Optimistic scenario (Max ₿/PP): List output @ Ask, Buy ingredients @ Bid
        """
        target_items = list(config.ITEM_PRETTY_NAMES.keys())
        stats = self.client.get_item_stats(target_items)

        snapshot: dict[str, Any] = {}

        for item_code in target_items:
            prod_info = self.client.get_item_production_info(item_code)
            pp = int(
                prod_info.get("productionPoints")
                or config.ITEM_PRODUCTION_POINTS.get(item_code, 0)
            )
            if pp <= 0:
                continue

            needs = prod_info.get("productionNeeds")
            if needs is None:
                needs = config.DEFAULT_RECIPES.get(item_code, {})

            item_stats = stats.get(item_code, {})
            bid_price = float(item_stats.get("bid", 0.0))
            avg_price = float(item_stats.get("avg", 0.0))
            ask_price = float(item_stats.get("ask", 0.0))

            cost_min_scenario = 0.0  # Buying inputs immediately from Ask book
            cost_max_scenario = 0.0  # Acquiring inputs via Bid orders
            ingredients_breakdown = []

            for res_code, qty in needs.items():
                qty_num = float(qty)
                res_stats = stats.get(res_code, {})
                res_bid = float(res_stats.get("bid", 0.0))
                res_avg = float(res_stats.get("avg", 0.0))
                res_ask = float(res_stats.get("ask", 0.0))

                sub_min = round(res_ask * qty_num, 3)  # Conservative: pay Ask price
                sub_max = round(res_bid * qty_num, 3)  # Optimistic: pay Bid price

                cost_min_scenario += sub_min
                cost_max_scenario += sub_max

                ingredients_breakdown.append(
                    {
                        "item": res_code,
                        "name": config.ITEM_PRETTY_NAMES.get(res_code, res_code),
                        "qty": int(qty_num) if qty_num.is_integer() else qty_num,
                        "bid_price": round(res_bid, 3),
                        "avg_price": round(res_avg, 3),
                        "ask_price": round(res_ask, 3),
                        "cost_min_scenario": sub_min,
                        "cost_max_scenario": sub_max,
                    }
                )

            min_net_profit = round(bid_price - cost_min_scenario, 3)
            max_net_profit = round(ask_price - cost_max_scenario, 3)

            min_pp = round(min_net_profit / pp, 3)
            max_pp = round(max_net_profit / pp, 3)
            avg_net = round(
                avg_price - ((cost_min_scenario + cost_max_scenario) / 2.0), 3
            )
            avg_pp = round(avg_net / pp, 3)

            snapshot[item_code] = {
                "pp": pp,
                "bid": round(bid_price, 3),
                "avg": round(avg_price, 3),
                "ask": round(ask_price, 3),
                "cost_min_scenario": round(cost_min_scenario, 3),
                "cost_max_scenario": round(cost_max_scenario, 3),
                "min_net_profit": min_net_profit,
                "max_net_profit": max_net_profit,
                "min_pp": min_pp,
                "avg_pp": avg_pp,
                "max_pp": max_pp,
                "needs": needs,
                "ingredients": ingredients_breakdown,
            }

        return snapshot

