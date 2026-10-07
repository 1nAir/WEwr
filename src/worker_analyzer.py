import logging
from typing import Any

from src import config
from src.api_client import TRPCClient
from src.region_analyzer import RegionBonusAnalyzer

logger = logging.getLogger(__name__)


class WorkerAnalyzer:
    """Analyzes worker profitability across items and production locations.

    Deducts income tax and market labor wage from production profits to find
    optimal places for employing workers.
    """

    def __init__(self, client: TRPCClient, region_analyzer: RegionBonusAnalyzer | None = None):
        self.client = client
        self.region_analyzer = region_analyzer or RegionBonusAnalyzer(client)

    def get_market_wage(self) -> dict[str, Any]:
        """Fetches top work offers, filters out citizenship requirements,
        skips top 4 offers, and computes the average wage after tax of the next 4.
        """
        logger.info("Fetching labor market offers...")
        res = self.client.call(
            "workOffer.getWorkOffersPaginated",
            {"limit": 25, **config.WORKER_PLAYER_STATS},
        )
        items = res.get("result", {}).get("data", {}).get("items", [])

        # Filter out citizenship-restricted offers (only open market offers)
        open_offers = [it for it in items if not it.get("citizenship")]

        if len(open_offers) < 8:
            logger.warning(
                f"Less than 8 open offers found ({len(open_offers)}). Falling back to available offers."
            )
            used = open_offers[4:] if len(open_offers) > 4 else open_offers
        else:
            used = open_offers[4:8]

        if used:
            avg_wage = sum(float(it.get("wageAfterTax", 0)) for it in used) / len(used)
        else:
            avg_wage = 0.142  # Fallback default

        avg_wage = round(avg_wage, 3)
        logger.info(
            f"Calculated labor market wage (after tax): {avg_wage} ₿/PP "
            f"(used {len(used)} offers from {len(open_offers)} open offers)"
        )

        return {
            "avg_wage_after_tax": avg_wage,
            "top_skipped": [round(float(it.get("wageAfterTax", 0)), 3) for it in open_offers[:4]],
            "used_offers": [round(float(it.get("wageAfterTax", 0)), 3) for it in used],
            "total_open_offers": len(open_offers),
        }

    def calculate_worker_snapshot(
        self,
        market_snapshot: dict[str, Any],
        bonuses_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Calculates worker profitability for all items across candidate locations."""
        wage_info = self.get_market_wage()
        avg_wage = wage_info["avg_wage_after_tax"]

        if bonuses_data is None:
            bonuses_data = self.region_analyzer.collect_all_bonuses()

        by_item = bonuses_data.get("by_item", {})
        worker_items: dict[str, list[dict[str, Any]]] = {}

        for item, m_data in market_snapshot.items():
            pp = m_data.get("production_points", 0)
            if pp <= 0:
                continue

            locs = by_item.get(item, [])
            evaluated_locs = []

            for loc in locs:
                bonus = float(loc.get("total_bonus", 0))
                tax = float(loc.get("tax_percent", 0))

                tax_rate = min(max(tax / 100.0, 0.0), 0.99)
                gross_wage = avg_wage / (1.0 - tax_rate) if tax_rate < 1.0 else avg_wage
                wage_tax = gross_wage - avg_wage

                mult = 1.0 + (bonus / 100.0)
                mult_f5 = 1.0 + ((bonus + 5.0) / 100.0)
                mult_f10 = 1.0 + ((bonus + 10.0) / 100.0)

                loc_metrics: dict[str, float] = {
                    "gross_wage": round(gross_wage, 4),
                    "wage_tax": round(wage_tax, 4),
                }
                for m_type in ["min", "avg", "max"]:
                    net_p = float(m_data.get(f"{m_type}_price", 0))

                    # Product profitability per PP (without worker cost)
                    prod_pp = (net_p * mult) / pp
                    prod_f5 = (net_p * mult_f5) / pp
                    prod_f10 = (net_p * mult_f10) / pp

                    # Net profit after deducting gross wage (market wage + wage tax)
                    worker_net = prod_pp - gross_wage
                    worker_f5 = prod_f5 - gross_wage
                    worker_f10 = prod_f10 - gross_wage

                    loc_metrics[f"{m_type}_pp"] = round(worker_net, 4)
                    loc_metrics[f"{m_type}_pp_f5"] = round(worker_f5, 4)
                    loc_metrics[f"{m_type}_pp_f10"] = round(worker_f10, 4)
                    loc_metrics[f"prod_{m_type}_pp"] = round(prod_pp, 4)
                    loc_metrics[f"prod_{m_type}_pp_f5"] = round(prod_f5, 4)
                    loc_metrics[f"prod_{m_type}_pp_f10"] = round(prod_f10, 4)
                    loc_metrics[f"gross_{m_type}_pp"] = round(prod_pp, 4)
                    loc_metrics[f"gross_{m_type}_pp_f5"] = round(prod_f5, 4)
                    loc_metrics[f"gross_{m_type}_pp_f10"] = round(prod_f10, 4)

                reg_list = loc.get("regions", [])
                if loc.get("has_deposit") and reg_list:
                    reg_name = reg_list[0].get("name", "Unknown")
                else:
                    reg_name = "All regions"

                evaluated_locs.append(
                    {
                        "country_name": loc.get("country_name", "Unknown"),
                        "region_name": reg_name,
                        "tax_percent": int(tax) if tax.is_integer() else round(tax, 2),
                        "total_bonus": round(bonus, 2),
                        "bonus_breakdown": loc.get("breakdown", {}),
                        "deposit_ends_at": loc.get("deposit_ends_at"),
                        "has_deposit": loc.get("has_deposit", False),
                        **loc_metrics,
                    }
                )

            # Sort candidate locations by min_pp desc by default
            evaluated_locs.sort(key=lambda x: x["min_pp"], reverse=True)
            worker_items[item] = evaluated_locs

        return {
            "market_wage": wage_info,
            "items": worker_items,
        }
