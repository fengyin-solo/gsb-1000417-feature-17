"""车辆消杀业务规则：状态流转、字段校验、筛选口径与并发修正都收在这里。

口径约定：
- 看板统计、列表分页、明细详情与车辆归属视图全部走 :meth:`canonical_rows`，
  按「消杀编号」去重后只认最新一条，保证处处同源；
- 翻页 total 始终等于去重后的条数；
- 登记接口以「消杀编号」做幂等键，失败重试命中已有记录时直接回显，不再落库副本；
- 修正车辆归属走乐观锁（version），并发提交时只有携带当前版本号的那一个能落库，
  其余返回冲突，由调用方重新拉取最新版本后再提交。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.store import store

MODULE = "sanitation"
REQUIRED_FIELDS = ["消杀编号", "车辆编号", "消杀方式"]
OPTIONAL_FIELDS = ["消毒剂名称", "消杀区域", "操作人员", "消杀日期"]
ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS
STATUS_ORDER = ["待消杀", "已消杀", "复消中"]
ACTION_RULES = {"执行消杀": "已消杀", "安排复消": "复消中"}
NEGATIVE_ACTIONS = []

# 列表定位字段：编号、车辆、方式、区域
SEARCH_FIELDS = ["消杀编号", "车辆编号", "消杀方式", "消杀区域"]


class StaleVersionError(Exception):
    """并发修正归属时携带的版本号已过期，本次请求不得落库。"""

    def __init__(self, current_version: int) -> None:
        super().__init__(f"记录已被其他人更新，当前版本为 v{current_version}，请刷新后重试")
        self.current_version = current_version


def _version_of(row: dict[str, Any]) -> int:
    return int(row.get("version") or 1)


class SanitationService:
    def __init__(self) -> None:
        # 内存仓库没有数据库的行锁，所有写入串行化，保证幂等判断与版本比较不被并发穿透。
        self._lock = threading.RLock()

    # ---- 同源数据口径 -------------------------------------------------

    def canonical_rows(self) -> list[dict[str, Any]]:
        """按消杀编号去重后的消杀记录，编号相同只保留最后写入的一条。

        列表、详情、看板、导出和车辆归属视图都从这里取数，杜绝各处各算一份。
        """
        unique: dict[str, dict[str, Any]] = {}
        for row in store.rows(MODULE):
            code = str(row.get("消杀编号") or "").strip()
            row.setdefault("version", 1)
            if code:
                unique[code] = row
        return list(unique.values())

    # ---- 查询 ---------------------------------------------------------

    def list_entries(
        self,
        *,
        filters: dict[str, str] | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self.canonical_rows()
        terms = {
            field: value.strip()
            for field, value in (filters or {}).items()
            if value and value.strip()
        }
        for field, term in terms.items():
            if field in SEARCH_FIELDS:
                rows = [row for row in rows if term in str(row.get(field, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        # total 在去重后的口径上统计，保证翻页总数与实际消杀条数对得上。
        total = len(rows)
        page = max(page, 1)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in self.canonical_rows():
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def stats(self) -> dict[str, int]:
        """消杀看板：与列表/明细同源，按去重后的记录统计。"""
        rows = self.canonical_rows()
        month_prefix = datetime.now().strftime("%Y-%m")
        return {
            "total": len(rows),
            "pending": sum(1 for row in rows if row.get("status") == "待消杀"),
            "done": sum(1 for row in rows if row.get("status") == "已消杀"),
            "thisMonth": sum(
                1 for row in rows if str(row.get("消杀日期", "")).startswith(month_prefix)
            ),
        }

    def vehicle_groups(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        """车辆归属视图：按车辆编号聚合同一套消杀记录，不另起数据源。

        支持与列表完全一致的编号、车辆、方式、区域定位条件。
        """
        rows = self.canonical_rows()
        terms = {
            field: value.strip()
            for field, value in (filters or {}).items()
            if value and value.strip()
        }
        for field, term in terms.items():
            if field in SEARCH_FIELDS:
                rows = [row for row in rows if term in str(row.get(field, ""))]
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(str(row.get("车辆编号") or "未归属车辆"), []).append(row)
        return [
            {"vehicle": code, "count": len(items), "items": items}
            for code, items in sorted(groups.items())
        ]

    # ---- 写入 ---------------------------------------------------------

    def create_entry(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[str], bool]:
        """登记消杀记录，返回 (记录, 缺失字段, 是否新建)。

        以消杀编号为幂等键：重试或并发重复提交时直接回显已有记录，不追加副本。
        """
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        code = str(values["消杀编号"]).strip()
        with self._lock:
            for row in self.canonical_rows():
                if str(row.get("消杀编号") or "").strip() == code:
                    return row, [], False
            rows = store.rows(MODULE)
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in ALL_FIELDS:
                value = values.get(field)
                if value is not None and str(value).strip() != "":
                    entry[field] = value
            entry["消杀编号"] = code
            entry["status"] = STATUS_ORDER[0]
            entry["消杀状态"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            entry["version"] = 1
            rows.append(entry)
            return entry, [], True

    def reassign_vehicle(
        self, entry_id: int, vehicle: str, expected_version: int
    ) -> dict[str, Any]:
        """修正消杀记录的车辆归属（乐观锁）。

        只有 expected_version 与库内当前版本一致才允许落库并把 version 加一；
        并发的其它请求版本号过期，抛 :class:`StaleVersionError`，拒绝落库。
        """
        vehicle = vehicle.strip()
        if not vehicle:
            raise ValueError("车辆编号不能为空")
        with self._lock:
            entry = self.get_entry(entry_id)
            if entry is None:
                raise KeyError(entry_id)
            current = _version_of(entry)
            if int(expected_version) != current:
                raise StaleVersionError(current)
            entry["车辆编号"] = vehicle
            entry["version"] = current + 1
            return entry

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        with self._lock:
            entry = self.get_entry(entry_id)
            if entry is None:
                return None, f"消杀记录 {entry_id} 不存在或已归档"
            if action not in ACTION_RULES:
                return None, f"动作「{action}」不属于车辆消杀可执行范围"
            target = ACTION_RULES[action]
            if target not in STATUS_ORDER:
                return None, f"目标状态「{target}」不在允许的状态序列里"
            entry["status"] = target
            entry["消杀状态"] = target
            entry["pending"] = target != STATUS_ORDER[-1]
            entry["abnormal"] = action in NEGATIVE_ACTIONS
            entry["version"] = _version_of(entry) + 1
            return entry, f"消杀记录已{action}"
