import json
import os
import statistics
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from src import config


class DataProcessor:
    """
    Handles history management and integrates the original Spike Cleaner logic.
    """

    @staticmethod
    def load_history() -> Dict[str, Any]:
        if os.path.exists(config.HISTORY_FILE):
            try:
                with open(config.HISTORY_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        return {"labels": [], "items": {}}

                    # Ensure required keys exist
                    data.setdefault("labels", [])
                    data.setdefault("items", {})
                    return data
            except json.JSONDecodeError:
                pass
        return {"labels": [], "items": {}}

    @staticmethod
    def save_history(data: Dict[str, Any]) -> None:
        with open(config.HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=None)

    @staticmethod
    def append_snapshot(
        history: Dict[str, Any], current_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Adds new data point and maintains history size."""
        # Restore old logic: Unix timestamp (int)
        timestamp = int(datetime.now(timezone.utc).timestamp())
        history["labels"].append(timestamp)

        # Ensure item structure exists
        current_len = len(history["labels"])
        for item_name in current_data.keys():
            if item_name not in history["items"]:
                # Pad with 0s to align with history length (minus the new point we just added)
                history["items"][item_name] = {
                    "min_pp": [0.0] * (current_len - 1),
                    "avg_pp": [0.0] * (current_len - 1),
                    "max_pp": [0.0] * (current_len - 1),
                }

        # Append new values
        for item_name, metrics in current_data.items():
            item_hist = history["items"][item_name]
            item_hist["min_pp"].append(metrics["min_pp"])
            item_hist["avg_pp"].append(metrics["avg_pp"])
            item_hist["max_pp"].append(metrics["max_pp"])

        # Trim to MAX_HISTORY_POINTS
        if len(history["labels"]) > config.MAX_HISTORY_POINTS:
            history["labels"] = history["labels"][-config.MAX_HISTORY_POINTS :]
            for item in history["items"].values():
                for key in ["min_pp", "avg_pp", "max_pp"]:
                    item[key] = item[key][-config.MAX_HISTORY_POINTS :]

        return history

    # --- Original Spike Cleaner Logic ---

    @staticmethod
    def _get_global_thresholds(data: Dict[str, Any]) -> Tuple[float, float]:
        """
        Calculates thresholds based on global market median.
        Logic preserved from original spike_cleaner.py
        """
        all_values = []
        for item_data in data["items"].values():
            for metric in ["min_pp", "avg_pp", "max_pp"]:
                if metric in item_data:
                    valid_vals = [x for x in item_data[metric] if x > 0.001]
                    all_values.extend(valid_vals)

        if not all_values:
            return 0.05, 0.15

        median_val = statistics.median(all_values)
        min_val_thresh = median_val * config.GLOBAL_COEF_MIN
        global_thresh = median_val * config.GLOBAL_COEF_THRESH
        return min_val_thresh, global_thresh

    @staticmethod
    def _smooth_series(
        series: List[float], min_abs_val: float, min_val_thresh: float
    ) -> Tuple[List[float], int]:
        """
        Recursive smoothing logic exactly as in original spike_cleaner.py
        """
        cleaned = series[:]
        n = len(cleaned)
        changes_count = 0
        i = 1

        while i < n - 1:
            prev_val = cleaned[i - 1]
            curr_val = cleaned[i]

            # 1. Protection from zero/dips (Logic from spike_cleaner.py)
            if curr_val < min_abs_val:
                next_val = cleaned[i + 1]
                avg = (prev_val + next_val) / 2
                if avg < min_abs_val:
                    avg = min_abs_val * 1.1
                cleaned[i] = round(avg, 4)
                changes_count += 1
                i += 1
                continue

            if prev_val <= 0.001:
                i += 1
                continue

            # 2. GROUP OUTLIERS (5, 4, 3, 2 points) - Was missing in refactoring
            found_group = False
            for size in [5, 4, 3, 2]:
                if i < n - size:
                    end_neighbor_val = cleaned[i + size]
                    step_size = (end_neighbor_val - prev_val) / (size + 1)
                    is_group_outlier = True
                    expected_vals = []

                    for k in range(size):
                        check_val = cleaned[i + k]
                        expected_val = prev_val + step_size * (k + 1)
                        expected_vals.append(expected_val)

                        if not (
                            (check_val > expected_val * config.THRESHOLD_MULTIPLIER)
                            and (check_val > min_val_thresh)
                        ):
                            is_group_outlier = False
                            break

                    if is_group_outlier:
                        for k in range(size):
                            cleaned[i + k] = round(expected_vals[k], 4)
                        changes_count += size
                        i += size
                        found_group = True
                        break

            if found_group:
                continue

            # 3. SINGLE SPIKE
            next_val = cleaned[i + 1]
            if next_val > 0.001:
                expected = (prev_val + next_val) / 2
                is_spike = (curr_val > expected * config.THRESHOLD_MULTIPLIER) and (
                    curr_val > min_val_thresh
                )

                if is_spike:
                    cleaned[i] = round(expected, 4)
                    changes_count += 1

            i += 1

        # Recursive pass if changes happened
        if changes_count > 0:
            cleaned, extra_changes = DataProcessor._smooth_series(
                cleaned, min_abs_val, min_val_thresh
            )
            changes_count += extra_changes

        return cleaned, changes_count

    @classmethod
    def clean_history(cls, history: Dict[str, Any]) -> Dict[str, Any]:
        """Runs the cleaning process on the full history object."""

        glob_min, glob_thresh = cls._get_global_thresholds(history)
        total_fixes = 0

        for item_name, item_data in history["items"].items():
            for metric in ["min_pp", "avg_pp", "max_pp"]:
                if metric in item_data:
                    original_series = item_data[metric]
                    new_series, count = cls._smooth_series(
                        original_series, glob_min, glob_thresh
                    )

                    if count > 0:
                        history["items"][item_name][metric] = new_series
                        total_fixes += count

        if total_fixes > 0:
            print(f"SpikeCleaner: Fixed {total_fixes} anomalies.")

        return history
