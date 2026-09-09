# Training polygons

`training_polygons.geojson` contains 93 manually drawn training polygons for the five-class land-cover workflow.

| `landcover` | Class | Polygon count |
| --- | --- | ---: |
| 0 | Water | 16 |
| 1 | Vegetation | 20 |
| 2 | Cropland | 17 |
| 3 | Bare land | 18 |
| 4 | Built-up | 22 |

The polygons are provided so the classifier can be retrained in a caller's own Earth Engine account. They are source data for this portfolio workflow; inspect them against imagery and adapt them before using them for a different study area or date.
