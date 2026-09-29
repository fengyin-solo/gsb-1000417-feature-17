"""车辆消杀业务规则：筛选、状态流转、归属修正与版本控制都收在这里。

口径约定（列表、看板、明细、车辆归属视图共用同一份数据）：
- 全部视图都从「去重后的消杀记录」出发，按消杀编号去重，翻页总数等于去重后的条数。
- 登记接口幂等：同一消杀编号重复提交只返回原记录，失败重试不生成副本。
- 修正车辆归属时携带版本号，版本不一致直接拒绝落库（乐观并发控制）。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "sanitation"
REQUIRED_FIELDS = ["消杀编号", "车辆编号", "消杀方式"]
BUSINESS_FIELDS = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期"]
STATUS_ORDER = ["待消杀", "已消杀", "复消中"]
ACTION_RULES = {"执行消杀": "已消杀", "安排复消": "复消中"}
NEGATIVE_ACTIONS = []
NATURAL_KEY = "消杀编号"
VERSION_FIELD = "version"
DEFAULT_VERSION = 1


class SanitationConflictError(Exception):
    """归属修正版本冲突：客户端基于过期版本提交，拒绝落库。"""


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


class SanitationService:
    # ---------- 数据源：去重后的消杀记录 ----------
    def _rows(self) -> list[dict[str, Any]]:
        rows = store.rows(MODULE)
        for row in rows:
            row.setdefault(VERSION_FIELD, DEFAULT_VERSION)
        return rows

    def _dedupe(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按消杀编号去重，保留首次出现的记录；缺失编号时用 id 兜底。"""
        seen: set[str] = set()
        deduped: list[dict[str, Any]] = []
        for row in rows:
            key = str(row.get(NATURAL_KEY) or f"__id:{row.get('id')}")
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        return deduped

    def _base_rows(self) -> list[dict[str, Any]]:
        return self._dedupe(self._rows())

    # ---------- 统一筛选口径（列表、看板、归属视图共用） ----------
    def _filter(
        self,
        rows: list[dict[str, Any]],
        *,
        keyword: str | None = None,
        vehicle: str | None = None,
        method: str | None = None,
        area: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(NATURAL_KEY, ""))]
        if vehicle:
            rows = [row for row in rows if vehicle in str(row.get("车辆编号", ""))]
        if method:
            rows = [row for row in rows if method in str(row.get("消杀方式", ""))]
        if area:
            rows = [row for row in rows if area in str(row.get("消杀区域", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        vehicle: str | None = None,
        method: str | None = None,
        area: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = self._filter(
            self._base_rows(),
            keyword=keyword,
            vehicle=vehicle,
            method=method,
            area=area,
            status=status,
        )
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in self._base_rows():
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    # ---------- 登记（幂等） ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], bool]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing, False
        code = str(values.get(NATURAL_KEY) or "").strip()
        # 幂等：同一消杀编号已存在时直接返回原记录，重试不生成副本。
        for row in self._base_rows():
            if str(row.get(NATURAL_KEY) or "") == code:
                return row, [], True
        rows = self._rows()
        entry: dict[str, Any] = {"id": max((int(r.get("id", 0)) for r in rows), default=0) + 1}
        entry.update({field: values[field] for field in BUSINESS_FIELDS if field in values})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry[VERSION_FIELD] = DEFAULT_VERSION
        rows.append(entry)
        return entry, [], False

    # ---------- 状态流转 ----------
    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"消杀记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于车辆消杀可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"消杀记录已{action}"

    # ---------- 归属修正（乐观并发控制） ----------
    def correct_attribution(
        self,
        entry_id: int,
        vehicle: str,
        expected_version: int,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = self.get_entry(entry_id)
        if entry is None:
            return None, f"消杀记录 {entry_id} 不存在或已归档"
        current_version = int(entry.get(VERSION_FIELD, DEFAULT_VERSION))
        if current_version != expected_version:
            raise SanitationConflictError(
                f"消杀记录 {entry_id} 已被他人修正（当前版本 {current_version}，提交版本 {expected_version}），请刷新后重试"
            )
        vehicle = str(vehicle or "").strip()
        if not vehicle:
            return None, "车辆编号不能为空"
        entry["车辆编号"] = vehicle
        entry[VERSION_FIELD] = current_version + 1
        return entry, f"消杀记录 {entry_id} 归属已修正为 {vehicle}"

    # ---------- 看板统计（与列表同源） ----------
    def stats(
        self,
        *,
        keyword: str | None = None,
        vehicle: str | None = None,
        method: str | None = None,
        area: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        rows = self._filter(
            self._base_rows(),
            keyword=keyword,
            vehicle=vehicle,
            method=method,
            area=area,
            status=status,
        )
        month = _current_month()
        return {
            "total": len(rows),
            "pending": sum(1 for r in rows if r.get("status") == STATUS_ORDER[0]),
            "done": sum(1 for r in rows if r.get("status") == STATUS_ORDER[1]),
            "recheck": sum(1 for r in rows if r.get("status") == STATUS_ORDER[2]),
            "monthly": sum(1 for r in rows if str(r.get("消杀日期", "")).startswith(month)),
        }

    # ---------- 车辆归属视图（与列表同源） ----------
    def by_vehicle(
        self,
        *,
        keyword: str | None = None,
        vehicle: str | None = None,
        method: str | None = None,
        area: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._filter(
            self._base_rows(),
            keyword=keyword,
            vehicle=vehicle,
            method=method,
            area=area,
            status=status,
        )
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            key = str(row.get("车辆编号") or "未归属")
            groups.setdefault(key, []).append(row)
        return [
            {"车辆编号": key, "count": len(items), "items": items}
            for key, items in sorted(groups.items())
        ]
