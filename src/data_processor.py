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
    def _load_json(filepath: str) -> Dict[str, Any]:
        """Generic loader for history files."""
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        return {"labels": [], "items": {}}
                    data.setdefault("labels", [])
                    data.setdefault("items", {})
                    return data
            except json.JSONDecodeError:
                pass
        return {"labels": [], "items": {}}

    @staticmethod
    def _save_json(filepath: str, data: Dict[str, Any]) -> None:
        """Generic saver for history files."""
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=None)

    @staticmethod
    def _append_metrics(
        history: Dict[str, Any],
        current_data: Dict[str, Any],
        metric_keys: List[str],
    ) -> Dict[str, Any]:
        """
        Generic logic to append a new snapshot of metrics to history.
        Handles timestamp generation, padding missing items, and trimming.
        """
        timestamp = int(datetime.now(timezone.utc).timestamp())
        history["labels"].append(timestamp)
        current_len = len(history["labels"])

        # Ensure all items in current snapshot exist in history
        for item_name in current_data.keys():
            if item_name not in history["items"]:
                history["items"][item_name] = {}

        # Iterate over all items in history (to handle items that might be missing from current snapshot)
        # or just iterate current_data if we assume it covers everything.
        # Better: Iterate current_data to update, and we might need to handle missing items later if needed.
        # For now, we follow the pattern of updating based on current_data.

        for item_name, metrics in current_data.items():
            item_hist = history["items"][item_name]

            for key in metric_keys:
                if key not in item_hist:
                    # Pad with 0s for previous time points
                    item_hist[key] = [0] * (current_len - 1)

                # Get value or default to 0
                val = metrics.get(key, 0)
                item_hist[key].append(val)

        # Trim to MAX_HISTORY_POINTS
        if len(history["labels"]) > config.MAX_HISTORY_POINTS:
            history["labels"] = history["labels"][-config.MAX_HISTORY_POINTS :]
            for item in history["items"].values():
                for key in item.keys():
                    item[key] = item[key][-config.MAX_HISTORY_POINTS :]

        return history

    # --- Public Interface ---

    @classmethod
    def load_history(cls) -> Dict[str, Any]:
        return cls._load_json(config.HISTORY_FILE)

    @classmethod
    def save_history(cls, data: Dict[str, Any]) -> None:
        cls._save_json(config.HISTORY_FILE, data)

    @classmethod
    def append_snapshot(
        cls, history: Dict[str, Any], current_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return cls._append_metrics(history, current_data, config.PROFITABILITY_METRICS)

    @classmethod
    def load_companies_history(cls) -> Dict[str, Any]:
        return cls._load_json(config.HISTORY_COMPANIES_FILE)

    @classmethod
    def save_companies_history(cls, data: Dict[str, Any]) -> None:
        cls._save_json(config.HISTORY_COMPANIES_FILE, data)

    @classmethod
    def append_companies_snapshot(
        cls, history: Dict[str, Any], current_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        return cls._append_metrics(history, current_data, config.COMPANY_METRICS)

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
