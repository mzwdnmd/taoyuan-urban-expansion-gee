# 桃园城市扩张：Google Earth Engine 自动化项目

[English README](README.md)

这是一个开源的 Python + Google Earth Engine（GEE）遥感项目，用 Landsat 8/9 影像绘制台湾桃园市的土地覆盖，并展示可复现的训练、资产导出、独立精度验证和质量控制流程。

项目公开了训练多边形、独立验证参考点、自动化脚本、模型导出脚本和结果文件；不包含 OAuth 凭据、私钥或本机缓存。

## 项目流程

~~~mermaid
flowchart LR
    A[Landsat 8/9 Collection 2 L2] --> B[云与饱和像元掩膜]
    B --> C[年度合成与特征构建]
    D[93个训练多边形] --> E[像元采样与类别平衡]
    C --> E
    E --> F[300棵树随机森林]
    F --> G[2020土地覆盖资产与分类器]
    G --> H[250个独立验证点]
    H --> I[精度指标与质量门]
~~~

1. **配置与认证**：使用者填写自己的 Google Cloud 项目 ID，并通过 GEE OAuth 认证。仓库不会保存任何账号凭据。
2. **影像预处理**：筛选 Landsat 8/9 Collection 2 Level 2 影像，使用 QA_PIXEL 和 QA_RADSAT 去除云、阴影与饱和像元，进行地表反射率缩放，再生成年度中值合成影像。
3. **特征构建**：模型使用蓝、绿、红、近红外、两个短波红外波段，以及 NDVI、NDBI、MNDWI、BSI、NDVI 分位数/范围、高程和坡度。
4. **训练样本**：五个类别为水体、植被、农地、裸地和建成区。data/training_polygons.geojson 公开了全部 93 个手工绘制的训练多边形；类别数量见 [data/TRAINING_DATA.md](data/TRAINING_DATA.md)。
5. **随机森林训练**：每个类别按多边形切分为训练和内部验证部分；从影像中采样后对类别进行平衡，训练固定随机种子的 300 棵树 GEE Random Forest。
6. **成果导出**：脚本将分类图、面积统计和相关结果导出到 GEE Assets。export_classifier_asset.py 可将训练好的随机森林保存为可复用的 GEE Classifier Asset。
7. **独立验证**：250 个 2020 年人工判读、按地图分层抽样的参考点完全不参与训练。其中 11 个属于 30 m 混合像元或判读不清晰点，被排除后使用 239 个有效点进行评价。
8. **质量控制**：项目输出独立精度指标，并检查多年份结果的时间一致性。当前多年份序列未通过该质量门，因此项目不宣称已精确测得 2014–2025 年的城市扩张面积。

## 包含内容

- Landsat 8/9 预处理、光谱指数、地形特征、随机森林训练、GEE Asset 导出和面积统计脚本。
- data/training_polygons.geojson：93 个公开训练多边形。
- data/validation_reference_2020.csv：250 个独立人工判读参考点。
- results/：独立验证、模型比较和质量门结果。
- export_classifier_asset.py：导出 GEE 分类器资产的脚本。

## 已导出的预训练模型

项目已将五分类、300 棵树的随机森林导出为所有 GEE 用户可读取的 Classifier Asset：

~~~text
projects/urban-expansion-in-taoyuan/assets/taoyuan_urban_expansion/five_class_rf_2020_v1
~~~

在自己的 GEE 工作流中加载：

~~~python
classifier = ee.Classifier.load(
    'projects/urban-expansion-in-taoyuan/assets/taoyuan_urban_expansion/five_class_rf_2020_v1'
)
~~~

该模型属于 GEE Asset，并非可直接下载的通用 joblib 或 pickle 文件。使用者也可以依据公开训练多边形和脚本，在自己的 GEE 项目中重新训练。

## 复现步骤

1. 创建并启用 Earth Engine 的 Google Cloud 项目。
2. 安装依赖：

   ~~~powershell
   python -m venv .venv
   .venv/Scripts/pip install -r requirements.txt
   ~~~

3. 用自己的账号认证：

   ~~~powershell
   .venv/Scripts/python gee_connect.py --authenticate
   ~~~

4. 将 pipeline_config.example.json 复制为 pipeline_config.json，并填写自己的项目 ID。
5. 按 landcover 属性将 data/training_polygons.geojson 中的五个类别上传到 GEE Assets。脚本默认查找 samples_water、samples_vegetation、samples_cropland、samples_bareland 和 samples_builtup。
6. 运行 run_training.py、run_multiyear.py 与 quality_check.py。

## 当前验证结果与限制

- 独立参考点：250 个；有效点：239 个；排除混合或不清晰点：11 个。
- 五分类面积加权总体精度：71.2%。
- 建成区二分类总体精度：88.8%。
- 建成区精确率：89.4%；召回率：70.7%；F1：79.0%。

农地与裸地的区分仍较弱，且多年份结果未通过时间一致性检查。因此，本项目适合展示 Python/GEE 自动化、样本管理、独立验证和质量控制能力；不适合宣称已经精确估计 2014–2025 年桃园城市扩张面积。

## 许可证

MIT。使用 Landsat Collection 2、Google Earth Engine、geoBoundaries、Dynamic World 和 GHSL 时，请遵循各数据源的引用和使用条款。
