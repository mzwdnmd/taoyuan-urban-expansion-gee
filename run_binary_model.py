"""Train a task-focused built-up/non-built-up model and evaluate it once."""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

import ee

from taoyuan_gee.pipeline import PREDICTOR_BANDS, annual_composite, load_samples, study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def balanced_binary_pixels(samples: ee.FeatureCollection, maximum: int, seed: int) -> ee.FeatureCollection:
    result = ee.FeatureCollection([])
    for value in (0, 1):
        subset = (
            samples.filter(ee.Filter.eq("urban", value))
            .randomColumn("pixel_random", seed + value)
            .sort("pixel_random")
            .limit(maximum)
        )
        result = result.merge(subset)
    return result


def train(config: dict, roi: ee.Geometry) -> ee.Classifier:
    polygons = load_samples(config["asset_root"]).map(
        lambda feature: ee.Feature(feature).set(
            "urban", ee.Number(feature.get("landcover")).eq(4).toInt()
        )
    )
    extent = roi.union(polygons.geometry().bounds(1), 1)
    image, _ = annual_composite(config["training_year"], extent, config["max_cloud_cover"])
    raw = image.sampleRegions(
        collection=polygons,
        properties=["urban"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    pixels = balanced_binary_pixels(raw, 4000, config["random_seed"] + 2000)
    return ee.Classifier.smileRandomForest(
        numberOfTrees=400,
        minLeafPopulation=2,
        bagFraction=0.7,
        seed=config["random_seed"],
    ).train(features=pixels, classProperty="urban", inputProperties=PREDICTOR_BANDS)


def validation_features(config: dict) -> tuple[ee.FeatureCollection, dict[int, float], int]:
    labels = json.loads((RESULTS / "validation_labels_2020.json").read_text(encoding="utf-8"))
    summary = json.loads((RESULTS / "validation_candidates_2020_summary.json").read_text(encoding="utf-8"))
    with (RESULTS / "validation_candidates_2020.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    features = []
    strata = []
    for row in rows:
        reference = int(labels[row["candidate_id"]]["reference_class"])
        if reference not in range(5):
            continue
        stratum = int(row["model_class"])
        strata.append(stratum)
        features.append(
            ee.Feature(
                ee.Geometry.Point([float(row["longitude"]), float(row["latitude"])]),
                {
                    "candidate_id": row["candidate_id"],
                    "design_stratum": stratum,
                    "reference_urban": int(reference == 4),
                },
            )
        )
    areas = {int(k): float(v) for k, v in summary["mapped_area_km2_by_class"].items()}
    total = sum(areas.values())
    weights = {key: value / total for key, value in areas.items()}
    return ee.FeatureCollection(features), weights, len(features)


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    classifier = train(config, roi)
    validation_points, stratum_weights, usable_count = validation_features(config)
    stratum_counts = Counter(
        int(feature["properties"]["design_stratum"])
        for feature in validation_points.getInfo()["features"]
    )

    results = {"model": "binary_random_forest_v1", "years": {}}
    validation_image = None
    for year in config["years"]:
        image, scenes = annual_composite(year, roi, config["max_cloud_cover"])
        classified = image.select(PREDICTOR_BANDS).classify(classifier).rename("urban").clip(roi)
        area = (
            ee.Image.pixelArea()
            .updateMask(classified.eq(1))
            .reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi, scale=30, crs="EPSG:3826",
                maxPixels=1e9, tileScale=4,
            )
            .get("area")
            .getInfo()
            / 1e6
        )
        results["years"][str(year)] = {
            "scene_count": scenes.getInfo(), "builtup_km2": area
        }
        if year == config["training_year"]:
            validation_image = classified

    sampled = validation_image.sampleRegions(
        collection=validation_points,
        properties=["candidate_id", "design_stratum", "reference_urban"],
        scale=30,
        projection="EPSG:3826",
        geometries=False,
        tileScale=4,
    ).getInfo()["features"]
    matrix = [[0.0, 0.0], [0.0, 0.0]]
    counts = [[0, 0], [0, 0]]
    for feature in sampled:
        props = feature["properties"]
        pred = int(props["urban"])
        ref = int(props["reference_urban"])
        stratum = int(props["design_stratum"])
        point_weight = stratum_weights[stratum] / stratum_counts[stratum]
        matrix[pred][ref] += point_weight
        counts[pred][ref] += 1
    tn, fn = matrix[0]
    fp, tp = matrix[1]
    precision = tp / (tp + fp)
    recall = tp / (tp + fn)
    results["validation"] = {
        "usable_points": usable_count,
        "confusion_counts_rows_map_columns_reference": counts,
        "area_adjusted_proportions": matrix,
        "overall_accuracy": tn + tp,
        "builtup_precision": precision,
        "builtup_recall": recall,
        "builtup_f1": 2 * precision * recall / (precision + recall),
        "data_leakage_check": "Reference labels were loaded only after classifier training.",
    }
    first = results["years"][str(config["years"][0])]["builtup_km2"]
    last = results["years"][str(config["years"][-1])]["builtup_km2"]
    results["change_2014_2025"] = {
        "absolute_km2": last - first,
        "relative_percent": 100 * (last - first) / first,
    }
    output = RESULTS / "binary_model_v1.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
