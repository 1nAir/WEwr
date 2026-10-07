import json
import os
from datetime import datetime, timezone
from typing import Any

from src import config, html_templates


class ReportGenerator:
    """
    Orchestrates the creation of the HTML report.
    """

    @staticmethod
    def _chart_safe_history(
        item_code: str, item_history: dict[str, Any]
    ) -> dict[str, Any]:
        """Return a copy of a history item with zero placeholders hidden.

        A zero is a missing-data sentinel in these chart series, not a valid
        measurement.  Converting it to ``None`` makes it a gap in Chart.js
        while retaining its timestamp and every non-zero historical value.
        The persisted history is deliberately never changed here.
        """
        return {
            metric: [None if value == 0 else value for value in values]
            if isinstance(values, list)
            else values
            for metric, values in item_history.items()
        }

    @staticmethod
    def generate(
        history: dict[str, Any],
        comp_history: dict[str, Any],
        current_snapshot: dict[str, Any],
        market_timestamp: int | None = None,
        comp_timestamp: int | None = None,
        workers_snapshot: dict[str, Any] | None = None,
        workers_timestamp: int | None = None,
        workers_history: dict[str, Any] | None = None,
    ):
        """Builds the index.html file."""
        print("Generating HTML report...")

        # Fallback to history labels if timestamps not provided
        current_time = int(datetime.now(timezone.utc).timestamp())
        m_ts = (
            market_timestamp
            or (history.get("labels") and history["labels"][-1])
            or current_time
        )
        c_ts = (
            comp_timestamp
            or (comp_history.get("labels") and comp_history["labels"][-1])
            or m_ts
        )
        w_ts = (
            workers_timestamp
            or (workers_history and workers_history.get("labels") and workers_history["labels"][-1])
            or m_ts
        )

        # Prepare table data structure for JS
        table_data = []

        for item_code, metrics in current_snapshot.items():
            # Enrich resources with pretty names
            resources = metrics.get("resources", [])
            for r in resources:
                r["pretty_name"] = config.ITEM_PRETTY_NAMES.get(r["item"], r["item"])

            # Get history for this item
            item_history = ReportGenerator._chart_safe_history(
                item_code, history["items"].get(item_code, {})
            )
            item_comp_history = ReportGenerator._chart_safe_history(
                item_code, comp_history["items"].get(item_code, {})
            )
            # Worker history is raw without synthetic clipping or thresholds
            item_worker_history = (
                workers_history["items"].get(item_code, {})
                if workers_history and "items" in workers_history
                else {}
            )

            row = {
                "item": item_code,
                "pretty_name": config.ITEM_PRETTY_NAMES.get(item_code, item_code),
                **metrics,  # Includes min_pp, prices, bonuses, location info
                "history": item_history,
                "comp_history": item_comp_history,
                "worker_history": item_worker_history,
                "labels": history.get("labels", []),  # Using labels (Unix timestamps)
                "comp_labels": comp_history.get("labels", []),
                "worker_labels": workers_history.get("labels", []) if workers_history else [],
                "worker_wages": workers_history.get("wages", []) if workers_history else [],
            }
            tax = metrics.get("tax_percent")
            if (tax is None or tax == 0) and workers_snapshot and "items" in workers_snapshot:
                w_locs = workers_snapshot["items"].get(item_code, [])
                for wl in w_locs:
                    if wl.get("country_name") == metrics.get("country_name"):
                        tax = wl.get("tax_percent")
                        break
                if (tax is None or tax == 0) and w_locs:
                    tax = w_locs[0].get("tax_percent")
            if tax is not None:
                row["tax_percent"] = tax

            table_data.append(row)

        # Serialize data for JS injection
        table_data_json = json.dumps(table_data)
        workers_data_json = json.dumps(workers_snapshot or {})
        metric_labels_json = json.dumps(config.METRIC_LABELS)
        item_colors_json = json.dumps(config.ITEM_COLORS)
        item_short_names_json = json.dumps(config.ITEM_SHORT_NAMES)
        production_lines_json = json.dumps(config.PRODUCTION_LINES)

        full_html = html_templates.get_base_template(
            table_data_json=table_data_json,
            workers_data_json=workers_data_json,
            metric_labels_json=metric_labels_json,
            item_colors_json=item_colors_json,
            item_short_names_json=item_short_names_json,
            production_lines_json=production_lines_json,
            timestamp=m_ts,
            market_timestamp=m_ts,
            comp_timestamp=c_ts,
            workers_timestamp=w_ts,
        )

        os.makedirs(os.path.dirname(config.OUTPUT_HTML), exist_ok=True)
        with open(config.OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(full_html)

        print(f"Report generated successfully: {config.OUTPUT_HTML}")
