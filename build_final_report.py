"""Assemble the current portfolio decision from completed validation outputs."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"

def main() -> None:
    validation = json.loads((RESULTS / "exported_asset_validation_2020.json").read_text(encoding="utf-8"))
    areas = json.loads((RESULTS / "asset_statistics.json").read_text(encoding="utf-8"))
    binary = validation["urban_binary_metrics"]
    five = validation["per_class_metrics"]
    report = {
        "status": "ENGINEERING_PORTFOLIO_READY_MODEL_REVISION_REQUIRED",
        "validation": {
            "reference_points_total": 250,
            "usable_points": validation["usable_reference_points"],
            "excluded_mixed_or_uncertain": 11,
            "five_class_overall_accuracy": validation["area_adjusted_overall_accuracy_five_class"],
            "urban_binary_overall_accuracy": binary["overall_accuracy"],
            "builtup_precision": binary["builtup_precision"],
            "builtup_recall": binary["builtup_recall"],
            "builtup_f1": binary["builtup_f1"],
        },
        "quality_findings": [
            {
                "finding": "The exported map and validation-candidate predictions agree at all 239 usable points.",
                "decision": "Validation metrics correspond to the delivered 2020 GEE Asset.",
            },
            {
                "finding": (
                    f"Cropland map precision is {five['2']['map_precision_users_accuracy']:.1%}; "
                    f"bare-land precision is {five['3']['map_precision_users_accuracy']:.1%} and recall is "
                    f"{five['3']['reference_recall_producers_accuracy']:.1%}."
                ),
                "decision": "Do not present the five-class product as a production-quality land-cover map.",
            },
            {
                "finding": (
                    f"Exported built-up area changes from {areas['years']['2014']['builtup_km2']:.2f} km² "
                    f"in 2014 to {areas['years']['2020']['builtup_km2']:.2f} km² in 2020, then "
                    f"{areas['years']['2025']['builtup_km2']:.2f} km² in 2025."
                ),
                "decision": "Temporal transfer remains unstable; do not claim a validated expansion magnitude.",
            },
        ],
        "resume_safe_claim": (
            "Built a Python–Google Earth Engine workflow for Taoyuan using Landsat 8/9, cloud masking, "
            "spectral/terrain features, Random Forest classification, idempotent Asset exports, and stratified "
            f"independent validation. Labeled 250 map-based reference samples; the delivered 2020 Asset achieved "
            f"{binary['builtup_precision']:.1%} built-up precision, {binary['builtup_recall']:.1%} recall, and "
            f"{binary['builtup_f1']:.1%} F1. Automated QA detected mixed-pixel and temporal-transfer limitations."
        ),
        "next_model_target": {
            "scope": "Binary built-up versus non-built-up classifier",
            "reason": "The job-facing project goal is urban expansion; weak cropland/bare-land separation should not dominate it.",
            "acceptance_checks": [
                "Re-evaluate on the same independent probability sample without retraining on those labels.",
                "Improve built-up recall while preserving precision.",
                "Resolve or explain the 2014-2020 direction conflict before reporting change magnitude.",
            ],
        },
    }
    json_path = RESULTS / "final_quality_gate.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md = f"""# 桃园城市扩张项目状态

## 当前结论

工程作品集已经可用；多年份城市扩张数值仍需模型修订。

## 独立验证

- 验证点：250个；有效239个；混合或不清晰11个。
- 五分类面积加权总体精度：{validation['area_adjusted_overall_accuracy_five_class']:.1%}。
- 建成区二分类总体精度：{binary['overall_accuracy']:.1%}。
- 建成区精确率：{binary['builtup_precision']:.1%}；召回率：{binary['builtup_recall']:.1%}；F1：{binary['builtup_f1']:.1%}。

## 简历可用描述

{report['resume_safe_claim']}

## 限制

农地和裸地分类表现不足，且2014至2020建成区结果轻微下降。当前结果适合展示Python/GEE自动化、数据质量检查和独立验证能力，不适合宣称精确测得2014至2025扩张面积。
"""
    md_path = ROOT / "PROJECT_STATUS.md"
    md_path.write_text(md, encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")


if __name__ == "__main__":
    main()
