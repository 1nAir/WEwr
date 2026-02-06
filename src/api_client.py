import json
import random
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import requests


class TRPCClient:
    """
    Client for interacting with the game tRPC API.
    Includes logic for complex stats gathering and key rotation.
    """

    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("No API keys provided.")
        self.api_keys = api_keys
        self.base_url = "https://api2.warera.io/trpc"
        self._current_key = random.choice(self.api_keys)
        self._game_config_cache = None

    def _get_headers(self) -> Dict[str, str]:
        return {"accept": "*/*", "X-API-Key": self._current_key}

    def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        raise_on_error: bool = True,
    ) -> Any:
        params = params or {}
        encoded_input = quote(json.dumps(params))
        url = f"{self.base_url}/{method}?input={encoded_input}"

        try:
            resp = requests.get(url, headers=self._get_headers())
            if raise_on_error:
                resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.RequestException:
            # Simple rotation on failure could be added here
            if raise_on_error:
                raise
            return {}

    # --- Core Data Endpoints ---

    def get_game_config(self) -> Any:
        if self._game_config_cache is None:
            self._game_config_cache = self.call("gameConfig.getGameConfig", {})
        return self._game_config_cache

    def get_countries(self) -> List[Dict]:
        resp = self.call("country.getAllCountries", {})
        return resp.get("result", {}).get("data", [])

    def get_regions(self) -> Dict[str, Any]:
        resp = self.call("region.getRegionsObject", {})
        return resp.get("result", {}).get("data", {})

    def get_item_prices(self) -> Any:
        return self.call("itemTrading.getPrices", {})

    def get_top_orders(self, item_code: str, limit: int = 10) -> Any:
        return self.call(
            "tradingOrder.getTopOrders", {"itemCode": item_code, "limit": limit}
        )

    # --- Complex Logic Preserved from original script ---

    def get_item_stats(
        self, item_codes: List[str], limit: int = 3
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculates min/avg/max based on order depth.
        Preserves original logic: checks top 10 orders to determine stability.
        """
        prices_resp = self.get_item_prices()
        prices_data = prices_resp.get("result", {}).get("data", {})

        exclude_items = {"case1", "case2", "scraps"}
        results = {}

        for item_code in item_codes:
            if item_code not in prices_data or item_code in exclude_items:
                continue

            avg = round(prices_data[item_code], 3)

            try:
                # Fetch depth
                orders_resp = self.get_top_orders(item_code, limit=10)
                orders_data = orders_resp.get("result", {}).get("data", {})

                buy_prices = [
                    o["price"] for o in orders_data.get("buyOrders", []) if "price" in o
                ]
                sell_prices = [
                    o["price"]
                    for o in orders_data.get("sellOrders", [])
                    if "price" in o
                ]

                # Logic from original script
                if len(buy_prices) >= 10:
                    top_buy = buy_prices[:limit]
                    min_price = round(sum(top_buy) / len(top_buy), 3)
                else:
                    min_price = round(buy_prices[0], 3) if buy_prices else avg

                if len(sell_prices) >= 10:
                    top_sell = sell_prices[:limit]
                    max_price = round(sum(top_sell) / len(top_sell), 3)
                else:
                    max_price = round(sell_prices[0], 3) if sell_prices else avg

                results[item_code] = {
                    "min": min_price,
                    "avg": avg,
                    "max": max_price,
                }
            except Exception:
                # Fallback to simple average if orders fail
                results[item_code] = {"min": avg, "avg": avg, "max": avg}

        return results

    def get_item_production_info(self, item_code: str) -> Dict[str, Any]:
        """Extracts production requirements from cached config."""
        config = self.get_game_config()
        items_config = config.get("result", {}).get("data", {}).get("items", {})

        item_info = items_config.get(item_code, {})
        return {
            "productionPoints": item_info.get("productionPoints", 0),
            "productionNeeds": item_info.get("productionNeeds", {}),
        }
