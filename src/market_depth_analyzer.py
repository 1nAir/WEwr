from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from src import config
from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class MarketDepthAnalyzer:
    """
    Analyzes global market depth across all market orders by polling
    countries, parties, military units, and all active/listed players.
    Calculates total units, total PP, top 3 sellers, and the price ladder.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def _discover_owners(
        self, target_items: list[str]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], set[str]]:
        """
        Gathers IDs and metadata for countries, parties, MUs, and all players.
        Ensures zero duplicate checks.
        """
        logger.info("Discovering market participants across the game...")

        # 1. Countries
        c_res = self.client.call("country.getAllCountries", {}, raise_on_error=False)
        countries_data = (
            c_res.get("result", {}).get("data", []) if isinstance(c_res, dict) else []
        )
        country_meta: dict[str, dict[str, Any]] = {}
        for c in countries_data:
            cid = c.get("_id")
            if cid:
                code = c.get("code", "")
                country_meta[cid] = {
                    "id": cid,
                    "name": c.get("name", "Country"),
                    "type": "country",
                    "code": code,
                    "avatar_url": f"https://flagcdn.com/w40/{code.lower()}.png" if code else None,
                    "profile_url": f"https://app.warera.io/country/{cid}",
                }

        # 2. Parties
        party_meta: dict[str, dict[str, Any]] = {}
        cursor = None
        while True:
            payload: dict[str, Any] = {"limit": 100}
            if cursor:
                payload["cursor"] = cursor
            res = self.client.call("party.getManyPaginated", payload, raise_on_error=False)
            data = res.get("result", {}).get("data", {}) if isinstance(res, dict) else {}
            items = data.get("items", [])
            for p in items:
                pid = p.get("_id")
                if pid:
                    party_meta[pid] = {
                        "id": pid,
                        "name": p.get("name", "Party"),
                        "type": "party",
                        "avatar_url": p.get("avatarUrl"),
                        "profile_url": f"https://app.warera.io/party/{pid}",
                    }
            cursor = data.get("nextCursor")
            if not cursor or not items:
                break

        # 3. MUs
        mu_meta: dict[str, dict[str, Any]] = {}
        cursor = None
        while True:
            payload = {"limit": 100}
            if cursor:
                payload["cursor"] = cursor
            res = self.client.call("mu.getManyPaginated", payload, raise_on_error=False)
            data = res.get("result", {}).get("data", {}) if isinstance(res, dict) else {}
            items = data.get("items", [])
            for m in items:
                mid = m.get("_id")
                if mid:
                    mu_meta[mid] = {
                        "id": mid,
                        "name": m.get("name", "MU"),
                        "type": "mu",
                        "avatar_url": m.get("avatarUrl"),
                        "profile_url": f"https://app.warera.io/mu/{mid}",
                    }
            cursor = data.get("nextCursor")
            if not cursor or not items:
                break

        # 4. Players: start with ranked players
        ranked_players = self.client.get_users_ranking("userLevel")
        all_user_ids = {
            it["user"] for it in ranked_players if isinstance(it, dict) and it.get("user")
        }

        # 5. Inactive players who have active listings: catch from getTopOrders
        top_calls = [
            ("tradingOrder.getTopOrders", {"itemCode": code, "limit": 100})
            for code in target_items
        ]
        top_resps = self.client.batch_call(top_calls, raise_on_error=False)
        for resp in top_resps:
            if isinstance(resp, dict):
                sells = resp.get("result", {}).get("data", {}).get("sellOrders", [])
                for o in sells:
                    uid = o.get("user")
                    if uid:
                        all_user_ids.add(uid)

        logger.info(
            f"Discovered: {len(country_meta)} countries, {len(party_meta)} parties, "
            f"{len(mu_meta)} MUs, and {len(all_user_ids)} unique players."
        )

        return country_meta, party_meta, mu_meta, all_user_ids

    def collect_market_depth(
        self, items: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Polls all market owners via tradingOrder.getPublicOrdersByOwner in batches.
        Aggregates units, PP, top 3 sellers, and ladder per commodity.
        """
        target_items = items or list(config.ITEM_PRETTY_NAMES.keys())

        # 1. Discover all owners
        country_meta, party_meta, mu_meta, all_user_ids = self._discover_owners(target_items)

        # 2. Build owner query list
        calls = []
        owner_meta = []  # tuple of (owner_id, owner_type)
        for cid in country_meta:
            calls.append(("tradingOrder.getPublicOrdersByOwner", {"countryId": cid}))
            owner_meta.append((cid, "country"))
        for pid in party_meta:
            calls.append(("tradingOrder.getPublicOrdersByOwner", {"partyId": pid}))
            owner_meta.append((pid, "party"))
        for mid in mu_meta:
            calls.append(("tradingOrder.getPublicOrdersByOwner", {"muId": mid}))
            owner_meta.append((mid, "mu"))
        for uid in all_user_ids:
            calls.append(("tradingOrder.getPublicOrdersByOwner", {"userId": uid}))
            owner_meta.append((uid, "user"))

        logger.info(
            f"Querying public orders across {len(calls)} owners in batches of {self.client.BATCH_SIZE}..."
        )

        responses = self.client.batch_call(
            calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
        )

        # 3. Collect unique sell orders and track owner volume and price tiers
        # itemCode -> list of unique sell orders
        item_orders = defaultdict(list)
        # itemCode -> owner_id -> total_qty
        item_owner_volume = defaultdict(lambda: defaultdict(int))
        # itemCode -> owner_id -> price -> qty
        item_owner_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        # owner_id -> owner_type
        owner_type_map = {}

        seen_order_ids = set()

        for idx, resp in enumerate(responses):
            if not isinstance(resp, dict) or "result" not in resp:
                continue

            owner_id, o_type = owner_meta[idx]
            owner_type_map[owner_id] = o_type

            data = resp.get("result", {}).get("data", {})
            sells = data.get("sellOrders", [])
            for o in sells:
                oid = o.get("_id")
                if oid and oid not in seen_order_ids:
                    seen_order_ids.add(oid)
                    item_code = o.get("itemCode")
                    if item_code in target_items:
                        item_orders[item_code].append(o)
                        qty = int(o.get("quantity", 0))
                        p = round(float(o.get("price", 0.0)), 3)
                        # Identify owner ID
                        item_owner_volume[item_code][owner_id] += qty
                        item_owner_orders[item_code][owner_id][p] += qty

        logger.info(f"Collected {len(seen_order_ids)} unique sell orders across all items.")

        # 4. Resolve names and avatars for Top 3 sellers per commodity
        users_to_resolve = set()
        top_sellers_raw = {}

        for code in target_items:
            owner_vols = item_owner_volume[code]
            # Sort owners by quantity descending
            sorted_owners = sorted(owner_vols.items(), key=lambda kv: kv[1], reverse=True)[:3]
            top_sellers_raw[code] = sorted_owners
            for oid, _ in sorted_owners:
                if owner_type_map.get(oid) == "user":
                    users_to_resolve.add(oid)

        # Batch resolve usernames and avatars for top seller players
        user_meta: dict[str, dict[str, Any]] = {}
        if users_to_resolve:
            user_calls = [("user.getUserLite", {"userId": uid}) for uid in users_to_resolve]
            user_resps = self.client.batch_call(
                user_calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
            )
            for i, u_resp in enumerate(user_resps):
                uid = list(users_to_resolve)[i]
                if isinstance(u_resp, dict) and "result" in u_resp:
                    u_data = u_resp.get("result", {}).get("data", {})
                    user_meta[uid] = {
                        "id": uid,
                        "name": u_data.get("username", f"Player_{uid[:6]}"),
                        "type": "user",
                        "avatar_url": u_data.get("avatarUrl"),
                        "profile_url": f"https://app.warera.io/user/{uid}",
                    }
                else:
                    user_meta[uid] = {
                        "id": uid,
                        "name": f"Player_{uid[:6]}",
                        "type": "user",
                        "avatar_url": None,
                        "profile_url": f"https://app.warera.io/user/{uid}",
                    }

        # Helper to get full owner details
        def get_owner_info(oid: str) -> dict[str, Any]:
            o_type = owner_type_map.get(oid, "user")
            if o_type == "country":
                return country_meta.get(oid, {
                    "id": oid,
                    "name": "Country",
                    "type": "country",
                    "code": "",
                    "avatar_url": None,
                    "profile_url": f"https://app.warera.io/country/{oid}",
                })
            elif o_type == "party":
                return party_meta.get(oid, {
                    "id": oid,
                    "name": "Party",
                    "type": "party",
                    "avatar_url": None,
                    "profile_url": f"https://app.warera.io/party/{oid}",
                })
            elif o_type == "mu":
                return mu_meta.get(oid, {
                    "id": oid,
                    "name": "MU",
                    "type": "mu",
                    "avatar_url": None,
                    "profile_url": f"https://app.warera.io/mu/{oid}",
                })
            else:
                return user_meta.get(oid, {
                    "id": oid,
                    "name": f"Player_{oid[:6]}",
                    "type": "user",
                    "avatar_url": None,
                    "profile_url": f"https://app.warera.io/user/{oid}",
                })

        # 5. Format Snapshot
        snapshot: dict[str, Any] = {}

        for code in target_items:
            sells = item_orders.get(code, [])
            pp_per_unit = config.ITEM_PRODUCTION_POINTS.get(code, 1)
            total_units = sum(int(o.get("quantity", 0)) for o in sells)
            total_pp = total_units * pp_per_unit

            # Build ladder sorted by price ascending
            price_map = defaultdict(int)
            for o in sells:
                p = round(float(o.get("price", 0.0)), 3)
                price_map[p] += int(o.get("quantity", 0))

            ladder = []
            for p in sorted(price_map.keys()):
                qty = price_map[p]
                ladder.append({
                    "price": p,
                    "quantity": qty,
                    "pp": qty * pp_per_unit,
                })

            # Format top 3 sellers with metadata (avatar, profile link, type, active listings)
            top_sellers = []
            for oid, qty in top_sellers_raw.get(code, []):
                share = round((qty / total_units * 100), 1) if total_units > 0 else 0.0
                info = get_owner_info(oid)
                seller_orders = [
                    {"price": p, "quantity": q}
                    for p, q in sorted(item_owner_orders[code][oid].items())
                ]
                top_sellers.append({
                    "id": info.get("id", oid),
                    "name": info.get("name", "Unknown"),
                    "type": info.get("type", "user"),
                    "code": info.get("code"),
                    "avatar_url": info.get("avatar_url"),
                    "profile_url": info.get("profile_url"),
                    "quantity": qty,
                    "share_pct": share,
                    "orders": seller_orders,
                })

            snapshot[code] = {
                "total_units": total_units,
                "pp_per_unit": pp_per_unit,
                "total_pp": total_pp,
                "top_sellers": top_sellers,
                "ladder": ladder,
            }

        logger.info(f"Market depth analysis completed for {len(snapshot)} items.")
        return snapshot

