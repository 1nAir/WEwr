import logging
import sys

from src import config
from src.api_client import TRPCClient
from src.data_processor import DataProcessor
from src.market_analyzer import MarketAnalyzer
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
        if not config.API_KEY_MAIN:
            raise ValueError("API_KEY_MAIN is missing in config")
        client = TRPCClient(api_keys=[config.API_KEY_MAIN])
    except Exception as e:
        logger.critical(f"Failed to initialize API client: {e}")
        sys.exit(1)

    # 2. Analyze Market (Business Logic)
    logger.info("Fetching and analyzing market data...")
    try:
        analyzer = MarketAnalyzer(client)
        current_snapshot = analyzer.calculate_snapshot()
    except Exception as e:
        logger.error(f"Failed to analyze market: {e}", exc_info=True)
        sys.exit(1)

    # 3. History & Cleaning
    logger.info("Processing history...")
    try:
        history = DataProcessor.load_history()
        history = DataProcessor.append_snapshot(history, current_snapshot)

        # Auto-clean anomalies (Spike Cleaner)
        history = DataProcessor.clean_history(history)

        DataProcessor.save_history(history)
    except Exception as e:
        logger.error(f"Failed to process history: {e}", exc_info=True)
        sys.exit(1)

    # 4. Generate Report
    logger.info("Generating report...")
    try:
        ReportGenerator.generate(history, current_snapshot)
    except Exception as e:
        logger.error(f"Failed to generate report: {e}", exc_info=True)
        sys.exit(1)

    logger.info("--- Update Complete ---")


if __name__ == "__main__":
    main()
