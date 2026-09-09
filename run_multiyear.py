"""Run the baseline classifier for 2014, 2020 and 2025 and export Assets."""
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


def train_classifier(config: dict, roi: ee.Geometry) -> ee.Classifier:
    polygons = load_samples(config["asset_root"])
    training_extent = roi.union(polygons.geometry().bounds(1), 1)
    image, _ = annual_composite(
        config["training_year"], training_extent, config["max_cloud_cover"]
    )
    train_polygons, _ = split_polygons(
        polygons, config["train_fraction"], config["random_seed"]
    )
    raw = image.sampleRegions(
        collection=train_polygons,
        properties=["landcover"],
        scale=30,
        geometries=False,
        tileScale=4,
    )
    training = balance_pixels(
        raw,
        config["max_training_pixels_per_class"],
        config["random_seed"] + 100,
    )
    return ee.Classifier.smileRandomForest(
        numberOfTrees=300,
        minLeafPopulation=2,
        bagFraction=0.7,
        seed=config["random_seed"],
    ).train(
        features=training,
        classProperty="landcover",
        inputProperties=PREDICTOR_BANDS,
    )


def asset_exists(asset_id: str) -> bool:
    try:
        ee.data.getAsset(asset_id)
        return True
    except ee.EEException:
        return False


def active_task(description: str) -> dict | None:
    for task in ee.data.getTaskList():
        if task.get("description") == description and task.get("state") in {
            "READY",
            "RUNNING",
        }:
            return task
    return None


def start_export(image: ee.Image, roi: ee.Geometry, asset_id: str, description: str) -> dict:
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


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    classifier = train_classifier(config, roi)
    results = {"boundary": config["boundary_value"], "years": {}, "exports": []}

    for year in config["years"]:
        image, scene_count = annual_composite(year, roi, config["max_cloud_cover"])
        classified = (
            image.select(PREDICTOR_BANDS)
            .classify(classifier)
            .rename("landcover")
            .clip(roi)
            .toByte()
        )
        builtup = classified.eq(4)
        areas = (
            ee.Image.cat(
                [
                    ee.Image.pixelArea().updateMask(builtup).rename("builtup_m2"),
                    ee.Image.pixelArea()
                    .updateMask(classified.mask())
                    .rename("valid_m2"),
                ]
            )
            .reduceRegion(
                reducer=ee.Reducer.sum(),
                geometry=roi,
                scale=30,
                crs="EPSG:3826",
                maxPixels=1e9,
                tileScale=4,
            )
            .combine(ee.Dictionary({"scene_count": scene_count}))
            .getInfo()
        )
        builtup_km2 = areas.get("builtup_m2", 0) / 1e6
        valid_km2 = areas.get("valid_m2", 0) / 1e6
        results["years"][str(year)] = {
            "scene_count": areas["scene_count"],
            "builtup_km2": builtup_km2,
            "valid_area_km2": valid_km2,
            "builtup_share_of_valid_percent": 100 * builtup_km2 / valid_km2,
        }
        description = f"Taoyuan_LandCover_{year}_baseline"
        asset_id = f"{config['asset_root']}/landcover_{year}_baseline"
        results["exports"].append(
            start_export(classified, roi, asset_id, description)
        )

    first_year, last_year = config["years"][0], config["years"][-1]
    first_area = results["years"][str(first_year)]["builtup_km2"]
    last_area = results["years"][str(last_year)]["builtup_km2"]
    elapsed = last_year - first_year
    results["change_summary"] = {
        "from_year": first_year,
        "to_year": last_year,
        "absolute_change_km2": last_area - first_area,
        "relative_change_percent": 100 * (last_area - first_area) / first_area,
        "annual_average_change_km2": (last_area - first_area) / elapsed,
    }
    output = ROOT / "results" / "multiyear_baseline.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
