"""外站交接包的入库与独立验算。

处理顺序固定为：先识别原巡检批次，再按交接包声明的规则版本重算，最后落报告。
每一步都以唯一约束兜底，因此中断后重跑同一条交接包会续用已验结果，不新增报告。
"""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.constants.enums import Handoff
from src.domain import analysis, rules
from src.models.handoff import HandoffBatch, HandoffReport
from src.services.datasets import checksum


class HandoffConflict(Exception):
    """同站同号但内容与已存报告不一致，需要退回。"""

    def __init__(self, message, existing=None):
        super().__init__(message)
        self.existing = existing


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _identity_hash(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _package_identity(package, batch_signature, rule):
    """报告身份只取决于交接包输入，便于重试时直接识别已验批次。

    条件先规范成 (字段, 取值)，命中单号按集合比较；因此同一份交接包只要内容
    等价，即便标签顺序或单号顺序不同，也视为同一个包，不会误报「内容有变」。
    """
    claimed = {
        "ranking": parse_ranking(package["claimed"], rule),
        "positive_hits": _ids(package["claimed"], "positive_hits", "见霉斑组"),
        "negative_hits": _ids(package["claimed"], "negative_hits", "未见霉斑组"),
    }
    params = analysis.normalize_params(package.get("params") or {}, rule.PARAMS)
    return _identity_hash({
        "batch_checksum": batch_signature,
        "rule_version": package["rule_version"],
        "params": params,
        "claimed": claimed,
    })


def _batch_key(package, signature):
    key = package.get("batch_key")
    if key is None:
        return f"sha256:{signature[:16]}"
    key = key.strip()
    if not key:
        raise ValueError("批次编号不能为空")
    return key


def _label_index(rule):
    """标签到 (字段, 取值) 的映射，用于识别交接包用业务标签书写的条件。"""
    index = {}
    for field, (low, high) in rule.condition_labels().items():
        index[low] = (field, False)
        index[high] = (field, True)
    return index


def _conditions(raw, rule):
    """把交接包的条件写法规范为 [(字段, 取值), ...]，标签须能对上该版本的取值。"""
    if isinstance(raw, str):
        parts = [part.strip() for part in raw.split("且") if part.strip()]
    elif isinstance(raw, (list, tuple)):
        parts = raw
    else:
        raise ValueError("排名中的条件须为条件键名列表或「且」连接的标签")
    index = _label_index(rule)
    resolved = []
    try:
        for part in parts:
            if isinstance(part, (list, tuple)) and len(part) == 2:
                field, value = str(part[0]).strip(), part[1]
                if not isinstance(value, bool) or (field, True) not in index.values():
                    raise KeyError(part)
                resolved.append((field, value))
            else:
                resolved.append(index[str(part).strip()])
    except KeyError as error:
        raise ValueError(f"排名中出现无法识别的条件「{error.args[0]}」") from None
    return tuple(sorted(resolved))


def _count(raw, label):
    if type(raw) is not int or raw < 0:
        raise ValueError(f"排名中的{label}须为非负整数")
    return raw


def parse_ranking(claimed, rule):
    items = claimed.get("ranking")
    if not isinstance(items, list):
        raise ValueError("交接包缺少排名结果")
    ranking = []
    for position, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"排名第 {position} 项格式有误")
        ranking.append({
            "conditions": _conditions(item.get("conditions"), rule),
            "positive_count": _count(item.get("positive_count"), "正组命中"),
            "negative_count": _count(item.get("negative_count"), "负组命中"),
        })
    return ranking


def _ids(claimed, key, label):
    raw = claimed.get(key)
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item.strip() for item in raw):
        raise ValueError(f"交接包缺少{label}命中单号")
    return sorted(item.strip() for item in raw)


def _phrase(labels, conditions):
    return "且".join(labels[field][value] for field, value in conditions)


def compare(claimed, computed, rule):
    """比较交接包声明与本地重算的排名和两组命中单号，返回差异说明。"""
    labels = rule.condition_labels()

    def describe(item):
        if not item:
            return "无"
        text = "且".join(labels[field][value] for field, value in item["conditions"])
        return f"{text}（正组 {item['positive_count']} / 负组 {item['negative_count']}）"

    messages = []
    actual = claimed["ranking"]
    expected = [{
        "conditions": tuple((field, value) for field, value in item["conditions"]),
        "positive_count": item["positive_count"],
        "negative_count": item["negative_count"],
    } for item in computed["ranking"]]
    for index in range(max(len(actual), len(expected))):
        left = expected[index] if index < len(expected) else None
        right = actual[index] if index < len(actual) else None
        if left != right:
            messages.append(f"第 {index + 1} 名应为 {describe(left)}，交接包写为 {describe(right)}")
            if len(messages) >= 5:
                break
    for key, label in (("positive_hits", "见霉斑组"), ("negative_hits", "未见霉斑组")):
        if claimed[key] != computed[key]:
            messages.append(f"{label}命中单号不一致：交接包 {len(claimed[key])} 条，"
                            f"本站重算 {len(computed[key])} 条")
    return messages


def verify(package, rows):
    """按交接包声明的规则版本重算，返回验算结论与页面对账数据。"""
    version = package["rule_version"]
    rule = rules.get(version)
    supplied = package.get("params") or {}
    expected = {field["key"] for field in rule.PARAMS}
    unknown = set(supplied) - expected
    if unknown:
        raise ValueError(f"交接包参数与规则 {version} 不符，未知参数：{'、'.join(sorted(unknown))}")
    missing = expected - set(supplied)
    if missing:
        # 参数必须随包带到，避免用本站默认值替代外站实际口径。
        raise ValueError(f"交接包缺少规则 {version} 的参数：{'、'.join(sorted(missing))}")
    params = analysis.normalize_params(supplied, rule.PARAMS)
    _result, computed = analysis.evaluate(rows, params, version)
    claimed_raw = package["claimed"]
    claimed = {
        "ranking": parse_ranking(claimed_raw, rule),
        "positive_hits": _ids(claimed_raw, "positive_hits", "见霉斑组"),
        "negative_hits": _ids(claimed_raw, "negative_hits", "未见霉斑组"),
    }
    differences = compare(claimed, computed, rule)
    if not computed["positive_total"] or not computed["negative_total"]:
        differences.insert(0, "原巡检缺少一组记录，无法按原版规则比较两组命中")
    labels = rule.condition_labels()
    state = Handoff.RETURNED if differences else Handoff.VERIFIED
    headline = (
        f"交接包 {package['report_no']} 按规则 {version} 验算一致，排名与两组命中单号均可复核。"
        if state == Handoff.VERIFIED else
        f"交接包 {package['report_no']} 与规则 {version} 的独立重算不一致，已退回。"
    )
    ranking = [{
        "rank": index,
        "conditions": _phrase(labels, item["conditions"]),
        "positive_count": item["positive_count"],
        "negative_count": item["negative_count"],
        "growth": float(item["growth"]),
    } for index, item in enumerate(computed["ranking"], start=1)]
    return {
        "state": state,
        "headline": headline,
        "rule_version": version,
        "params": params,
        "differences": differences,
        "result": {
            "ranking": ranking,
            "positive_hits": computed["positive_hits"],
            "negative_hits": computed["negative_hits"],
            "positive_total": computed["positive_total"],
            "negative_total": computed["negative_total"],
            "differences": differences,
        },
    }


def example_package():
    """用当前规则和演示巡检生成一份可验算通过的示例交接包。"""
    from src.domain.demo import demo_rows

    version = rules.CURRENT
    rule = rules.get(version)
    params = {field["key"]: field["default"] for field in rule.PARAMS}
    rows = demo_rows()
    _result, computed = analysis.evaluate(rows, params, version)
    return {
        "station": "示例外站",
        "report_no": "R-EXAMPLE-01",
        "batch_key": "PQ-20261116-20",
        "rule_version": version,
        "params": params,
        "rows": rows,
        "claimed": {
            "ranking": computed["ranking"],
            "positive_hits": computed["positive_hits"],
            "negative_hits": computed["negative_hits"],
        },
    }


def _prepare(package):
    """在写入前完成结构校验，返回批次签名与报告身份。"""
    rule = rules.get(package["rule_version"])
    rows = package["rows"]
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"原巡检第 {index} 条格式有误")
    analysis.validate_rows(rows)
    signature = checksum(rows)
    return signature, _package_identity(package, signature, rule)


def _find_report(db, station, report_no):
    return db.scalar(select(HandoffReport).where(
        HandoffReport.station == station, HandoffReport.report_no == report_no))


def _save_batch(db, package, signature, rows, actor):
    """相同巡检内容只存一份：先按批次编号，再按内容指纹复用。"""
    key = _batch_key(package, signature)
    existing = db.scalar(select(HandoffBatch).where(HandoffBatch.batch_key == key))
    if existing:
        if existing.checksum != signature:
            raise HandoffConflict(f"批次编号「{key}」已存在且巡检内容不一致，请核对来源")
        return existing, False
    existing = db.scalar(select(HandoffBatch).where(HandoffBatch.checksum == signature))
    if existing:
        # 同一批巡检换了批次编号再次交接，复用已存批次，不重复保存。
        return existing, False
    item = HandoffBatch(batch_key=key, checksum=signature, row_count=len(rows),
                        rows=rows, author=actor)
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(HandoffBatch).where(HandoffBatch.batch_key == key).with_for_update())
        if existing and existing.checksum == signature:
            return existing, False
        existing = db.scalar(select(HandoffBatch).where(HandoffBatch.checksum == signature))
        if existing:
            return existing, False
        raise HandoffConflict(f"批次编号「{key}」已被其他导入占用，请核对来源") from None
    return item, True


def _save_report(db, package, batch, verification, identity, actor):
    """只保存验算通过的报告；退回内容只回给调用方，不入库。"""
    station, report_no = package["station"], package["report_no"]
    existing = _find_report(db, station, report_no)
    if existing:
        if existing.content_hash != identity:
            raise HandoffConflict(
                f"站点「{station}」报告号「{report_no}」已有不同内容，已退回", existing)
        return existing, False
    item = HandoffReport(
        station=station, report_no=report_no, batch_id=batch.id, params=verification["params"],
        rule_version=verification["rule_version"], content_hash=identity,
        state=verification["state"], headline=verification["headline"],
        result=verification["result"], author=actor,
    )
    try:
        with db.begin_nested():
            db.add(item)
            db.flush()
    except IntegrityError:
        existing = db.scalar(select(HandoffReport).where(
            HandoffReport.station == station, HandoffReport.report_no == report_no).with_for_update())
        if existing and existing.content_hash == identity:
            return existing, False
        raise HandoffConflict(
            f"站点「{station}」报告号「{report_no}」已被其他导入占用且内容不同，已退回",
            existing) from None
    return item, True


def ingest(db, package, actor):
    """验算并保存一条交接包。

    返回 ``(report, verification, batch_created, report_created)``。验算不一致时
    ``report`` 为 ``None``：退回内容不入库，也不占用批次编号。顺序固定为先验算、
    再落批次、最后落报告；新批次单独提交，因此进程中断后重试会复用已验批次，
    同一条交接包重跑不会再新增报告。
    """
    signature, identity = _prepare(package)
    existing = _find_report(db, package["station"], package["report_no"])
    if existing:
        if existing.content_hash != identity:
            raise HandoffConflict(
                f"站点「{package['station']}」报告号「{package['report_no']}」已有不同内容，已退回",
                existing)
        return existing, None, False, False
    verification = verify(package, package["rows"])
    if verification["state"] != Handoff.VERIFIED:
        return None, verification, False, False
    batch, batch_created = _save_batch(db, package, signature, package["rows"], actor)
    if batch_created:
        # 批次先单独落库：验算已通过的批次成为续跑检查点。
        db.commit()
    report, report_created = _save_report(db, package, batch, verification, identity, actor)
    return report, verification, batch_created, report_created
