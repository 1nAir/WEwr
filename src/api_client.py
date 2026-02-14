import json
import time
from collections import deque
from itertools import cycle
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests


class TRPCClient:
    """
    Client for interacting with the game tRPC API.
    Includes logic for complex stats gathering and key rotation.
    """

    BATCH_SIZE = 50  # Testing higher limits (watch for HTTP 414 errors)

    def __init__(self, api_keys: List[str]):
        if not api_keys:
            raise ValueError("No API keys provided.")
        self.api_keys = api_keys
        # Rate limiting: 200 req/min per key
        self._key_usage = {k: deque(maxlen=200) for k in api_keys}
        self._key_cycle = cycle(api_keys)
        self.base_url = "https://api2.warera.io/trpc"
        self._game_config_cache = None

    def _get_valid_key(self) -> str:
        """Rotates keys respecting the rate limit (200 req/min)."""
        # Try to find an available key
        for _ in range(len(self.api_keys)):
            key = next(self._key_cycle)
            history = self._key_usage[key]

            # Check if key has quota
            if len(history) < 200:
                history.append(time.time())
                return key

            # Check if oldest request is older than 60s
            if time.time() - history[0] > 60:
                history.append(time.time())
                return key

        # If all keys are exhausted, wait for the soonest one to free up
        wait_times = [
            max(0, 60 - (time.time() - self._key_usage[k][0])) for k in self.api_keys
        ]
        sleep_time = min(wait_times)
        if sleep_time > 0:
            time.sleep(sleep_time + 0.1)

        return self._get_valid_key()

    def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        raise_on_error: bool = True,
    ) -> Any:
        params = params or {}
        key = self._get_valid_key()
        encoded_input = quote(json.dumps(params))
        url = f"{self.base_url}/{method}?input={encoded_input}"

        try:
            resp = requests.get(url, headers={"accept": "*/*", "X-API-Key": key})
            if raise_on_error:
                resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.RequestException:
            # Simple rotation on failure could be added here
            if raise_on_error:
                raise
            return {}

    def batch_call(
        self,
        calls: List[Tuple[str, Dict[str, Any]]],
        raise_on_error: bool = True,
    ) -> List[Any]:
        """
        Executes multiple tRPC calls in a single HTTP request (batching).
        Chunks requests to avoid URL length limits.
        """
        if not calls:
            return []

        results = []

        for i in range(0, len(calls), self.BATCH_SIZE):
            chunk = calls[i : i + self.BATCH_SIZE]
            key = self._get_valid_key()
            methods = [c[0] for c in chunk]
            # tRPC batch input keys are indices "0", "1", etc. relative to the batch
            inputs = {str(idx): c[1] for idx, c in enumerate(chunk)}

            encoded_input = quote(json.dumps(inputs))
            method_string = ",".join(methods)
            url = f"{self.base_url}/{method_string}?batch=1&input={encoded_input}"

            try:
                resp = requests.get(url, headers={"accept": "*/*", "X-API-Key": key})
                if raise_on_error:
                    resp.raise_for_status()

                data = resp.json() if resp.text else []
                if isinstance(data, list):
                    results.extend(data)
                else:
                    if raise_on_error:
                        raise requests.RequestException(
                            f"Invalid batch response: {data}"
                        )
                    results.extend([{} for _ in chunk])
            except requests.RequestException:
                if raise_on_error:
                    raise
                results.extend([{} for _ in chunk])

        return results

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

    def get_recommended_regions(
        self, item_code: str, include_deposit: bool = True
    ) -> List[Dict]:
        resp = self.call(
            "company.getRecommendedRegionIdsByItemCode",
            {"itemCode": item_code, "includeDeposit": include_deposit},
        )
        if not isinstance(resp, dict):
            return []
        data = resp.get("result", {}).get("data", resp)
        final_data = data.get("json", data) if isinstance(data, dict) else data
        return final_data if isinstance(final_data, list) else []

    # --- Complex Logic Preserved from original script ---

    def get_item_stats(
        self, item_codes: List[str], limit: int = 3
    ) -> Dict[str, Dict[str, Any]]:
        """
        Calculates min/avg/max based on order depth.
        Preserves original logic: checks top 10 orders to determine stability.
        Optimized to use batch requests.
        """
        prices_resp = self.get_item_prices()
        prices_data = prices_resp.get("result", {}).get("data", {})

        exclude_items = {"case1", "case2", "scraps"}
        results = {}

        # Filter items to process
        items_to_process = [
            code
            for code in item_codes
            if code in prices_data and code not in exclude_items
        ]

        # Prepare batch calls
        calls = [
            ("tradingOrder.getTopOrders", {"itemCode": code, "limit": 10})
            for code in items_to_process
        ]

        # Execute batch calls
        batch_responses = self.batch_call(calls, raise_on_error=True)

        for i, item_code in enumerate(items_to_process):
            avg = round(prices_data[item_code], 3)

            # Get corresponding response
            resp = batch_responses[i] if i < len(batch_responses) else {}

            # Explicitly check for tRPC error in the individual response
            if "error" in resp:
                error_details = resp["error"]
                raise requests.RequestException(
                    f"API error for item '{item_code}': {error_details}"
                )

            orders_data = (
                resp.get("result", {}).get("data", {}) if isinstance(resp, dict) else {}
            )

            buy_prices = [
                o["price"] for o in orders_data.get("buyOrders", []) if "price" in o
            ]
            sell_prices = [
                o["price"] for o in orders_data.get("sellOrders", []) if "price" in o
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
