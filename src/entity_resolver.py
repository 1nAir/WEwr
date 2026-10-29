import logging
import time
from typing import Any

from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class EntityResolver:
    """
    Centralized entity metadata resolver with in-memory caching during execution.
    Resolves countries, parties, military units (MUs), and users on the fly.
    """

    _mem_cache: dict[str, dict[str, Any]] = {}
    _attempted_uids: set[str] = set()
    _countries_loaded: bool = False

    def __init__(self, client: TRPCClient):
        self.client = client
        self.cache = self._mem_cache

    def resolve(
        self,
        entity_ids: set[str] | list[str],
        force_refresh_ids: set[str] | list[str] | None = None,
        ttl_seconds: int = 86400,
    ) -> dict[str, dict[str, Any]]:
        now_ts = int(time.time())
        entity_set = {eid for eid in entity_ids if eid}
        force_set = {eid for eid in (force_refresh_ids or []) if eid}

        # 1. Refresh organizations (countries, parties, MUs) once per process run
        if not EntityResolver._countries_loaded:
            # 1a. Countries
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

            # 1b. Parties
            p_cursor = None
            while True:
                p_params: dict[str, Any] = {"limit": 100}
                if p_cursor:
                    p_params["cursor"] = p_cursor
                p_res = self.client.call("party.getManyPaginated", p_params, raise_on_error=False)
                p_data = p_res.get("result", {}).get("data", {}) if isinstance(p_res, dict) else {}
                p_items = p_data.get("items", [])
                for p in p_items:
                    pid = p.get("_id")
                    if pid:
                        self.cache[pid] = {
                            "id": pid,
                            "name": p.get("name", "Party"),
                            "type": "party",
                            "avatar_url": p.get("avatarUrl"),
                            "profile_url": f"https://app.warera.io/party/{pid}",
                            "updated_at": now_ts,
                        }
                p_cursor = p_data.get("nextCursor")
                if not p_cursor or not p_items:
                    break

            # 1c. Military Units (MUs)
            m_cursor = None
            while True:
                m_params: dict[str, Any] = {"limit": 100}
                if m_cursor:
                    m_params["cursor"] = m_cursor
                m_res = self.client.call("mu.getManyPaginated", m_params, raise_on_error=False)
                m_data = m_res.get("result", {}).get("data", {}) if isinstance(m_res, dict) else {}
                m_items = m_data.get("items", [])
                for m in m_items:
                    mid = m.get("_id")
                    if mid:
                        self.cache[mid] = {
                            "id": mid,
                            "name": m.get("name", "Military Unit"),
                            "type": "mu",
                            "avatar_url": m.get("avatarUrl"),
                            "profile_url": f"https://app.warera.io/mu/{mid}",
                            "updated_at": now_ts,
                        }
                m_cursor = m_data.get("nextCursor")
                if not m_cursor or not m_items:
                    break

            EntityResolver._countries_loaded = True

        # 2. Identify user IDs needing resolution
        ids_to_resolve = []
        for eid in entity_set:
            if eid in self.cache and self.cache[eid].get("type") in ("country", "party", "mu"):
                continue
            if eid in EntityResolver._attempted_uids and eid not in force_set:
                continue
            cached = self.cache.get(eid)
            needs_resolve = (
                not cached
                or eid in force_set
                or str(cached.get("name", "")).startswith("Player_")
            )
            if needs_resolve:
                ids_to_resolve.append(eid)

        if ids_to_resolve:
            logger.info(
                f"Resolving metadata for {len(ids_to_resolve)} entities via user.getUserLite..."
            )
            calls = [("user.getUserLite", {"userId": uid}) for uid in ids_to_resolve]
            resps = self.client.batch_call(
                calls, raise_on_error=False, batch_size=self.client.BATCH_SIZE
            )

            for idx, r in enumerate(resps):
                uid = ids_to_resolve[idx]
                EntityResolver._attempted_uids.add(uid)
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
                    self.cache[uid] = {
                        "id": uid,
                        "name": f"Player_{uid[:6]}",
                        "type": "user",
                        "avatar_url": None,
                        "profile_url": f"https://app.warera.io/user/{uid}",
                        "updated_at": now_ts,
                    }

        return self.cache

    def get_info(self, eid: str) -> dict[str, Any]:
        if eid in self.cache:
            return self.cache[eid]
        return {
            "id": eid,
            "name": f"Player_{eid[:6]}",
            "type": "user",
            "avatar_url": None,
            "profile_url": f"https://app.warera.io/user/{eid}",
        }
