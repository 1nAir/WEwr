import argparse
from functools import partial
import http.server
import logging
import socketserver
import subprocess
import sys
import webbrowser

from src import config
from src.analyzers.leaderboards import MarketLeaderboardAnalyzer
from src.analyzers.orderbook import OrderBookAnalyzer
from src.analyzers.profitability import ProfitabilityAnalyzer
from src.analyzers.trades import MarketTradesAnalyzer
from src.api_client import TRPCClient
from src.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def init_client() -> TRPCClient:
    if not config.API_KEYS:
        raise ValueError(
            "No API keys found in environment (WEALTHRATE1, WEALTHRATE2, WEALTHRATE3)"
        )
    return TRPCClient(api_keys=config.API_KEYS)


def run_profitability(client: TRPCClient) -> None:
    """Calculates dry 1 PP production value relative to current market Bid/Ask prices."""
    logger.info("--- Starting Dry Profitability Analysis (1 PP Value) ---")
    analyzer = ProfitabilityAnalyzer(client)
    snapshot = analyzer.calculate_snapshot()

    Storage.save_latest_profitability(snapshot)
    logger.info(f"Saved latest profitability snapshot to {config.LATEST_PROFITABILITY_FILE}")

    history = Storage.load_profitability_history()
    history = Storage.append_profitability_snapshot(history, snapshot)
    Storage.save_profitability_history(history)
    logger.info("Profitability history updated successfully.")


def run_orderbook(client: TRPCClient) -> None:
    """Collects unified Buy & Sell order book depth and appends to history."""
    logger.info("--- Starting Unified Order Book Collection (Buy & Sell Depth) ---")
    analyzer = OrderBookAnalyzer(client)
    snapshot = analyzer.collect_orderbook()

    Storage.save_latest_orderbook(snapshot)
    logger.info(f"Saved latest order book snapshot to {config.LATEST_ORDERBOOK_FILE}")

    history = Storage.load_orderbook_history()
    history = Storage.append_orderbook_snapshot(history, snapshot)
    Storage.save_orderbook_history(history)
    logger.info("Order book history updated successfully.")


def run_trades(client: TRPCClient) -> None:
    """Syncs completed trading transactions incrementally and updates daily stats + history."""
    logger.info("--- Starting Market Transactions Sync ---")
    existing_trades, _ = Storage.load_latest_trades()
    existing_daily = Storage.load_daily_trader_stats()

    analyzer = MarketTradesAnalyzer(client)
    latest_trades, daily_stats = analyzer.sync_trades(
        existing_trades_cache=existing_trades,
        existing_daily_stats=existing_daily,
        max_lookback_hours=24,
    )

    Storage.save_latest_trades(latest_trades)
    Storage.save_daily_trader_stats(daily_stats)
    logger.info(f"Saved latest market trades and daily stats to {config.LATEST_TRADES_FILE}")

    trades_history = Storage.load_trades_history()
    trades_history = MarketTradesAnalyzer.append_trades_history(trades_history, latest_trades)
    Storage.save_trades_history(trades_history)
    logger.info("Market trades history updated successfully.")


def run_leaderboards(client: TRPCClient) -> None:
    """Builds pre-aggregated Top-25 leaderboards for live order book and historical trades."""
    logger.info("--- Starting Market Leaderboards Generation ---")
    ob_snapshot, _ = Storage.load_latest_orderbook()
    daily_stats = Storage.load_daily_trader_stats()

    analyzer = MarketLeaderboardAnalyzer(client)
    leaderboards = analyzer.build_leaderboards(ob_snapshot or {}, daily_stats)
    Storage.save_market_leaderboards(leaderboards)
    logger.info(f"Saved market leaderboards to {config.MARKET_LEADERBOARDS_FILE}")


def run_build() -> None:
    """Exports lightweight static JSON slices to `public/data/*.json` for the modular frontend."""
    logger.info("--- Building Static Frontend JSON Slices (public/data/*.json) ---")
    Storage.build_frontend_data()
    logger.info("--- Frontend Data Build Complete ---")


def run_pull_data() -> None:
    """Pulls latest data_store JSONs from remote 'data' branch."""
    logger.info("Fetching latest data from 'data' branch...")
    cmd = (
        "git fetch origin data && "
        "git checkout origin/data -- data_store/ public/data/ && "
        "git restore --staged data_store/ public/data/"
    )
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode == 0:
        logger.info("Successfully synced latest data from 'data' branch.")
    else:
        logger.error(f"Failed to pull data from 'data' branch: {res.stderr}")


def run_serve(port: int = 8000) -> None:
    """Starts a local static HTTP server for `public/` and opens the browser."""
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=config.PUBLIC_DIR)
    socketserver.TCPServer.allow_reuse_address = True
    url = f"http://localhost:{port}"
    logger.info(f"Serving Wealthrate v2 from {config.PUBLIC_DIR} at {url}")
    webbrowser.open(url)
    with socketserver.TCPServer(("", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down local preview server.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Wealthrate v2 Analytics Runner")
    parser.add_argument(
        "--task",
        choices=[
            "profitability",
            "market",
            "orderbook",
            "depth",
            "trades",
            "leaderboards",
            "build",
            "all",
            "pull_data",
            "serve",
        ],
        default="all",
        help="Task to execute",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for --task serve (default: 8000)",
    )
    args = parser.parse_args()

    if args.task == "pull_data":
        run_pull_data()
        return

    if args.task == "serve":
        run_serve(args.port)
        return

    client = None
    if args.task in ("profitability", "market", "orderbook", "depth", "trades", "leaderboards", "all"):
        try:
            client = init_client()
        except Exception as e:
            logger.critical(f"Failed to initialize API client: {e}")
            sys.exit(1)

    try:
        if args.task in ("orderbook", "depth", "all"):
            run_orderbook(client)

        if args.task in ("trades", "all"):
            run_trades(client)

        if args.task in ("leaderboards", "all"):
            run_leaderboards(client)

        if args.task in ("profitability", "all"):
            run_profitability(client)

        if args.task in ("build", "all"):
            run_build()

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

