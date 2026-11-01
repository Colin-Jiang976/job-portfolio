"""新批次看图选地点后完成本地材料；不重新压图或调用AWS。"""
from pathlib import Path
import uuid

import prepare_photos as core
from photo_locations import clean_location


def finish_locations(batch, assignments):
    from photo_publish import atomic_json, marshal
    batch = Path(batch).resolve(strict=True)
    if not batch.is_relative_to(core.LOCAL.resolve()):
        raise ValueError("批次须位于项目.local内。")
    photos = core.load_baseline(batch / "catalog.json")
    before = core.load_baseline(batch / "baseline-before.json")
    current = core.load_baseline(core.DEFAULT_BASELINE)
    if before != current:
        raise ValueError("已发布基准发生变化，请基于当前记录重新准备。")
    if ({p["id"] for p in photos} & {p["id"] for p in current}
            or not isinstance(assignments, dict) or set(assignments) != {p["id"] for p in photos}):
        raise ValueError("新批次照片身份不一致，未完成准备。")
    assignments = {key: clean_location(value) for key, value in assignments.items()}
    missing = sum(not label or label in ("未分类", "未分類", "unassigned") for label in assignments.values())
    if missing:
        return {"complete": False, "remaining": missing, "preparedCount": len(photos)}
    items = [{**p, "location": assignments[p["id"]]} for p in photos]
    # 文件更新中禁止菜单5读到未完成的资料；中断后重开页面可用保存进度重试。
    marker = batch / "location-finalizing.json"
    atomic_json(marker, {"status": "finishing-local-locations"})
    atomic_json(batch / "catalog.json", items)
    atomic_json(batch / "selection.json", {**core.read_json(batch / "selection.json"), "photos": [
        {**row, "location": assignments[row["id"]]} for row in core.read_json(batch / "selection.json")["photos"]]})
    atomic_json(batch / "baseline-after.json", sorted(current + items, key=lambda p: p["SK"]))
    for start in range(0, len(items), 25):
        atomic_json(batch / f"batch-{start//25+1:03d}.json", {"cj-photo-catalog": [
            {"PutRequest": {"Item": marshal(item)}} for item in items[start:start+25]]})
    manifest = core.read_json(batch / "manifest.json")
    atomic_json(batch / "manifest.json", {**manifest, "locationsComplete": True})
    marker.unlink(missing_ok=True)
    return {"complete": True, "remaining": 0, "preparedCount": len(items)}
