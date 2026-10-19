import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("bootstrap")

API_KEY = os.environ.get("WEALTHRATE1") or "wae_88cf7e5ef0ac955298887d52a2412fd433f3debfe26a963bfd0a6c15226fec44"
BASE_URL = "https://api2.warera.io/trpc"
BATCH_SIZE = 100
CHECKPOINT_FILE = "known_players_checkpoint.json"
FINAL_FILE = "known_players.json"
INPUT_USERS_FILE = "users_202610081303.json"

MISSING_INACTIVE_29 = [
    "6813b776efecdf9bab197146", "681d5050470bf2a142d99dfa", "6835f526c80e4bc2f9c463b4",
    "6836042b1e96db6e38e3d81c", "6839b21b7da7c2bb5df31b04", "68af31414a187200446374bf",
    "68baf180734cbd8d42ed0748", "68d272f6f3052db00ef9b62b", "68ea4e781cf4d42b58c0d239",
    "691f55d6c66380bdd8c96908", "69355790834d3cc323695149", "6936a352f9b4e3f58ad6fd69",
    "693e64836a349c962aea44f1", "6945abe4a3e161cb35b187c9", "695e683031f299b219baed43",
    "696952a0f8fa9f2c178aae83", "6969c8c023ca7dbecc9847c0", "69808fb3d94f506d1e3de295",
    "698631b951756dc6338d42c1", "6996aa5e7bb099ced6bf824f", "69b847f395d04b39a3ea1191",
    "69bd18da21c887ccfd7b5394", "69cbd44f155a8ecde36f554e", "69cccdb8b45239c34e5e436e",
    "69ce3a8c5f9cbc0148460ddf", "69d069b6eb2caa96e7ae816e", "69d6b47dabd1bf8c1fe8f2ca",
    "69fa0da229f79d62df36acc2", "6a2a6ceeac61cb0bfb832a2b"
]


def load_candidate_ids() -> list[str]:
    logger.info(f"Loading candidates from {INPUT_USERS_FILE}...")
    with open(INPUT_USERS_FILE) as f:
        data = json.load(f)
    key = list(data.keys())[0]
    file_ids = [x["external_id"] for x in data[key] if x.get("external_id")]
    all_candidates = set(file_ids).union(MISSING_INACTIVE_29)
    logger.info(f"Loaded {len(file_ids)} from file + {len(MISSING_INACTIVE_29)} known missing. Total unique: {len(all_candidates)}")
    return sorted(all_candidates)


def fetch_active_ranking(session: requests.Session) -> set[str]:
    logger.info("Fetching active players ranking (userLevel)...")
    url = f"{BASE_URL}/ranking.getRanking?input=%7B%22rankingType%22%3A%22userLevel%22%7D"
    r = session.get(url)
    r.raise_for_status()
    data = r.json().get("result", {}).get("data", {})
    items = data.get("items", []) if isinstance(data, dict) else []
    active_ids = {it["user"] for it in items if isinstance(it, dict) and it.get("user")}
    logger.info(f"Fetched {len(active_ids)} active ranked players.")
    return active_ids


def run_batch_orders(session: requests.Session, uids: list[str]) -> list[dict]:
    methods = ["tradingOrder.getPublicOrdersByOwner"] * len(uids)
    inputs = {str(idx): {"userId": uid} for idx, uid in enumerate(uids)}
    method_str = ",".join(methods)
    encoded_input = quote(json.dumps(inputs))
    url = f"{BASE_URL}/{method_str}?batch=1&input={encoded_input}"

    for attempt in range(5):
        try:
            resp = session.get(url, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    return data
            elif resp.status_code == 429:
                wait_t = 2 ** attempt + 1
                logger.warning(f"Rate limited (429). Sleeping {wait_t}s...")
                time.sleep(wait_t)
                continue
            else:
                logger.warning(f"HTTP {resp.status_code} on batch. Attempt {attempt+1}/5")
                time.sleep(1)
        except requests.RequestException as e:
            logger.warning(f"Request exception: {e}. Attempt {attempt+1}/5")
            time.sleep(1.5)
    return [{} for _ in uids]


def main():
    session = requests.Session()
    session.headers.update({"accept": "*/*", "X-API-Key": API_KEY})

    # 1. Fetch active players
    active_user_ids = fetch_active_ranking(session)

    # 2. Load candidates
    candidate_ids = load_candidate_ids()
    total_candidates = len(candidate_ids)
    total_batches = (total_candidates + BATCH_SIZE - 1) // BATCH_SIZE

    # 3. Check for existing checkpoint
    processed_count = 0
    sellers_with_orders = {}  # uid -> {order_count, items}

    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE) as f:
                ckpt = json.load(f)
                processed_count = ckpt.get("processed_count", 0)
                sellers_with_orders = ckpt.get("sellers_with_orders", {})
                logger.info(f"Resuming from checkpoint: {processed_count}/{total_candidates} already processed, {len(sellers_with_orders)} sellers found.")
        except Exception as e:
            logger.warning(f"Could not load checkpoint: {e}")

    start_idx = processed_count
    start_time = time.time()
    last_ckpt_time = time.time()

    logger.info(f"Starting sweep across {total_candidates - start_idx} remaining candidates in {total_batches - (start_idx // BATCH_SIZE)} batches...")

    for i in range(start_idx, total_candidates, BATCH_SIZE):
        batch_uids = candidate_ids[i : i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1

        results = run_batch_orders(session, batch_uids)

        for idx, res in enumerate(results):
            if idx >= len(batch_uids):
                break
            uid = batch_uids[idx]
            data = res.get("result", {}).get("data", {})
            sells = data.get("sellOrders", [])
            if sells:
                items_sold = list({o.get("itemCode") for o in sells if o.get("itemCode")})
                sellers_with_orders[uid] = {
                    "count": len(sells),
                    "items": items_sold,
                }

        # Small pause between batches
        time.sleep(0.12)

        # Logging & checkpoint every 50 batches or at end
        if batch_num % 50 == 0 or (i + BATCH_SIZE) >= total_candidates:
            elapsed = time.time() - start_time
            done = min(i + BATCH_SIZE, total_candidates)
            pct = (done / total_candidates) * 100
            rate = done / max(elapsed, 0.001)
            eta_sec = (total_candidates - done) / max(rate, 0.001) if done < total_candidates else 0
            logger.info(
                f"[Batch {batch_num}/{total_batches}] {pct:.1f}% ({done}/{total_candidates}) | "
                f"Sellers found so far: {len(sellers_with_orders)} | "
                f"Elapsed: {elapsed:.0f}s, ETA: {eta_sec:.0f}s"
            )

            # Save checkpoint
            if time.time() - last_ckpt_time > 15 or (i + BATCH_SIZE) >= total_candidates:
                with open(CHECKPOINT_FILE, "w") as f:
                    json.dump({
                        "processed_count": done,
                        "sellers_with_orders": sellers_with_orders,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }, f)
                last_ckpt_time = time.time()

    # 4. Separate active players vs inactive sellers
    inactive_sellers = []
    for uid, info in sellers_with_orders.items():
        if uid not in active_user_ids:
            inactive_sellers.append(uid)

    final_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned_candidates": total_candidates,
        "active_users_count": len(active_user_ids),
        "inactive_sellers_count": len(inactive_sellers),
        "total_sellers_with_orders": len(sellers_with_orders),
        "active_users": sorted(active_user_ids),
        "inactive_sellers": sorted(inactive_sellers),
        "inactive_sellers_details": {
            uid: sellers_with_orders[uid] for uid in sorted(inactive_sellers)
        }
    }

    with open(FINAL_FILE, "w") as f:
        json.dump(final_data, f, indent=2)

    logger.info(f"=== SWEEP COMPLETED SUCCESSFULLY ===")
    logger.info(f"Total candidates scanned: {total_candidates}")
    logger.info(f"Active users (from ranking): {len(active_user_ids)}")
    logger.info(f"Total users with sell orders: {len(sellers_with_orders)}")
    logger.info(f"Inactive sellers with active lots: {len(inactive_sellers)}")
    logger.info(f"Saved results to {FINAL_FILE}")

    # Remove temporary checkpoint
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


if __name__ == "__main__":
    main()

