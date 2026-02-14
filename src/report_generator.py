import json
from datetime import datetime, timezone
from typing import Any, Dict

from src import config, html_templates


class ReportGenerator:
    """
    Orchestrates the creation of the HTML report.
    """

    @staticmethod
    def generate(
        history: Dict[str, Any],
        comp_history: Dict[str, Any],
        current_snapshot: Dict[str, Any],
    ):
        """Builds the index.html file."""
        print("Generating HTML report...")

        # Prepare table data structure for JS
        table_data = []

        for item_code, metrics in current_snapshot.items():
            # Enrich resources with pretty names
            resources = metrics.get("resources", [])
            for r in resources:
                r["pretty_name"] = config.ITEM_PRETTY_NAMES.get(r["item"], r["item"])

            # Get history for this item
            item_history = history["items"].get(item_code, {})
            item_comp_history = comp_history["items"].get(item_code, {})

            row = {
                "item": item_code,
                "pretty_name": config.ITEM_PRETTY_NAMES.get(item_code, item_code),
                **metrics,  # Includes min_pp, prices, bonuses, location info
                "history": item_history,
                "comp_history": item_comp_history,
                "labels": history.get("labels", []),  # Using labels (Unix timestamps)
                "comp_labels": comp_history.get("labels", []),
            }
            table_data.append(row)

        # Serialize data for JS injection
        table_data_json = json.dumps(table_data)
        metric_labels_json = json.dumps(config.METRIC_LABELS)
        item_colors_json = json.dumps(config.ITEM_COLORS)
        item_short_names_json = json.dumps(config.ITEM_SHORT_NAMES)
        production_lines_json = json.dumps(config.PRODUCTION_LINES)
        timestamp = int(datetime.now(timezone.utc).timestamp())

        full_html = html_templates.get_base_template(
            table_data_json=table_data_json,
            metric_labels_json=metric_labels_json,
            item_colors_json=item_colors_json,
            item_short_names_json=item_short_names_json,
            production_lines_json=production_lines_json,
            timestamp=timestamp,
        )

        with open(config.OUTPUT_HTML, "w", encoding="utf-8") as f:
            f.write(full_html)

        print(f"Report generated successfully: {config.OUTPUT_HTML}")
