from datetime import datetime, timezone
import json
import logging
import os
from typing import Any

from src import config

logger = logging.getLogger(__name__)


class Storage:
    """
    Manages reading/writing internal cumulative JSON data in `data_store/`
    and exporting optimized, lightweight JSON slices to `public/data/`.
    """

    @staticmethod
    def _ensure_dirs() -> None:
        os.makedirs(config.DATA_STORE_DIR, exist_ok=True)
        os.makedirs(config.PUBLIC_DATA_DIR, exist_ok=True)

    @staticmethod
    def _read_json(path: str, default: Any = None) -> Any:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {path}: {e}")
        return default

    @staticmethod
    def _write_json(path: str, data: Any, compact: bool = False) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            if compact:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)

    # =========================================================================
    # 1. PROFITABILITY STORAGE
    # =========================================================================

    @staticmethod
    def save_latest_profitability(snapshot: dict[str, Any]) -> None:
        payload = {
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "data": snapshot,
        }
        Storage._write_json(config.LATEST_PROFITABILITY_FILE, payload)

    @staticmethod
    def load_latest_profitability() -> tuple[dict[str, Any] | None, int | None]:
        raw = Storage._read_json(config.LATEST_PROFITABILITY_FILE)
        if isinstance(raw, dict) and "data" in raw:
            return raw["data"], raw.get("timestamp")
        return None, None

    @staticmethod
    def load_profitability_history() -> dict[str, Any]:
        raw = Storage._read_json(config.HISTORY_PROFITABILITY_FILE)
        if isinstance(raw, dict) and "labels" in raw and "items" in raw:
            return raw
        return {
            "labels": [],
            "items": {
                item: {"min_pp": [], "max_pp": [], "bid": [], "ask": []}
                for item in config.ITEM_PRETTY_NAMES
            },
        }

    @staticmethod
    def append_profitability_snapshot(
        history: dict[str, Any], snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        history["labels"].append(now_ts)
        current_len = len(history["labels"])

        for item in config.ITEM_PRETTY_NAMES:
            if item not in history["items"]:
                history["items"][item] = {
                    "min_pp": [None] * (current_len - 1),
                    "max_pp": [None] * (current_len - 1),
                    "bid": [None] * (current_len - 1),
                    "ask": [None] * (current_len - 1),
                }
            item_hist = history["items"][item]
            metrics = snapshot.get(item)
            for k in ("min_pp", "max_pp", "bid", "ask"):
                if k not in item_hist:
                    item_hist[k] = [None] * (current_len - 1)
                val = metrics.get(k) if metrics else None
                item_hist[k].append(val)

        # Trim to MAX_HISTORY_POINTS
        if len(history["labels"]) > config.MAX_HISTORY_POINTS:
            history["labels"] = history["labels"][-config.MAX_HISTORY_POINTS :]
            for item_data in history["items"].values():
                for k in item_data:
                    if isinstance(item_data[k], list):
                        item_data[k] = item_data[k][-config.MAX_HISTORY_POINTS :]

        return history

    @staticmethod
    def save_profitability_history(history: dict[str, Any]) -> None:
        Storage._write_json(config.HISTORY_PROFITABILITY_FILE, history)

    # =========================================================================
    # 2. ORDER BOOK (MARKET DEPTH) STORAGE
    # =========================================================================

    @staticmethod
    def save_latest_orderbook(snapshot: dict[str, Any]) -> None:
        payload = {
            "timestamp": int(datetime.now(timezone.utc).timestamp()),
            "data": snapshot,
        }
        Storage._write_json(config.LATEST_ORDERBOOK_FILE, payload)

    @staticmethod
    def load_latest_orderbook() -> tuple[dict[str, Any] | None, int | None]:
        raw = Storage._read_json(config.LATEST_ORDERBOOK_FILE)
        if isinstance(raw, dict) and "data" in raw:
            return raw["data"], raw.get("timestamp")
        return None, None

    @staticmethod
    def compute_75_depth_money(
        ladder: list[dict[str, Any]], best_price: float, is_buy: bool
    ) -> float:
        """
        Computes cumulative ₿ (Received for Buy book / Total Cost for Sell book)
        across regular price tiers until cumulative quantity crosses >= 85%
        of regular book units (Demand Cleared / Market Share >= 85%).
        The tier that crosses the 85% threshold is included in full.
        """
        if not ladder:
            return 0.0
        threshold_price = (
            (best_price * 0.5 if is_buy else best_price * 2.0)
            if best_price > 0
            else 0.0
        )
        normal_tiers: list[tuple[int, float]] = []
        for row in ladder:
            p = float(row.get("p", row.get("price", 0.0)))
            q = int(row.get("q", row.get("quantity", 0)))
            if best_price > 0:
                if is_buy and p < threshold_price - 1e-9:
                    continue
                if not is_buy and p >= threshold_price - 1e-9:
                    continue
            m = float(row.get("m", p * q))
            normal_tiers.append((q, m))

        reg_total_units = sum(q for q, _ in normal_tiers)
        if reg_total_units <= 0:
            return 0.0

        target_units = reg_total_units * 0.75
        cum_qty = 0
        cum_money = 0.0
        for q, m in normal_tiers:
            cum_qty += q
            cum_money += m
            if cum_qty >= target_units - 1e-9:
                break
        return round(cum_money, 2)

    @staticmethod
    def load_orderbook_history() -> dict[str, Any]:
        raw = Storage._read_json(config.HISTORY_ORDERBOOK_FILE)
        if isinstance(raw, dict) and "labels" in raw and "items" in raw:
            return raw
        return {
            "labels": [],
            "items": {
                item: {
                    "liquidity_pct": [],
                    "buy_money_btc": [],
                    "sell_supply": [],
                    "total_units": [],
                    "total_pp": [],
                    "buy_total_units": [],
                    "buy_total_pp": [],
                    "sell_value_btc": [],
                }
                for item in config.ALL_MARKET_ITEMS
            },
        }

    @staticmethod
    def append_orderbook_snapshot(
        history: dict[str, Any], snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        history["labels"].append(now_ts)
        prev_len = len(history["labels"]) - 1

        metrics_keys = (
            "liquidity_pct",
            "buy_money_btc",
            "sell_supply",
            "total_units",
            "total_pp",
            "buy_total_units",
            "buy_total_pp",
            "sell_value_btc",
        )

        for item in config.ALL_MARKET_ITEMS:
            if item not in history["items"]:
                history["items"][item] = {k: [0] * prev_len for k in metrics_keys}

            item_hist = history["items"][item]
            for k in metrics_keys:
                if k not in item_hist:
                    item_hist[k] = [0] * prev_len
                while len(item_hist[k]) < prev_len:
                    item_hist[k].insert(0, 0)

            it_snap = snapshot.get(item, {})
            sell_block = it_snap.get("sell", it_snap)
            buy_block = it_snap.get("buy", it_snap.get("buy_depth", {}))

            s_ladder = sell_block.get("ladder", it_snap.get("ladder", []))
            b_ladder = buy_block.get("ladder", [])
            best_bid = float(b_ladder[0].get("p", b_ladder[0].get("price", 0.0))) if b_ladder else 0.0
            best_ask = float(s_ladder[0].get("p", s_ladder[0].get("price", 0.0))) if s_ladder else 0.0
            s_ask_limit = (best_ask * 2.0) if best_ask > 0 else 0.0
            b_bid_limit = (best_bid * 0.5) if best_bid > 0 else 0.0

            pp_rate = config.ALL_ITEMS_PP.get(item, 0)
            s_units = int(sell_block.get("total_units", it_snap.get("total_units", 0)))
            s_pp = int(sell_block.get("total_pp", it_snap.get("total_pp", s_units * pp_rate)))
            s_btc = float(sell_block.get("total_value_btc", 0.0))
            if not s_btc and s_ladder:
                s_btc = round(
                    sum(
                        float(r.get("price", r.get("p", 0))) * int(r.get("quantity", r.get("q", 0)))
                        for r in s_ladder
                        if not (s_ask_limit > 0 and float(r.get("price", r.get("p", 0))) >= s_ask_limit - 1e-9)
                    ),
                    2,
                )

            b_units = int(buy_block.get("total_units", it_snap.get("buy_total_units", 0)))
            b_pp = int(buy_block.get("total_pp", it_snap.get("buy_total_pp", b_units * pp_rate)))
            b_btc = float(
                buy_block.get(
                    "total_money_btc",
                    buy_block.get("total_money_invested", it_snap.get("buy_total_money", 0.0)),
                )
            )
            if not b_btc and b_ladder:
                b_btc = round(
                    sum(
                        float(r.get("price", r.get("p", 0))) * int(r.get("quantity", r.get("q", 0)))
                        for r in b_ladder
                        if not (b_bid_limit > 0 and float(r.get("price", r.get("p", 0))) < b_bid_limit - 1e-9)
                    ),
                    2,
                )
            buy_75 = Storage.compute_75_depth_money(b_ladder, best_bid, is_buy=True)
            sell_75 = Storage.compute_75_depth_money(s_ladder, best_ask, is_buy=False)
            total_75 = buy_75 + sell_75
            liq_pct = round((buy_75 / total_75) * 100, 1) if total_75 > 0 else 50.0
            sell_supply = s_pp if pp_rate > 0 else s_units

            item_hist["liquidity_pct"].append(liq_pct)
            item_hist["buy_money_btc"].append(round(b_btc, 2))
            item_hist["sell_supply"].append(sell_supply)
            item_hist["total_units"].append(s_units)
            item_hist["total_pp"].append(s_pp)
            item_hist["buy_total_units"].append(b_units)
            item_hist["buy_total_pp"].append(b_pp)
            item_hist["sell_value_btc"].append(round(s_btc, 2))

        if len(history["labels"]) > config.MAX_HISTORY_POINTS:
            history["labels"] = history["labels"][-config.MAX_HISTORY_POINTS :]
            for item_data in history["items"].values():
                for k in item_data:
                    if isinstance(item_data[k], list):
                        item_data[k] = item_data[k][-config.MAX_HISTORY_POINTS :]

        return history

    @staticmethod
    def save_orderbook_history(history: dict[str, Any]) -> None:
        Storage._write_json(config.HISTORY_ORDERBOOK_FILE, history)

    # =========================================================================
    # 3. TRADES, DAILY STATS, LEADERBOARDS & PLAYERS CACHE
    # =========================================================================

    @staticmethod
    def load_latest_trades() -> tuple[dict[str, Any] | None, int | None]:
        raw = Storage._read_json(config.LATEST_TRADES_FILE)
        if isinstance(raw, dict):
            return raw, raw.get("timestamp")
        return None, None

    @staticmethod
    def save_latest_trades(data: dict[str, Any]) -> None:
        if "timestamp" not in data:
            data["timestamp"] = int(datetime.now(timezone.utc).timestamp())
        Storage._write_json(config.LATEST_TRADES_FILE, data)

    @staticmethod
    def load_trades_history() -> dict[str, Any]:
        raw = Storage._read_json(config.HISTORY_TRADES_FILE)
        if isinstance(raw, dict) and "labels" in raw and "items" in raw:
            return raw
        return {
            "labels": [],
            "items": {
                item: {
                    "hourly_units": [],
                    "hourly_pp": [],
                    "hourly_money": [],
                    "hourly_vwap": [],
                    "hourly_tx": [],
                }
                for item in config.ALL_MARKET_ITEMS
            },
        }

    @staticmethod
    def save_trades_history(history: dict[str, Any]) -> None:
        Storage._write_json(config.HISTORY_TRADES_FILE, history)

    @staticmethod
    def load_daily_trader_stats() -> dict[str, Any]:
        raw = Storage._read_json(config.DAILY_TRADER_STATS_FILE)
        if isinstance(raw, dict) and "days" in raw:
            return raw
        return {"last_updated": 0, "days": {}}

    @staticmethod
    def save_daily_trader_stats(stats: dict[str, Any]) -> None:
        Storage._write_json(config.DAILY_TRADER_STATS_FILE, stats)

    @staticmethod
    def load_market_leaderboards() -> dict[str, Any] | None:
        return Storage._read_json(config.MARKET_LEADERBOARDS_FILE)

    @staticmethod
    def save_market_leaderboards(leaderboards: dict[str, Any]) -> None:
        Storage._write_json(config.MARKET_LEADERBOARDS_FILE, leaderboards)

    @staticmethod
    def load_known_players() -> dict[str, dict[str, Any]]:
        raw = Storage._read_json(config.KNOWN_PLAYERS_FILE)
        if isinstance(raw, dict) and "players" in raw:
            players_data = raw["players"]
            if isinstance(players_data, list):
                return {
                    uid: {"id": uid, "name": f"Player_{uid[:6]}", "type": "user"}
                    for uid in players_data
                    if isinstance(uid, str)
                }
            if isinstance(players_data, dict):
                return players_data
        return {}

    @staticmethod
    def save_known_players(players: dict[str, dict[str, Any]]) -> None:
        payload = {
            "updated_at": int(datetime.now(timezone.utc).timestamp()),
            "count": len(players),
            "players": dict(sorted(players.items())),
        }
        Storage._write_json(config.KNOWN_PLAYERS_FILE, payload)

    @staticmethod
    def load_player_meta_cache() -> dict[str, dict[str, Any]]:
        raw = Storage._read_json(config.PLAYER_META_CACHE_FILE)
        if isinstance(raw, dict) and "entities" in raw:
            return raw["entities"]
        return {}

    @staticmethod
    def save_player_meta_cache(entities: dict[str, dict[str, Any]]) -> None:
        payload = {
            "updated_at": int(datetime.now(timezone.utc).timestamp()),
            "count": len(entities),
            "entities": entities,
        }
        Storage._write_json(config.PLAYER_META_CACHE_FILE, payload)

    # =========================================================================
    # 4. FRONTEND STATIC DATA SLICES BUILDER (public/data/*.json)
    # =========================================================================

    @staticmethod
    def _normalize_orderbook_item(
        item_code: str, raw_item: dict[str, Any], sparkline_7d: dict[str, list[float]]
    ) -> dict[str, Any]:
        """
        Ensures unified order book schema whether loaded from new OrderBookAnalyzer
        or legacy latest_market_depth.json.
        """
        pp_per_unit = config.ALL_ITEMS_PP.get(item_code, 0)

        # Extract Sell block
        sell_src = raw_item.get("sell", raw_item)
        raw_sell_ladder = sell_src.get("ladder", [])
        sell_ladder = []
        for row in raw_sell_ladder:
            p = round(float(row.get("p", row.get("price", 0.0))), 3)
            q = int(row.get("q", row.get("quantity", 0)))
            m = round(p * q, 2)
            sell_ladder.append({"p": p, "q": q, "m": m})

        # Extract Buy block
        buy_src = raw_item.get("buy", raw_item.get("buy_depth", {}))
        raw_buy_ladder = buy_src.get("ladder", [])
        buy_ladder = []
        for row in raw_buy_ladder:
            p = round(float(row.get("p", row.get("price", 0.0))), 3)
            q = int(row.get("q", row.get("quantity", 0)))
            m = round(p * q, 2)
            buy_ladder.append({"p": p, "q": q, "m": m})

        best_bid = buy_ladder[0]["p"] if buy_ladder else 0.0
        best_ask = sell_ladder[0]["p"] if sell_ladder else 0.0

        # Outlier thresholds: 2x+ for ask, 2x- for bid
        s_ask_limit = (best_ask * 2.0) if best_ask > 0 else 0.0
        b_bid_limit = (best_bid * 0.5) if best_bid > 0 else 0.0

        reg_sell_units = int(
            sell_src.get(
                "total_units",
                sum(
                    r["q"]
                    for r in sell_ladder
                    if not (s_ask_limit > 0 and r["p"] >= s_ask_limit - 1e-9)
                ),
            )
        )
        sell_pp = int(sell_src.get("total_pp", reg_sell_units * pp_per_unit))
        reg_sell_btc = round(
            float(
                sell_src.get(
                    "total_value_btc",
                    sum(
                        r["m"]
                        for r in sell_ladder
                        if not (s_ask_limit > 0 and r["p"] >= s_ask_limit - 1e-9)
                    ),
                )
            ),
            2,
        )

        sell_top = sell_src.get("top_sellers", [])
        sell_top3_share = round(
            sum(float(s.get("share_pct", 0.0)) for s in sell_top[:3]), 1
        )

        reg_buy_units = int(
            buy_src.get(
                "total_units",
                sum(
                    r["q"]
                    for r in buy_ladder
                    if not (b_bid_limit > 0 and r["p"] < b_bid_limit - 1e-9)
                ),
            )
        )
        buy_pp = int(buy_src.get("total_pp", reg_buy_units * pp_per_unit))
        reg_buy_money = round(
            float(
                buy_src.get(
                    "total_money_btc",
                    buy_src.get(
                        "total_money_invested",
                        sum(
                            r["m"]
                            for r in buy_ladder
                            if not (b_bid_limit > 0 and r["p"] < b_bid_limit - 1e-9)
                        ),
                    ),
                )
            ),
            2,
        )
        buy_top = buy_src.get("top_buyers", [])
        buy_top3_share = round(
            sum(float(b.get("share_pct", 0.0)) for b in buy_top[:3]), 1
        )

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

        return {
            "pp_per_unit": pp_per_unit,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "spread_btc": spread_btc,
            "spread_pct": spread_pct,
            "buy": {
                "total_units": reg_buy_units,
                "total_pp": buy_pp,
                "total_money_btc": reg_buy_money,
                "top3_share_pct": buy_top3_share,
                "top_buyers": buy_top[:3],
                "ladder": buy_ladder,
            },
            "sell": {
                "total_units": reg_sell_units,
                "total_pp": sell_pp,
                "total_value_btc": reg_sell_btc,
                "top3_share_pct": sell_top3_share,
                "top_sellers": sell_top[:3],
                "ladder": sell_ladder,
            },
            "sparkline_7d": sparkline_7d,
        }

    @staticmethod
    def build_frontend_data() -> None:
        """
        Generates the 8 compact JSON files in `public/data/` for the modular static frontend.
        """
        Storage._ensure_dirs()
        now_ts = int(datetime.now(timezone.utc).timestamp())

        prof_snap, prof_ts = Storage.load_latest_profitability()
        prof_hist = Storage.load_profitability_history()

        ob_snap, ob_ts = Storage.load_latest_orderbook()
        ob_hist = Storage.load_orderbook_history()

        trades_snap, trades_ts = Storage.load_latest_trades()
        trades_hist = Storage.load_trades_history()

        leaderboards = Storage.load_market_leaderboards() or {}

        # Determine line mapping per item
        item_to_line = {}
        for line_name, codes in config.PRODUCTION_LINES.items():
            for code in codes:
                item_to_line[code] = line_name

        # 1. Build meta.json
        items_meta = {}
        for code, pretty_name in config.ALL_MARKET_ITEMS.items():
            pp = config.ALL_ITEMS_PP.get(code, 0)
            needs = config.DEFAULT_RECIPES.get(code, {})
            if prof_snap and code in prof_snap and "needs" in prof_snap[code]:
                needs = prof_snap[code]["needs"]
            category = (
                "unmanufactured"
                if pp == 0
                else ("raw" if not needs else "manufactured")
            )
            items_meta[code] = {
                "code": code,
                "name": pretty_name,
                "short": config.ITEM_SHORT_NAMES.get(code, pretty_name),
                "pp": pp,
                "color": config.ITEM_COLORS.get(code, "#6366f1"),
                "category": category,
                "line": item_to_line.get(code, "Other"),
                "needs": needs,
            }

        meta_payload = {
            "generated_at": now_ts,
            "timestamps": {
                "profitability": prof_ts or now_ts,
                "orderbook": ob_ts or now_ts,
                "trades": trades_ts or now_ts,
                "leaderboards": leaderboards.get("timestamp", now_ts),
            },
            "items": items_meta,
            "production_lines": config.PRODUCTION_LINES,
        }
        Storage._write_json(config.FE_META_FILE, meta_payload, compact=True)

        # 2. Build profitability.json & profitability_history.json
        prof_items_out = {}
        prof_labels = prof_hist.get("labels", [])
        spark_labels_prof = prof_labels[-config.SPARKLINE_POINTS :]

        for code in config.ITEM_PRETTY_NAMES:
            it_data = (prof_snap or {}).get(code, {})
            it_hist = prof_hist.get("items", {}).get(code, {})
            min_series = (it_hist.get("min_pp") or [])[-config.SPARKLINE_POINTS :]
            max_series = (it_hist.get("max_pp") or [])[-config.SPARKLINE_POINTS :]

            # If history has fewer than 2 points, seed sparkline with current value
            cur_min = it_data.get("min_pp", 0.0)
            cur_max = it_data.get("max_pp", 0.0)
            if len([x for x in min_series if x is not None]) < 2 and cur_min:
                min_series = [cur_min, cur_min]
                max_series = [cur_max, cur_max]

            prof_items_out[code] = {
                **it_data,
                "sparkline_7d": {
                    "labels": spark_labels_prof if len(spark_labels_prof) >= 2 else [now_ts - 86400, now_ts],
                    "min_pp": min_series,
                    "max_pp": max_series,
                },
            }

        Storage._write_json(
            config.FE_PROFITABILITY_FILE,
            {"timestamp": prof_ts or now_ts, "items": prof_items_out},
            compact=True,
        )
        Storage._write_json(config.FE_PROFITABILITY_HISTORY_FILE, prof_hist, compact=True)

        # 3. Build orderbook.json & orderbook_history.json
        ob_items_out = {}
        ob_labels = ob_hist.get("labels", [])
        spark_labels_ob = ob_labels[-config.SPARKLINE_POINTS :]
        hist_len = len(ob_labels)

        for code in config.ALL_MARKET_ITEMS:
            raw_it = (ob_snap or {}).get(code, {})
            if "items" not in ob_hist:
                ob_hist["items"] = {}
            if code not in ob_hist["items"]:
                ob_hist["items"][code] = {}
            it_hist = ob_hist["items"][code]

            sell_pp_series = (it_hist.get("total_pp") or [])[-config.SPARKLINE_POINTS :]
            buy_pp_series = (it_hist.get("buy_total_pp") or [])[-config.SPARKLINE_POINTS :]
            sell_u_series = (it_hist.get("total_units") or [])[-config.SPARKLINE_POINTS :]
            buy_u_series = (it_hist.get("buy_total_units") or [])[-config.SPARKLINE_POINTS :]

            spark_ob = {
                "labels": spark_labels_ob,
                "sell_pp": sell_pp_series,
                "buy_pp": buy_pp_series,
                "sell_units": sell_u_series,
                "buy_units": buy_u_series,
            }
            norm_it = Storage._normalize_orderbook_item(code, raw_it, spark_ob)
            ob_items_out[code] = norm_it

            # Ensure sell_supply, buy_money_btc, and liquidity_pct exist in ob_hist
            pp_rate = config.ALL_ITEMS_PP.get(code, 0)
            if "sell_supply" not in it_hist or len(it_hist["sell_supply"]) < hist_len:
                base_src = it_hist.get("total_pp" if pp_rate > 0 else "total_units") or []
                it_hist["sell_supply"] = list(base_src)
                while len(it_hist["sell_supply"]) < hist_len:
                    it_hist["sell_supply"].insert(0, 0)

            cur_buy_money = round(float(norm_it.get("buy", {}).get("total_money_btc", 0.0)), 2)
            if "buy_money_btc" not in it_hist or len(it_hist["buy_money_btc"]) < hist_len:
                existing_bm = list(it_hist.get("buy_money_btc") or [])
                while len(existing_bm) < hist_len:
                    existing_bm.insert(0, 0)
                if hist_len > 0 and not existing_bm[-1] and cur_buy_money > 0:
                    existing_bm[-1] = cur_buy_money
                it_hist["buy_money_btc"] = existing_bm

            b_lad = norm_it.get("buy", {}).get("ladder", [])
            s_lad = norm_it.get("sell", {}).get("ladder", [])
            buy_75 = Storage.compute_75_depth_money(b_lad, float(norm_it.get("best_bid", 0.0)), True)
            sell_75 = Storage.compute_75_depth_money(s_lad, float(norm_it.get("best_ask", 0.0)), False)
            tot_75 = buy_75 + sell_75
            cur_liq_pct = round((buy_75 / tot_75) * 100, 1) if tot_75 > 0 else 50.0
            if "liquidity_pct" not in it_hist or len(it_hist["liquidity_pct"]) < hist_len:
                existing_lq = list(it_hist.get("liquidity_pct") or [])
                while len(existing_lq) < hist_len:
                    existing_lq.insert(0, 0)
                if hist_len > 0 and not existing_lq[-1]:
                    existing_lq[-1] = cur_liq_pct
                it_hist["liquidity_pct"] = existing_lq

        Storage._write_json(
            config.FE_ORDERBOOK_FILE,
            {"timestamp": ob_ts or now_ts, "items": ob_items_out},
            compact=True,
        )
        Storage._write_json(config.FE_ORDERBOOK_HISTORY_FILE, ob_hist, compact=True)

        # 4. Build trades.json & trades_history.json
        t_labels = trades_hist.get("labels", [])
        spark_labels_tr = t_labels[-config.SPARKLINE_POINTS :]
        frontend_trades = {
            k: v for k, v in (trades_snap or {}).items() if k != "raw_trades"
        }

        # Ensure period-specific Top-3 buyers/sellers in 7d/30d/all are populated
        lb_by_item = leaderboards.get("by_item", {}) if isinstance(leaderboards, dict) else {}
        periods_dict = frontend_trades.get("periods", {})
        for p_key in ("24h", "7d", "30d", "all"):
            p_block = periods_dict.get(p_key, {})
            p_items = p_block.get("items", {})
            for code, it_obj in p_items.items():
                lb_period = lb_by_item.get(code, {}).get("trades", {}).get(p_key, {})
                if not lb_period:
                    continue
                total_u = float(it_obj.get("total_units") or 0)
                for role_key in ("top_buyers", "top_sellers"):
                    lb_list = lb_period.get(role_key, [])
                    if lb_list:
                        converted = []
                        for entry in lb_list[:3]:
                            by_it = (entry.get("by_item") or [{}])[0]
                            u_val = int(by_it.get("units", entry.get("sub_value", 0)) or 0)
                            m_val = round(float(by_it.get("money", entry.get("value", 0.0)) or 0.0), 2)
                            orders_val = by_it.get("orders", [])
                            converted.append(
                                {
                                    "id": entry.get("id"),
                                    "name": entry.get("name"),
                                    "type": entry.get("type"),
                                    "code": entry.get("code"),
                                    "avatar_url": entry.get("avatar_url"),
                                    "profile_url": entry.get("profile_url"),
                                    "units": u_val,
                                    "money": m_val,
                                    "share_pct": round(u_val / total_u * 100, 1) if total_u > 0 else 0.0,
                                    "orders": orders_val,
                                }
                            )
                        it_obj[role_key] = converted

        # Inject 7d VWAP & volume sparklines per item into trades.json
        trades_sparklines = {}
        for code in config.ALL_MARKET_ITEMS:
            th_item = trades_hist.get("items", {}).get(code, {})
            trades_sparklines[code] = {
                "labels": spark_labels_tr,
                "vwap": (th_item.get("hourly_vwap") or [])[-config.SPARKLINE_POINTS :],
                "money": (th_item.get("hourly_money") or [])[-config.SPARKLINE_POINTS :],
                "units": (th_item.get("hourly_units") or [])[-config.SPARKLINE_POINTS :],
            }
        frontend_trades["sparklines_7d"] = trades_sparklines

        Storage._write_json(config.FE_TRADES_FILE, frontend_trades, compact=True)
        Storage._write_json(config.FE_TRADES_HISTORY_FILE, trades_hist, compact=True)

        # 5. Build leaderboards.json
        Storage._write_json(config.FE_LEADERBOARDS_FILE, leaderboards, compact=True)

        logger.info(f"Exported 8 static frontend JSON slices to {config.PUBLIC_DATA_DIR}")

