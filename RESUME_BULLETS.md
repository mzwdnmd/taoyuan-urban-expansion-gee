# 简历项目条目

## 中文

**桃园城市扩张遥感自动化｜Python、Google Earth Engine、Landsat、Random Forest**

- 构建Python与Google Earth Engine自动化流水线，完成Landsat 8/9云掩膜、光谱指数与地形特征生成、随机森林分类、面积统计及GEE Asset幂等导出。
- 设计并完成250个地图分层验证点的独立人工判读，加入30米像元边界、混合像元规则和自动进度保存；最终239点进入评价，2020年建成区识别精确率89.4%、召回率70.7%、F1 79.0%。
- 建立自动质量门，以GHSL趋势和独立混淆矩阵识别时间迁移、混合像元及类别混淆问题；拒绝两个面积高估或时间不稳定的模型版本，保留可复现的实验与决策记录。

## English

**Taoyuan Urban Expansion Automation | Python, Google Earth Engine, Landsat, Random Forest**

- Built a Python–Google Earth Engine pipeline for Landsat 8/9 cloud masking, spectral and terrain features, Random Forest classification, area statistics, and idempotent GEE Asset exports.
- Designed and labeled 250 stratified map-validation samples with explicit 30 m pixel and mixed-pixel rules; 239 usable reference points yielded 89.4% built-up precision, 70.7% recall, and 79.0% F1 for the delivered 2020 Asset.
- Implemented automated QA using GHSL trend checks and independent confusion matrices; rejected two models with area overprediction or unstable temporal transfer and preserved reproducible experiment records.

## 面试说明

五分类总体精度为71.2%，其中农地与裸地分离较弱。项目目前证明的是GEE自动化、独立验证和质量控制能力；不要声称已经准确测得2014至2025年的城市扩张量。
