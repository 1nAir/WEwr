from datetime import datetime, timezone
import logging
from collections import defaultdict
from typing import Any

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor

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

        # 4. Players: load from known_players cache
        known_data = DataProcessor.load_known_players()
        if isinstance(known_data, list):
            cached_player_ids = set(known_data)
        elif isinstance(known_data, dict):
            cached_player_ids = set(known_data.get("players", []))
            if not cached_player_ids:
                cached_player_ids = set(known_data.get("active_users", [])).union(
                    known_data.get("inactive_sellers", [])
                )
        else:
            cached_player_ids = set()

        # 5. Live active players from ranking
        ranked_players = self.client.get_users_ranking("userLevel")
        live_active_ids = {
            it["user"] for it in ranked_players if isinstance(it, dict) and it.get("user")
        }

        # 6. Safety Net: Discover sellers from Top 100 orders across all target commodities
        top_calls = [
            ("tradingOrder.getTopOrders", {"itemCode": code, "limit": 100})
            for code in target_items
        ]
        top_resps = self.client.batch_call(
            top_calls, raise_on_error=False, batch_size=len(target_items)
        )
        top_order_uids = set()
        for resp in top_resps:
            if isinstance(resp, dict):
                data = resp.get("result", {}).get("data", {})
                sells = data.get("sellOrders", [])
                buys = data.get("buyOrders", [])
                for o in sells + buys:
                    uid = o.get("user")
                    if uid:
                        top_order_uids.add(uid)

        # Guaranteed players: active players + top-100 sellers (always kept / added to file)
        guaranteed_players = live_active_ids.union(top_order_uids)

        # Unconfirmed candidates: players in file who are neither in active ranking nor in top-100
        unconfirmed_candidates = cached_player_ids - guaranteed_players

        # All players to query for orders: guaranteed + candidates to verify
        all_user_ids = guaranteed_players.union(unconfirmed_candidates)

        logger.info(
            f"Discovered: {len(country_meta)} countries, {len(party_meta)} parties, "
            f"{len(mu_meta)} MUs, {len(guaranteed_players)} guaranteed players (active/top100), "
            f"and {len(unconfirmed_candidates)} candidates to verify from file. "
            f"Total unique users to scan: {len(all_user_ids)}."
        )

        return (
            country_meta,
            party_meta,
            mu_meta,
            all_user_ids,
            guaranteed_players,
            unconfirmed_candidates,
        )

    def collect_market_depth(
        self, items: list[str] | None = None
    ) -> dict[str, Any]:
        """
        Polls all market owners via tradingOrder.getPublicOrdersByOwner in batches.
        Aggregates units, PP, top 3 sellers, and ladder per commodity.
        """
        target_items = items or list(config.MARKET_DEPTH_ITEMS.keys())

        # 1. Discover all owners
        (
            country_meta,
            party_meta,
            mu_meta,
            all_user_ids,
            guaranteed_players,
            unconfirmed_candidates,
        ) = self._discover_owners(target_items)

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

        # 3. Collect unique sell and buy orders and track owner volume and price tiers
        # itemCode -> list of unique sell orders
        item_orders = defaultdict(list)
        # itemCode -> owner_id -> total_qty
        item_owner_volume = defaultdict(lambda: defaultdict(int))
        # itemCode -> owner_id -> price -> qty
        item_owner_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # itemCode -> list of unique buy orders
        item_buy_orders = defaultdict(list)
        # itemCode -> owner_id -> total_buy_qty
        item_buy_owner_volume = defaultdict(lambda: defaultdict(int))
        # itemCode -> owner_id -> price -> qty
        item_buy_owner_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        # owner_id -> owner_type
        owner_type_map = {}

        seen_order_ids = set()
        seen_buy_order_ids = set()
        users_with_active_orders = set()

        for idx, resp in enumerate(responses):
            if not isinstance(resp, dict) or "result" not in resp:
                continue

            owner_id, o_type = owner_meta[idx]
            owner_type_map[owner_id] = o_type

            data = resp.get("result", {}).get("data", {})
            sells = data.get("sellOrders", [])
            buys = data.get("buyOrders", [])

            # Active player has at least 1 active sell OR buy order
            if (sells or buys) and o_type == "user":
                users_with_active_orders.add(owner_id)

            for o in sells:
                oid = o.get("_id")
                if oid and oid not in seen_order_ids:
                    seen_order_ids.add(oid)
                    item_code = o.get("itemCode")
                    if item_code in target_items:
                        item_orders[item_code].append(o)
                        qty = int(o.get("quantity", 0))
                        p = round(float(o.get("price", 0.0)), 3)
                        item_owner_volume[item_code][owner_id] += qty
                        item_owner_orders[item_code][owner_id][p] += qty

            for o in buys:
                oid = o.get("_id")
                if oid and oid not in seen_buy_order_ids:
                    seen_buy_order_ids.add(oid)
                    item_code = o.get("itemCode")
                    if item_code in target_items:
                        item_buy_orders[item_code].append(o)
                        qty = int(o.get("quantity", 0))
                        p = round(float(o.get("price", 0.0)), 3)
                        item_buy_owner_volume[item_code][owner_id] += qty
                        item_buy_owner_orders[item_code][owner_id][p] += qty

        logger.info(
            f"Collected {len(seen_order_ids)} unique sell orders and "
            f"{len(seen_buy_order_ids)} unique buy orders across all items."
        )

        # 3.5 Verify candidates and update known_players pool:
        # Candidates from the file who were not in guaranteed (active/top100) are checked:
        # If they have >= 1 active orders -> kept in file.
        # If they have 0 active orders -> removed from file.
        verified_candidates = {
            uid for uid in unconfirmed_candidates if uid in users_with_active_orders
        }
        removed_candidates = unconfirmed_candidates - verified_candidates

        # Final pool of known players: guaranteed (active + top100) + verified candidates with orders
        final_players = guaranteed_players.union(verified_candidates)

        logger.info(
            f"Known players update: {len(guaranteed_players)} guaranteed (active/top100), "
            f"{len(verified_candidates)} unconfirmed candidates with active orders retained, "
            f"{len(removed_candidates)} candidates with 0 orders removed. "
            f"Total saved: {len(final_players)}."
        )

        updated_known_players = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "count": len(final_players),
            "guaranteed_count": len(guaranteed_players),
            "verified_candidates_count": len(verified_candidates),
            "players": sorted(final_players),
        }
        DataProcessor.save_known_players(updated_known_players)

        # 4. Resolve names and avatars for Top 3 sellers and Top 3 buyers per commodity
        users_to_resolve = set()
        top_sellers_raw = {}
        top_buyers_raw = {}

        for code in target_items:
            # Sellers (Top 10 for Leaderboards & Drawers)
            owner_vols = item_owner_volume[code]
            sorted_sellers = sorted(owner_vols.items(), key=lambda kv: kv[1], reverse=True)[:10]
            top_sellers_raw[code] = sorted_sellers
            for oid, _ in sorted_sellers:
                if owner_type_map.get(oid) == "user":
                    users_to_resolve.add(oid)

            # Buyers: Rank Top 10 by MONEY waiting on the market (sum of qty * price)
            buy_money = {
                oid: sum(p * q for p, q in item_buy_owner_orders[code][oid].items())
                for oid in item_buy_owner_orders[code]
            }
            sorted_buyers = sorted(buy_money.items(), key=lambda kv: kv[1], reverse=True)[:10]
            top_buyers_raw[code] = sorted_buyers
            for oid, _ in sorted_buyers:
                if owner_type_map.get(oid) == "user":
                    users_to_resolve.add(oid)

        # Batch resolve usernames and avatars with EntityResolver (force refreshing active top participants)
        from src.entity_resolver import EntityResolver
        resolver = EntityResolver(self.client)
        resolver.resolve(users_to_resolve, force_refresh_ids=users_to_resolve)

        def get_owner_info(oid: str) -> dict[str, Any]:
            o_type = owner_type_map.get(oid, "user")
            if o_type == "country":
                return country_meta.get(oid, resolver.get_info(oid))
            elif o_type == "party":
                return party_meta.get(oid, resolver.get_info(oid))
            elif o_type == "mu":
                return mu_meta.get(oid, resolver.get_info(oid))
            else:
                return resolver.get_info(oid)

        # 5. Format Snapshot (Both Sell Depth and Buy Depth)
        snapshot: dict[str, Any] = {}

        for code in target_items:
            pp_per_unit = config.MARKET_DEPTH_PP.get(code, 0)

            # --- SELL DEPTH ---
            sells = item_orders.get(code, [])
            total_sell_units = sum(int(o.get("quantity", 0)) for o in sells)
            total_sell_pp = total_sell_units * pp_per_unit if pp_per_unit else 0
            total_sell_money = sum(
                int(o.get("quantity", 0)) * float(o.get("price", 0.0)) for o in sells
            )

            min_sell_price = min((float(o.get("price", 0.0)) for o in sells), default=0.0)
            sell_2x_threshold = min_sell_price * 2.0
            regular_sell_money = sum(
                int(o.get("quantity", 0)) * float(o.get("price", 0.0))
                for o in sells
                if float(o.get("price", 0.0)) < sell_2x_threshold - 1e-9
            )

            # Build ladder sorted by price ascending (cheapest asks first)
            price_map = defaultdict(int)
            for o in sells:
                p = round(float(o.get("price", 0.0)), 3)
                price_map[p] += int(o.get("quantity", 0))

            sell_ladder = []
            for p in sorted(price_map.keys()):
                qty = price_map[p]
                sell_ladder.append({
                    "price": p,
                    "quantity": qty,
                    "pp": qty * pp_per_unit if pp_per_unit else 0,
                })

            top_sellers = []
            for oid, qty in top_sellers_raw.get(code, []):
                share = round((qty / total_sell_units * 100), 1) if total_sell_units > 0 else 0.0
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

            # --- BUY DEPTH ---
            buys = item_buy_orders.get(code, [])
            all_buy_units = sum(int(o.get("quantity", 0)) for o in buys)
            all_buy_money = sum(
                int(o.get("quantity", 0)) * float(o.get("price", 0.0)) for o in buys
            )
            max_buy_price = max((float(o.get("price", 0.0)) for o in buys), default=0.0)
            buy_2x_threshold = max_buy_price / 2.0 if max_buy_price > 0 else 0.0

            # 2x- filter: regular buy orders have price >= buy_2x_threshold
            regular_buys = [
                o for o in buys
                if float(o.get("price", 0.0)) >= buy_2x_threshold - 1e-9
            ]
            regular_buy_units = sum(int(o.get("quantity", 0)) for o in regular_buys)
            regular_buy_pp = regular_buy_units * pp_per_unit if pp_per_unit else 0
            regular_buy_money = sum(
                int(o.get("quantity", 0)) * float(o.get("price", 0.0)) for o in regular_buys
            )

            # Buy ladder sorted by price DESCENDING (highest buy bids first)
            buy_price_map = defaultdict(int)
            for o in buys:
                p = round(float(o.get("price", 0.0)), 3)
                buy_price_map[p] += int(o.get("quantity", 0))

            buy_ladder = []
            for p in sorted(buy_price_map.keys(), reverse=True):
                qty = buy_price_map[p]
                buy_ladder.append({
                    "price": p,
                    "quantity": qty,
                    "pp": qty * pp_per_unit if pp_per_unit else 0,
                })

            top_buyers = []
            for oid, b_money in top_buyers_raw.get(code, []):
                # Calculate buyer's regular money and regular quantity
                b_orders_all = item_buy_owner_orders[code][oid]
                b_reg_money = sum(p * q for p, q in b_orders_all.items() if p >= buy_2x_threshold - 1e-9)
                b_reg_qty = sum(q for p, q in b_orders_all.items() if p >= buy_2x_threshold - 1e-9)
                b_tot_qty = sum(q for q in b_orders_all.values())

                share = round((b_reg_money / regular_buy_money * 100), 1) if regular_buy_money > 0 else 0.0
                info = get_owner_info(oid)
                buyer_orders = [
                    {"price": p, "quantity": q}
                    for p, q in sorted(b_orders_all.items(), reverse=True)
                ]
                top_buyers.append({
                    "id": info.get("id", oid),
                    "name": info.get("name", "Unknown"),
                    "type": info.get("type", "user"),
                    "code": info.get("code"),
                    "avatar_url": info.get("avatar_url"),
                    "profile_url": info.get("profile_url"),
                    "quantity": b_reg_qty if b_reg_qty > 0 else b_tot_qty,
                    "money": round(b_reg_money if b_reg_money > 0 else b_money, 3),
                    "share_pct": share,
                    "orders": buyer_orders,
                })

            snapshot[code] = {
                "total_units": total_sell_units,
                "pp_per_unit": pp_per_unit,
                "total_pp": total_sell_pp,
                "total_money": round(regular_sell_money, 3),
                "all_total_money": round(total_sell_money, 3),
                "buy_total_units": regular_buy_units,
                "buy_total_pp": regular_buy_pp,
                "buy_total_money": round(regular_buy_money, 3),
                "top_sellers": top_sellers,
                "ladder": sell_ladder,
                "buy_depth": {
                    "total_units": regular_buy_units,
                    "total_pp": regular_buy_pp,
                    "total_money_invested": round(regular_buy_money, 3),
                    "all_total_units": all_buy_units,
                    "all_total_money_invested": round(all_buy_money, 3),
                    "threshold_price": round(buy_2x_threshold, 3),
                    "max_price": round(max_buy_price, 3),
                    "top_buyers": top_buyers,
                    "ladder": buy_ladder,
                },
            }


        logger.info(f"Market depth analysis completed for {len(snapshot)} items.")
        return snapshot

