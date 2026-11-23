"""已发布筛查规则的只读登记表。

规则每次变更都追加一个新版本模块，已发布模块不再改写。外站交接包声明
计算时使用的规则版本，本站验算始终按该版本重算，因此本站升级规则不会
改变旧报告的对账结果。
"""

from . import r1

_MODULES = {module.VERSION: module for module in (r1,)}
CURRENT = r1.VERSION


def catalog():
    """按发布顺序返回可用规则版本，供页面展示与交接包选择。"""
    return [
        {"version": module.VERSION, "label": module.LABEL,
         "released": module.RELEASED, "notes": module.NOTES}
        for module in _MODULES.values()
    ]


def exists(version):
    return version in _MODULES


def get(version):
    try:
        return _MODULES[version]
    except KeyError:
        raise ValueError(f"规则版本「{version}」未登记，无法按原版验算") from None
