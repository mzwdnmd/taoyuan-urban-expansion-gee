"""Reproduce the Taoyuan workflow from the public GeoJSON in one command."""
import argparse
import json
from pathlib import Path

import ee

from taoyuan_gee.pipeline import (
    PREDICTOR_BANDS,
    annual_composite,
    balance_pixels,
    load_samples_geojson,
    split_polygons,
    study_area,
)
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
DEFAULTS = {
    "boundary_dataset": "WM/geoLab/geoBoundaries/600/ADM1",
    "boundary_field": "shapeName",
    "boundary_value": "Taoyuan",
    "years": [2014, 2020, 2025],
    "training_year": 2020,
    "max_cloud_cover": 80,
    "train_fraction": 0.7,
    "max_training_pixels_per_class": 1200,
    "random_seed": 42,
}


def active_task(description: str) -> dict | None:
    for task in ee.data.getTaskList():
        if task.get("description") == description and task.get("state") in {
            "READY",
            "RUNNING",
        }:
            return task
    return None


def asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def start_classifier_export(classifier: ee.Classifier, asset_id: str) -> dict:
    description = "Taoyuan_five_class_rf_2020_v1"
    if asset_exists(asset_id):
        return {"description": description, "state": "ASSET_EXISTS", "asset_id": asset_id}
    existing = active_task(description)
    if existing:
        return {
            "description": description,
            "state": existing["state"],
            "task_id": existing["id"],
            "asset_id": asset_id,
        }
    task = ee.batch.Export.classifier.toAsset(
        classifier=classifier,
        description=description,
        assetId=asset_id,
    )
    task.start()
    return {
        "description": description,
        "state": task.status().get("state"),
        "task_id": task.id,
        "asset_id": asset_id,
    }


def start_image_export(image: ee.Image, roi: ee.Geometry, asset_id: str, year: int) -> dict:
    description = f"Taoyuan_LandCover_{year}_baseline"
    if asset_exists(asset_id):
        return {"description": description, "state": "ASSET_EXISTS", "asset_id": asset_id}
    existing = active_task(description)
    if existing:
        return {
            "description": description,
            "state": existing["state"],
            "task_id": existing["id"],
            "asset_id": asset_id,
        }
    task = ee.batch.Export.image.toAsset(
        image=image.unmask(255).toByte(),
        description=description,
        assetId=asset_id,
        region=roi,
        scale=30,
        crs="EPSG:3826",
        maxPixels=1e13,
        pyramidingPolicy={".default": "mode"},
    )
    task.start()
    return {
        "description": description,
        "state": task.status().get("state"),
        "task_id": task.id,
        "asset_id": asset_id,
    }


def load_config(path: Path, project: str) -> dict:
    config = DEFAULTS.copy()
    if path.exists():
        config.update(json.loads(path.read_text(encoding="utf-8")))
    config["project"] = project
    config["asset_root"] = f"projects/{project}/assets/taoyuan_urban_expansion"
    return config


def train_classifier(config: dict, polygons: ee.FeatureCollection) -> tuple[ee.Classifier, dict]:
    roi = study_area(config)
    polygon_count = polygons.size().getInfo()
    if not polygon_count:
        raise ValueError("The public polygons do not overlap the Taoyuan boundary.")
    # The baseline polygons were collected across Taiwan. Train on their full
    # extent so every class remains represented; final maps are clipped to ROI.
    training_extent = roi.union(polygons.geometry().bounds(1), 1)
    image, scene_count = annual_composite(
        config["training_year"], training_extent, config["max_cloud_cover"]
    )
    train_polygons, validation_polygons = split_polygons(
        polygons, config["train_fraction"], config["random_seed"]
    )
    raw_training = image.sampleRegions(
        collection=train_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    raw_validation = image.sampleRegions(
        collection=validation_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    training = balance_pixels(
        raw_training,
        config["max_training_pixels_per_class"],
        config["random_seed"] + 100,
    )
    classifier = ee.Classifier.smileRandomForest(
        numberOfTrees=300,
        minLeafPopulation=2,
        bagFraction=0.7,
        seed=config["random_seed"],
    ).train(
        features=training,
        classProperty="landcover",
        inputProperties=PREDICTOR_BANDS,
    )
    matrix = raw_validation.classify(classifier).errorMatrix(
        "landcover", "classification", [0, 1, 2, 3, 4]
    )
    summary = {
        "polygon_count_used": polygon_count,
        "scene_count": scene_count.getInfo(),
        "internal_validation_accuracy": matrix.accuracy().getInfo(),
        "internal_validation_confusion_matrix": matrix.array().getInfo(),
    }
    return classifier, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="Google Cloud project ID")
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "pipeline_config.example.json",
        help="Optional JSON configuration file",
    )
    parser.add_argument(
        "--training-data",
        type=Path,
        default=ROOT / "data" / "training_polygons.geojson",
    )
    parser.add_argument("--skip-exports", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config, args.project)
    initialize(config["project"])
    roi = study_area(config)
    polygons = load_samples_geojson(args.training_data)
    classifier, summary = train_classifier(config, polygons)
    results = {"config": config, "training": summary, "exports": []}
    if not args.skip_exports:
        classifier_asset = f"{config['asset_root']}/five_class_rf_2020_v1"
        results["exports"].append(
            start_classifier_export(classifier, classifier_asset)
        )
        for year in config["years"]:
            image, _ = annual_composite(year, roi, config["max_cloud_cover"])
            classified = (
                image.classify(classifier)
                .rename("landcover")
                .clip(roi)
                .toByte()
            )
            asset_id = f"{config['asset_root']}/landcover_{year}_baseline"
            results["exports"].append(
                start_image_export(classified, roi, asset_id, year)
            )
    output = ROOT / "results" / "pipeline_run_latest.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
