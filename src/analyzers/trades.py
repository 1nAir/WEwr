from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from src import config
from src.api_client import TRPCClient
from src.entity_resolver import EntityResolver
from src.storage import Storage

logger = logging.getLogger(__name__)


class MarketTradesAnalyzer:
    """
    Analyzes global completed trading transactions (transactionType="trading").
    Uses incremental delta polling via `last_tx_id`, maintains sharded `daily_trader_stats`
    (with rolling 31-day daily shards + cumulative All-Time archive),
    24h/7d/30d/all multi-window summaries, POC Volume Profiles, and hourly history.
    """

    @staticmethod
    def _merge_player_records(
        target_players: dict[str, Any], source_players: dict[str, Any]
    ) -> None:
        for pid, prec in source_players.items():
            if not isinstance(prec, dict):
                continue
            dst = target_players.setdefault(
                pid,
                {
                    "buy": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                    "sell": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                },
            )
            for side in ("buy", "sell"):
                src_side = prec.get(side)
                if not isinstance(src_side, dict):
                    continue
                dst_side = dst[side]
                dst_side["money"] = round(
                    float(dst_side.get("money", 0.0)) + float(src_side.get("money", 0.0)),
                    4,
                )
                dst_side["units"] = int(dst_side.get("units", 0)) + int(
                    src_side.get("units", 0)
                )
                dst_side["pp"] = int(dst_side.get("pp", 0)) + int(src_side.get("pp", 0))
                dst_items = dst_side.setdefault("by_item", {})
                for item_code, idata in (src_side.get("by_item") or {}).items():
                    if not isinstance(idata, dict):
                        continue
                    dst_it = dst_items.setdefault(
                        item_code, {"units": 0, "money": 0.0, "pp": 0}
                    )
                    dst_it["units"] = int(dst_it.get("units", 0)) + int(
                        idata.get("units", 0)
                    )
                    dst_it["money"] = round(
                        float(dst_it.get("money", 0.0)) + float(idata.get("money", 0.0)),
                        4,
                    )
                    dst_it["pp"] = int(dst_it.get("pp", 0)) + int(idata.get("pp", 0))

    @classmethod
    def _rollup_old_days(cls, daily_stats: dict[str, Any], cutoff_day_str: str) -> bool:
        """
        Rolls calendar days older than `cutoff_day_str` from per-day shards into
        `daily_stats["archive"]` so All-Time metrics stay exact without unbounded daily growth.
        """
        days_dict = daily_stats.setdefault("days", {})
        day_profiles_dict = daily_stats.setdefault("day_item_profiles", {})
        day_tx_map = daily_stats.setdefault("day_tx_counts", {})
        archive = daily_stats.get("archive")
        if not isinstance(archive, dict):
            archive = Storage.empty_daily_archive()
            daily_stats["archive"] = archive

        all_day_keys = set(days_dict.keys()) | set(day_profiles_dict.keys())
        old_days = sorted(d for d in all_day_keys if d < cutoff_day_str)
        if not old_days:
            return False

        archived_set = set(archive.get("archived_days") or [])
        arch_players = archive.setdefault("players", {})
        arch_profiles = archive.setdefault("item_profiles", {})
        arch_vwap = archive.setdefault("item_daily_vwap", {})
        arch_tx_count = int(archive.get("tx_count", 0) or 0)

        for d in old_days:
            d_players = days_dict.pop(d, {}) or {}
            d_profs = day_profiles_dict.pop(d, {}) or {}
            d_tx_stored = int(day_tx_map.pop(d, 0) or 0)

            if d in archived_set:
                continue

            cls._merge_player_records(arch_players, d_players)

            # Capture per-item daily VWAP for All-Time chronological sparklines
            day_item_totals: dict[str, list[float]] = {}
            for prec in d_players.values():
                if not isinstance(prec, dict):
                    continue
                for it_code, idata in ((prec.get("buy") or {}).get("by_item") or {}).items():
                    u = int(idata.get("units", 0) or 0)
                    m = float(idata.get("money", 0.0) or 0.0)
                    if u > 0:
                        acc = day_item_totals.setdefault(it_code, [0, 0.0])
                        acc[0] += u
                        acc[1] += m
            for it_code, (u_tot, m_tot) in day_item_totals.items():
                if u_tot > 0:
                    arch_vwap.setdefault(it_code, {})[d] = round(m_tot / u_tot, 3)

            d_prof_tx = 0
            for it_code, tiers_dict in d_profs.items():
                dst_it = arch_profiles.setdefault(it_code, {})
                for p_str, t_info in tiers_dict.items():
                    cnt = int(t_info.get("count", 1) or 0)
                    d_prof_tx += cnt
                    dst_tier = dst_it.setdefault(
                        p_str, {"units": 0, "money": 0.0, "count": 0}
                    )
                    dst_tier["units"] = int(dst_tier.get("units", 0)) + int(
                        t_info.get("units", 0) or 0
                    )
                    dst_tier["money"] = round(
                        float(dst_tier.get("money", 0.0))
                        + float(t_info.get("money", 0.0) or 0.0),
                        4,
                    )
                    dst_tier["count"] = int(dst_tier.get("count", 0)) + cnt

            arch_tx_count += d_prof_tx if d_prof_tx > 0 else d_tx_stored
            archived_set.add(d)

        sorted_archived = sorted(archived_set)
        archive["archived_days"] = sorted_archived
        archive["days_count"] = len(sorted_archived)
        archive["start_date"] = sorted_archived[0] if sorted_archived else None
        archive["end_date"] = sorted_archived[-1] if sorted_archived else None
        archive["tx_count"] = arch_tx_count
        daily_stats["_archive_dirty"] = True

        logger.info(
            f"Rolled up {len(old_days)} day(s) older than {cutoff_day_str} into All-Time archive "
            f"(archived total: {archive['days_count']} day(s))."
        )
        return True

    @staticmethod
    def get_trade_buyer_id(tx: dict[str, Any]) -> str | None:
        return (
            tx.get("buyerCountryId")
            or tx.get("buyerPartyId")
            or tx.get("buyerMuId")
            or tx.get("buyerId")
        )

    @staticmethod
    def get_trade_seller_id(tx: dict[str, Any]) -> str | None:
        return (
            tx.get("sellerCountryId")
            or tx.get("sellerPartyId")
            or tx.get("sellerMuId")
            or tx.get("sellerId")
        )

    def __init__(self, client: TRPCClient):
        self.client = client

    def sync_trades(
        self,
        existing_trades_cache: dict[str, Any] | None = None,
        existing_daily_stats: dict[str, Any] | None = None,
        max_lookback_hours: int = 24,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        cache = existing_trades_cache or {}
        last_tx_id = cache.get("last_tx_id")
        existing_raw_trades = cache.get("raw_trades", [])

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=max_lookback_hours)

        logger.info(
            f"Starting transaction sync (last_tx_id: {last_tx_id or 'NONE (cold start)'}, "
            f"lookback window: {max_lookback_hours}h)..."
        )

        new_trades: list[dict[str, Any]] = []
        cursor = None
        reached_end = False
        page_count = 0

        while not reached_end:
            payload: dict[str, Any] = {"limit": 100, "transactionType": "trading"}
            if cursor:
                payload["cursor"] = cursor

            res = self.client.call(
                "transaction.getPaginatedTransactions", payload, raise_on_error=False
            )
            page_count += 1
            if not isinstance(res, dict) or "result" not in res:
                break

            data = res.get("result", {}).get("data", {})
            items = data.get("items", [])
            if not items:
                break

            for tx in items:
                tx_id = tx.get("_id")
                if tx_id and tx_id == last_tx_id:
                    logger.info(
                        f"Encountered known last_tx_id '{last_tx_id}' at page {page_count}. Stopping sync."
                    )
                    reached_end = True
                    break

                created_str = tx.get("createdAt")
                if created_str:
                    try:
                        tx_time = datetime.fromisoformat(
                            created_str.replace("Z", "+00:00")
                        )
                        if not last_tx_id and tx_time < cutoff:
                            logger.info(
                                f"Reached {max_lookback_hours}h cutoff at page {page_count}. Stopping sync."
                            )
                            reached_end = True
                            break
                    except Exception:
                        pass

                new_trades.append(tx)

            cursor = data.get("nextCursor")
            if not cursor or reached_end:
                break

        logger.info(
            f"Fetched {len(new_trades)} new trading transactions across {page_count} pages."
        )

        new_last_tx_id = new_trades[0].get("_id") if new_trades else last_tx_id

        seen_tx_ids: set[str] = set()
        merged_raw_trades: list[dict[str, Any]] = []
        if not new_trades and existing_raw_trades:
            merged_raw_trades = list(existing_raw_trades)
        else:
            for tx in new_trades + existing_raw_trades:
                tid = tx.get("_id")
                if tid and tid not in seen_tx_ids:
                    seen_tx_ids.add(tid)
                    created_str = tx.get("createdAt")
                    if created_str:
                        try:
                            tx_time = datetime.fromisoformat(
                                created_str.replace("Z", "+00:00")
                            )
                            if tx_time >= cutoff:
                                merged_raw_trades.append(tx)
                        except Exception:
                            merged_raw_trades.append(tx)
                    else:
                        merged_raw_trades.append(tx)

        # Update daily_trader_stats
        daily_stats = existing_daily_stats or {
            "last_updated": int(now.timestamp()),
            "days": {},
            "day_item_profiles": {},
            "day_tx_counts": {},
            "archive": Storage.empty_daily_archive(),
        }
        daily_stats["last_updated"] = int(now.timestamp())
        days_dict = daily_stats.setdefault("days", {})
        day_profiles_dict = daily_stats.setdefault("day_item_profiles", {})
        dirty_days: set[str] = set()

        for tx in new_trades:
            created_str = tx.get("createdAt", "")
            day_key = (
                created_str[:10]
                if len(created_str) >= 10
                else now.strftime("%Y-%m-%d")
            )
            dirty_days.add(day_key)
            day_entry = days_dict.setdefault(day_key, {})

            buyer_id = self.get_trade_buyer_id(tx)
            seller_id = self.get_trade_seller_id(tx)
            item_code = tx.get("itemCode")
            qty = int(tx.get("quantity", 0))
            money = round(float(tx.get("money", 0.0)), 4)
            pp_rate = config.ALL_ITEMS_PP.get(item_code, 0)
            pp = qty * pp_rate if pp_rate else 0

            if item_code and qty > 0:
                unit_p_str = f"{round(money / qty, 3):.3f}"
                d_prof = day_profiles_dict.setdefault(day_key, {}).setdefault(
                    item_code, {}
                )
                p_tier = d_prof.setdefault(
                    unit_p_str, {"units": 0, "money": 0.0, "count": 0}
                )
                p_tier["units"] += qty
                p_tier["money"] = round(p_tier["money"] + money, 4)
                p_tier["count"] += 1

            if buyer_id:
                b_rec = day_entry.setdefault(
                    buyer_id,
                    {
                        "buy": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                        "sell": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                    },
                )
                b_rec["buy"]["money"] = round(b_rec["buy"]["money"] + money, 4)
                b_rec["buy"]["units"] += qty
                b_rec["buy"]["pp"] += pp
                if item_code:
                    item_b = b_rec["buy"]["by_item"].setdefault(
                        item_code, {"units": 0, "money": 0.0, "pp": 0}
                    )
                    item_b["units"] += qty
                    item_b["money"] = round(item_b["money"] + money, 4)
                    item_b["pp"] += pp

            if seller_id:
                s_rec = day_entry.setdefault(
                    seller_id,
                    {
                        "buy": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                        "sell": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                    },
                )
                s_rec["sell"]["money"] = round(s_rec["sell"]["money"] + money, 4)
                s_rec["sell"]["units"] += qty
                s_rec["sell"]["pp"] += pp
                if item_code:
                    item_s = s_rec["sell"]["by_item"].setdefault(
                        item_code, {"units": 0, "money": 0.0, "pp": 0}
                    )
                    item_s["units"] += qty
                    item_s["money"] = round(item_s["money"] + money, 4)
                    item_s["pp"] += pp

        cutoff_day_str = (
            now - timedelta(days=config.DAILY_STATS_RETENTION_DAYS)
        ).strftime("%Y-%m-%d")
        self._rollup_old_days(daily_stats, cutoff_day_str)
        daily_stats["_dirty_days"] = {d for d in dirty_days if d in days_dict}

        # Group 24h trades by itemCode
        all_target_items = list(config.ALL_MARKET_ITEMS.keys())
        item_trades_map = defaultdict(list)
        for tx in merged_raw_trades:
            icode = tx.get("itemCode")
            if icode:
                item_trades_map[icode].append(tx)

        top_buyers_by_item = {}
        top_sellers_by_item = {}
        active_top_entities: set[str] = set()
        item_buyer_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        item_seller_orders = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))

        for code in all_target_items:
            trades = item_trades_map.get(code, [])
            item_buyer_vols = defaultdict(int)
            item_buyer_money = defaultdict(float)
            item_seller_vols = defaultdict(int)
            item_seller_money = defaultdict(float)

            for t in trades:
                bid = self.get_trade_buyer_id(t)
                sid = self.get_trade_seller_id(t)
                qty = int(t.get("quantity", 0))
                mny = float(t.get("money", 0.0))
                unit_p = round(mny / qty, 3) if qty > 0 else 0.0

                if bid:
                    item_buyer_vols[bid] += qty
                    item_buyer_money[bid] += mny
                    if unit_p > 0:
                        item_buyer_orders[code][bid][unit_p] += qty
                if sid:
                    item_seller_vols[sid] += qty
                    item_seller_money[sid] += mny
                    if unit_p > 0:
                        item_seller_orders[code][sid][unit_p] += qty

            sorted_b = sorted(
                item_buyer_vols.items(), key=lambda kv: kv[1], reverse=True
            )[:3]
            sorted_s = sorted(
                item_seller_vols.items(), key=lambda kv: kv[1], reverse=True
            )[:3]
            top_buyers_by_item[code] = (sorted_b, item_buyer_money)
            top_sellers_by_item[code] = (sorted_s, item_seller_money)

            for bid, _ in sorted_b:
                active_top_entities.add(bid)
            for sid, _ in sorted_s:
                active_top_entities.add(sid)

            # Also resolve recent 15 trades participants
            for t in trades[:15]:
                t_bid = self.get_trade_buyer_id(t)
                t_sid = self.get_trade_seller_id(t)
                if t_bid:
                    active_top_entities.add(t_bid)
                if t_sid:
                    active_top_entities.add(t_sid)

        resolver = EntityResolver(self.client)
        resolver.resolve(active_top_entities)

        items_summary: dict[str, Any] = {}
        total_market_money = 0.0
        total_market_pp = 0
        total_market_units = 0

        for code in all_target_items:
            trades = item_trades_map.get(code, [])
            pp_per_unit = config.ALL_ITEMS_PP.get(code, 0)

            total_units = sum(int(t.get("quantity", 0)) for t in trades)
            total_money = round(sum(float(t.get("money", 0.0)) for t in trades), 3)
            total_pp = total_units * pp_per_unit if pp_per_unit else 0
            vwap = round(total_money / total_units, 3) if total_units > 0 else 0.0

            prices = [
                round(float(t.get("money", 0.0)) / int(t.get("quantity", 1)), 3)
                for t in trades
                if int(t.get("quantity", 0)) > 0
            ]
            min_price = round(min(prices), 3) if prices else 0.0
            max_price = round(max(prices), 3) if prices else 0.0

            total_market_money += total_money
            total_market_pp += total_pp
            total_market_units += total_units

            sorted_b, buyer_money_map = top_buyers_by_item[code]
            top_buyers = []
            for bid, vol in sorted_b:
                b_info = resolver.get_info(bid)
                b_orders = [
                    {"price": round(p, 3), "quantity": q}
                    for p, q in sorted(item_buyer_orders[code][bid].items())
                ]
                top_buyers.append(
                    {
                        **b_info,
                        "units": vol,
                        "money": round(buyer_money_map[bid], 2),
                        "share_pct": (
                            round(vol / total_units * 100, 1)
                            if total_units > 0
                            else 0.0
                        ),
                        "orders": b_orders,
                    }
                )

            sorted_s, seller_money_map = top_sellers_by_item[code]
            top_sellers = []
            for sid, vol in sorted_s:
                s_info = resolver.get_info(sid)
                s_orders = [
                    {"price": round(p, 3), "quantity": q}
                    for p, q in sorted(item_seller_orders[code][sid].items())
                ]
                top_sellers.append(
                    {
                        **s_info,
                        "units": vol,
                        "money": round(seller_money_map[sid], 2),
                        "share_pct": (
                            round(vol / total_units * 100, 1)
                            if total_units > 0
                            else 0.0
                        ),
                        "orders": s_orders,
                    }
                )

            # Volume Profile (POC)
            profile_map = defaultdict(lambda: {"units": 0, "money": 0.0, "count": 0})
            for t in trades:
                qty = int(t.get("quantity", 0))
                mny = float(t.get("money", 0.0))
                if qty > 0:
                    unit_p = round(mny / qty, 3)
                    entry = profile_map[unit_p]
                    entry["units"] += qty
                    entry["money"] = round(entry["money"] + mny, 3)
                    entry["count"] += 1

            price_profile = []
            max_volume_level = 0
            poc_price = 0.0

            for p in sorted(profile_map.keys()):
                d = profile_map[p]
                units = d["units"]
                money = round(d["money"], 2)
                pp = units * pp_per_unit if pp_per_unit else 0
                share = (
                    round((units / total_units * 100), 1) if total_units > 0 else 0.0
                )
                if units > max_volume_level:
                    max_volume_level = units
                    poc_price = p

                price_profile.append(
                    {
                        "price": round(p, 3),
                        "units": units,
                        "pp": pp,
                        "money": money,
                        "share_pct": share,
                        "trades_count": d["count"],
                    }
                )

            recent_trades = []
            for t in trades[:15]:
                qty = int(t.get("quantity", 0))
                mny = round(float(t.get("money", 0.0)), 2)
                unit_p = round(mny / qty, 3) if qty > 0 else 0.0
                recent_trades.append(
                    {
                        "id": t.get("_id", ""),
                        "time": t.get("createdAt", ""),
                        "price": unit_p,
                        "quantity": qty,
                        "money": mny,
                        "buyer": resolver.get_info(self.get_trade_buyer_id(t) or ""),
                        "seller": resolver.get_info(self.get_trade_seller_id(t) or ""),
                    }
                )

            # Build 24h intraday sparkline (up to 20 chronological buckets)
            spark_24h = []
            if trades:
                chron_trades = list(reversed(trades))
                bucket_size = max(1, len(chron_trades) // 20)
                for i in range(0, len(chron_trades), bucket_size):
                    chunk = chron_trades[i : i + bucket_size]
                    c_u = sum(int(x.get("quantity", 0)) for x in chunk)
                    c_m = sum(float(x.get("money", 0.0)) for x in chunk)
                    if c_u > 0:
                        spark_24h.append(round(c_m / c_u, 3))
            if len(spark_24h) < 2 and vwap > 0:
                spark_24h = [vwap, vwap]

            items_summary[code] = {
                "total_units": total_units,
                "pp_per_unit": pp_per_unit,
                "total_pp": total_pp,
                "total_money": total_money,
                "vwap": vwap,
                "min_price": min_price,
                "max_price": max_price,
                "tx_count": len(trades),
                "top_buyers": top_buyers,
                "top_sellers": top_sellers,
                "price_profile": price_profile,
                "poc_price": round(poc_price, 3),
                "sparkline_vwap": spark_24h,
                "recent_trades": recent_trades,
            }

        day_tx_map = daily_stats.setdefault("day_tx_counts", {})
        # Accurately compute transaction counts for each calendar day from day_item_profiles
        for d, it_profiles in day_profiles_dict.items():
            profile_tx_count = sum(
                int(t.get("count", 1))
                for tiers in it_profiles.values()
                for t in tiers.values()
            )
            day_tx_map[d] = profile_tx_count

        # Use latest recorded day as reference when offline so 7d/30d windows remain anchored
        ref_dt = now
        if not new_trades and days_dict:
            latest_day_key = max(days_dict.keys())
            try:
                ref_dt = datetime.fromisoformat(f"{latest_day_key}T23:59:59+00:00")
            except Exception:
                ref_dt = now

        archive = daily_stats.get("archive") or {}
        archive_days_count = int(archive.get("days_count", 0) or 0)

        periods_config = {"24h": 1, "7d": 7, "30d": 30, "all": 0}
        periods_summary = {}

        for p_key, days_count in periods_config.items():
            if p_key == "24h":
                periods_summary["24h"] = {
                    "total_market_money": round(total_market_money, 2),
                    "total_market_pp": total_market_pp,
                    "total_market_units": total_market_units,
                    "total_market_tx": len(merged_raw_trades),
                    "days_count": 1,
                    "target_days": 1,
                    "start_date": now.strftime("%Y-%m-%d"),
                    "end_date": now.strftime("%Y-%m-%d"),
                    "is_partial": False,
                    "items": items_summary,
                }
            else:
                if p_key == "all":
                    matching_days = sorted(days_dict.keys())
                else:
                    p_cutoff_day = (ref_dt - timedelta(days=days_count)).strftime("%Y-%m-%d")
                    matching_days = sorted([d for d in days_dict.keys() if d >= p_cutoff_day])
                include_archive = p_key == "all" and archive_days_count > 0

                p_item_stats = defaultdict(
                    lambda: {"units": 0, "money": 0.0, "pp": 0}
                )
                p_buyer_stats = defaultdict(
                    lambda: defaultdict(lambda: {"units": 0, "money": 0.0})
                )
                p_seller_stats = defaultdict(
                    lambda: defaultdict(lambda: {"units": 0, "money": 0.0})
                )
                p_profile_map = defaultdict(
                    lambda: defaultdict(lambda: {"units": 0, "money": 0.0, "count": 0})
                )
                p_day_series = defaultdict(
                    lambda: defaultdict(lambda: {"units": 0, "money": 0.0})
                )
                p_market_money = 0.0
                p_market_pp = 0
                p_market_units = 0
                p_market_tx = sum(day_tx_map.get(d, 0) for d in matching_days)
                if include_archive:
                    p_market_tx += int(archive.get("tx_count", 0) or 0)
                if p_market_tx < len(merged_raw_trades):
                    p_market_tx = max(p_market_tx, len(merged_raw_trades))

                p_item_prices = defaultdict(list)

                def _merge_profiles_block(profs_map: dict[str, Any], record_prices: bool = False) -> None:
                    for it_code, tiers_dict in profs_map.items():
                        for p_str, t_info in tiers_dict.items():
                            try:
                                p_val = round(float(p_str), 3)
                            except Exception:
                                continue
                            u_tier = int(t_info.get("units", 0))
                            entry = p_profile_map[it_code][p_val]
                            entry["units"] += u_tier
                            entry["money"] = round(entry["money"] + float(t_info.get("money", 0.0)), 3)
                            entry["count"] += int(t_info.get("count", 1))
                            if record_prices and u_tier > 0 and p_val > 0:
                                p_item_prices[it_code].append(p_val)

                def _merge_players_block(
                    players_map: dict[str, Any],
                    day_key_for_series: str | None = None,
                    known_prof_items: set[str] | None = None,
                ) -> None:
                    nonlocal p_market_units, p_market_money, p_market_pp
                    for pid, prec in players_map.items():
                        b_rec = prec.get("buy", {})
                        for it, idata in b_rec.get("by_item", {}).items():
                            u = int(idata.get("units", 0))
                            m = float(idata.get("money", 0.0))
                            pp = int(idata.get("pp", 0))
                            p_item_stats[it]["units"] += u
                            p_item_stats[it]["money"] += m
                            p_item_stats[it]["pp"] += pp
                            p_buyer_stats[it][pid]["units"] += u
                            p_buyer_stats[it][pid]["money"] += m
                            if day_key_for_series is not None:
                                p_day_series[it][day_key_for_series]["units"] += u
                                p_day_series[it][day_key_for_series]["money"] += m
                            p_market_units += u
                            p_market_money += m
                            p_market_pp += pp
                            if u > 0 and m > 0:
                                unit_p = round(m / u, 3)
                                p_item_prices[it].append(unit_p)
                                if known_prof_items is not None and it not in known_prof_items:
                                    entry = p_profile_map[it][unit_p]
                                    entry["units"] += u
                                    entry["money"] = round(entry["money"] + m, 3)
                                    entry["count"] += 1

                        s_rec = prec.get("sell", {})
                        for it, idata in s_rec.get("by_item", {}).items():
                            u = int(idata.get("units", 0))
                            m = float(idata.get("money", 0.0))
                            p_seller_stats[it][pid]["units"] += u
                            p_seller_stats[it][pid]["money"] += m
                            if u > 0 and m > 0:
                                p_item_prices[it].append(round(m / u, 3))

                if include_archive:
                    arch_profs = archive.get("item_profiles") or {}
                    _merge_profiles_block(arch_profs, record_prices=True)
                    _merge_players_block(
                        archive.get("players") or {},
                        day_key_for_series=None,
                        known_prof_items=set(arch_profs.keys()),
                    )

                for day in matching_days:
                    d_players = days_dict.get(day, {})
                    d_prof_for_day = day_profiles_dict.get(day, {})
                    _merge_profiles_block(d_prof_for_day)
                    _merge_players_block(
                        d_players,
                        day_key_for_series=day,
                        known_prof_items=set(d_prof_for_day.keys()),
                    )

                # Collect top-3 buyers/sellers across all items for this period to resolve metadata
                period_top_buyers_raw = {}
                period_top_sellers_raw = {}
                extra_entities: set[str] = set()
                for code in all_target_items:
                    sb = sorted(
                        p_buyer_stats[code].items(),
                        key=lambda kv: (kv[1]["units"], kv[1]["money"]),
                        reverse=True,
                    )[:3]
                    ss = sorted(
                        p_seller_stats[code].items(),
                        key=lambda kv: (kv[1]["units"], kv[1]["money"]),
                        reverse=True,
                    )[:3]
                    period_top_buyers_raw[code] = sb
                    period_top_sellers_raw[code] = ss
                    for bid, _ in sb:
                        extra_entities.add(bid)
                    for sid, _ in ss:
                        extra_entities.add(sid)

                if extra_entities - active_top_entities:
                    resolver.resolve(extra_entities - active_top_entities)
                    active_top_entities.update(extra_entities)

                p_items_formatted = {}
                for code in all_target_items:
                    it_s = p_item_stats[code]
                    u = it_s["units"]
                    m = round(it_s["money"], 2)
                    pp = it_s["pp"]
                    pp_per_unit = config.ALL_ITEMS_PP.get(code, 0)
                    vwap = round(m / u, 3) if u > 0 else 0.0
                    base_item = items_summary.get(code, {})
                    base_u = base_item.get("total_units", 0)
                    base_tx = base_item.get("tx_count", 0)

                    # Build real Volume Profile & POC for this period
                    p_profile = []
                    p_poc_price = 0.0
                    max_vol_lvl = 0
                    raw_prof_for_code = p_profile_map.get(code, {})
                    if raw_prof_for_code and u > 0:
                        for p_val in sorted(raw_prof_for_code.keys()):
                            d_lvl = raw_prof_for_code[p_val]
                            lvl_u = int(d_lvl["units"])
                            lvl_m = round(float(d_lvl["money"]), 2)
                            lvl_pp = lvl_u * pp_per_unit if pp_per_unit else 0
                            lvl_share = round((lvl_u / u) * 100, 1) if u > 0 else 0.0
                            if lvl_u > max_vol_lvl:
                                max_vol_lvl = lvl_u
                                p_poc_price = p_val
                            p_profile.append(
                                {
                                    "price": round(p_val, 3),
                                    "units": lvl_u,
                                    "pp": lvl_pp,
                                    "money": lvl_m,
                                    "share_pct": lvl_share,
                                    "trades_count": int(d_lvl["count"]),
                                }
                            )
                    else:
                        p_profile = base_item.get("price_profile", [])
                        p_poc_price = base_item.get("poc_price", 0.0)

                    est_tx = max(
                        base_tx, sum(lvl.get("trades_count", 0) for lvl in p_profile)
                    )

                    prices_list = p_item_prices.get(code, [])
                    if prices_list:
                        min_p = round(min(prices_list), 3)
                        max_p = round(max(prices_list), 3)
                    else:
                        min_p = base_item.get("min_price", 0.0)
                        max_p = base_item.get("max_price", 0.0)

                    # Build period-specific chronological VWAP sparkline
                    p_spark = []
                    if include_archive:
                        arch_item_vwap = (archive.get("item_daily_vwap") or {}).get(code) or {}
                        for d_key in sorted(arch_item_vwap.keys()):
                            val = float(arch_item_vwap[d_key] or 0.0)
                            if val > 0:
                                p_spark.append(round(val, 3))
                    for d_key in matching_days:
                        ds = p_day_series[code].get(d_key)
                        if ds and ds["units"] > 0:
                            p_spark.append(round(ds["money"] / ds["units"], 3))
                    if len(p_spark) < 2:
                        p_spark = base_item.get("sparkline_vwap", [vwap, vwap])

                    # Build period-specific Top-3 Buyers & Top-3 Sellers
                    p_top_buyers = []
                    for bid, bstat in period_top_buyers_raw.get(code, []):
                        b_vol = int(bstat["units"])
                        b_mny = float(bstat["money"])
                        b_info = resolver.get_info(bid)
                        merged_orders = dict(item_buyer_orders[code].get(bid, {}))
                        sum_24h_q = sum(merged_orders.values())
                        sum_24h_m = sum(p * q for p, q in merged_orders.items())
                        rem_q = b_vol - sum_24h_q
                        rem_m = b_mny - sum_24h_m
                        if rem_q > 0:
                            rem_p = round(rem_m / rem_q, 3) if rem_m > 0 else vwap
                            if rem_p > 0:
                                merged_orders[rem_p] = merged_orders.get(rem_p, 0) + rem_q
                        b_orders = [
                            {"price": round(p, 3), "quantity": q}
                            for p, q in sorted(merged_orders.items())
                        ]
                        p_top_buyers.append(
                            {
                                **b_info,
                                "units": b_vol,
                                "money": round(b_mny, 2),
                                "share_pct": round(b_vol / u * 100, 1) if u > 0 else 0.0,
                                "orders": b_orders,
                            }
                        )

                    p_top_sellers = []
                    for sid, sstat in period_top_sellers_raw.get(code, []):
                        s_vol = int(sstat["units"])
                        s_mny = float(sstat["money"])
                        s_info = resolver.get_info(sid)
                        merged_orders = dict(item_seller_orders[code].get(sid, {}))
                        sum_24h_q = sum(merged_orders.values())
                        sum_24h_m = sum(p * q for p, q in merged_orders.items())
                        rem_q = s_vol - sum_24h_q
                        rem_m = s_mny - sum_24h_m
                        if rem_q > 0:
                            rem_p = round(rem_m / rem_q, 3) if rem_m > 0 else vwap
                            if rem_p > 0:
                                merged_orders[rem_p] = merged_orders.get(rem_p, 0) + rem_q
                        s_orders = [
                            {"price": round(p, 3), "quantity": q}
                            for p, q in sorted(merged_orders.items())
                        ]
                        p_top_sellers.append(
                            {
                                **s_info,
                                "units": s_vol,
                                "money": round(s_mny, 2),
                                "share_pct": round(s_vol / u * 100, 1) if u > 0 else 0.0,
                                "orders": s_orders,
                            }
                        )

                    p_items_formatted[code] = {
                        "total_units": u,
                        "total_pp": pp,
                        "total_money": m,
                        "vwap": vwap,
                        "tx_count": est_tx,
                        "min_price": min_p,
                        "max_price": max_p,
                        "top_buyers": p_top_buyers,
                        "top_sellers": p_top_sellers,
                        "price_profile": p_profile,
                        "poc_price": round(p_poc_price, 3),
                        "sparkline_vwap": p_spark,
                        "recent_trades": base_item.get("recent_trades", []),
                    }

                actual_cnt = len(matching_days) + (archive_days_count if include_archive else 0)
                target = actual_cnt if p_key == "all" else days_count
                start_candidates = [
                    d
                    for d in (
                        archive.get("start_date") if include_archive else None,
                        matching_days[0] if matching_days else None,
                    )
                    if d
                ]
                end_candidates = [
                    d
                    for d in (
                        archive.get("end_date") if include_archive else None,
                        matching_days[-1] if matching_days else None,
                    )
                    if d
                ]
                periods_summary[p_key] = {
                    "total_market_money": round(p_market_money, 2),
                    "total_market_pp": p_market_pp,
                    "total_market_units": p_market_units,
                    "total_market_tx": p_market_tx,
                    "days_count": actual_cnt,
                    "target_days": target,
                    "start_date": min(start_candidates) if start_candidates else now.strftime("%Y-%m-%d"),
                    "end_date": max(end_candidates) if end_candidates else now.strftime("%Y-%m-%d"),
                    "is_partial": actual_cnt < target if p_key not in ("24h", "all") else False,
                    "items": p_items_formatted,
                }

        latest_market_trades = {
            "timestamp": int(now.timestamp()),
            "last_tx_id": new_last_tx_id,
            "window_seconds": max_lookback_hours * 3600,
            "summary": {
                "total_market_money": round(total_market_money, 2),
                "total_market_pp": total_market_pp,
                "total_market_units": total_market_units,
                "total_market_tx": len(merged_raw_trades),
            },
            "items": items_summary,
            "periods": periods_summary,
            "raw_trades": merged_raw_trades,
        }

        return latest_market_trades, daily_stats

    @staticmethod
    def append_trades_history(
        history: dict[str, Any],
        trades_snapshot: dict[str, Any],
        timestamp: int | None = None,
    ) -> dict[str, Any]:
        ts = timestamp or int(datetime.now(timezone.utc).timestamp())
        labels = history.get("labels", [])
        items = history.get("items", {})
        labels.append(ts)

        items_snapshot = trades_snapshot.get("items", {})
        for item_code in config.ALL_MARKET_ITEMS:
            item_hist = items.setdefault(
                item_code,
                {
                    "hourly_units": [],
                    "hourly_pp": [],
                    "hourly_money": [],
                    "hourly_vwap": [],
                    "hourly_tx": [],
                },
            )
            item_data = items_snapshot.get(item_code, {})

            item_hist["hourly_units"].append(item_data.get("total_units", 0))
            item_hist["hourly_pp"].append(item_data.get("total_pp", 0))
            item_hist["hourly_money"].append(item_data.get("total_money", 0.0))
            item_hist["hourly_vwap"].append(item_data.get("vwap", 0.0))
            item_hist["hourly_tx"].append(item_data.get("tx_count", 0))

            if len(item_hist["hourly_units"]) > config.MAX_HISTORY_POINTS:
                for k in (
                    "hourly_units",
                    "hourly_pp",
                    "hourly_money",
                    "hourly_vwap",
                    "hourly_tx",
                ):
                    item_hist[k] = item_hist[k][-config.MAX_HISTORY_POINTS :]

        if len(labels) > config.MAX_HISTORY_POINTS:
            labels = labels[-config.MAX_HISTORY_POINTS :]

        return {"labels": labels, "items": items}

