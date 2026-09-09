"""Evaluate the actual exported 2020 Asset with the independent reference labels."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import ee

from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CLASSES = range(5)
CLASS_NAMES = {0: "water", 1: "vegetation", 2: "cropland", 3: "bareland", 4: "builtup"}


def ratio(a: float, b: float) -> float | None:
    return a / b if b else None


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    labels = json.loads((RESULTS / "validation_labels_2020.json").read_text(encoding="utf-8"))
    summary = json.loads((RESULTS / "validation_candidates_2020_summary.json").read_text(encoding="utf-8"))
    with (RESULTS / "validation_candidates_2020.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    usable = []
    features = []
    for row in rows:
        saved = labels[row["candidate_id"]]
        reference = int(saved["reference_class"])
        if reference not in CLASSES:
            continue
        item = {
            "candidate_id": row["candidate_id"],
            "design_stratum": int(row["model_class"]),
            "reference_class": reference,
            "candidate_model_class": int(row["model_class"]),
        }
        usable.append(item)
        features.append(
            ee.Feature(
                ee.Geometry.Point([float(row["longitude"]), float(row["latitude"])]),
                item,
            )
        )

    asset_id = f"{config['asset_root']}/landcover_2020_baseline"
    sampled = ee.Image(asset_id).rename("asset_class").sampleRegions(
        collection=ee.FeatureCollection(features),
        properties=["candidate_id", "design_stratum", "reference_class", "candidate_model_class"],
        scale=30,
        projection="EPSG:3826",
        geometries=False,
        tileScale=4,
    ).getInfo()["features"]

    mapped_areas = {int(k): float(v) for k, v in summary["mapped_area_km2_by_class"].items()}
    total_area = sum(mapped_areas.values())
    stratum_weights = {key: value / total_area for key, value in mapped_areas.items()}
    stratum_counts = Counter(item["design_stratum"] for item in usable)

    counts = [[0 for _ in CLASSES] for _ in CLASSES]
    proportions = [[0.0 for _ in CLASSES] for _ in CLASSES]
    disagreements = 0
    for feature in sampled:
        props = feature["properties"]
        predicted = int(props["asset_class"])
        reference = int(props["reference_class"])
        stratum = int(props["design_stratum"])
        if predicted not in CLASSES:
            continue
        counts[predicted][reference] += 1
        proportions[predicted][reference] += stratum_weights[stratum] / stratum_counts[stratum]
        disagreements += predicted != int(props["candidate_model_class"])

    overall = sum(proportions[value][value] for value in CLASSES)
    metrics = {}
    for value in CLASSES:
        row_sum = sum(proportions[value])
        col_sum = sum(proportions[row][value] for row in CLASSES)
        metrics[str(value)] = {
            "class_name": CLASS_NAMES[value],
            "map_precision_users_accuracy": ratio(proportions[value][value], row_sum),
            "reference_recall_producers_accuracy": ratio(proportions[value][value], col_sum),
        }

    p_nn = sum(proportions[mapped][reference] for mapped in range(4) for reference in range(4))
    p_nb = sum(proportions[mapped][4] for mapped in range(4))
    p_bn = sum(proportions[4][reference] for reference in range(4))
    p_bb = proportions[4][4]
    precision = ratio(p_bb, p_bb + p_bn)
    recall = ratio(p_bb, p_bb + p_nb)
    report = {
        "status": "SCORED",
        "asset_id": asset_id,
        "usable_reference_points": len(usable),
        "sampled_asset_points": len(sampled),
        "candidate_vs_asset_prediction_disagreements": disagreements,
        "weighting": "Original candidate-map strata area weights; valid for evaluating the exported map on the same probability sample.",
        "confusion_counts_rows_asset_map_columns_reference": counts,
        "area_adjusted_overall_accuracy_five_class": overall,
        "per_class_metrics": metrics,
        "urban_binary_metrics": {
            "overall_accuracy": p_nn + p_bb,
            "builtup_precision": precision,
            "builtup_recall": recall,
            "builtup_f1": ratio(2 * precision * recall, precision + recall),
            "area_adjusted_proportions": {
                "map_nonbuilt_reference_nonbuilt": p_nn,
                "map_nonbuilt_reference_built": p_nb,
                "map_built_reference_nonbuilt": p_bn,
                "map_built_reference_built": p_bb,
            },
        },
    }
    output = RESULTS / "exported_asset_validation_2020.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
