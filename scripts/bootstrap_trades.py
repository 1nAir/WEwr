import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import init_client
from src.analyzers.trades import MarketTradesAnalyzer
from src.storage import Storage


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap historical trading transactions")
    parser.add_argument("--days", type=int, default=7, help="Days to look back (default: 7)")
    args = parser.parse_args()

    client = init_client()
    analyzer = MarketTradesAnalyzer(client)
    existing_trades, _ = Storage.load_latest_trades()
    existing_daily = Storage.load_daily_trader_stats()

    latest_trades, daily_stats = analyzer.sync_trades(
        existing_trades_cache=existing_trades,
        existing_daily_stats=existing_daily,
        max_lookback_hours=args.days * 24,
    )
    Storage.save_latest_trades(latest_trades)
    Storage.save_daily_trader_stats(daily_stats)
    print(f"Bootstrapped trades for {args.days} days successfully.")


if __name__ == "__main__":
    main()

