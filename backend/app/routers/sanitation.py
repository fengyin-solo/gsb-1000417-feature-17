"""车辆消杀接口：维护消杀记录，覆盖执行消杀、安排复消与车辆归属修正。

筛选、看板、车辆归属、导出都委托给 SanitationService 的同一份去重数据，
接口层不再各自取数，避免看板与明细对不上。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.sanitation import StaleVersionError, SanitationService

router = APIRouter(prefix="/api/sanitation", tags=["车辆消杀"])

service = SanitationService()

LIST_FIELDS = ["消杀编号", "车辆编号", "消杀方式", "消毒剂名称", "消杀区域", "操作人员", "消杀日期", "消杀状态"]


class ReassignPayload(BaseModel):
    """修正车辆归属：必须带上读取记录时拿到的版本号。"""

    vehicle: str
    version: int


@router.get("/stats")
def stats_entries() -> dict[str, Any]:
    """消杀看板：待消杀/已消杀/本月消杀，口径与列表完全同源。"""
    return {"module": "sanitation", **service.stats()}


@router.get("/by-vehicle")
def by_vehicle(
    code: str | None = Query(default=None, description="按消杀编号定位"),
    vehicle: str | None = Query(default=None, description="按车辆编号定位"),
    method: str | None = Query(default=None, description="按消杀方式定位"),
    area: str | None = Query(default=None, description="按消杀区域定位"),
) -> dict[str, Any]:
    """车辆归属视图：按车辆编号聚合的消杀记录，与列表、详情使用同一份数据。"""
    filters = {
        "消杀编号": code or "",
        "车辆编号": vehicle or "",
        "消杀方式": method or "",
        "消杀区域": area or "",
    }
    groups = service.vehicle_groups(filters)
    return {"module": "sanitation", "groups": groups, "total": sum(len(group["items"]) for group in groups)}


@router.get("", response_model=PageResult[dict])
def list_entries(
    code: str | None = Query(default=None, description="按消杀编号检索"),
    vehicle: str | None = Query(default=None, description="按车辆编号检索"),
    method: str | None = Query(default=None, description="按消杀方式检索"),
    area: str | None = Query(default=None, description="按消杀区域检索"),
    status: str | None = Query(default=None, description="待消杀、已消杀、复消中"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、车辆、方式、区域定位消杀记录；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    filters = {
        "消杀编号": code or "",
        "车辆编号": vehicle or "",
        "消杀方式": method or "",
        "消杀区域": area or "",
    }
    items, total = service.list_entries(filters=filters, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条消杀记录，缺字段时说明原因；同编号重试幂等返回，不生成副本。"""
    entry, missing, created = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if created:
        return ActionResult(ok=True, message="消杀记录已登记", entry=entry)
    return ActionResult(ok=True, message="消杀编号已存在，已返回既有记录，未重复登记", entry=entry)


@router.post("/{entry_id}/reassign", response_model=ActionResult)
def reassign_entry(entry_id: int, payload: ReassignPayload) -> ActionResult:
    """修正车辆归属：版本号过期（并发冲突）返回 409，拒绝落库。"""
    try:
        entry = service.reassign_vehicle(entry_id, payload.vehicle, payload.version)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"消杀记录 {entry_id} 不存在或已归档")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except StaleVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return ActionResult(ok=True, message="车辆归属已修正", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条消杀记录执行执行消杀、安排复消；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出车辆消杀清单：与列表同源，返回去重后的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "sanitation", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消杀记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消杀记录 {entry_id} 不存在或已归档")
    return entry
