"""Check the Earth Engine project assets and recent batch tasks."""
import json
from pathlib import Path

import ee

from taoyuan_gee.runtime import initialize


ROOT = Path(__file__).resolve().parent
def main():
    config = json.loads((ROOT / "pipeline_config.json").read_text(encoding="utf-8"))
    project = config["project"]
    project_folder = config["asset_root"]
    initialize(project)
    assets = ee.data.listAssets({"parent": project_folder, "pageSize": 1000}).get(
        "assets", []
    )
    tasks = ee.data.getTaskList()
    summary = {
        "project": project,
        "asset_folder": project_folder,
        "assets": [
            {"name": item.get("name"), "type": item.get("type")}
            for item in assets
        ],
        "recent_tasks": [
            {
                "id": task.get("id"),
                "description": task.get("description"),
                "state": task.get("state"),
                "type": task.get("task_type"),
                "destination": task.get("destination_uris", []),
            }
            for task in tasks[:20]
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
