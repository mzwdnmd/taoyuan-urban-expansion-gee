# 桃园城市扩张项目状态

## 当前结论

工程作品集已经可用；多年份城市扩张数值仍需模型修订。

## 独立验证

- 验证点：250个；有效239个；混合或不清晰11个。
- 五分类面积加权总体精度：71.2%。
- 建成区二分类总体精度：88.8%。
- 建成区精确率：89.4%；召回率：70.7%；F1：79.0%。

## 简历可用描述

Built a Python–Google Earth Engine workflow for Taoyuan using Landsat 8/9, cloud masking, spectral/terrain features, Random Forest classification, idempotent Asset exports, and stratified independent validation. Labeled 250 map-based reference samples; the delivered 2020 Asset achieved 89.4% built-up precision, 70.7% recall, and 79.0% F1. Automated QA detected mixed-pixel and temporal-transfer limitations.

## 限制

农地和裸地分类表现不足，且2014至2020建成区结果轻微下降。当前结果适合展示Python/GEE自动化、数据质量检查和独立验证能力，不适合宣称精确测得2014至2025扩张面积。

## 模型修订实验

| 模型 | 建成区精确率 | 召回率 | F1 | 决策 |
|---|---:|---:|---:|---|
| 已导出五分类基线（按二分类评价） | 89.4% | 70.7% | 79.0% | 保留为2020验证基线 |
| 二分类v1 | 78.6% | 86.6% | 82.4% | 面积高估、时间不稳定，拒绝导出 |
| Dynamic World弱监督v2 | 71.1% | 89.6% | 79.3% | 精确率下降、面积高估，拒绝导出 |

两个二分类实验都没有通过时间一致性质量门。下一次模型开发需要桃园本地训练样本，尤其是建成区与裸地、农地的边界案例；现有独立验证集不应直接转为训练集。
