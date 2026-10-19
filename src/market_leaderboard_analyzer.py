import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from src import config
from src.api_client import TRPCClient
from src.entity_resolver import EntityResolver

logger = logging.getLogger(__name__)


class MarketLeaderboardAnalyzer:
    """
    Computes pre-aggregated Top-10 leaderboards across:
    1. Live Order Book (Sell Depth & Buy Depth)
    2. Historical Realized Trades across time windows (24h, 7d, 30d, all)
    3. Dual modes: By-Item, Global (PP > 0), and Unmanufactured (Cases/Scraps).
    4. Includes detailed by-item breakdown for each leader.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def build_leaderboards(
        self,
        depth_snapshot: dict[str, Any],
        daily_stats: dict[str, Any],
        raw_trades: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Pre-aggregates Top 10 leaderboards for frontend:
        1. Live Order Book (Sell Depth & Buy Depth)
        2. Realized Historical Trades across 24h, 7d, 30d, all
        3. Global, Unmanufactured, and By-Commodity scopes
        4. Detailed executed price level breakdown for drawers
        """
        now = datetime.now(timezone.utc)
        now_ts = int(now.timestamp())
        today_str = now.strftime("%Y-%m-%d")

        # Load raw_trades if not explicitly provided
        if raw_trades is None:
            try:
                from src.data_processor import DataProcessor
                t_snap, _ = DataProcessor.load_latest_market_trades()
                if t_snap:
                    raw_trades = t_snap.get("raw_trades", [])
            except Exception:
                raw_trades = []

        # Index 24h trade orders by buyer, seller, and commodity
        trade_buyer_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        trade_seller_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        if raw_trades:
            for t in raw_trades:
                bid = t.get("buyerId")
                sid = t.get("sellerId")
                code = t.get("itemCode")
                qty = int(t.get("quantity", 0))
                mny = float(t.get("money", 0.0))
                if qty > 0 and code:
                    unit_p = round(mny / qty, 3)
                    if bid:
                        trade_buyer_orders[bid][code][unit_p] += qty
                    if sid:
                        trade_seller_orders[sid][code][unit_p] += qty

        # Initialize EntityResolver and pre-seed cache from depth_snapshot and known_players
        resolver = EntityResolver(self.client)
        try:
            from src.data_processor import DataProcessor
            kp = DataProcessor.load_known_players() or {}
            for k_id, k_meta in kp.items():
                if k_id not in resolver.cache or resolver.cache[k_id].get("name", "").startswith("Player_"):
                    resolver.cache[k_id] = {
                        "id": k_id,
                        "name": k_meta.get("name", f"Player_{k_id[:6]}"),
                        "type": k_meta.get("type", "user"),
                        "avatar_url": k_meta.get("avatar_url"),
                        "profile_url": k_meta.get("profile_url") or f"https://app.warera.io/{k_meta.get('type', 'user')}/{k_id}",
                        "updated_at": now_ts,
                    }
        except Exception:
            pass

        # Pre-seed resolver from depth_snapshot (contains resolved countries, MUs, parties, and users)
        for code, it_data in depth_snapshot.items():
            for s in it_data.get("top_sellers", []):
                sid = s.get("id")
                sname = s.get("name")
                if sid and sname and not str(sname).startswith("Player_"):
                    resolver.cache[sid] = {
                        "id": sid,
                        "name": sname,
                        "type": s.get("type", "user"),
                        "code": s.get("code"),
                        "avatar_url": s.get("avatar_url"),
                        "profile_url": s.get("profile_url") or f"https://app.warera.io/{s.get('type', 'user')}/{sid}",
                        "updated_at": now_ts,
                    }
            for b in it_data.get("buy_depth", {}).get("top_buyers", []):
                bid = b.get("id")
                bname = b.get("name")
                if bid and bname and not str(bname).startswith("Player_"):
                    resolver.cache[bid] = {
                        "id": bid,
                        "name": bname,
                        "type": b.get("type", "user"),
                        "code": b.get("code"),
                        "avatar_url": b.get("avatar_url"),
                        "profile_url": b.get("profile_url") or f"https://app.warera.io/{b.get('type', 'user')}/{bid}",
                        "updated_at": now_ts,
                    }

        days_data = daily_stats.get("days", {})
        available_days = sorted(days_data.keys(), reverse=True)

        periods = {
            "24h": [today_str, (now - timedelta(days=1)).strftime("%Y-%m-%d")],
            "7d": [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)],
            "30d": [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(30)],
            "all": available_days,
        }

        # 1. Aggregate trades for each period
        period_aggregates: dict[str, dict[str, Any]] = {}
        entities_to_resolve = set()

        unman_items = set(config.MARKET_DEPTH_EXTRA_ITEMS.keys())
        global_items = set(config.ITEM_PRODUCTION_POINTS.keys())
        all_commodity_items = set(config.MARKET_DEPTH_ITEMS.keys())

        for period_key, valid_dates in periods.items():
            valid_set = set(valid_dates)
            matched_days = [d for d in available_days if d in valid_set]

            buyer_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": defaultdict(lambda: {"units": 0, "money": 0.0, "pp": 0})})
            seller_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": defaultdict(lambda: {"units": 0, "money": 0.0, "pp": 0})})

            for day in matched_days:
                day_players = days_data.get(day, {})
                for eid, pdata in day_players.items():
                    # Buy
                    b = pdata.get("buy", {})
                    buyer_totals[eid]["money"] += float(b.get("money", 0.0))
                    buyer_totals[eid]["pp"] += int(b.get("pp", 0))
                    buyer_totals[eid]["units"] += int(b.get("units", 0))
                    for it, iv in b.get("by_item", {}).items():
                        buyer_totals[eid]["by_item"][it]["units"] += int(iv.get("units", 0))
                        buyer_totals[eid]["by_item"][it]["money"] += float(iv.get("money", 0.0))
                        buyer_totals[eid]["by_item"][it]["pp"] += int(iv.get("pp", 0))

                    # Sell
                    s = pdata.get("sell", {})
                    seller_totals[eid]["money"] += float(s.get("money", 0.0))
                    seller_totals[eid]["pp"] += int(s.get("pp", 0))
                    seller_totals[eid]["units"] += int(s.get("units", 0))
                    for it, iv in s.get("by_item", {}).items():
                        seller_totals[eid]["by_item"][it]["units"] += int(iv.get("units", 0))
                        seller_totals[eid]["by_item"][it]["money"] += float(iv.get("money", 0.0))
                        seller_totals[eid]["by_item"][it]["pp"] += int(iv.get("pp", 0))

            # Group 1: Global manufactured items (PP > 0)
            global_buyer_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": {}})
            global_seller_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": {}})
            for eid, d in buyer_totals.items():
                for code in global_items:
                    it_stats = d["by_item"].get(code)
                    if it_stats and (it_stats.get("units", 0) > 0 or it_stats.get("money", 0) > 0 or it_stats.get("pp", 0) > 0):
                        global_buyer_totals[eid]["units"] += it_stats.get("units", 0)
                        global_buyer_totals[eid]["money"] += float(it_stats.get("money", 0.0))
                        global_buyer_totals[eid]["pp"] += int(it_stats.get("pp", 0))
                        global_buyer_totals[eid]["by_item"][code] = it_stats

            for eid, d in seller_totals.items():
                for code in global_items:
                    it_stats = d["by_item"].get(code)
                    if it_stats and (it_stats.get("units", 0) > 0 or it_stats.get("money", 0) > 0 or it_stats.get("pp", 0) > 0):
                        global_seller_totals[eid]["units"] += it_stats.get("units", 0)
                        global_seller_totals[eid]["money"] += float(it_stats.get("money", 0.0))
                        global_seller_totals[eid]["pp"] += int(it_stats.get("pp", 0))
                        global_seller_totals[eid]["by_item"][code] = it_stats

            # Group 2: Unmanufactured items (0 PP: Cases & Scraps)
            unman_buyer_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": {}})
            unman_seller_totals = defaultdict(lambda: {"money": 0.0, "pp": 0, "units": 0, "by_item": {}})
            for eid, d in buyer_totals.items():
                for code in unman_items:
                    it_stats = d["by_item"].get(code)
                    if it_stats and (it_stats.get("units", 0) > 0 or it_stats.get("money", 0) > 0):
                        unman_buyer_totals[eid]["units"] += it_stats.get("units", 0)
                        unman_buyer_totals[eid]["money"] += float(it_stats.get("money", 0.0))
                        unman_buyer_totals[eid]["by_item"][code] = it_stats

            for eid, d in seller_totals.items():
                for code in unman_items:
                    it_stats = d["by_item"].get(code)
                    if it_stats and (it_stats.get("units", 0) > 0 or it_stats.get("money", 0) > 0):
                        unman_seller_totals[eid]["units"] += it_stats.get("units", 0)
                        unman_seller_totals[eid]["money"] += float(it_stats.get("money", 0.0))
                        unman_seller_totals[eid]["by_item"][code] = it_stats

            period_aggregates[period_key] = {
                "buyers": buyer_totals,
                "sellers": seller_totals,
                "global_buyers": global_buyer_totals,
                "global_sellers": global_seller_totals,
                "unman_buyers": unman_buyer_totals,
                "unman_sellers": unman_seller_totals,
            }

            # Add Global Top 15 to resolve
            for eid, _ in sorted(global_buyer_totals.items(), key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(global_buyer_totals.items(), key=lambda kv: kv[1]["pp"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(global_seller_totals.items(), key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(global_seller_totals.items(), key=lambda kv: kv[1]["pp"], reverse=True)[:15]:
                entities_to_resolve.add(eid)

            # Add Unmanufactured Top 15 to resolve
            for eid, _ in sorted(unman_buyer_totals.items(), key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(unman_buyer_totals.items(), key=lambda kv: kv[1]["units"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(unman_seller_totals.items(), key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                entities_to_resolve.add(eid)
            for eid, _ in sorted(unman_seller_totals.items(), key=lambda kv: kv[1]["units"], reverse=True)[:15]:
                entities_to_resolve.add(eid)

            # Add By-Commodity Top 15 to resolve across all 24 items
            for c_code in all_commodity_items:
                c_buyers = [(eid, d["by_item"][c_code]) for eid, d in buyer_totals.items() if c_code in d["by_item"] and d["by_item"][c_code]["units"] > 0]
                for eid, _ in sorted(c_buyers, key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                    entities_to_resolve.add(eid)
                for eid, _ in sorted(c_buyers, key=lambda kv: kv[1]["units"], reverse=True)[:15]:
                    entities_to_resolve.add(eid)

                c_sellers = [(eid, d["by_item"][c_code]) for eid, d in seller_totals.items() if c_code in d["by_item"] and d["by_item"][c_code]["units"] > 0]
                for eid, _ in sorted(c_sellers, key=lambda kv: kv[1]["money"], reverse=True)[:15]:
                    entities_to_resolve.add(eid)
                for eid, _ in sorted(c_sellers, key=lambda kv: kv[1]["units"], reverse=True)[:15]:
                    entities_to_resolve.add(eid)

        # Collect entities from Live Depth
        depth_sellers_by_item = defaultdict(lambda: defaultdict(lambda: {"units": 0, "money": 0.0, "pp": 0}))
        depth_buyers_by_item = defaultdict(lambda: defaultdict(lambda: {"units": 0, "money": 0.0, "pp": 0}))
        depth_sellers_pp = defaultdict(int)
        depth_sellers_units = defaultdict(int)
        depth_buyers_pp = defaultdict(int)
        depth_buyers_money = defaultdict(float)

        unman_sellers_units = defaultdict(int)
        unman_buyers_units = defaultdict(int)
        unman_buyers_money = defaultdict(float)

        for code, it_data in depth_snapshot.items():
            pp_rate = config.MARKET_DEPTH_PP.get(code, 0)
            is_unman = code in unman_items

            for s in it_data.get("top_sellers", []):
                sid = s.get("id")
                if not sid:
                    continue
                entities_to_resolve.add(sid)
                sqty = int(s.get("quantity", 0))
                smoney = sum(float(o.get("price", 0.0)) * int(o.get("quantity", 0)) for o in s.get("orders", []))
                spp = sqty * pp_rate if pp_rate else 0

                depth_sellers_by_item[sid][code]["units"] += sqty
                depth_sellers_by_item[sid][code]["money"] += smoney
                depth_sellers_by_item[sid][code]["pp"] += spp
                depth_sellers_by_item[sid][code]["orders"] = s.get("orders", [])

                if pp_rate > 0:
                    depth_sellers_pp[sid] += spp
                    depth_sellers_units[sid] += sqty
                if is_unman:
                    unman_sellers_units[sid] += sqty

            for b in it_data.get("buy_depth", {}).get("top_buyers", []):
                bid = b.get("id")
                if not bid:
                    continue
                entities_to_resolve.add(bid)
                bqty = int(b.get("quantity", 0))
                bmoney = float(b.get("money", 0.0)) or sum(float(o.get("price", 0.0)) * int(o.get("quantity", 0)) for o in b.get("orders", []))
                bpp = bqty * pp_rate if pp_rate else 0

                depth_buyers_by_item[bid][code]["units"] += bqty
                depth_buyers_by_item[bid][code]["money"] += bmoney
                depth_buyers_by_item[bid][code]["pp"] += bpp
                depth_buyers_by_item[bid][code]["orders"] = b.get("orders", [])

                if pp_rate > 0:
                    depth_buyers_pp[bid] += bpp
                    depth_buyers_money[bid] += bmoney
                if is_unman:
                    unman_buyers_units[bid] += bqty
                    unman_buyers_money[bid] += bmoney

        # Resolve entity details using EntityResolver with auto-refresh
        resolver.resolve(entities_to_resolve, force_refresh_ids=entities_to_resolve)

        def filter_items(by_item_map: dict[str, Any] | None, allowed: set[str] | None = None) -> dict[str, Any]:
            if not by_item_map:
                return {}
            if allowed is not None:
                return {k: v for k, v in by_item_map.items() if k in allowed}
            return by_item_map

        def make_entry(
            eid: str,
            metric_val: float | int,
            sub_metric: str,
            sub_val: float | int,
            by_item_map: dict[str, Any] | None = None,
            allowed_items: set[str] | None = None,
            is_buyer: bool = False,
            is_seller: bool = False,
        ) -> dict[str, Any]:
            meta = resolver.get_info(eid)
            breakdown = []
            filtered_map = filter_items(by_item_map, allowed_items)
            if filtered_map:
                for icode, idata in filtered_map.items():
                    u = int(idata.get("units", 0))
                    m = round(float(idata.get("money", 0.0)), 3)
                    pp = int(idata.get("pp", 0))
                    orders = idata.get("orders", [])
                    if not orders:
                        if is_buyer and eid in trade_buyer_orders and icode in trade_buyer_orders[eid]:
                            orders = [
                                {"price": round(p, 3), "quantity": q}
                                for p, q in sorted(trade_buyer_orders[eid][icode].items(), key=lambda kv: kv[1], reverse=True)[:12]
                            ]
                        elif is_seller and eid in trade_seller_orders and icode in trade_seller_orders[eid]:
                            orders = [
                                {"price": round(p, 3), "quantity": q}
                                for p, q in sorted(trade_seller_orders[eid][icode].items(), key=lambda kv: kv[1], reverse=True)[:12]
                            ]
                    avg_p = round(m / u, 3) if u > 0 and m > 0 else 0.0
                    if u > 0 or m > 0 or pp > 0:
                        breakdown.append({
                            "item": icode,
                            "pretty_name": config.ITEM_PRETTY_NAMES.get(icode, config.MARKET_DEPTH_EXTRA_ITEMS.get(icode, icode)),
                            "units": u,
                            "pp": pp,
                            "money": m,
                            "avg_price": avg_p,
                            "orders": orders[:12] if orders else [],
                        })
                if is_buyer:
                    breakdown.sort(key=lambda x: (x["money"], x["pp"], x["units"]), reverse=True)
                else:
                    breakdown.sort(key=lambda x: (x["pp"], x["units"], x["money"]), reverse=True)

            return {
                **meta,
                "value": metric_val,
                "sub_metric": sub_metric,
                "sub_value": sub_val,
                "by_item": breakdown,
            }

        # 2. Build Global Leaderboards (PP > 0)
        global_pp_leaderboards: dict[str, Any] = {
            "live_depth": {
                "top_sellers_pp": [
                    make_entry(eid, pp_val, "units", depth_sellers_units[eid], depth_sellers_by_item[eid], allowed_items=global_items, is_seller=True)
                    for eid, pp_val in sorted(depth_sellers_pp.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    if pp_val > 0
                ],
                "top_buyers_pp": [
                    make_entry(eid, round(depth_buyers_money[eid], 3), "pp", depth_buyers_pp[eid], depth_buyers_by_item[eid], allowed_items=global_items, is_buyer=True)
                    for eid, m_val in sorted(depth_buyers_money.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    if m_val > 0
                ],
            },
            "trades": {},
        }

        # Trades global PP per period
        for p_key, p_data in period_aggregates.items():
            buyers = p_data["global_buyers"]
            sellers = p_data["global_sellers"]

            top_b_money = sorted(buyers.items(), key=lambda kv: kv[1]["money"], reverse=True)[:10]
            top_s_money = sorted(sellers.items(), key=lambda kv: kv[1]["money"], reverse=True)[:10]

            buyers_list = [make_entry(eid, round(d["money"], 2), "pp", d["pp"], d["by_item"], allowed_items=global_items, is_buyer=True) for eid, d in top_b_money if d["money"] > 0]
            sellers_list = [make_entry(eid, round(d["money"], 2), "pp", d["pp"], d["by_item"], allowed_items=global_items, is_seller=True) for eid, d in top_s_money if d["money"] > 0]

            global_pp_leaderboards["trades"][p_key] = {
                "top_buyers": buyers_list,
                "top_sellers": sellers_list,
                # Backward compatibility aliases
                "top_buyers_money": buyers_list,
                "top_sellers_money": sellers_list,
                "top_buyers_pp": buyers_list,
                "top_sellers_pp": sellers_list,
            }

        # 3. Build Unmanufactured Leaderboards (0 PP: Cases & Scraps)
        unman_leaderboards: dict[str, Any] = {
            "live_depth": {
                "top_sellers_units": [
                    make_entry(eid, u_val, "units", u_val, depth_sellers_by_item[eid], allowed_items=unman_items, is_seller=True)
                    for eid, u_val in sorted(unman_sellers_units.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    if u_val > 0
                ],
                "top_buyers_units": [
                    make_entry(eid, round(m_val, 3), "units", unman_buyers_units[eid], depth_buyers_by_item[eid], allowed_items=unman_items, is_buyer=True)
                    for eid, m_val in sorted(unman_buyers_money.items(), key=lambda kv: kv[1], reverse=True)[:10]
                    if m_val > 0
                ],
            },
            "trades": {},
        }

        for p_key, p_data in period_aggregates.items():
            unman_b = p_data["unman_buyers"]
            unman_s = p_data["unman_sellers"]

            unman_b_list = [
                make_entry(eid, round(d["money"], 2), "units", d["units"], d["by_item"], allowed_items=unman_items, is_buyer=True)
                for eid, d in sorted(unman_b.items(), key=lambda kv: kv[1]["money"], reverse=True)[:10]
                if d["money"] > 0
            ]
            unman_s_list = [
                make_entry(eid, round(d["money"], 2), "units", d["units"], d["by_item"], allowed_items=unman_items, is_seller=True)
                for eid, d in sorted(unman_s.items(), key=lambda kv: kv[1]["money"], reverse=True)[:10]
                if d["money"] > 0
            ]

            unman_leaderboards["trades"][p_key] = {
                "top_buyers": unman_b_list,
                "top_sellers": unman_s_list,
                # Backward compatibility aliases
                "top_buyers_money": unman_b_list,
                "top_buyers_units": unman_b_list,
                "top_sellers_money": unman_s_list,
                "top_sellers_units": unman_s_list,
            }

        # 4. Build By-Item Leaderboards
        by_item_leaderboards: dict[str, Any] = {}
        for code in config.MARKET_DEPTH_ITEMS:
            it_depth = depth_snapshot.get(code, {})
            live_sellers = it_depth.get("top_sellers", [])[:10]
            live_buyers = it_depth.get("buy_depth", {}).get("top_buyers", [])[:10]

            item_trades_period = {}
            for p_key, p_data in period_aggregates.items():
                b_map = p_data["buyers"]
                s_map = p_data["sellers"]

                it_buyers = []
                for eid, d in b_map.items():
                    it_data = d["by_item"].get(code)
                    if it_data and it_data["units"] > 0:
                        it_buyers.append((eid, it_data))

                it_sellers = []
                for eid, d in s_map.items():
                    it_data = d["by_item"].get(code)
                    if it_data and it_data["units"] > 0:
                        it_sellers.append((eid, it_data))

                item_b_list = [
                    make_entry(eid, round(d["money"], 2), "units", d["units"], {code: d}, allowed_items={code}, is_buyer=True)
                    for eid, d in sorted(it_buyers, key=lambda kv: kv[1]["money"], reverse=True)[:10]
                ]
                item_s_list = [
                    make_entry(eid, round(d["money"], 2), "units", d["units"], {code: d}, allowed_items={code}, is_seller=True)
                    for eid, d in sorted(it_sellers, key=lambda kv: kv[1]["money"], reverse=True)[:10]
                ]

                item_trades_period[p_key] = {
                    "top_buyers": item_b_list,
                    "top_sellers": item_s_list,
                    # Backward compatibility aliases
                    "top_buyers_money": item_b_list,
                    "top_buyers_volume": item_b_list,
                    "top_sellers_money": item_s_list,
                    "top_sellers_volume": item_s_list,
                }

            # Enforce by_item breakdown for live_depth top sellers & buyers too
            formatted_live_sellers = []
            for s in live_sellers:
                sid = s.get("id")
                entry = make_entry(
                    sid,
                    s.get("quantity", 0),
                    "share",
                    s.get("share_pct", 0),
                    {code: {"units": s.get("quantity", 0), "orders": s.get("orders", [])}},
                    allowed_items={code},
                    is_seller=True,
                )
                formatted_live_sellers.append(entry)

            formatted_live_buyers = []
            for b in live_buyers:
                bid = b.get("id")
                b_money = round(float(b.get("money", 0.0)), 3)
                b_qty = int(b.get("quantity", 0))
                entry = make_entry(
                    bid,
                    b_money,
                    "units",
                    b_qty,
                    {code: {"units": b_qty, "money": b_money, "orders": b.get("orders", [])}},
                    allowed_items={code},
                    is_buyer=True,
                )
                formatted_live_buyers.append(entry)

            by_item_leaderboards[code] = {
                "live_depth": {
                    "top_sellers": formatted_live_sellers,
                    "top_buyers": formatted_live_buyers,
                },
                "trades": item_trades_period,
            }

        return {
            "timestamp": int(now.timestamp()),
            "by_item": by_item_leaderboards,
            "global_pp": global_pp_leaderboards,
            "unmanufactured": unman_leaderboards,
        }
