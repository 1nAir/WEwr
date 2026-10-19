import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor
from src.market_leaderboard_analyzer import MarketLeaderboardAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_trades")


def main():
    parser = argparse.ArgumentParser(description="Backfill historical trades into daily_trader_stats.json")
    parser.add_argument("--days", type=int, default=7, help="Total days of history to cover (default: 7)")
    args = parser.parse_args()

    client = TRPCClient(api_keys=config.API_KEYS)
    now = datetime.now(timezone.utc)
    target_cutoff = now - timedelta(days=args.days)
    logger.info(f"=== Starting Background Backfill for {args.days} Days (Cutoff: {target_cutoff.strftime('%Y-%m-%d %H:%M:%S UTC')}) ===")

    # 1. Find oldest trade in current latest_market_trades.json to resume from
    latest_trades, _ = DataProcessor.load_latest_market_trades()
    raw_trades = latest_trades.get("raw_trades", [])

    cursor = None
    if raw_trades:
        oldest = raw_trades[-1]
        oldest_id = oldest.get("_id")
        oldest_date = oldest.get("createdAt")
        if oldest_id and oldest_date:
            cursor_obj = [{"t": "date", "v": oldest_date}, {"t": "str", "v": oldest_id}]
            json_str = json.dumps(cursor_obj, separators=(",", ":"))
            b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8").rstrip("=")
            cursor = f"v2.{b64_str}"
            logger.info(f"Resuming backfill backwards from oldest known trade: {oldest_id} ({oldest_date})")

    # 2. Load daily stats ledger
    daily_stats = DataProcessor.load_daily_trader_stats() or {"last_updated": int(now.timestamp()), "days": {}}
    days_dict = daily_stats.setdefault("days", {})

    page = 0
    total_fetched = 0
    t0 = time.time()
    reached_cutoff = False

    while not reached_cutoff:
        payload: dict[str, Any] = {"limit": 100, "transactionType": "trading"}
        if cursor:
            payload["cursor"] = cursor

        res = client.call("transaction.getPaginatedTransactions", payload, raise_on_error=False)
        page += 1

        if not isinstance(res, dict) or "result" not in res:
            logger.warning(f"Unexpected response at page {page}: {res}. Retrying in 2s...")
            time.sleep(2)
            continue

        data = res.get("result", {}).get("data", {})
        items = data.get("items", [])
        if not items:
            logger.info(f"No more items returned at page {page}. Backfill reached beginning of market history.")
            break

        total_fetched += len(items)

        # Process transactions into daily ledger
        for tx in items:
            created_str = tx.get("createdAt", "")
            if created_str:
                try:
                    tx_time = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    if tx_time < target_cutoff:
                        logger.info(f"Reached target cutoff {target_cutoff} at page {page} ({created_str}). Stopping backfill.")
                        reached_cutoff = True
                        break
                except Exception:
                    pass

            day_key = created_str[:10] if len(created_str) >= 10 else now.strftime("%Y-%m-%d")
            day_entry = days_dict.setdefault(day_key, {})

            buyer_id = tx.get("buyerId")
            seller_id = tx.get("sellerId")
            item_code = tx.get("itemCode")
            qty = int(tx.get("quantity", 0))
            money = round(float(tx.get("money", 0.0)), 4)
            pp_rate = config.MARKET_DEPTH_PP.get(item_code, 0)
            pp = qty * pp_rate if pp_rate else 0

            # Buyer
            if buyer_id:
                b_rec = day_entry.setdefault(buyer_id, {
                    "buy": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                    "sell": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                })
                b_rec["buy"]["money"] = round(b_rec["buy"]["money"] + money, 4)
                b_rec["buy"]["units"] += qty
                b_rec["buy"]["pp"] += pp
                if item_code:
                    item_b = b_rec["buy"]["by_item"].setdefault(item_code, {"units": 0, "money": 0.0, "pp": 0})
                    item_b["units"] += qty
                    item_b["money"] = round(item_b["money"] + money, 4)
                    item_b["pp"] += pp

            # Seller
            if seller_id:
                s_rec = day_entry.setdefault(seller_id, {
                    "buy": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                    "sell": {"money": 0.0, "pp": 0, "units": 0, "by_item": {}},
                })
                s_rec["sell"]["money"] = round(s_rec["sell"]["money"] + money, 4)
                s_rec["sell"]["units"] += qty
                s_rec["sell"]["pp"] += pp
                if item_code:
                    item_s = s_rec["sell"]["by_item"].setdefault(item_code, {"units": 0, "money": 0.0, "pp": 0})
                    item_s["units"] += qty
                    item_s["money"] = round(item_s["money"] + money, 4)
                    item_s["pp"] += pp

        # Save checkpoint every 100 pages (~10,000 trades)
        if page % 100 == 0:
            daily_stats["last_updated"] = int(time.time())
            DataProcessor.save_daily_trader_stats(daily_stats)
            elapsed = time.time() - t0
            latest_in_batch = items[-1].get("createdAt", "")
            logger.info(
                f"[Checkpoint] Page {page}: fetched {total_fetched:,} trades in {elapsed:.1f}s. "
                f"Current timestamp: {latest_in_batch}. Days in stats: {len(days_dict)}"
            )

        cursor = data.get("nextCursor")
        if not cursor or reached_cutoff:
            break

    # Final save
    daily_stats["last_updated"] = int(time.time())
    DataProcessor.save_daily_trader_stats(daily_stats)
    total_time = time.time() - t0
    logger.info(
        f"=== Backfill Completed! Processed {total_fetched:,} trades across {page} pages in {total_time:.1f}s. "
        f"Total days recorded: {len(days_dict)}: {sorted(days_dict.keys())} ==="
    )

    # Re-compute Leaderboards with newly backfilled days
    depth_snapshot, _ = DataProcessor.load_latest_market_depth()
    if depth_snapshot:
        logger.info("Recomputing market leaderboards across 24h, 7d, 30d, all...")
        lb_analyzer = MarketLeaderboardAnalyzer(client)
        leaderboards = lb_analyzer.build_leaderboards(depth_snapshot, daily_stats)
        DataProcessor.save_market_leaderboards(leaderboards)
        logger.info("Market leaderboards updated successfully.")


if __name__ == "__main__":
    main()

