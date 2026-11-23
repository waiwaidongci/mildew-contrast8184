"""规则版本 r1：与首版筛查口径一致。

本模块一经发布即冻结。任何口径调整都新建版本模块，不在本文件就地修改，
否则旧交接包将无法按原版重算。
"""

from fractions import Fraction
from itertools import combinations

VERSION = "r1"
LABEL = "首版口径"
RELEASED = "2026-11-21"
NOTES = "正组与负组各加平滑量后比较增长倍数，单项与成对条件统一排序。"

# 版本内固定的条件定义与排序口径。字段键名、布尔判断和排序键属于规则口径，
# 改动须新建版本。
CONDITIONS = (
    {"field": "high_humidity", "scale": ("低于高湿切分点", "高湿")},
    {"field": "vent_blocked", "scale": ("风口未遮挡", "风口遮挡")},
    {"field": "maintenance_pending", "scale": ("无待结报修", "设施报修待结")},
)

# 参数定义随版本冻结，避免本站调整表单上下限后无法按原版验算旧交接包。
PARAMS = (
    {"key": "humidity_threshold", "label": "高湿切分点（%）", "type": "number",
     "min": 0, "max": 100, "default": 65},
    {"key": "smoothing", "label": "平滑量 α", "type": "number",
     "min": 0.01, "max": 10, "default": 0.5},
    {"key": "min_positive_count", "label": "正组最少命中", "type": "int",
     "min": 1, "max": 5000, "default": 3},
    {"key": "min_total_count", "label": "两组最少命中合计", "type": "int",
     "min": 1, "max": 5000, "default": 5},
    {"key": "min_growth", "label": "最低增长倍数", "type": "number",
     "min": 1.01, "max": 5000, "default": 1.5},
)

SORT_KEYS = ("-growth", "-positive_count", "size", "conditions")


def condition_labels():
    return {item["field"]: item["scale"] for item in CONDITIONS}


def row_patterns(row, params):
    """枚举一条巡检命中的单项条件与成对条件。"""
    conditions = (
        ("high_humidity", row["humidity"] >= params["humidity_threshold"]),
        ("vent_blocked", row["vent_blocked"]),
        ("maintenance_pending", row["maintenance_pending"]),
    )
    return tuple((condition,) for condition in conditions) + tuple(combinations(conditions, 2))


def score(hits, positives, negatives, params):
    """按 r1 口径筛选并排序模式，返回按名次排列的得分。"""
    alpha = Fraction(str(params["smoothing"]))
    minimum_growth = Fraction(str(params["min_growth"]))
    eligible = []
    for pattern, counts in hits.items():
        positive, negative = counts[True], counts[False]
        if positive < params["min_positive_count"] or positive + negative < params["min_total_count"]:
            continue
        positive_smoothed = (positive + alpha) / (positives + 2 * alpha)
        negative_smoothed = (negative + alpha) / (negatives + 2 * alpha)
        growth = positive_smoothed / negative_smoothed
        if growth >= minimum_growth:
            eligible.append({
                "pattern": pattern, "growth": growth,
                "positive_count": positive, "negative_count": negative,
                "positive_smoothed": positive_smoothed, "negative_smoothed": negative_smoothed,
            })
    eligible.sort(key=lambda item: (-item["growth"], -item["positive_count"],
                                    len(item["pattern"]), item["pattern"]))
    return eligible
