"""Flag pre-box labels that merit human review; never replace reference labels."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import ee

from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
CONFIG = ROOT / "pipeline_config.json"
CURRENT_LABELS = RESULTS / "validation_labels_2020.json"
QUEUE = RESULTS / "validation_review_queue_2020.json"

# Dynamic World: 0 water, 1 trees, 2 grass, 3 flooded vegetation,
# 4 crops, 5 shrub/scrub, 6 built, 7 bare, 8 snow/ice.
DW_TO_PROJECT = {0: 0, 1: 1, 2: 1, 4: 2, 5: 1, 6: 4, 7: 3}


def find_prebox_backup() -> Path:
    backups = sorted(RESULTS.glob("validation_labels_2020-backup-*.json"))
    if not backups:
        raise FileNotFoundError("No pre-box label backup found")
    return backups[-1]


def main() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    initialize(config["project"])
    backup_path = find_prebox_backup()
    prebox = json.loads(backup_path.read_text(encoding="utf-8"))
    current = json.loads(CURRENT_LABELS.read_text(encoding="utf-8"))
    with (RESULTS / "validation_candidates_2020.csv").open(encoding="utf-8-sig", newline="") as handle:
        candidates = {row["candidate_id"]: row for row in csv.DictReader(handle)}

    features = []
    for candidate_id in prebox:
        row = candidates[candidate_id]
        features.append(
            ee.Feature(
                ee.Geometry.Point([float(row["longitude"]), float(row["latitude"])]),
                {"candidate_id": candidate_id},
            )
        )
    points = ee.FeatureCollection(features)
    dw_mode = (
        ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1")
        .filterDate("2020-01-01", "2021-01-01")
        .select("label")
        .mode()
    )

    def summarize(feature: ee.Feature) -> ee.Feature:
        square = feature.geometry().buffer(15).bounds(1)
        histogram = ee.Dictionary(
            dw_mode.reduceRegion(
                reducer=ee.Reducer.frequencyHistogram(),
                geometry=square,
                scale=10,
                maxPixels=100,
            ).get("label")
        )
        keys = histogram.keys()
        values = histogram.values(keys)
        maximum = ee.Number(values.reduce(ee.Reducer.max()))
        total = ee.Number(values.reduce(ee.Reducer.sum()))
        dominant = ee.Number.parse(ee.String(keys.get(values.indexOf(maximum)))).toInt()
        return feature.set(
            {"dw_dominant_class": dominant, "dw_dominant_share": maximum.divide(total)}
        )

    audited = points.map(summarize).getInfo()["features"]
    queue = []
    details = {}
    for feature in audited:
        candidate_id = feature["properties"]["candidate_id"]
        dw_class = int(feature["properties"]["dw_dominant_class"])
        share = float(feature["properties"]["dw_dominant_share"])
        saved = current[candidate_id]
        reference = int(saved["reference_class"])
        reasons = []
        if saved["review_status"] != "DONE":
            reasons.append("previously_uncertain")
        if share < 0.67:
            reasons.append("heterogeneous_10m_subpixels")
        mapped_dw = DW_TO_PROJECT.get(dw_class)
        if share >= 0.67 and mapped_dw is not None and reference >= 0 and mapped_dw != reference:
            reasons.append("high_confidence_external_disagreement")
        if dw_class in {3, 8}:
            reasons.append("dynamic_world_ambiguous_class")
        details[candidate_id] = {
            "reference_class": reference,
            "dw_dominant_class": dw_class,
            "dw_dominant_share": share,
            "reasons": reasons,
        }
        if reasons:
            queue.append(candidate_id)

    output = {
        "purpose": "Prioritize human review of labels created before the 30 m box was visible.",
        "warning": "Dynamic World is a screening aid, not reference truth. Human review decides the final class.",
        "prebox_labels_checked": len(prebox),
        "review_queue_count": len(queue),
        "review_queue": queue,
        "details": details,
    }
    QUEUE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("prebox_labels_checked", "review_queue_count", "review_queue")}, ensure_ascii=False, indent=2))
    print(f"Saved: {QUEUE}")


if __name__ == "__main__":
    main()
