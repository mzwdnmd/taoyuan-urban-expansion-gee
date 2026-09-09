"""Recompute area statistics directly from the exported GEE Assets."""
from __future__ import annotations

import json
from pathlib import Path

import ee

from taoyuan_gee.pipeline import study_area
from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent


def main() -> None:
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    initialize(config["project"])
    roi = study_area(config)
    years = {}
    for year in config["years"]:
        asset_id = f"{config['asset_root']}/landcover_{year}_baseline"
        image = ee.Image(asset_id).select("landcover")
        areas = (
            ee.Image.cat(
                [
                    ee.Image.pixelArea().updateMask(image.eq(4)).rename("builtup_m2"),
                    ee.Image.pixelArea().updateMask(image.neq(255)).rename("valid_m2"),
                ]
            )
            .reduceRegion(
                reducer=ee.Reducer.sum(), geometry=roi, scale=30, crs="EPSG:3826",
                maxPixels=1e9, tileScale=4,
            )
            .getInfo()
        )
        builtup = areas["builtup_m2"] / 1e6
        valid = areas["valid_m2"] / 1e6
        years[str(year)] = {
            "asset_id": asset_id,
            "builtup_km2": builtup,
            "valid_area_km2": valid,
            "builtup_share_percent": 100 * builtup / valid,
        }

    intervals = {}
    for first, last in zip(config["years"], config["years"][1:]):
        a = years[str(first)]["builtup_km2"]
        b = years[str(last)]["builtup_km2"]
        intervals[f"{first}_{last}"] = {
            "absolute_change_km2": b - a,
            "relative_change_percent": 100 * (b - a) / a,
        }
    report = {"source": "exported_gee_assets", "years": years, "intervals": intervals}
    output = ROOT / "results" / "asset_statistics.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Saved: {output}")


if __name__ == "__main__":
    main()
