"""Score a completed stratified reference sample with area-adjusted estimates."""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CLASSES = range(5)
CLASS_NAMES = {0: "water", 1: "vegetation", 2: "cropland", 3: "bareland", 4: "builtup"}


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def main() -> None:
    csv_path = RESULTS / "validation_candidates_2020.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    labels_path = RESULTS / "validation_labels_2020.json"
    labels = json.loads(labels_path.read_text(encoding="utf-8")) if labels_path.exists() else {}
    for row in rows:
        saved = labels.get(row["candidate_id"])
        if saved:
            row["reference_class"] = str(saved["reference_class"])
            row["review_status"] = str(saved["review_status"])
    pending = [row["candidate_id"] for row in rows if row["review_status"] == "TODO"]
    if pending:
        status = {
            "status": "PENDING_LABELS",
            "total_points": len(rows),
            "pending_points": len(pending),
            "next_action": "Review every TODO point as class 0-4, MIXED, or UNCERTAIN, then run this script again.",
        }
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    summary = json.loads((RESULTS / "validation_candidates_2020_summary.json").read_text(encoding="utf-8"))
    mapped_areas = {
        int(key): float(value) for key, value in summary["mapped_area_km2_by_class"].items()
    }
    total_area = sum(mapped_areas.values())
    weights = {key: area / total_area for key, area in mapped_areas.items()}

    excluded = [row for row in rows if row["reference_class"] not in {"0", "1", "2", "3", "4"}]
    rows = [row for row in rows if row["reference_class"] in {"0", "1", "2", "3", "4"}]
    # Rows are mapped classes; columns are independently interpreted reference classes.
    counts = [[0 for _ in CLASSES] for _ in CLASSES]
    for row in rows:
        counts[int(row["model_class"])][int(row["reference_class"])] += 1

    proportions = [[0.0 for _ in CLASSES] for _ in CLASSES]
    for mapped_class in CLASSES:
        row_total = sum(counts[mapped_class])
        if row_total == 0:
            raise ValueError(f"No usable reference labels for mapped class {mapped_class}")
        for reference_class in CLASSES:
            proportions[mapped_class][reference_class] = (
                weights[mapped_class] * counts[mapped_class][reference_class] / row_total
            )

    overall = sum(proportions[value][value] for value in CLASSES)
    variance = 0.0
    for value in CLASSES:
        n_h = sum(counts[value])
        correct_fraction = counts[value][value] / n_h
        if n_h > 1:
            variance += weights[value] ** 2 * correct_fraction * (1 - correct_fraction) / (n_h - 1)
    margin = 1.96 * math.sqrt(variance)

    metrics = {}
    adjusted_areas = {}
    for value in CLASSES:
        row_sum = sum(proportions[value])
        column_sum = sum(proportions[row][value] for row in CLASSES)
        metrics[str(value)] = {
            "class_name": CLASS_NAMES[value],
            "map_precision_users_accuracy": safe_ratio(proportions[value][value], row_sum),
            "reference_recall_producers_accuracy": safe_ratio(proportions[value][value], column_sum),
        }
        adjusted_areas[str(value)] = column_sum * total_area

    binary = {
        "map_nonbuilt_reference_nonbuilt": sum(
            proportions[mapped][reference] for mapped in range(4) for reference in range(4)
        ),
        "map_nonbuilt_reference_built": sum(proportions[mapped][4] for mapped in range(4)),
        "map_built_reference_nonbuilt": sum(proportions[4][reference] for reference in range(4)),
        "map_built_reference_built": proportions[4][4],
    }
    binary_overall = (
        binary["map_nonbuilt_reference_nonbuilt"] + binary["map_built_reference_built"]
    )
    binary_precision = safe_ratio(
        binary["map_built_reference_built"],
        binary["map_built_reference_built"] + binary["map_built_reference_nonbuilt"],
    )
    binary_recall = safe_ratio(
        binary["map_built_reference_built"],
        binary["map_built_reference_built"] + binary["map_nonbuilt_reference_built"],
    )
    binary_f1 = safe_ratio(2 * binary_precision * binary_recall, binary_precision + binary_recall)

    report = {
        "status": "SCORED",
        "sample_design": "Stratified by mapped class; 300 m exclusion from training polygons.",
        "usable_points": len(rows),
        "excluded_uncertain_or_mixed_points": len(excluded),
        "confusion_counts_rows_map_columns_reference": counts,
        "area_adjusted_overall_accuracy": overall,
        "overall_accuracy_95_percent_ci": [max(0.0, overall - margin), min(1.0, overall + margin)],
        "per_class_metrics": metrics,
        "area_adjusted_class_area_km2": adjusted_areas,
        "urban_binary_metrics": {
            "definition": "Built-up class 4 versus classes 0-3.",
            "area_adjusted_proportions": binary,
            "overall_accuracy": binary_overall,
            "builtup_precision": binary_precision,
            "builtup_recall": binary_recall,
            "builtup_f1": binary_f1,
            "mapped_builtup_area_km2": mapped_areas[4],
            "reference_adjusted_builtup_area_km2": adjusted_areas["4"],
        },
        "review_warning": "Inspect ambiguous points and document imagery/date rules before using these figures in a portfolio.",
    }
    output = RESULTS / "independent_validation_2020.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
