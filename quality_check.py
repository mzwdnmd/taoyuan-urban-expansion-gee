"""Build a reproducible diagnostic gate for the Taoyuan baseline results."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import ee

from taoyuan_gee.pipeline import CLASS_ASSETS, study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
GHSL_DATASET = "JRC/GHSL/P2023A/GHS_BUILT_S"
CLASS_NAMES = {
    0: "water",
    1: "vegetation",
    2: "cropland",
    3: "bareland",
    4: "builtup",
}


def ghsl_built_surface_km2(year: int, roi: ee.Geometry) -> float:
    """Sum GHSL built-surface area; pixels contain square metres of built surface."""
    image = ee.Image(f"{GHSL_DATASET}/{year}").select("built_surface")
    value = image.reduceRegion(
        reducer=ee.Reducer.sum(),
        geometry=roi,
        scale=100,
        maxPixels=1e9,
        tileScale=4,
    ).get("built_surface")
    return float(ee.Number(value).getInfo()) / 1e6


def sample_coverage(config: dict, roi: ee.Geometry) -> dict:
    coverage = {}
    for class_value, asset_name in CLASS_ASSETS.items():
        collection = ee.FeatureCollection(f"{config['asset_root']}/{asset_name}")
        counts = ee.Dictionary(
            {
                "total": collection.size(),
                "intersecting_taoyuan": collection.filterBounds(roi).size(),
            }
        ).getInfo()
        coverage[str(class_value)] = {
            "class_name": CLASS_NAMES[class_value],
            "total_polygons": int(counts["total"]),
            "intersecting_taoyuan": int(counts["intersecting_taoyuan"]),
        }
    return coverage


def pct_change(first: float, last: float) -> float:
    return 100.0 * (last - first) / first


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    baseline = json.loads((RESULTS / "multiyear_baseline.json").read_text(encoding="utf-8"))
    training = json.loads((RESULTS / "training_2020.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)

    coverage = sample_coverage(config, roi)
    ghsl = {str(year): ghsl_built_surface_km2(year, roi) for year in (2015, 2020, 2025)}
    model = {year: float(data["builtup_km2"]) for year, data in baseline["years"].items()}

    model_2014_2020 = pct_change(model["2014"], model["2020"])
    model_2020_2025 = pct_change(model["2020"], model["2025"])
    ghsl_2015_2020 = pct_change(ghsl["2015"], ghsl["2020"])
    ghsl_2020_2025 = pct_change(ghsl["2020"], ghsl["2025"])

    zero_local_classes = [
        item["class_name"] for item in coverage.values() if item["intersecting_taoyuan"] == 0
    ]
    flags = [
        {
            "code": "NO_INDEPENDENT_LOCAL_VALIDATION",
            "severity": "BLOCKER",
            "evidence": "Accuracy was computed from held-out pixels inside the same polygon inventory used for training.",
            "required_action": "Label a spatially separate Taoyuan validation set and recompute the confusion matrix.",
        }
    ]
    if zero_local_classes:
        flags.append(
            {
                "code": "TARGET_SAMPLE_CLASS_GAP",
                "severity": "BLOCKER",
                "evidence": f"Classes with zero training polygons intersecting Taoyuan: {', '.join(zero_local_classes)}.",
                "required_action": "Add Taoyuan-local polygons for every missing class.",
            }
        )
    if model_2014_2020 < 0 < ghsl_2015_2020:
        flags.append(
            {
                "code": "REFERENCE_TREND_DIRECTION_CONFLICT",
                "severity": "BLOCKER",
                "evidence": (
                    f"Model built-up changed {model_2014_2020:.2f}% from 2014 to 2020, "
                    f"while GHSL built surface changed {ghsl_2015_2020:.2f}% from 2015 to 2020."
                ),
                "required_action": "Diagnose temporal transfer and validate each mapped year before reporting expansion.",
            }
        )

    report = {
        "status": "NEEDS_LOCAL_VALIDATION" if flags else "PASS",
        "portfolio_decision": {
            "may_claim": [
                "Built a reproducible Python workflow that authenticates to Earth Engine, trains a classifier, computes area statistics, and exports assets.",
                "Implemented idempotent export handling, retry logic, and automated quality diagnostics.",
            ],
            "do_not_claim_yet": [
                "A validated 2014-2025 Taoyuan urban expansion magnitude.",
                "88% independent accuracy for Taoyuan.",
            ],
        },
        "method_note": (
            "GHSL built_surface measures building surface within 100 m cells; the model's built-up class can include "
            "roads and other impervious surfaces. Absolute areas are therefore not directly comparable. The reference "
            "is used only as a temporal direction sanity check."
        ),
        "target_sample_coverage": coverage,
        "reported_holdout_metrics": {
            "overall_accuracy": training["overall_accuracy"],
            "kappa": training["kappa"],
            "limitation": "Polygon-inventory holdout; not an independent Taoyuan-local validation set.",
        },
        "model_builtup_km2": model,
        "ghsl_built_surface_km2": ghsl,
        "interval_change_percent": {
            "model_2014_2020": model_2014_2020,
            "model_2020_2025": model_2020_2025,
            "ghsl_2015_2020": ghsl_2015_2020,
            "ghsl_2020_2025": ghsl_2020_2025,
        },
        "flags": flags,
        "next_gate": {
            "required": "Independent Taoyuan validation samples covering all five classes and all three periods.",
            "minimum_design": "Use spatially separated validation points; report per-class precision/recall and mapped-area uncertainty.",
        },
    }

    RESULTS.mkdir(exist_ok=True)
    json_path = RESULTS / "quality_gate.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    csv_path = RESULTS / "area_comparison.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "year", "area_km2", "definition"])
        writer.writeheader()
        for year, area in model.items():
            writer.writerow(
                {"source": "random_forest", "year": year, "area_km2": area, "definition": "five-class built-up"}
            )
        for year, area in ghsl.items():
            writer.writerow(
                {"source": "GHSL_P2023A", "year": year, "area_km2": area, "definition": "built surface"}
            )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved: {json_path}")
    print(f"Saved: {csv_path}")


if __name__ == "__main__":
    main()
