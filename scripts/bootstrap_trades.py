import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta

# Add parent directory to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor
from src.market_trades_analyzer import MarketTradesAnalyzer
from src.market_leaderboard_analyzer import MarketLeaderboardAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="One-time bootstrap for historical trades")
    parser.add_argument("--days", type=int, default=7, help="Number of days of trades to download (default: 7)")
    args = parser.parse_args()

    client = TRPCClient(api_keys=config.API_KEYS)
    logger.info(f"=== Starting Bootstrap for {args.days} Days of Market Trades ===")

    # 1. Load existing cache if any
    existing_trades, _ = DataProcessor.load_latest_market_trades()
    existing_daily = DataProcessor.load_daily_trader_stats()

    analyzer = MarketTradesAnalyzer(client)
    t0 = time.time()
    latest_trades, daily_stats = analyzer.sync_trades(
        existing_trades_cache=existing_trades,
        existing_daily_stats=existing_daily,
        max_lookback_hours=args.days * 24,
    )
    elapsed = time.time() - t0

    # 2. Save latest trades and daily stats
    DataProcessor.save_latest_market_trades(latest_trades)
    DataProcessor.save_daily_trader_stats(daily_stats)
    logger.info(f"Saved latest market trades and daily stats in {elapsed:.1f}s.")

    # 3. Update trades history
    trades_history = DataProcessor.load_market_trades_history()
    trades_history = MarketTradesAnalyzer.append_trades_history(trades_history, latest_trades)
    DataProcessor.save_market_trades_history(trades_history)
    logger.info("Updated market trades history.")

    # 4. Generate Leaderboards if depth snapshot exists
    depth_snapshot, _ = DataProcessor.load_latest_market_depth()
    if depth_snapshot:
        logger.info("Computing initial market leaderboards...")
        lb_analyzer = MarketLeaderboardAnalyzer(client)
        leaderboards = lb_analyzer.build_leaderboards(depth_snapshot, daily_stats)
        DataProcessor.save_market_leaderboards(leaderboards)
        logger.info("Market leaderboards saved successfully.")

    logger.info("=== Bootstrap Completed Successfully! ===")


if __name__ == "__main__":
    main()

