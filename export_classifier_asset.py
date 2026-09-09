"""Train the five-class Random Forest and export it as an Earth Engine asset."""
import argparse
import json
from pathlib import Path

import ee

from taoyuan_gee.pipeline import (
    PREDICTOR_BANDS,
    annual_composite,
    balance_pixels,
    load_samples,
    split_polygons,
    study_area,
)
from taoyuan_gee.runtime import initialize


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="pipeline_config.json")
    parser.add_argument("--asset-id", required=True)
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    polygons = load_samples(config["asset_root"])
    training_extent = roi.union(polygons.geometry().bounds(1), 1)
    image, _ = annual_composite(
        config["training_year"], training_extent, config["max_cloud_cover"]
    )
    train_polygons, _ = split_polygons(
        polygons, config["train_fraction"], config["random_seed"]
    )
    pixels = image.sampleRegions(
        collection=train_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    training = balance_pixels(
        pixels,
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
    task = ee.batch.Export.classifier.toAsset(
        classifier=classifier,
        description="taoyuan_five_class_rf_2020_v1",
        assetId=args.asset_id,
    )
    task.start()
    print(json.dumps({"task_id": task.id, "asset_id": args.asset_id}))


if __name__ == "__main__":
    main()
