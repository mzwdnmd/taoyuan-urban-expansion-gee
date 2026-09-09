"""Train and validate the 2020 Taoyuan land-cover model on GEE."""
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


ROOT = Path(__file__).resolve().parent


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    polygons = load_samples(config["asset_root"])
    # Existing polygons were drawn across Taiwan because the original script
    # used a province-wide boundary. Keep them as training data, while the
    # final classification target remains the verified Taoyuan boundary.
    training_extent = roi.union(polygons.geometry().bounds(1), 1)
    image, scene_count = annual_composite(
        config["training_year"], training_extent, config["max_cloud_cover"]
    )
    train_polygons, validation_polygons = split_polygons(
        polygons, config["train_fraction"], config["random_seed"]
    )
    train_raw = image.sampleRegions(
        collection=train_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    validation_raw = image.sampleRegions(
        collection=validation_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    training = balance_pixels(
        train_raw,
        config["max_training_pixels_per_class"],
        config["random_seed"] + 100,
    )
    validation = balance_pixels(
        validation_raw,
        config["max_validation_pixels_per_class"],
        config["random_seed"] + 200,
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
    matrix = validation.classify(classifier).errorMatrix(
        "landcover", "classification", [0, 1, 2, 3, 4]
    )
    server_result = ee.Dictionary(
        {
            "boundary_name": config["boundary_value"],
            "boundary_area_km2": roi.area(1).divide(1e6),
            "training_year": config["training_year"],
            "scene_count": scene_count,
            "polygon_counts": polygons.aggregate_histogram("landcover"),
            "training_pixel_counts": training.aggregate_histogram("landcover"),
            "validation_pixel_counts": validation.aggregate_histogram("landcover"),
            "confusion_matrix": matrix.array(),
            "overall_accuracy": matrix.accuracy(),
            "kappa": matrix.kappa(),
            "producer_accuracy": matrix.producersAccuracy(),
            "user_accuracy": matrix.consumersAccuracy(),
        }
    ).getInfo()
    output = ROOT / "results" / "training_2020.json"
    output.write_text(
        json.dumps(server_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(server_result, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
