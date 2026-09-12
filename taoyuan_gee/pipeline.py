from __future__ import annotations

import json
from pathlib import Path

import ee


CLASS_ASSETS = {
    0: "samples_water",
    1: "samples_vegetation",
    2: "samples_cropland",
    3: "samples_bareland",
    4: "samples_builtup",
}

PREDICTOR_BANDS = [
    "blue",
    "green",
    "red",
    "nir",
    "swir1",
    "swir2",
    "NDVI",
    "NDBI",
    "MNDWI",
    "BSI",
    "NDVI_p20",
    "NDVI_p80",
    "NDVI_range",
    "elevation",
    "slope",
]


def study_area(config: dict) -> ee.Geometry:
    boundary = ee.FeatureCollection(config["boundary_dataset"]).filter(
        ee.Filter.eq(config["boundary_field"], config["boundary_value"])
    )
    return boundary.geometry()


def preprocess_l89(image: ee.Image) -> ee.Image:
    qa_mask = image.select("QA_PIXEL").bitwiseAnd(63).eq(0)
    saturation_mask = image.select("QA_RADSAT").eq(0)
    optical = (
        image.select(
            ["SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"],
            ["blue", "green", "red", "nir", "swir1", "swir2"],
        )
        .multiply(0.0000275)
        .add(-0.2)
    )
    return (
        optical.updateMask(qa_mask)
        .updateMask(saturation_mask)
        .copyProperties(image, ["system:time_start"])
    )


def add_indices(image: ee.Image) -> ee.Image:
    ndvi = image.normalizedDifference(["nir", "red"]).rename("NDVI")
    ndbi = image.normalizedDifference(["swir1", "nir"]).rename("NDBI")
    mndwi = image.normalizedDifference(["green", "swir1"]).rename("MNDWI")
    bsi = image.expression(
        "((s + r) - (n + b)) / ((s + r) + (n + b))",
        {
            "s": image.select("swir1"),
            "r": image.select("red"),
            "n": image.select("nir"),
            "b": image.select("blue"),
        },
    ).rename("BSI")
    return image.addBands([ndvi, ndbi, mndwi, bsi])


def annual_composite(year: int, roi: ee.Geometry, max_cloud_cover: int) -> tuple[ee.Image, ee.Number]:
    start = ee.Date.fromYMD(year, 1, 1)
    end = start.advance(1, "year")

    def collection(dataset: str) -> ee.ImageCollection:
        return (
            ee.ImageCollection(dataset)
            .filterBounds(roi)
            .filterDate(start, end)
            .filter(ee.Filter.lt("CLOUD_COVER", max_cloud_cover))
            .map(preprocess_l89)
        )

    images = collection("LANDSAT/LC08/C02/T1_L2")
    if year >= 2021:
        images = images.merge(collection("LANDSAT/LC09/C02/T1_L2"))

    indexed = images.map(add_indices)
    median = indexed.median()
    percentiles = indexed.select("NDVI").reduce(ee.Reducer.percentile([20, 80]))
    ndvi_range = (
        percentiles.select("NDVI_p80")
        .subtract(percentiles.select("NDVI_p20"))
        .rename("NDVI_range")
    )
    elevation = ee.Image("USGS/SRTMGL1_003").select("elevation")
    slope = ee.Terrain.slope(elevation).rename("slope")
    result = (
        median.addBands(percentiles)
        .addBands(ndvi_range)
        .addBands(elevation)
        .addBands(slope)
        .select(PREDICTOR_BANDS)
        .clip(roi)
    )
    return result, images.size()


def load_samples(asset_root: str) -> ee.FeatureCollection:
    merged = ee.FeatureCollection([])
    for class_value, name in CLASS_ASSETS.items():
        source = ee.FeatureCollection(f"{asset_root}/{name}").map(
            lambda feature, value=class_value: ee.Feature(feature).set(
                "landcover", value
            )
        )
        merged = merged.merge(source)
    return merged


def load_samples_geojson(path: str | Path) -> ee.FeatureCollection:
    """Load public local training polygons without requiring GEE table assets."""
    source = json.loads(Path(path).read_text(encoding="utf-8"))
    features = []
    for index, item in enumerate(source.get("features", [])):
        properties = item.get("properties", {})
        if properties.get("landcover") is None:
            raise ValueError(f"Missing landcover property in feature {index}")
        features.append(
            ee.Feature(
                item["geometry"],
                {
                    "landcover": int(properties["landcover"]),
                    "sample_id": str(properties.get("sample_id", index)),
                },
            )
        )
    if not features:
        raise ValueError(f"No GeoJSON features found in {path}")
    return ee.FeatureCollection(features)


def split_polygons(
    samples: ee.FeatureCollection, train_fraction: float, seed: int
) -> tuple[ee.FeatureCollection, ee.FeatureCollection]:
    training = ee.FeatureCollection([])
    validation = ee.FeatureCollection([])
    for class_value in CLASS_ASSETS:
        subset = samples.filter(ee.Filter.eq("landcover", class_value)).randomColumn(
            "split_sort", seed + class_value
        )
        count = subset.size()
        # Slice the shuffled list so every class is guaranteed to have both
        # training and validation polygons. Some imported geometries do not
        # have stable system:index values, making a threshold split collapse.
        training_count = (
            ee.Number(count)
            .multiply(train_fraction)
            .floor()
            .max(1)
            .min(ee.Number(count).subtract(1))
        )
        ordered = subset.sort("split_sort").toList(count)
        training = training.merge(
            ee.FeatureCollection(ordered.slice(0, training_count))
        )
        validation = validation.merge(
            ee.FeatureCollection(ordered.slice(training_count, count))
        )
    return training, validation


def balance_pixels(
    samples: ee.FeatureCollection, maximum_per_class: int, seed: int
) -> ee.FeatureCollection:
    balanced = ee.FeatureCollection([])
    for class_value in CLASS_ASSETS:
        subset = (
            samples.filter(ee.Filter.eq("landcover", class_value))
            .randomColumn("pixel_random", seed + class_value)
            .sort("pixel_random")
            .limit(maximum_per_class)
        )
        balanced = balanced.merge(subset)
    return balanced
