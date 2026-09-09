# Taoyuan Urban Expansion with Google Earth Engine

An open Python/Google Earth Engine workflow for mapping urban land cover in Taoyuan, Taiwan with Landsat 8/9. The repository includes the manually drawn training polygons, a 250-point reference sample, automated GEE processing scripts, and quality-control results.

## What is included

- Landsat 8/9 preprocessing, spectral indices, terrain features, Random Forest training, GEE Asset export, and area-statistics scripts.
- `data/training_polygons.geojson`: 93 public training polygons (water, vegetation, cropland, bare land, built-up).
- `data/validation_reference_2020.csv`: 250 human-interpreted stratified reference points; 239 were usable after excluding mixed or unclear pixels.
- Independent validation and model-comparison outputs in `results/`.

No OAuth credentials, private keys, local cache files, or user-specific credential paths are included.

## Saved Earth Engine classifier

The five-class 300-tree Random Forest can be saved as an Earth Engine Classifier asset:

```powershell
python export_classifier_asset.py --asset-id projects/YOUR_GCP_PROJECT_ID/assets/taoyuan_urban_expansion/five_class_rf_2020_v1
```

After its export task completes, load it in another Earth Engine workflow with `ee.Classifier.load(asset_id)`. This is an Earth Engine asset, not a portable local `joblib` or `pickle` model. The published polygons and scripts let anyone retrain the model in their own project.

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

4. Upload the five classes from `data/training_polygons.geojson` to your Earth Engine Asset folder using the class values in the `landcover` property. The scripts expect Assets named `samples_water`, `samples_vegetation`, `samples_cropland`, `samples_bareland`, and `samples_builtup`.

5. Run `run_training.py`, `run_multiyear.py`, and `quality_check.py`.

## Validation result and limits

The delivered 2020 GEE Asset was evaluated with an independent map-stratified sample. Built-up detection achieved 89.4% precision, 70.7% recall, and 79.0% F1. The five-class product has weaker cropland and bare-land performance (71.2% area-adjusted overall accuracy), and the multi-year time series did not pass the temporal-consistency gate. This repository demonstrates reproducible GEE automation and quality control; it does not claim a validated 2014–2025 urban-expansion magnitude.

## License

MIT. Cite the source datasets according to their respective terms: Landsat Collection 2, Google Earth Engine, geoBoundaries, Dynamic World, and GHSL.
