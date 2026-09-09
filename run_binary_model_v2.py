"""Test a Taoyuan-local weakly supervised binary model without exporting it."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import ee

from run_binary_model import validation_features
from taoyuan_gee.pipeline import PREDICTOR_BANDS, annual_composite, study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def train_local(config: dict, roi: ee.Geometry) -> ee.Classifier:
    landsat, _ = annual_composite(config["training_year"], roi, config["max_cloud_cover"])
    built_probability = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterBounds(roi)
        .filterDate("2020-01-01", "2021-01-01")
        .select("built")
        .median()
    )
    confident = built_probability.gte(0.65).Or(built_probability.lte(0.05))
    labels = built_probability.gte(0.65).toByte().rename("urban").updateMask(confident)
    pixels = landsat.addBands(labels).stratifiedSample(
        numPoints=4000,
        classBand="urban",
        region=roi,
        scale=30,
        projection="EPSG:3826",
        seed=config["random_seed"] + 3000,
        geometries=False,
        tileScale=4,
    )
    return ee.Classifier.smileRandomForest(
        numberOfTrees=400,
        minLeafPopulation=2,
        bagFraction=0.7,
        seed=config["random_seed"],
    ).train(features=pixels, classProperty="urban", inputProperties=PREDICTOR_BANDS)


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    classifier = train_local(config, roi)
    validation_points, stratum_weights, usable_count = validation_features(config)
    validation_info = validation_points.getInfo()["features"]
    stratum_counts = Counter(int(f["properties"]["design_stratum"]) for f in validation_info)

    results = {
        "model": "binary_random_forest_v2_dynamic_world_weak_supervision",
        "training": "Dynamic World 2020 built probability >=0.65 positive; <=0.05 negative.",
        "years": {},
    }
    validation_image = None
    for year in config["years"]:
        image, scenes = annual_composite(year, roi, config["max_cloud_cover"])
        classified = image.select(PREDICTOR_BANDS).classify(classifier).rename("urban").clip(roi)
        area = (
            ee.Image.pixelArea().updateMask(classified.eq(1)).reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi, scale=30, crs="EPSG:3826",
                maxPixels=1e9, tileScale=4,
            ).get("area").getInfo() / 1e6
        )
        results["years"][str(year)] = {"scene_count": scenes.getInfo(), "builtup_km2": area}
        if year == config["training_year"]:
            validation_image = classified

    sampled = validation_image.sampleRegions(
        collection=validation_points,
        properties=["design_stratum", "reference_urban"],
        scale=30,
        projection="EPSG:3826",
        geometries=False,
        tileScale=4,
    ).getInfo()["features"]
    matrix = [[0.0, 0.0], [0.0, 0.0]]
    counts = [[0, 0], [0, 0]]
    for feature in sampled:
        props = feature["properties"]
        pred, ref, stratum = int(props["urban"]), int(props["reference_urban"]), int(props["design_stratum"])
        matrix[pred][ref] += stratum_weights[stratum] / stratum_counts[stratum]
        counts[pred][ref] += 1
    tn, fn = matrix[0]
    fp, tp = matrix[1]
    precision, recall = tp / (tp + fp), tp / (tp + fn)
    results["validation"] = {
        "usable_points": usable_count,
        "confusion_counts_rows_map_columns_reference": counts,
        "area_adjusted_proportions": matrix,
        "overall_accuracy": tn + tp,
        "builtup_precision": precision,
        "builtup_recall": recall,
        "builtup_f1": 2 * precision * recall / (precision + recall),
        "data_leakage_check": "Human reference labels were loaded only after classifier training.",
    }
    output = RESULTS / "binary_model_v2.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
