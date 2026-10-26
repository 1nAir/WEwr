import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import init_client, run_orderbook


if __name__ == "__main__":
    client = init_client()
    run_orderbook(client)

