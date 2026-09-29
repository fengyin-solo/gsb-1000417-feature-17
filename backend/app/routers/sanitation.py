"""车辆消杀接口：列表筛选、明细、登记、动作、归属修正与看板统计。

列表、看板、车辆归属视图共用同一套筛选与去重口径；归属修正带版本号，
版本不一致时返回 409，拒绝落库。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.sanitation import SanitationConflictError, SanitationService

router = APIRouter(prefix="/api/sanitation", tags=["车辆消杀"])

service = SanitationService()

PAGE_SIZE_MAX = 200


def _parse_version(payload: EntryPayload) -> int:
    raw = payload.values.get("version")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="version 必须是整数")


def _list_filters(
    keyword: str | None,
    vehicle: str | None,
    method: str | None,
    area: str | None,
    status: str | None,
) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "vehicle": vehicle,
        "method": method,
        "area": area,
        "status": status,
    }


@router.get("")
def list_entries(
    keyword: str | None = Query(default=None, description="按消杀编号检索"),
    vehicle: str | None = Query(default=None, description="按车辆编号检索"),
    method: str | None = Query(default=None, description="按消杀方式检索"),
    area: str | None = Query(default=None, description="按消杀区域检索"),
    status: str | None = Query(default=None, description="待消杀、已消杀、复消中"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、车辆、方式、区域与状态过滤车辆消杀列表；翻页总数等于去重后的条数。"""
    if size > PAGE_SIZE_MAX:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        **_list_filters(keyword, vehicle, method, area, status), page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/stats")
def get_stats(
    keyword: str | None = Query(default=None),
    vehicle: str | None = Query(default=None),
    method: str | None = Query(default=None),
    area: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """看板统计：与列表同一份筛选口径，保证看板与明细同源。"""
    return service.stats(**_list_filters(keyword, vehicle, method, area, status))


@router.get("/by-vehicle")
def list_by_vehicle(
    keyword: str | None = Query(default=None),
    vehicle: str | None = Query(default=None),
    method: str | None = Query(default=None),
    area: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """车辆归属视图：与列表同源的消杀记录按车辆编号分组。"""
    groups = service.by_vehicle(**_list_filters(keyword, vehicle, method, area, status))
    return {"groups": groups, "total": sum(group["count"] for group in groups)}


@router.get("/export")
def export_entries(
    keyword: str | None = Query(default=None),
    vehicle: str | None = Query(default=None),
    method: str | None = Query(default=None),
    area: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """导出车辆消杀清单：与列表同口径的全量数据。"""
    items, total = service.list_entries(
        **_list_filters(keyword, vehicle, method, area, status), page=1, size=10000
    )
    return {"module": "sanitation", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条消杀记录明细；与列表、归属视图是同一条记录。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"消杀记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条消杀记录；同一消杀编号重复提交只返回原记录，失败重试不生成副本。"""
    entry, missing, duplicated = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    if duplicated:
        return ActionResult(ok=True, message="该消杀编号已存在，已返回原记录", entry=entry)
    return ActionResult(ok=True, message="消杀记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条消杀记录执行执行消杀、安排复消；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.patch("/{entry_id}/attribution", response_model=ActionResult)
def correct_attribution(entry_id: int, payload: EntryPayload) -> ActionResult:
    """修正车辆归属：提交读到的版本号，版本不一致时拒绝落库（乐观并发控制）。"""
    vehicle = str(payload.values.get("车辆编号") or "").strip()
    version = _parse_version(payload)
    try:
        entry, message = service.correct_attribution(entry_id, vehicle, version)
    except SanitationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
