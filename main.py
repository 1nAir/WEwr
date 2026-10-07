import argparse
import logging
import sys

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor
from src.market_analyzer import MarketAnalyzer
from src.production_analyzer import CompanyAnalyzer
from src.report_generator import ReportGenerator
from src.worker_analyzer import WorkerAnalyzer

# logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def init_client() -> TRPCClient:
    """Initializes and returns the tRPC client."""
    if not config.API_KEYS:
        raise ValueError(
            "No API keys found in environment (WEALTHRATE1, WEALTHRATE2, WEALTHRATE3)"
        )
    return TRPCClient(api_keys=config.API_KEYS)


def run_companies(client: TRPCClient) -> None:
    """Scrapes company basing stats, saves latest cache and appends to companies history."""
    logger.info("--- Starting Company Basing Collection ---")
    items = list(config.ITEM_PRETTY_NAMES.keys())
    comp_analyzer = CompanyAnalyzer(client)
    company_stats = comp_analyzer.collect_company_stats(items)

    # 1. Save latest snapshot for market/report generator
    DataProcessor.save_latest_companies(company_stats)
    logger.info(f"Saved latest company stats to {config.LATEST_COMPANIES_FILE}")

    # 2. Append to companies history
    logger.info("Updating companies history...")
    comp_history = DataProcessor.load_companies_history()
    comp_history = DataProcessor.append_companies_snapshot(comp_history, company_stats)
    DataProcessor.save_companies_history(comp_history)
    logger.info("Company basing collection completed successfully.")


def run_market(client: TRPCClient) -> None:
    """Fetches market prices, saves latest market snapshot, updates profitability history, and runs worker analysis."""
    logger.info("--- Starting Market Data Collection ---")

    # 1. Market Analysis
    analyzer = MarketAnalyzer(client)
    current_snapshot = analyzer.calculate_snapshot()

    # 2. Save latest market snapshot to file
    DataProcessor.save_latest_market(current_snapshot)
    logger.info(f"Saved latest market snapshot to {config.LATEST_MARKET_FILE}")

    # 3. Worker Analysis (using cached bonuses to minimize API requests)
    try:
        logger.info("Starting Worker Analysis...")
        worker_analyzer = WorkerAnalyzer(client, region_analyzer=analyzer.region_analyzer)
        worker_snapshot = worker_analyzer.calculate_worker_snapshot(
            current_snapshot, bonuses_data=analyzer.last_bonuses_data
        )
        DataProcessor.save_latest_workers(worker_snapshot)
        logger.info(f"Saved latest workers snapshot to {config.LATEST_WORKERS_FILE}")

        # Update Workers History
        logger.info("Updating workers history...")
        workers_history = DataProcessor.load_workers_history()
        workers_history = DataProcessor.append_workers_snapshot(workers_history, worker_snapshot)
        DataProcessor.save_workers_history(workers_history)
        logger.info("Workers history updated successfully.")
    except Exception as e:
        logger.error(f"Failed to calculate worker snapshot: {e}", exc_info=True)

    # 4. Profitability History
    logger.info("Processing profitability history...")
    history = DataProcessor.load_history()
    history = DataProcessor.append_snapshot(history, current_snapshot)
    history = DataProcessor.clean_history(history)
    DataProcessor.save_history(history)
    logger.info("Market data collection completed successfully.")


def run_workers(client: TRPCClient) -> None:
    """Runs worker analysis using latest market prices and saves latest workers snapshot and history."""
    logger.info("--- Starting Worker Analysis ---")
    current_snapshot, _ = DataProcessor.load_latest_market()
    if not current_snapshot:
        logger.warning("No latest market snapshot found. Running market collection first...")
        run_market(client)
        return
    worker_analyzer = WorkerAnalyzer(client)
    worker_snapshot = worker_analyzer.calculate_worker_snapshot(current_snapshot)
    DataProcessor.save_latest_workers(worker_snapshot)
    logger.info(f"Saved latest workers snapshot to {config.LATEST_WORKERS_FILE}")

    # Update Workers History
    logger.info("Updating workers history...")
    workers_history = DataProcessor.load_workers_history()
    workers_history = DataProcessor.append_workers_snapshot(workers_history, worker_snapshot)
    DataProcessor.save_workers_history(workers_history)
    logger.info("Workers history updated successfully.")


def run_build() -> None:
    """Builds the HTML report from the latest cached snapshots of all modules."""
    logger.info("--- Starting HTML Site Build ---")

    # 1. Load latest market snapshot
    combined_snapshot, market_ts = DataProcessor.load_latest_market()
    if not combined_snapshot:
        logger.warning(
            f"No latest market snapshot found in {config.LATEST_MARKET_FILE}. Aborting build."
        )
        return

    # 2. Merge cached company stats into combined snapshot
    company_stats, comp_ts = DataProcessor.load_latest_companies()
    if company_stats:
        logger.info(f"Loaded cached company stats for {len(company_stats)} items.")
        for item_code, stats in company_stats.items():
            if item_code in combined_snapshot:
                combined_snapshot[item_code].update(stats)
    else:
        logger.warning(
            "No cached company stats found. Building without company basing data."
        )

    # 3. Load latest workers data
    workers_snapshot, workers_ts = DataProcessor.load_latest_workers()
    if workers_snapshot:
        logger.info(
            f"Loaded cached workers data for {len(workers_snapshot.get('items', {}))} items."
        )
    else:
        logger.warning("No cached workers data found.")

    # 4. Load Histories for Charting
    history = DataProcessor.load_history()
    comp_history = DataProcessor.load_companies_history()
    workers_history = DataProcessor.load_workers_history()

    # 5. Generate Report
    logger.info("Generating report...")
    ReportGenerator.generate(
        history,
        comp_history,
        combined_snapshot,
        market_timestamp=market_ts,
        comp_timestamp=comp_ts,
        workers_snapshot=workers_snapshot,
        workers_timestamp=workers_ts,
        workers_history=workers_history,
    )
    logger.info("--- HTML Site Build Complete ---")


def run_pull_data() -> None:
    """Pulls the latest historical data and snapshots from the remote 'data' branch."""
    import subprocess

    logger.info("Fetching latest data from 'data' branch...")
    cmd = (
        "git fetch origin data && "
        "git checkout origin/data -- history*.json latest*.json public/ && "
        "git restore --staged history*.json latest*.json public/"
    )
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if res.returncode == 0:
        logger.info("Successfully synced latest data and report from 'data' branch.")
    else:
        logger.error(f"Failed to pull data from 'data' branch: {res.stderr}")


def main():
    parser = argparse.ArgumentParser(description="Wealthrate Analytics Runner")
    parser.add_argument(
        "--task",
        choices=["market", "companies", "workers", "build", "market_and_build", "all", "pull_data"],
        default="market_and_build",
        help="Task to execute: 'market', 'companies', 'workers', 'build', 'market_and_build', 'all', or 'pull_data'",
    )
    args = parser.parse_args()

    # Initialize API Client only if needed (build & pull_data tasks don't require API keys!)
    client = None
    if args.task in ("market", "companies", "workers", "market_and_build", "all"):
        try:
            client = init_client()
        except Exception as e:
            logger.critical(f"Failed to initialize API client: {e}")
            sys.exit(1)

    try:
        if args.task == "pull_data":
            run_pull_data()
            return

        if args.task in ("companies", "all"):
            run_companies(client)

        if args.task in ("market", "market_and_build", "all"):
            run_market(client)

        if args.task == "workers":
            run_workers(client)

        if args.task in ("build", "market_and_build", "all"):
            run_build()

    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
