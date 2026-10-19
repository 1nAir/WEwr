import logging
import time
from typing import Any

from src.api_client import TRPCClient
from src.data_processor import DataProcessor

logger = logging.getLogger(__name__)


class EntityResolver:
    """
    Centralized entity metadata resolver with persistent caching and intelligent auto-refresh.
    Guarantees:
    1. Active leaders / current top participants are actively refreshed from API on every run so name/avatar changes are immediate.
    2. Cached records are preserved so network glitches or historical entities never degrade to 'Player_xxx'.
    3. Countries, Parties, and Military Units (MUs) are resolved properly.
    """

    def __init__(self, client: TRPCClient):
        self.client = client
        self.cache: dict[str, dict[str, Any]] = DataProcessor.load_player_meta_cache() or {}

    def resolve(
        self,
        entity_ids: set[str] | list[str],
        force_refresh_ids: set[str] | list[str] | None = None,
        ttl_seconds: int = 86400,  # 24 hours
    ) -> dict[str, dict[str, Any]]:
        now_ts = int(time.time())
        entity_set = {eid for eid in entity_ids if eid}
        force_set = {eid for eid in (force_refresh_ids or []) if eid}

        # 1. Always refresh countries
        c_res = self.client.call("country.getAllCountries", {}, raise_on_error=False)
        countries_data = (
            c_res.get("result", {}).get("data", []) if isinstance(c_res, dict) else []
        )
        for c in countries_data:
            cid = c.get("_id")
            if cid:
                code = c.get("code", "")
                self.cache[cid] = {
                    "id": cid,
                    "name": c.get("name", "Country"),
                    "type": "country",
                    "code": code,
                    "avatar_url": f"https://flagcdn.com/w40/{code.lower()}.png" if code else None,
                    "profile_url": f"https://app.warera.io/country/{cid}",
                    "updated_at": now_ts,
                }

        # 2. Check which IDs need user resolution
        ids_to_resolve = []
        for eid in entity_set:
            if eid in self.cache and self.cache[eid].get("type") in ("country", "party", "mu"):
                continue
            cached = self.cache.get(eid)
            needs_resolve = (
                not cached
                or eid in force_set
                or (now_ts - cached.get("updated_at", 0) > ttl_seconds)
                or cached.get("name", "").startswith("Player_")
            )
            if needs_resolve:
                ids_to_resolve.append(eid)

        if ids_to_resolve:
            logger.info(f"Resolving/refreshing metadata for {len(ids_to_resolve)} entities via user.getUserLite...")
            calls = [("user.getUserLite", {"userId": uid}) for uid in ids_to_resolve]
            resps = self.client.batch_call(calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE)

            for idx, r in enumerate(resps):
                uid = ids_to_resolve[idx]
                if isinstance(r, dict) and "result" in r:
                    udata = r.get("result", {}).get("data", {})
                    self.cache[uid] = {
                        "id": uid,
                        "name": udata.get("username", f"Player_{uid[:6]}"),
                        "type": "user",
                        "avatar_url": udata.get("avatarUrl"),
                        "profile_url": f"https://app.warera.io/user/{uid}",
                        "updated_at": now_ts,
                    }
                else:
                    # If API call failed or user not found, preserve non-fallback cache if present
                    if uid not in self.cache or self.cache[uid].get("name", "").startswith("Player_"):
                        self.cache[uid] = {
                            "id": uid,
                            "name": f"Player_{uid[:6]}",
                            "type": "user",
                            "avatar_url": None,
                            "profile_url": f"https://app.warera.io/user/{uid}",
                            "updated_at": now_ts,
                        }

            DataProcessor.save_player_meta_cache(self.cache)

        return self.cache

    def get_info(self, eid: str) -> dict[str, Any]:
        """Returns entity dict from cache or default fallback."""
        if eid in self.cache:
            return self.cache[eid]
        return {
            "id": eid,
            "name": f"Player_{eid[:6]}",
            "type": "user",
            "avatar_url": None,
            "profile_url": f"https://app.warera.io/user/{eid}",
        }

