"""Authenticate locally and verify a real Earth Engine Landsat query."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
import ee


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authenticate", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.authenticate:
        ee.Authenticate(auth_mode="localhost:0", force=args.force)
        print("Authentication completed.", flush=True)
    ee.Initialize(project=config["project"])
    ee.data.setDeadline(60000)
    roi = ee.Geometry.Rectangle(config["roi"])
    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(roi)
        .filterDate(config["start"], config["end"])
        .filter(ee.Filter.lt("CLOUD_COVER", config["max_cloud_cover"]))
        .sort("system:time_start")
    )
    count = collection.size().getInfo()
    result = {
        "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "collection": "LANDSAT/LC08/C02/T1_L2",
        "image_count": count,
        "first_image_id": None,
        "first_image_bands": [],
    }
    if count:
        first = ee.Image(collection.first())
        info = ee.Dictionary({"id": first.id(), "bands": first.bandNames()}).getInfo()
        result["first_image_id"] = info["id"]
        result["first_image_bands"] = info["bands"]
    destination = ROOT / "results" / "landsat_2014.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()
