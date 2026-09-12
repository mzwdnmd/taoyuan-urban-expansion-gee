# Taoyuan Urban Expansion with Google Earth Engine

An open Python/Google Earth Engine workflow for mapping urban land cover in Taoyuan, Taiwan with Landsat 8/9. The repository includes the manually drawn training polygons, a 250-point reference sample, automated GEE processing scripts, and quality-control results.

[简体中文说明](README.zh-CN.md)

## Project workflow

~~~mermaid
flowchart LR
    A[Landsat 8/9 Collection 2 L2] --> B[Cloud and saturation masking]
    B --> C[Annual composite and predictors]
    D[93 training polygons] --> E[Sample pixels and balance classes]
    C --> E
    E --> F[300-tree Random Forest]
    F --> G[2020 land-cover Asset and saved Classifier]
    G --> H[250 independent reference points]
    H --> I[Accuracy metrics and quality gate]
~~~

1. **Configure and authenticate.** A user supplies a Google Cloud project and authenticates their own Earth Engine account. No credentials are stored in this repository.
2. **Build predictor imagery.** The workflow filters Landsat 8/9 Collection 2 Level 2 scenes, masks cloud and saturation flags, applies reflectance scaling, and creates annual median composites. Predictors include six optical bands, NDVI, NDBI, MNDWI, BSI, NDVI percentiles/range, elevation, and slope.
3. **Create training data.** The five land-cover classes are water, vegetation, cropland, bare land, and built-up. The repository publishes all 93 manually delineated polygons as GeoJSON, with class counts documented in [data/TRAINING_DATA.md](data/TRAINING_DATA.md).
4. **Train the classifier.** Polygons are split by class into training and internal validation sets. Sampled pixels are balanced by class and used to train a seeded 300-tree GEE Random Forest.
5. **Export outputs.** The workflow writes classified maps and statistics as Earth Engine Assets. The export_classifier_asset.py script saves the trained Random Forest as a reusable GEE Classifier Asset.
6. **Independently validate the delivered map.** A separate, map-stratified set of 250 human-interpreted 2020 reference points is kept out of training. Eleven mixed or unclear 30 m pixels are excluded, leaving 239 usable points.
7. **Apply a quality gate.** The project reports independent accuracy metrics and checks temporal consistency before accepting multi-year outputs. The current multi-year series failed that gate, so this repository does not claim a validated 2014–2025 urban-expansion magnitude.

## What is included

- Landsat 8/9 preprocessing, spectral indices, terrain features, Random Forest training, GEE Asset export, and area-statistics scripts.
- `data/training_polygons.geojson`: 93 public training polygons (water, vegetation, cropland, bare land, built-up).
- `data/validation_reference_2020.csv`: 250 human-interpreted stratified reference points; 239 were usable after excluding mixed or unclear pixels.
- Independent validation and model-comparison outputs in `results/`.

No OAuth credentials, private keys, local cache files, or user-specific credential paths are included.

The repository also includes HARD_CASE_SAMPLING_PLAN.md, which defines the next sampling round for difficult land-cover boundaries.

## One-command reproduction

After the one-time authentication step, the public training GeoJSON can be used directly; no manual split or upload of five GEE sample Assets is required:

~~~powershell
python run_pipeline.py --project YOUR_GCP_PROJECT_ID
~~~

This command reads data/training_polygons.geojson, rebuilds the seeded 300-tree Random Forest, computes an internal holdout check, starts idempotent exports for the classifier and 2014/2020/2025 maps, and saves a local run summary to results/pipeline_run_latest.json. Use --skip-exports for a smoke test that only trains and reports metrics.

## Saved Earth Engine classifier

The five-class 300-tree Random Forest can be saved as an Earth Engine Classifier asset:

```powershell
python export_classifier_asset.py --asset-id projects/YOUR_GCP_PROJECT_ID/assets/taoyuan_urban_expansion/five_class_rf_2020_v1
```

After its export task completes, load it in another Earth Engine workflow with `ee.Classifier.load(asset_id)`. This is an Earth Engine asset, not a portable local `joblib` or `pickle` model. The published polygons and scripts let anyone retrain the model in their own project.

The trained classifier from this release is publicly readable at:

```text
projects/urban-expansion-in-taoyuan/assets/taoyuan_urban_expansion/five_class_rf_2020_v1
```

## Reproduce

1. Create a Google Cloud project enabled for Earth Engine and install dependencies:

   ```bash
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ```

2. Authenticate your own account:

   ```bash
   .venv/Scripts/python gee_connect.py --authenticate
   ```

3. Copy `pipeline_config.example.json` to `pipeline_config.json` and replace `YOUR_GCP_PROJECT_ID`.

4. Run the one-command pipeline above. The older run_training.py and run_multiyear.py scripts remain available for workflows that already use separate GEE sample Assets.

## Validation result and limits

The delivered 2020 GEE Asset was evaluated with an independent map-stratified sample. Built-up detection achieved 89.4% precision, 70.7% recall, and 79.0% F1. The five-class product has weaker cropland and bare-land performance (71.2% area-adjusted overall accuracy), and the multi-year time series did not pass the temporal-consistency gate. This repository demonstrates reproducible GEE automation and quality control; it does not claim a validated 2014–2025 urban-expansion magnitude.

## License

MIT. Cite the source datasets according to their respective terms: Landsat Collection 2, Google Earth Engine, geoBoundaries, Dynamic World, and GHSL.
