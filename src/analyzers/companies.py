from datetime import datetime, timezone
import logging
from typing import Any

from src import config
from src.api_client import TRPCClient

logger = logging.getLogger(__name__)


class CompanyAnalyzer:
    """
    Collects and aggregates global company production, wages (employees + managers),
    and country/regional tax revenues for players of Level 15+ (XP >= 6,300).
    Disabled companies (disabledAt != null) are excluded.
    """

    def __init__(self, client: TRPCClient):
        self.client = client

    def analyze(self) -> dict[str, Any]:
        now_ts = int(datetime.now(timezone.utc).timestamp())

        # ---------------------------------------------------------------------
        # 1. Fetch Countries & Regions (Taxes & Real Treasury Income)
        # ---------------------------------------------------------------------
        logger.info("Step 1/5: Fetching countries and regions data...")
        meta_responses = self.client.batch_call(
            [
                ("country.getAllCountries", {}),
                ("region.getRegionsObject", {}),
            ],
            raise_on_error=False,
        )

        countries_raw = (
            meta_responses[0].get("result", {}).get("data", [])
            if len(meta_responses) > 0 and isinstance(meta_responses[0], dict)
            else []
        )
        regions_raw = (
            meta_responses[1].get("result", {}).get("data", {})
            if len(meta_responses) > 1 and isinstance(meta_responses[1], dict)
            else {}
        )

        countries_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(countries_raw, list):
            for c in countries_raw:
                if not isinstance(c, dict) or not c.get("_id"):
                    continue
                cid = str(c["_id"])
                c_code = str(c.get("code") or cid[:6]).lower()
                taxes = c.get("taxes") or {}
                c_inc = c.get("income") or {}
                countries_by_id[cid] = {
                    "id": cid,
                    "code": c_code,
                    "name": str(c.get("name") or "Unknown"),
                    "taxes": {
                        "income": round(float(taxes.get("income", 0) or 0), 1),
                        "manager": round(float(taxes.get("manager", 0) or 0), 1),
                    },
                    "raw_income": {
                        "employee_tax": float(c_inc.get("employeeIncomeTax", 0.0) or 0.0),
                        "manager_tax": float(c_inc.get("managerIncomeTax", 0.0) or 0.0),
                        "development": float(c_inc.get("development", 0.0) or 0.0),
                        "total": float(c_inc.get("total", 0.0) or 0.0),
                    },
                }

        regions_by_id: dict[str, dict[str, Any]] = {}
        if isinstance(regions_raw, dict):
            for rid, r in regions_raw.items():
                if not isinstance(r, dict):
                    continue
                r_inc = r.get("income") or {}
                regions_by_id[str(rid)] = {
                    "id": str(rid),
                    "code": str(r.get("code") or ""),
                    "name": str(r.get("name") or "Unknown Region"),
                    "country_id": str(r.get("country") or ""),
                    "country_code": str(r.get("countryCode") or "").lower(),
                    "raw_company_count": int(r.get("companyCount", 0) or 0),
                    "raw_employee_count": int(r.get("employeeCount", 0) or 0),
                    "income": {
                        "employee_tax": float(r_inc.get("employeeIncomeTax", 0.0) or 0.0),
                        "manager_tax": float(r_inc.get("managerIncomeTax", 0.0) or 0.0),
                        "development": float(r_inc.get("development", 0.0) or 0.0),
                        "total": float(r_inc.get("total", 0.0) or 0.0),
                    },
                }

        logger.info(
            f"Loaded {len(countries_by_id)} countries and {len(regions_by_id)} regions."
        )

        # ---------------------------------------------------------------------
        # 2. Fetch Level 15+ Players from userLevel Ranking
        # ---------------------------------------------------------------------
        logger.info(
            f"Step 2/5: Fetching userLevel ranking (filtering XP >= {config.COMPANY_MIN_USER_XP}, Level 15+)..."
        )
        rank_resp = self.client.call(
            "ranking.getRanking",
            {"rankingType": "userLevel"},
            raise_on_error=False,
        )
        rank_data = (
            rank_resp.get("result", {}).get("data", {})
            if isinstance(rank_resp, dict)
            else {}
        )
        rank_items = (
            rank_data
            if isinstance(rank_data, list)
            else (rank_data.get("items", []) if isinstance(rank_data, dict) else [])
        )

        eligible_users: list[str] = []
        seen_users: set[str] = set()
        for entry in rank_items:
            if not isinstance(entry, dict):
                continue
            xp_val = float(entry.get("value", 0) or 0)
            uid = entry.get("user")
            if xp_val >= config.COMPANY_MIN_USER_XP and uid and uid not in seen_users:
                seen_users.add(uid)
                eligible_users.append(str(uid))

        logger.info(
            f"Found {len(eligible_users)} players at Level 15+ (out of {len(rank_items)} ranked users)."
        )

        # ---------------------------------------------------------------------
        # 3. Fetch Company IDs for Eligible Players
        # ---------------------------------------------------------------------
        logger.info("Step 3/5: Fetching company IDs for Level 15+ players...")
        company_ids: list[str] = []
        seen_companies: set[str] = set()

        user_calls = [
            ("company.getCompanies", {"userId": uid, "perPage": 100})
            for uid in eligible_users
        ]
        user_responses = self.client.batch_call(user_calls, raise_on_error=False)

        next_page_calls: list[tuple[str, dict[str, Any]]] = []
        for idx, resp in enumerate(user_responses):
            if not isinstance(resp, dict):
                continue
            d = resp.get("result", {}).get("data", {})
            if not isinstance(d, dict):
                continue
            for cid in d.get("items") or []:
                if cid and cid not in seen_companies:
                    seen_companies.add(cid)
                    company_ids.append(str(cid))
            nxt = d.get("nextCursor")
            if nxt and idx < len(eligible_users):
                next_page_calls.append(
                    (
                        "company.getCompanies",
                        {
                            "userId": eligible_users[idx],
                            "perPage": 100,
                            "cursor": nxt,
                        },
                    )
                )

        while next_page_calls:
            extra_resps = self.client.batch_call(next_page_calls, raise_on_error=False)
            follow_up: list[tuple[str, dict[str, Any]]] = []
            for idx, resp in enumerate(extra_resps):
                if not isinstance(resp, dict):
                    continue
                d = resp.get("result", {}).get("data", {})
                if not isinstance(d, dict):
                    continue
                for cid in d.get("items") or []:
                    if cid and cid not in seen_companies:
                        seen_companies.add(cid)
                        company_ids.append(str(cid))
                nxt = d.get("nextCursor")
                if nxt:
                    orig_uid = next_page_calls[idx][1]["userId"]
                    follow_up.append(
                        (
                            "company.getCompanies",
                            {"userId": orig_uid, "perPage": 100, "cursor": nxt},
                        )
                    )
            next_page_calls = follow_up

        logger.info(f"Collected {len(company_ids)} total companies owned by Level 15+ players.")

        # ---------------------------------------------------------------------
        # 4. Fetch Company Details (company.getById) & Filter Active Ones
        # ---------------------------------------------------------------------
        logger.info("Step 4/5: Fetching company details (company.getById)...")
        active_companies: dict[str, dict[str, Any]] = {}
        estimate_candidates: list[str] = []
        disabled_skipped = 0

        chunk_size = 5000
        for start in range(0, len(company_ids), chunk_size):
            sub_ids = company_ids[start : start + chunk_size]
            calls = [("company.getById", {"companyId": cid}) for cid in sub_ids]
            resps = self.client.batch_call(calls, raise_on_error=False)

            for resp in resps:
                if not isinstance(resp, dict):
                    continue
                c_data = resp.get("result", {}).get("data")
                if not isinstance(c_data, dict):
                    continue

                cid = str(c_data.get("_id") or "")
                if not cid:
                    continue

                # Completely ignore disabled companies
                if c_data.get("disabledAt"):
                    disabled_skipped += 1
                    continue

                item_code = str(c_data.get("itemCode") or "")
                if item_code not in config.ITEM_PRETTY_NAMES:
                    continue

                region_id = str(c_data.get("region") or "")
                upgrades = c_data.get("activeUpgradeLevels") or {}
                ae_level = int(upgrades.get("automatedEngine", 0) or 0)
                break_room = int(upgrades.get("breakRoom", 0) or 0)

                # Each Automated Engine level yields 1 PP/hr (24 PP/day)
                ae_pp_hr = float(ae_level) * 1.0

                active_companies[cid] = {
                    "id": cid,
                    "item_code": item_code,
                    "region_id": region_id,
                    "ae_level": ae_level,
                    "break_room": break_room,
                    "ae_pp_hr": ae_pp_hr,
                    "emp_pp_hr": 0.0,
                    "emp_wages_hr": 0.0,
                    "mgr_wages_hr": 0.0,
                }

                # A company can have employees/managers if it has Break Room >= 1
                # (or if the region has any employees / manager tax)
                if break_room > 0:
                    reg_info = regions_by_id.get(region_id)
                    if (
                        not reg_info
                        or reg_info["raw_employee_count"] > 0
                        or reg_info["income"]["employee_tax"] > 0
                        or reg_info["income"]["manager_tax"] > 0
                    ):
                        estimate_candidates.append(cid)

            logger.info(
                f"  Processed {min(start + chunk_size, len(company_ids))}/{len(company_ids)} companies "
                f"(active: {len(active_companies)}, disabled skipped: {disabled_skipped})..."
            )

        # ---------------------------------------------------------------------
        # 5. Fetch Employee & Manager Estimates (employee.getCompanyEstimate)
        # ---------------------------------------------------------------------
        logger.info(
            f"Step 5/5: Fetching live employee/manager estimates for {len(estimate_candidates)} companies with Break Rooms..."
        )
        for start in range(0, len(estimate_candidates), chunk_size):
            sub_ids = estimate_candidates[start : start + chunk_size]
            calls = [
                ("employee.getCompanyEstimate", {"companyId": cid}) for cid in sub_ids
            ]
            resps = self.client.batch_call(calls, raise_on_error=False)

            for idx, resp in enumerate(resps):
                if not isinstance(resp, dict):
                    continue
                est = resp.get("result", {}).get("data")
                if not isinstance(est, dict):
                    continue
                cid = sub_ids[idx]
                comp = active_companies.get(cid)
                if not comp:
                    continue

                comp["emp_pp_hr"] = float(est.get("production", 0.0) or 0.0)
                comp["emp_wages_hr"] = float(est.get("wageCost", 0.0) or 0.0)
                comp["mgr_wages_hr"] = float(est.get("managerCost", 0.0) or 0.0)

            if len(estimate_candidates) > chunk_size:
                logger.info(
                    f"  Estimated {min(start + chunk_size, len(estimate_candidates))}/{len(estimate_candidates)} companies..."
                )

        # ---------------------------------------------------------------------
        # 6. Aggregate Metrics by Items, Countries, and Regions
        # ---------------------------------------------------------------------
        return self._build_aggregated_snapshot(
            now_ts=now_ts,
            active_companies=active_companies,
            countries_by_id=countries_by_id,
            regions_by_id=regions_by_id,
            eligible_players_count=len(eligible_users),
            disabled_skipped=disabled_skipped,
        )

    def _build_aggregated_snapshot(
        self,
        now_ts: int,
        active_companies: dict[str, dict[str, Any]],
        countries_by_id: dict[str, dict[str, Any]],
        regions_by_id: dict[str, dict[str, Any]],
        eligible_players_count: int,
        disabled_skipped: int,
    ) -> dict[str, Any]:
        # Initialize per-item accumulators
        item_acc: dict[str, dict[str, Any]] = {
            code: {
                "code": code,
                "companies": 0,
                "ae_pp_hr": 0.0,
                "emp_pp_hr": 0.0,
                "pp_hr": 0.0,
                "emp_wages_hr": 0.0,
                "mgr_wages_hr": 0.0,
                "wages_hr": 0.0,
            }
            for code in config.ITEM_PRETTY_NAMES
        }

        # Initialize per-region accumulators
        region_acc: dict[str, dict[str, Any]] = {}
        for rid, r_info in regions_by_id.items():
            region_acc[rid] = {
                "id": rid,
                "code": r_info["code"],
                "name": r_info["name"],
                "country_id": r_info["country_id"],
                "country_code": r_info["country_code"],
                "companies": 0,
                "ae_pp_hr": 0.0,
                "emp_pp_hr": 0.0,
                "pp_hr": 0.0,
                "emp_wages_hr": 0.0,
                "mgr_wages_hr": 0.0,
                "wages_hr": 0.0,
                "income": r_info["income"],
            }

        global_companies = 0
        global_ae_pp_hr = 0.0
        global_emp_pp_hr = 0.0
        global_pp_hr = 0.0
        global_emp_wages_hr = 0.0
        global_mgr_wages_hr = 0.0
        global_wages_hr = 0.0

        for comp in active_companies.values():
            code = comp["item_code"]
            rid = comp["region_id"]
            ae_pp = comp["ae_pp_hr"]
            emp_pp = comp["emp_pp_hr"]
            tot_pp = ae_pp + emp_pp
            emp_w = comp["emp_wages_hr"]
            mgr_w = comp["mgr_wages_hr"]
            tot_w = emp_w + mgr_w

            global_companies += 1
            global_ae_pp_hr += ae_pp
            global_emp_pp_hr += emp_pp
            global_pp_hr += tot_pp
            global_emp_wages_hr += emp_w
            global_mgr_wages_hr += mgr_w
            global_wages_hr += tot_w

            if code in item_acc:
                ia = item_acc[code]
                ia["companies"] += 1
                ia["ae_pp_hr"] += ae_pp
                ia["emp_pp_hr"] += emp_pp
                ia["pp_hr"] += tot_pp
                ia["emp_wages_hr"] += emp_w
                ia["mgr_wages_hr"] += mgr_w
                ia["wages_hr"] += tot_w

            if rid in region_acc:
                ra = region_acc[rid]
                ra["companies"] += 1
                ra["ae_pp_hr"] += ae_pp
                ra["emp_pp_hr"] += emp_pp
                ra["pp_hr"] += tot_pp
                ra["emp_wages_hr"] += emp_w
                ra["mgr_wages_hr"] += mgr_w
                ra["wages_hr"] += tot_w

        # Finalize By Items dictionary
        by_items: dict[str, dict[str, Any]] = {}
        for code, ia in item_acc.items():
            pp_unit = max(1, int(config.ITEM_PRODUCTION_POINTS.get(code, 1) or 1))
            c_cnt = ia["companies"]
            pp_h = round(ia["pp_hr"], 2)
            units_h = round(pp_h / pp_unit, 2)
            w_h = round(ia["wages_hr"], 4)

            by_items[code] = {
                "code": code,
                "pp_per_unit": pp_unit,
                "companies": c_cnt,
                "companies_share_pct": (
                    round((c_cnt / global_companies) * 100, 2)
                    if global_companies > 0
                    else 0.0
                ),
                "pp_hr": pp_h,
                "pp_24h": round(pp_h * 24, 1),
                "pp_share_pct": (
                    round((pp_h / global_pp_hr) * 100, 2)
                    if global_pp_hr > 0
                    else 0.0
                ),
                "ae_pp_hr": round(ia["ae_pp_hr"], 2),
                "emp_pp_hr": round(ia["emp_pp_hr"], 2),
                "units_hr": units_h,
                "units_24h": round(units_h * 24, 1),
                "wages_hr": w_h,
                "wages_24h": round(w_h * 24, 2),
                "emp_wages_hr": round(ia["emp_wages_hr"], 4),
                "mgr_wages_hr": round(ia["mgr_wages_hr"], 4),
            }

        # Group regions by owning country_id and finalize By Countries
        regions_by_country: dict[str, list[dict[str, Any]]] = {}
        for ra in region_acc.values():
            cid = ra["country_id"]
            if not cid:
                continue
            regions_by_country.setdefault(cid, []).append(ra)

        by_countries: dict[str, dict[str, Any]] = {}
        global_emp_tax = 0.0
        global_mgr_tax = 0.0
        global_dev_inc = 0.0
        global_tot_inc = 0.0

        all_country_ids = set(countries_by_id.keys()) | set(regions_by_country.keys())
        for cid in all_country_ids:
            c_meta = countries_by_id.get(
                cid,
                {
                    "id": cid,
                    "code": cid[:6].lower(),
                    "name": "Unknown Country",
                    "taxes": {"income": 0.0, "manager": 0.0},
                    "raw_income": {
                        "employee_tax": 0.0,
                        "manager_tax": 0.0,
                        "development": 0.0,
                        "total": 0.0,
                    },
                },
            )
            c_regs = regions_by_country.get(cid, [])
            c_comp = sum(r["companies"] for r in c_regs)
            c_pp_hr = sum(r["pp_hr"] for r in c_regs)
            c_ae_pp_hr = sum(r["ae_pp_hr"] for r in c_regs)
            c_emp_pp_hr = sum(r["emp_pp_hr"] for r in c_regs)
            c_wages_hr = sum(r["wages_hr"] for r in c_regs)
            c_emp_wages_hr = sum(r["emp_wages_hr"] for r in c_regs)
            c_mgr_wages_hr = sum(r["mgr_wages_hr"] for r in c_regs)

            if c_regs:
                c_emp_tax = sum(r["income"]["employee_tax"] for r in c_regs)
                c_mgr_tax = sum(r["income"]["manager_tax"] for r in c_regs)
                c_dev_inc = sum(r["income"]["development"] for r in c_regs)
                c_tot_inc = sum(r["income"]["total"] for r in c_regs)
            else:
                raw_inc = c_meta["raw_income"]
                c_emp_tax = raw_inc["employee_tax"]
                c_mgr_tax = raw_inc["manager_tax"]
                c_dev_inc = raw_inc["development"]
                c_tot_inc = raw_inc["total"]

            # Skip countries that have 0 regions and 0 companies and 0 income
            if not c_regs and c_comp == 0 and c_tot_inc <= 0:
                continue

            global_emp_tax += c_emp_tax
            global_mgr_tax += c_mgr_tax
            global_dev_inc += c_dev_inc
            global_tot_inc += c_tot_inc

            formatted_regions: list[dict[str, Any]] = []
            for r in sorted(
                c_regs,
                key=lambda x: (x["pp_hr"], x["companies"], x["income"]["total"]),
                reverse=True,
            ):
                r_comp = r["companies"]
                r_pp = round(r["pp_hr"], 2)
                r_w = round(r["wages_hr"], 4)
                r_inc = r["income"]
                formatted_regions.append(
                    {
                        "id": r["id"],
                        "code": r["code"],
                        "name": r["name"],
                        "companies": r_comp,
                        "companies_country_share_pct": (
                            round((r_comp / c_comp) * 100, 1) if c_comp > 0 else 0.0
                        ),
                        "pp_hr": r_pp,
                        "pp_24h": round(r_pp * 24, 1),
                        "pp_country_share_pct": (
                            round((r_pp / c_pp_hr) * 100, 1) if c_pp_hr > 0 else 0.0
                        ),
                        "wages_hr": r_w,
                        "wages_24h": round(r_w * 24, 2),
                        "emp_wages_hr": round(r["emp_wages_hr"], 4),
                        "mgr_wages_hr": round(r["mgr_wages_hr"], 4),
                        "income": {
                            "employee_tax": round(r_inc["employee_tax"], 4),
                            "manager_tax": round(r_inc["manager_tax"], 4),
                            "development": round(r_inc["development"], 4),
                            "total": round(r_inc["total"], 4),
                        },
                    }
                )

            c_key = c_meta["code"] or cid
            # Ensure unique key if two countries ever share a short code
            if c_key in by_countries:
                c_key = f"{c_key}_{cid[:4]}"

            c_pp_rounded = round(c_pp_hr, 2)
            c_w_rounded = round(c_wages_hr, 4)

            by_countries[c_key] = {
                "id": cid,
                "code": c_key,
                "name": c_meta["name"],
                "region_count": len(formatted_regions),
                "taxes": c_meta["taxes"],
                "companies": c_comp,
                "companies_share_pct": (
                    round((c_comp / global_companies) * 100, 2)
                    if global_companies > 0
                    else 0.0
                ),
                "pp_hr": c_pp_rounded,
                "pp_24h": round(c_pp_rounded * 24, 1),
                "pp_share_pct": (
                    round((c_pp_hr / global_pp_hr) * 100, 2)
                    if global_pp_hr > 0
                    else 0.0
                ),
                "ae_pp_hr": round(c_ae_pp_hr, 2),
                "emp_pp_hr": round(c_emp_pp_hr, 2),
                "wages_hr": c_w_rounded,
                "wages_24h": round(c_w_rounded * 24, 2),
                "emp_wages_hr": round(c_emp_wages_hr, 4),
                "mgr_wages_hr": round(c_mgr_wages_hr, 4),
                "income": {
                    "employee_tax": round(c_emp_tax, 4),
                    "manager_tax": round(c_mgr_tax, 4),
                    "development": round(c_dev_inc, 4),
                    "total": round(c_tot_inc, 4),
                },
                "regions": formatted_regions,
            }

        summary = {
            "eligible_players": eligible_players_count,
            "disabled_skipped": disabled_skipped,
            "total_companies": global_companies,
            "total_pp_hr": round(global_pp_hr, 2),
            "total_pp_24h": round(global_pp_hr * 24, 1),
            "total_ae_pp_hr": round(global_ae_pp_hr, 2),
            "total_emp_pp_hr": round(global_emp_pp_hr, 2),
            "total_wages_hr": round(global_wages_hr, 4),
            "total_wages_24h": round(global_wages_hr * 24, 2),
            "total_emp_wages_hr": round(global_emp_wages_hr, 4),
            "total_mgr_wages_hr": round(global_mgr_wages_hr, 4),
            "global_tax_income": {
                "employee_tax": round(global_emp_tax, 4),
                "manager_tax": round(global_mgr_tax, 4),
                "development": round(global_dev_inc, 4),
                "total": round(global_tot_inc, 4),
            },
        }

        return {
            "timestamp": now_ts,
            "summary": summary,
            "by_items": by_items,
            "by_countries": by_countries,
        }
