from collections import defaultdict
from datetime import datetime, timezone
import logging
from typing import Any

from src import config
from src.api_client import TRPCClient
from src.entity_resolver import EntityResolver
from src.storage import Storage

logger = logging.getLogger(__name__)

# Participants kept per item in the raw snapshot (frontend order book still shows only Top-3).
PER_ITEM_TOP_N = 25
# Owners ranked in the global Top-N (by PP / by money) are always kept in every item they trade.
GLOBAL_WHALES_N = 25


class OrderBookAnalyzer:
    """
    Polls global market orders across countries, parties, military units, and active players.
    Computes unified Sell & Buy Order Books, best Bid/Ask, spread, top participants
    (per-item Top-25 plus global whales), and price ladders.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def _discover_owners(
        self, target_items: list[str]
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        set[str],
        set[str],
    ]:
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
            params: dict[str, Any] = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            res = self.client.call("party.getManyPaginated", params, raise_on_error=False)
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

        # 3. Military Units (MUs)
        mu_meta: dict[str, dict[str, Any]] = {}
        cursor = None
        while True:
            params = {"limit": 100}
            if cursor:
                params["cursor"] = cursor
            res = self.client.call("mu.getManyPaginated", params, raise_on_error=False)
            data = res.get("result", {}).get("data", {}) if isinstance(res, dict) else {}
            items = data.get("items", [])
            for m in items:
                mid = m.get("_id")
                if mid:
                    mu_meta[mid] = {
                        "id": mid,
                        "name": m.get("name", "Military Unit"),
                        "type": "mu",
                        "avatar_url": m.get("avatarUrl"),
                        "profile_url": f"https://app.warera.io/mu/{mid}",
                    }
            cursor = data.get("nextCursor")
            if not cursor or not items:
                break

        # 4. Players by country
        country_Calls = [
            ("user.getUsersByCountry", {"countryId": cid, "limit": 100})
            for cid in country_meta
        ]
        first_pages = self.client.batch_call(
            country_Calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
        )

        guaranteed_users: set[str] = set()
        next_calls = []

        for idx, cid in enumerate(country_meta):
            r = first_pages[idx] if idx < len(first_pages) else {}
            if isinstance(r, dict) and "result" in r:
                d = r.get("result", {}).get("data", {})
                for u in d.get("items", []):
                    uid = u.get("_id")
                    if uid:
                        guaranteed_users.add(uid)
                nc = d.get("nextCursor")
                if nc:
                    next_calls.append(
                        ("user.getUsersByCountry", {"countryId": cid, "limit": 100, "cursor": nc})
                    )

        while next_calls:
            resps = self.client.batch_call(
                next_calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
            )
            new_next = []
            for idx, call_info in enumerate(next_calls):
                cid = call_info[1]["countryId"]
                r = resps[idx] if idx < len(resps) else {}
                if isinstance(r, dict) and "result" in r:
                    d = r.get("result", {}).get("data", {})
                    for u in d.get("items", []):
                        uid = u.get("_id")
                        if uid:
                            guaranteed_users.add(uid)
                    nc = d.get("nextCursor")
                    if nc:
                        new_next.append(
                            ("user.getUsersByCountry", {"countryId": cid, "limit": 100, "cursor": nc})
                        )
            next_calls = new_next

        # 5. Top-100 Orders per item
        top_calls = [
            ("tradingOrder.getTopOrders", {"itemCode": code, "limit": 100})
            for code in target_items
        ]
        top_resps = self.client.batch_call(
            top_calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
        )
        for r in top_resps:
            if isinstance(r, dict) and "result" in r:
                d = r.get("result", {}).get("data", {})
                for o in d.get("sellOrders", []) + d.get("buyOrders", []):
                    u = o.get("user")
                    if u and u not in country_meta and u not in party_meta and u not in mu_meta:
                        guaranteed_users.add(u)

        known_players = Storage.load_known_players()
        candidate_users = set(known_players.keys()) - guaranteed_users

        logger.info(
            f"Discovered: {len(country_meta)} countries, {len(party_meta)} parties, "
            f"{len(mu_meta)} MUs, {len(guaranteed_users)} guaranteed players, "
            f"and {len(candidate_users)} candidates from file."
        )
        return country_meta, party_meta, mu_meta, guaranteed_users, candidate_users

    def collect_orderbook(self) -> dict[str, Any]:
        target_items = list(config.ALL_MARKET_ITEMS.keys())
        country_meta, party_meta, mu_meta, guaranteed_users, candidate_users = (
            self._discover_owners(target_items)
        )
        all_users_to_scan = guaranteed_users | candidate_users

        order_calls: list[tuple[str, dict[str, Any]]] = []
        owner_lookup: list[tuple[str, str]] = []

        for cid in country_meta:
            order_calls.append(("tradingOrder.getPublicOrdersByOwner", {"countryId": cid}))
            owner_lookup.append(("country", cid))
        for pid in party_meta:
            order_calls.append(("tradingOrder.getPublicOrdersByOwner", {"partyId": pid}))
            owner_lookup.append(("party", pid))
        for mid in mu_meta:
            order_calls.append(("tradingOrder.getPublicOrdersByOwner", {"muId": mid}))
            owner_lookup.append(("mu", mid))
        for uid in all_users_to_scan:
            order_calls.append(("tradingOrder.getPublicOrdersByOwner", {"userId": uid}))
            owner_lookup.append(("user", uid))

        logger.info(f"Querying public orders across {len(order_calls)} owners in batches of 100...")
        responses = self.client.batch_call(
            order_calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
        )

        seen_order_ids: set[str] = set()
        users_with_active_orders: set[str] = set()
        target_items_set = set(target_items)

        sell_item_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
        buy_item_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for idx, r in enumerate(responses):
            if not isinstance(r, dict) or "result" not in r:
                continue
            data = r.get("result", {}).get("data", {})
            if not isinstance(data, dict):
                continue

            sells = data.get("sellOrders", [])
            buys = data.get("buyOrders", [])
            o_type, o_id = owner_lookup[idx]

            has_valid = False
            for o in sells:
                oid = o.get("_id")
                code = o.get("itemCode")
                qty = int(o.get("quantity", 0))
                price = float(o.get("price", 0.0))
                if not oid or oid in seen_order_ids or code not in target_items_set or qty <= 0:
                    continue
                seen_order_ids.add(oid)
                has_valid = True
                sell_item_orders[code].append(
                    {
                        "id": oid,
                        "owner_type": o_type,
                        "owner_id": o_id,
                        "quantity": qty,
                        "price": round(price, 4),
                    }
                )

            for o in buys:
                oid = o.get("_id")
                code = o.get("itemCode")
                qty = int(o.get("quantity", 0))
                price = float(o.get("price", 0.0))
                if not oid or oid in seen_order_ids or code not in target_items_set or qty <= 0:
                    continue
                seen_order_ids.add(oid)
                has_valid = True
                buy_item_orders[code].append(
                    {
                        "id": oid,
                        "owner_type": o_type,
                        "owner_id": o_id,
                        "quantity": qty,
                        "price": round(price, 4),
                    }
                )

            if has_valid and o_type == "user":
                users_with_active_orders.add(o_id)

        # Update known_players.json
        existing_known = Storage.load_known_players()
        verified_ids = guaranteed_users | (candidate_users & users_with_active_orders)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        updated_known = {}
        for uid in verified_ids:
            prev = existing_known.get(uid, {})
            updated_known[uid] = {
                "id": uid,
                "name": prev.get("name", f"Player_{uid[:6]}"),
                "type": "user",
                "avatar_url": prev.get("avatar_url"),
                "profile_url": f"https://app.warera.io/user/{uid}",
                "updated_at": prev.get("updated_at", now_iso),
            }
        Storage.save_known_players(updated_known)

        # Aggregate FULL per-owner totals for every item first (no truncation here).
        # Participant lists are trimmed afterwards, once global whales are known.
        top_user_ids_to_fetch: set[str] = set()
        item_Aggregates: dict[str, dict[str, Any]] = {}

        for code in target_items:
            # Sell Orders
            s_orders = sell_item_orders.get(code, [])
            s_total_units = sum(o["quantity"] for o in s_orders)
            s_ladder_map: dict[float, int] = defaultdict(int)
            s_owner_totals: dict[tuple[str, str], int] = defaultdict(int)
            s_owner_prices: dict[tuple[str, str], dict[float, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            for o in s_orders:
                p = o["price"]
                q = o["quantity"]
                ok = (o["owner_type"], o["owner_id"])
                s_ladder_map[p] += q
                s_owner_totals[ok] += q
                s_owner_prices[ok][p] += q

            # Buy Orders
            b_orders = buy_item_orders.get(code, [])
            b_total_units = sum(o["quantity"] for o in b_orders)
            b_total_money = sum(o["quantity"] * o["price"] for o in b_orders)
            b_ladder_map: dict[float, int] = defaultdict(int)
            b_owner_totals: dict[tuple[str, str], dict[str, float]] = defaultdict(
                lambda: {"units": 0, "money": 0.0}
            )
            b_owner_prices: dict[tuple[str, str], dict[float, int]] = defaultdict(
                lambda: defaultdict(int)
            )
            for o in b_orders:
                p = o["price"]
                q = o["quantity"]
                ok = (o["owner_type"], o["owner_id"])
                b_ladder_map[p] += q
                b_owner_totals[ok]["units"] += q
                b_owner_totals[ok]["money"] += q * p
                b_owner_prices[ok][p] += q

            item_Aggregates[code] = {
                "s_total_units": s_total_units,
                "s_ladder_map": s_ladder_map,
                "s_owner_totals": s_owner_totals,
                "s_owner_prices": s_owner_prices,
                "b_total_units": b_total_units,
                "b_total_money": round(b_total_money, 2),
                "b_ladder_map": b_ladder_map,
                "b_owner_totals": b_owner_totals,
                "b_owner_prices": b_owner_prices,
            }

        # Global "whales": owners that rank at the top across ALL items combined.
        # A big player who is only #4-#20 in every single item would be lost by a pure
        # per-item cut, so every whale is always kept (for every item they trade).
        extra_items = set(config.MARKET_EXTRA_ITEMS)
        g_sell_pp: dict[tuple[str, str], float] = defaultdict(float)
        g_sell_extra_units: dict[tuple[str, str], int] = defaultdict(int)
        g_buy_money: dict[tuple[str, str], float] = defaultdict(float)
        g_buy_extra_money: dict[tuple[str, str], float] = defaultdict(float)

        for code, agg in item_Aggregates.items():
            pp_rate = config.ALL_ITEMS_PP.get(code, 0)
            for ok, qty in agg["s_owner_totals"].items():
                if pp_rate > 0:
                    g_sell_pp[ok] += qty * pp_rate
                if code in extra_items:
                    g_sell_extra_units[ok] += qty
            for ok, stat in agg["b_owner_totals"].items():
                g_buy_money[ok] += stat["money"]
                if code in extra_items:
                    g_buy_extra_money[ok] += stat["money"]

        def _top_owner_keys(totals: dict[tuple[str, str], Any]) -> set[tuple[str, str]]:
            ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
            return {ok for ok, _ in ranked[:GLOBAL_WHALES_N]}

        sell_whales = _top_owner_keys(g_sell_pp) | _top_owner_keys(g_sell_extra_units)
        buy_whales = _top_owner_keys(g_buy_money) | _top_owner_keys(g_buy_extra_money)

        # Per item: local Top-N plus any global whale present in that item (ranked order kept).
        for agg in item_Aggregates.values():
            s_ranked = sorted(
                agg["s_owner_totals"].items(), key=lambda kv: kv[1], reverse=True
            )
            agg["s_top"] = s_ranked[:PER_ITEM_TOP_N] + [
                kv for kv in s_ranked[PER_ITEM_TOP_N:] if kv[0] in sell_whales
            ]
            b_ranked = sorted(
                agg["b_owner_totals"].items(),
                key=lambda kv: (kv[1]["money"], kv[1]["units"]),
                reverse=True,
            )
            agg["b_top"] = b_ranked[:PER_ITEM_TOP_N] + [
                kv for kv in b_ranked[PER_ITEM_TOP_N:] if kv[0] in buy_whales
            ]
            for (ot, oid), _ in agg["s_top"] + agg["b_top"]:
                if ot == "user":
                    top_user_ids_to_fetch.add(oid)

        resolver = EntityResolver(self.client)
        resolver.cache.update(country_meta)
        resolver.cache.update(party_meta)
        resolver.cache.update(mu_meta)
        resolver.resolve(top_user_ids_to_fetch)

        # Build final snapshot
        snapshot: dict[str, Any] = {}
        for code in target_items:
            agg = item_Aggregates[code]
            pp_rate = config.ALL_ITEMS_PP.get(code, 0)

            s_units = agg["s_total_units"]
            s_pp = s_units * pp_rate
            s_ladder = [
                {
                    "p": round(p, 3),
                    "q": q,
                    "m": round(p * q, 2),
                    "pp": q * pp_rate,
                }
                for p, q in sorted(agg["s_ladder_map"].items(), key=lambda kv: kv[0])
            ]
            s_value_btc = round(sum(r["m"] for r in s_ladder), 2)

            top_sellers = []
            for (ot, oid), qty in agg["s_top"]:
                meta = (
                    country_meta.get(oid)
                    if ot == "country"
                    else party_meta.get(oid)
                    if ot == "party"
                    else mu_meta.get(oid)
                    if ot == "mu"
                    else resolver.get_info(oid)
                ) or resolver.get_info(oid)
                orders_list = [
                    {"p": round(p, 3), "q": q, "price": round(p, 3), "quantity": q}
                    for p, q in sorted(agg["s_owner_prices"][(ot, oid)].items())
                ]
                val_btc = round(sum(o["p"] * o["q"] for o in orders_list), 2)
                share = round((qty / s_units * 100), 1) if s_units > 0 else 0.0
                top_sellers.append(
                    {
                        **meta,
                        "quantity": int(qty),
                        "units": int(qty),
                        "pp": int(qty * pp_rate),
                        "value_btc": val_btc,
                        "share_pct": share,
                        "orders": orders_list,
                    }
                )

            b_units = int(agg["b_total_units"])
            b_pp = b_units * pp_rate
            b_money = agg["b_total_money"]
            b_ladder = [
                {
                    "p": round(p, 3),
                    "q": q,
                    "m": round(p * q, 2),
                    "pp": q * pp_rate,
                }
                for p, q in sorted(
                    agg["b_ladder_map"].items(), key=lambda kv: kv[0], reverse=True
                )
            ]

            top_buyers = []
            for (ot, oid), b_stat in agg["b_top"]:
                meta = (
                    country_meta.get(oid)
                    if ot == "country"
                    else party_meta.get(oid)
                    if ot == "party"
                    else mu_meta.get(oid)
                    if ot == "mu"
                    else resolver.get_info(oid)
                ) or resolver.get_info(oid)
                qty = int(b_stat["units"])
                mny = round(float(b_stat["money"]), 2)
                orders_list = [
                    {"p": round(p, 3), "q": q, "price": round(p, 3), "quantity": q}
                    for p, q in sorted(
                        agg["b_owner_prices"][(ot, oid)].items(), reverse=True
                    )
                ]
                share = (
                    round((mny / b_money * 100), 1)
                    if b_money > 0
                    else (round((qty / b_units * 100), 1) if b_units > 0 else 0.0)
                )
                top_buyers.append(
                    {
                        **meta,
                        "quantity": qty,
                        "units": qty,
                        "pp": int(qty * pp_rate),
                        "money": mny,
                        "money_btc": mny,
                        "share_pct": share,
                        "orders": orders_list,
                    }
                )

            best_bid = b_ladder[0]["p"] if b_ladder else 0.0
            best_ask = s_ladder[0]["p"] if s_ladder else 0.0
            spread_btc = (
                round(best_ask - best_bid, 3)
                if (best_bid > 0 and best_ask > 0)
                else 0.0
            )
            spread_pct = (
                round((spread_btc / best_bid) * 100, 2)
                if (best_bid > 0 and best_ask > 0)
                else 0.0
            )

            # Normal (regular) book totals excluding 2x+ / 2x- outliers
            s_ask_limit = (best_ask * 2.0) if best_ask > 0 else 0.0
            b_bid_limit = (best_bid * 0.5) if best_bid > 0 else 0.0

            reg_s_ladder = [
                r for r in s_ladder
                if not (s_ask_limit > 0 and r["p"] >= s_ask_limit - 1e-9)
            ]
            reg_s_units = sum(r["q"] for r in reg_s_ladder)
            reg_s_pp = reg_s_units * pp_rate
            reg_s_value_btc = round(sum(r["m"] for r in reg_s_ladder), 2)

            reg_b_ladder = [
                r for r in b_ladder
                if not (b_bid_limit > 0 and r["p"] < b_bid_limit - 1e-9)
            ]
            reg_b_units = sum(r["q"] for r in reg_b_ladder)
            reg_b_pp = reg_b_units * pp_rate
            reg_b_money_btc = round(sum(r["m"] for r in reg_b_ladder), 2)

            snapshot[code] = {
                "pp_per_unit": pp_rate,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "spread_btc": spread_btc,
                "spread_pct": spread_pct,
                "total_units": reg_s_units,
                "total_pp": reg_s_pp,
                "top_sellers": top_sellers,
                "ladder": s_ladder,
                "buy_total_units": reg_b_units,
                "buy_total_pp": reg_b_pp,
                "buy_total_money": reg_b_money_btc,
                "sell": {
                    "total_units": reg_s_units,
                    "total_pp": reg_s_pp,
                    "total_value_btc": reg_s_value_btc,
                    "top3_share_pct": round(
                        sum(x["share_pct"] for x in top_sellers[:3]), 1
                    ),
                    "top_sellers": top_sellers,
                    "ladder": s_ladder,
                },
                "buy": {
                    "total_units": reg_b_units,
                    "total_pp": reg_b_pp,
                    "total_money_btc": reg_b_money_btc,
                    "top3_share_pct": round(
                        sum(x["share_pct"] for x in top_buyers[:3]), 1
                    ),
                    "top_buyers": top_buyers,
                    "ladder": b_ladder,
                },
                "buy_depth": {
                    "total_units": reg_b_units,
                    "total_pp": reg_b_pp,
                    "total_money": reg_b_money_btc,
                    "top_buyers": top_buyers,
                    "ladder": b_ladder,
                },
            }

        return snapshot

