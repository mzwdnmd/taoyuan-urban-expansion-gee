"""Prepare spatially separate 2020 candidate points for manual reference labeling."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import ee

from run_multiyear import active_task, asset_exists, train_classifier
from taoyuan_gee.pipeline import PREDICTOR_BANDS, annual_composite, load_samples, study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
CLASS_NAMES = {0: "water", 1: "vegetation", 2: "cropland", 3: "bareland", 4: "builtup"}


def build_candidates(config: dict, roi: ee.Geometry) -> ee.FeatureCollection:
    classifier = train_classifier(config, roi)
    image, _ = annual_composite(config["training_year"], roi, config["max_cloud_cover"])
    classified = image.select(PREDICTOR_BANDS).classify(classifier).rename("model_class")

    local_training = load_samples(config["asset_root"]).filterBounds(roi)
    exclusion = (
        ee.Image.constant(0)
        .toByte()
        .paint(local_training, 1)
        .focalMax(config["validation_exclusion_buffer_m"], "circle", "meters")
    )
    sampling_image = classified.addBands(ee.Image.pixelLonLat()).updateMask(exclusion.eq(0))
    candidates = sampling_image.stratifiedSample(
        numPoints=config["validation_points_per_class"],
        classBand="model_class",
        region=roi,
        scale=30,
        projection="EPSG:3826",
        seed=config["random_seed"] + 1000,
        geometries=True,
        tileScale=4,
    )

    def prepare(feature: ee.Feature) -> ee.Feature:
        model_class = ee.Number(feature.get("model_class")).toInt()
        return feature.set(
            {
                "candidate_id": ee.String("TY2020_").cat(feature.getString("system:index")),
                "model_class": model_class,
                "model_class_name": ee.Dictionary(
                    {str(key): value for key, value in CLASS_NAMES.items()}
                ).get(model_class.format()),
                "reference_class": -1,
                "review_status": "TODO",
                "review_year": config["training_year"],
            }
        )

    return candidates.map(prepare)


def start_asset_export(candidates: ee.FeatureCollection, asset_id: str) -> dict:
    description = "Taoyuan_validation_candidates_2020_v1"
    if asset_exists(asset_id):
        return {"state": "ASSET_EXISTS", "asset_id": asset_id}
    existing = active_task(description)
    if existing:
        return {"state": existing["state"], "task_id": existing["id"], "asset_id": asset_id}
    task = ee.batch.Export.table.toAsset(
        collection=candidates,
        description=description,
        assetId=asset_id,
    )
    task.start()
    return {"state": task.status()["state"], "task_id": task.id, "asset_id": asset_id}


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    candidates = build_candidates(config, roi)
    info = candidates.getInfo()
    features = info["features"]

    classifier = train_classifier(config, roi)
    image, _ = annual_composite(config["training_year"], roi, config["max_cloud_cover"])
    classified = image.select(PREDICTOR_BANDS).classify(classifier).rename("model_class")
    area_groups = (
        ee.Image.pixelArea()
        .rename("area_m2")
        .addBands(classified)
        .reduceRegion(
            reducer=ee.Reducer.sum().group(groupField=1, groupName="model_class"),
            geometry=roi,
            scale=30,
            crs="EPSG:3826",
            maxPixels=1e9,
            tileScale=4,
        )
        .get("groups")
        .getInfo()
    )
    mapped_area_km2 = {
        str(int(item["model_class"])): float(item["sum"]) / 1e6 for item in area_groups
    }

    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    geojson_path = results / "validation_candidates_2020.geojson"
    geojson_path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = results / "validation_candidates_2020.csv"
    fields = [
        "candidate_id",
        "longitude",
        "latitude",
        "model_class",
        "model_class_name",
        "reference_class",
        "review_status",
        "review_year",
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for feature in features:
            props = feature["properties"]
            writer.writerow({field: props.get(field, "") for field in fields})

    counts = {}
    for class_value, class_name in CLASS_NAMES.items():
        counts[class_name] = sum(
            1 for feature in features if feature["properties"]["model_class"] == class_value
        )
    asset_id = f"{config['asset_root']}/validation_candidates_2020_v1"
    export = start_asset_export(candidates, asset_id)
    summary = {
        "candidate_count": len(features),
        "counts_by_model_class": counts,
        "mapped_area_km2_by_class": mapped_area_km2,
        "selection": {
            "points_per_mapped_class": config["validation_points_per_class"],
            "training_exclusion_buffer_m": config["validation_exclusion_buffer_m"],
            "reference_class": "-1 means not labeled; reviewer must assign 0-4 from imagery without using model_class as truth.",
        },
        "asset_export": export,
    }
    summary_path = results / "validation_candidates_2020_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Saved: {geojson_path}")
    print(f"Saved: {csv_path}")
    print(f"Saved: {summary_path}")


if __name__ == "__main__":
    main()
