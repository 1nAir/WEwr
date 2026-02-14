import logging
import sys

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor
from src.market_analyzer import MarketAnalyzer
from src.production_analyzer import CompanyAnalyzer
from src.report_generator import ReportGenerator

# logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    logger.info("--- Starting Wealthrate Analytics Update ---")

    # 1. Initialize API
    try:
        if not config.API_KEYS:
            raise ValueError(
                "No API keys found in environment (WEALTHRATE1, WEALTHRATE2, WEALTHRATE3)"
            )
        client = TRPCClient(api_keys=config.API_KEYS)
    except Exception as e:
        logger.critical(f"Failed to initialize API client: {e}")
        sys.exit(1)

    # 2. Analyze Company Basing (New Concept) - Runs first as requested
    logger.info(
        "Fetching and analyzing company basing stats (this may take a while)..."
    )
    company_stats = {}
    try:
        comp_analyzer = CompanyAnalyzer(client)
        items = list(config.ITEM_PRETTY_NAMES.keys())
        company_stats = comp_analyzer.collect_company_stats(items)
    except Exception as e:
        logger.error(f"Failed to analyze company stats: {e}", exc_info=True)
        # Proceed to market analysis even if company stats fail

    # 3. Analyze Market (Business Logic)
    logger.info("Fetching and analyzing market data...")
    try:
        analyzer = MarketAnalyzer(client)
        current_snapshot = analyzer.calculate_snapshot()

        # Merge company stats into current_snapshot
        for item_code, stats in company_stats.items():
            if item_code in current_snapshot:
                current_snapshot[item_code].update(stats)
    except Exception as e:
        logger.error(f"Failed to analyze market: {e}", exc_info=True)
        sys.exit(1)

    # 4. History & Cleaning
    logger.info("Processing history...")
    try:
        # Profitability History (Original)
        history = DataProcessor.load_history()
        history = DataProcessor.append_snapshot(history, current_snapshot)
        history = DataProcessor.clean_history(history)
        DataProcessor.save_history(history)

        # Company Basing History (New)
        comp_history = DataProcessor.load_companies_history()
        comp_history = DataProcessor.append_companies_snapshot(
            comp_history, current_snapshot
        )
        DataProcessor.save_companies_history(comp_history)

    except Exception as e:
        logger.error(f"Failed to process history: {e}", exc_info=True)
        sys.exit(1)

    # 5. Generate Report
    logger.info("Generating report...")
    try:
        ReportGenerator.generate(history, comp_history, current_snapshot)
    except Exception as e:
        logger.error(f"Failed to generate report: {e}", exc_info=True)
        sys.exit(1)

    logger.info("--- Update Complete ---")


if __name__ == "__main__":
    main()
