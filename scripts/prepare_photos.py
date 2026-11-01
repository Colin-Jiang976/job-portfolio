"""本地照片批量准备：JPG → WebP、原图副本、目录及导入资料；不调用 AWS。"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/photo-api"))
from photo_locations import clean_location
LOCAL = ROOT / ".local"
PUBLISHED_BASELINE = LOCAL / "photo-app/published-catalog.json"
DEFAULT_BASELINE = PUBLISHED_BASELINE if PUBLISHED_BASELINE.is_file() else LOCAL / "photo-app/catalog.json"
ID = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
PREVIEW = re.compile(r"assets/photos/[A-Za-z0-9_.-]+\.webp")


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def order_of(item):
    match = re.fullmatch(r"PHOTO#(\d{9})#" + re.escape(item["id"]), item["SK"])
    if not match or int(match[1]) < 1:
        raise ValueError("基准目录含无效排序键。")
    return int(match[1])


def load_baseline(path):
    items = read_json(path)
    if not isinstance(items, list):
        raise ValueError("基准须为 catalog.json 格式的数组。")
    # 复用真实 API 的资料校验；这里不导入/连接 boto3。
    sys.path.insert(0, str(ROOT / "backend/photo-api"))
    from lambda_function import public_photo
    ids, orders, previews, hashes = set(), set(), set(), set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("基准记录须为对象。")
        public_photo(item, "main")
        order = order_of(item)
        if (item.get("PK") != "ALBUM#main" or item["id"] in ids or order in orders
                or item["previewKey"].lower() in previews or item["sha256"] in hashes):
            raise ValueError("基准目录的相册、ID、顺序、预览路径或原图哈希存在冲突。")
        ids.add(item["id"])
        orders.add(order)
        previews.add(item["previewKey"].lower())
        hashes.add(item["sha256"])
    return items


def source_file(source, filename):
    if (not isinstance(filename, str) or not re.fullmatch(r'[^/\\\x00-\x1f<>:"|?*]+\.jpe?g', filename, re.I)):
        raise ValueError("文件名须为输入目录内的 JPG/JPEG 文件名，不能包含子路径。")
    path = (source / filename).resolve(strict=True)
    if path.parent != source or not path.is_file():
        raise ValueError("原图不存在或通过链接指向输入目录外。")
    return path


def make_selection(source, selection_path, baseline, start_order):
    by_hash = {item["sha256"]: item for item in baseline}
    next_order = start_order if start_order is not None else max((order_of(item) for item in baseline), default=0) + 1
    if selection_path:
        selection = read_json(selection_path)
    else:
        photos = []
        # 只读取明确输入目录第一层，不递归收集其他目录。
        files = sorted((p for p in source.iterdir() if p.suffix.lower() in (".jpg", ".jpeg")), key=lambda p: p.name.casefold())
        for candidate in files:
            checksum = digest(source_file(source, candidate.name))
            known = by_hash.get(checksum)
            if known:
                photo = {"id": known["id"], "filename": candidate.name, "order": order_of(known),
                         "previewKey": known["previewKey"]}
                if "title" in known:
                    photo["title"] = known["title"]
                if "location" in known:
                    photo["location"] = known["location"]
            else:
                photo_id = "p-" + checksum[:24]
                photo = {"id": photo_id, "filename": candidate.name, "order": next_order,
                         "previewKey": f"assets/photos/{photo_id}.webp"}
                next_order += 1
            photos.append(photo)
        selection = {"albumId": "main", "tableName": "cj-photo-catalog", "photos": photos}
    if not isinstance(selection, dict):
        raise ValueError("选择清单须为对象。")
    if selection.get("albumId") != "main" or selection.get("tableName") != "cj-photo-catalog":
        raise ValueError("本轮仅准备已有 main 相册/cj-photo-catalog 表，不生成新资源。")
    if not isinstance(selection.get("photos"), list) or not selection["photos"]:
        raise ValueError("没有选择 JPG/JPEG；检查输入目录或清单。")
    return selection


def validate_selection(source, selection, baseline):
    by_id = {item["id"]: item for item in baseline}
    by_order = {order_of(item): item for item in baseline}
    by_preview = {item["previewKey"].lower(): item for item in baseline}
    by_hash = {item["sha256"]: item for item in baseline}
    ids, orders, previews, filenames, hashes = set(), set(), set(), set(), set()
    checked = []
    for photo in selection["photos"]:
        if not isinstance(photo, dict):
            raise ValueError("清单中的照片须为对象。")
        photo_id, order, preview = photo.get("id"), photo.get("order"), photo.get("previewKey")
        if (not isinstance(photo_id, str) or not ID.fullmatch(photo_id)
                or type(order) is not int or not 1 <= order <= 999999999
                or not isinstance(preview, str) or not PREVIEW.fullmatch(preview)):
            raise ValueError("清单的 ID、顺序或预览路径格式无效。")
        path = source_file(source, photo.get("filename"))
        checksum = digest(path)
        if (photo_id in ids or order in orders or preview.lower() in previews
                or path.name.casefold() in filenames or checksum in hashes):
            raise ValueError("本批含重复 ID、顺序、预览路径、文件名或相同原图，拒绝含糊冲突。")
        old = by_id.get(photo_id)
        if "location" in photo:
            photo["location"] = clean_location(photo["location"])
        if old and clean_location(old.get("location")) != clean_location(photo.get("location")):
            raise ValueError("已有照片地点请通过地点维护修改，不在新照片批次覆盖。")
        if old and (old["sha256"] != checksum or order_of(old) != order or old["previewKey"] != preview):
            raise ValueError(f"{photo_id} 与基准的原图、顺序或预览键不同；拒绝覆盖/产生重复记录。")
        for existing in (by_order.get(order), by_preview.get(preview.lower()), by_hash.get(checksum)):
            if existing and existing["id"] != photo_id:
                raise ValueError(f"{photo_id} 与基准的顺序、预览键或原图身份冲突。")
        with Image.open(path) as image:
            if image.format != "JPEG":
                raise ValueError(f"{photo_id} 的内容不是 JPEG。")
            image.verify()
        ids.add(photo_id)
        orders.add(order)
        previews.add(preview.lower())
        filenames.add(path.name.casefold())
        hashes.add(checksum)
        checked.append((photo, path, checksum))
    return checked


def prepare_batch(source, *, selection_path=None, baseline_path=DEFAULT_BASELINE, start_order=None, output=None):
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("输入须为一批 JPG 所在目录。")
    baseline_path = Path(baseline_path).resolve(strict=True)
    baseline = load_baseline(baseline_path)
    selection = make_selection(source, selection_path, baseline, start_order)
    checked = validate_selection(source, selection, baseline)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    output = Path(output or LOCAL / "photo-app/batches" / stamp).resolve()
    if not output.is_relative_to(LOCAL.resolve()) or output == LOCAL.resolve():
        raise ValueError("输出必须位于本项目 .local 的独立新目录。")
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("输出目录已存在或与输入目录重叠，拒绝覆盖。")
    node = shutil.which("node")
    if not node:
        fallback = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe"
        node = str(fallback) if fallback.is_file() else None
    if not node:
        raise ValueError("未找到 Node.js；资料生成需要现有 Node.js 工具。")
    output.parent.mkdir(parents=True, exist_ok=True)
    # 未完成目录不会冒充可发布结果；失败保留以便诊断，不删除用户文件。
    staging = output.with_name(".incomplete-" + output.name)
    staging.mkdir(exist_ok=False)
    s3 = staging / "s3"
    write_json(staging / "selection.json", selection)
    write_json(staging / "baseline-before.json", baseline)
    for photo, path, checksum in checked:
        destination = s3 / photo["previewKey"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        # 已有预览复用原字节，避免本次五样本演示覆盖线上预览。
        existing_preview = baseline_path.parent / "s3" / photo["previewKey"]
        if not existing_preview.is_file():
            existing_preview = ROOT / "dist" / photo["previewKey"]
        old = next((item for item in baseline if item["id"] == photo["id"]), None)
        if old and existing_preview.is_file():
            with Image.open(existing_preview) as image:
                if image.format != "WEBP":
                    raise ValueError("已有预览不是 WebP。")
                image.verify()
            shutil.copyfile(existing_preview, destination)
        else:
            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original)
                image.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                if image.mode not in ("RGB", "RGBA"):
                    image = image.convert("RGB")
                options = {"quality": 88, "method": 6}
                if original.mode == "RGB" and original.info.get("icc_profile"):
                    options["icc_profile"] = original.info["icc_profile"]
                image.save(destination, "WEBP", **options)
        original_copy = s3 / f"photo-originals/main/{photo['id']}.jpg"
        original_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, original_copy)
        if digest(path) != checksum or digest(original_copy) != checksum:
            raise ValueError("准备过程中原图变化，批次未完成，请核对后重新生成。")
    subprocess.run([node, str(ROOT / "scripts/prepare-photo-data.cjs"), str(source),
                    "--selection", str(staging / "selection.json"), "--output", str(staging),
                    "--preview-root", str(s3)], check=True)
    catalog = read_json(staging / "catalog.json")
    for item, (_, _, checksum) in zip(sorted(catalog, key=lambda p: p["id"]), sorted(checked, key=lambda p: p[0]["id"])):
        if item["sha256"] != checksum:
            raise ValueError("资料与复制原图哈希不一致，批次未完成。")
    merged = {item["id"]: item for item in baseline}
    merged.update({item["id"]: item for item in catalog})
    write_json(staging / "baseline-after.json", sorted(merged.values(), key=lambda p: p["SK"]))
    files = []
    for item in catalog:
        for key, kind in ((item["previewKey"], "preview"), (item["originalKey"], "original")):
            file = s3 / key
            files.append({"key": key, "kind": kind, "sizeBytes": file.stat().st_size, "sha256": digest(file)})
    write_json(staging / "manifest.json", {
        "status": "prepared-local-only", "tableName": selection["tableName"], "albumId": "main",
        "selectedCount": len(catalog), "knownCountAfter": len(merged),
        "baselinePath": str(baseline_path), "baselineSha256": digest(baseline_path),
        "baselineIsLiveAwsCheck": False, "s3Files": files,
        "batchFiles": sorted(p.name for p in staging.glob("batch-*.json")),
        "operation": "Put selected records at unchanged PK/SK; omitted records are not deleted",
    })
    # 预览用打包后的副本，不依赖输入目录之后是否改名/移动。
    write_json(staging / "source.json", {"directory": str(output / "s3/photo-originals/main"), "assetRoot": str(output / "s3")})
    (staging / "REVIEW.txt").write_text(
        f"仅本地准备：本批 {len(catalog)} 张；基准合并后已知 {len(merged)} 张。\n"
        "s3/ 内 assets/ 和 photo-originals/ 对应桶根对象键，不能上传外层 s3/。\n"
        "先核对 manifest.json 的精确键/大小/哈希，再由本人上传文件、导入所列 batch 文件。\n"
        "资料为 Put：同 PK/SK 会替换整条资料；未列出的照片不删除。\n"
        "baseline-after.json 只是本地候选基准；全部发布并核对成功后，下一批才使用它。\n"
        "本地基准不等于云端现状；本工具不删除、不重排、不替换原图、不自动上传。\n",
        encoding="utf-8")
    staging.rename(output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="明确选择的一批 JPG/JPEG；只读第一层")
    parser.add_argument("--selection", type=Path, help="可选显式清单；省略则自动生成 ID/顺序，无需标题")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="已知目录快照，优先使用已发布快照，否则使用原本地目录")
    parser.add_argument("--start-order", type=int, help="自动新增顺序起点，默认接在基准之后")
    parser.add_argument("--output", type=Path, help="可选独立新输出目录，限项目 .local 内")
    args = parser.parse_args()
    try:
        output = prepare_batch(args.source, selection_path=args.selection, baseline_path=args.baseline,
                               start_order=args.start_order, output=args.output)
        print(f"批次已准备：{output}\n未调用 AWS；未修改输入、dist 或原有准备目录。")
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"准备失败：{error}\n")


if __name__ == "__main__":
    main()
