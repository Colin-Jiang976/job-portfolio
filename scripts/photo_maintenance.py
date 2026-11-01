"""照片维护：准备、登录，以及仅在本人确认后发布固定目标的新批次。"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

import prepare_photos as core
import photo_publish
from photo_locations import clean_location

INPUT = core.LOCAL / "photo-app/new-input"
LATEST = core.LOCAL / "photo-app/latest-prepared.json"
PUBLISHED_STATE = core.LOCAL / "photo-app/published-state.json"
AWS_PROFILE = "photo-maintenance"
AWS_REGION = "ap-northeast-1"


def login_and_check_identity():
    """只在本人选择此项后启动官方登录，再读取身份；不上传/写表/改IAM。"""
    aws = shutil.which("aws")
    if not aws:
        raise ValueError("未找到 AWS CLI，尚未开始登录。")
    print("将打开 AWS 官方登录页面。请选择管理本站的同一账号和身份。")
    print("登录完成后会自动显示账号和身份；这一步不会上传或发布照片。", flush=True)
    print("如AWS询问为AI助手配置skills/MCP，输入n跳过；本工具不依赖这些集成。", flush=True)
    # login只建立独立配置的临时会话；不改其他profile、不创建长期访问密钥。
    subprocess.run([aws, "login", "--profile", AWS_PROFILE, "--region", AWS_REGION], check=True)
    subprocess.run([aws, "sts", "get-caller-identity", "--profile", AWS_PROFILE,
                    "--region", AWS_REGION, "--query", "{Account:Account,Arn:Arn}",
                    "--output", "json", "--no-cli-pager"], check=True)
    print("本机登录和身份读取已完成；没有发布照片。")


def prepare_new(source=INPUT, baseline_path=core.DEFAULT_BASELINE, *, output=None, latest_path=LATEST, choose_location=None):
    """仅打包快照中还没有的新原图；不会改动已发布快照。"""
    source = Path(source).resolve(strict=True)
    baseline_path = Path(baseline_path).resolve(strict=True)
    baseline = core.load_baseline(baseline_path)
    selection = core.make_selection(source, None, baseline, None)
    # 先检查整批，避免重复文件/坏图因跳过已发布照片而被悄悄忽略。
    core.validate_selection(source, selection, baseline)
    known = {item["id"] for item in baseline}
    selected = selection["photos"]
    new_photos = [photo for photo in selected if photo["id"] not in known]
    result = {"prepared": len(new_photos), "skipped": len(selected) - len(new_photos), "directory": None}
    if not new_photos:
        return result
    if choose_location:
        previous_location = ""
        known_locations = sorted({p.get("location", "") for p in baseline} - {""})
        for photo in new_photos:
            photo["location"] = clean_location(choose_location(photo["filename"], known_locations, previous_location))
            previous_location = photo["location"]
            if previous_location and previous_location not in known_locations:
                known_locations.append(previous_location)
    workspace = core.LOCAL / "photo-app/maintenance"
    workspace.mkdir(parents=True, exist_ok=True)
    selection_path = workspace / ("selection-" + uuid.uuid4().hex + ".json")
    core.write_json(selection_path, {**selection, "photos": new_photos})
    try:
        batch = core.prepare_batch(source, selection_path=selection_path, baseline_path=baseline_path, output=output)
    finally:
        # 仅删除本次明确创建的临时选择文件；原图和历史批次不删除。
        selection_path.unlink(missing_ok=True)
    latest_path = Path(latest_path).resolve()
    if not latest_path.is_relative_to(core.LOCAL.resolve()):
        raise ValueError("最近批次记录必须位于项目 .local 内。")
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = latest_path.with_name(latest_path.name + ".tmp-" + uuid.uuid4().hex)
    core.write_json(temporary, {"directory": str(batch), "preparedCount": len(new_photos),
                               "preparedAt": datetime.now(timezone.utc).isoformat(),
                               "status": "prepared-local-only"})
    temporary.replace(latest_path)
    result["directory"] = str(batch)
    return result


def latest_directory(latest_path=LATEST, published_state_path=PUBLISHED_STATE):
    if Path(latest_path).is_file():
        directory = Path(core.read_json(latest_path)["directory"])
    elif Path(published_state_path).is_file():
        directory = core.ROOT / core.read_json(published_state_path)["latestBatch"]
    else:
        raise ValueError("还没有准备好的批次，请先选择“生成新照片材料”。")
    directory = directory.resolve(strict=True)
    if not directory.is_relative_to(core.LOCAL.resolve()) or not (directory / "manifest.json").is_file():
        raise ValueError("最近批次位置无效；没有打开其他目录。")
    return directory


def status():
    known = len(core.load_baseline(core.DEFAULT_BASELINE))
    files = [p for p in INPUT.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg")] if INPUT.is_dir() else []
    return {"knownPublishedCount": known, "inputJpegCount": len(files), "awsCalled": False}


def open_directory(directory):
    directory = Path(directory).resolve(strict=True)
    if not directory.is_relative_to(core.LOCAL.resolve()) or not directory.is_dir():
        raise ValueError("只能打开项目 .local 内的照片维护目录。")
    os.startfile(str(directory))


def describe_result(result):
    if not result["prepared"]:
        print(f"检查完成：输入目录中的 {result['skipped']} 张照片均已在本地已发布记录中。")
        print("没有重新打包，也没有上传。以后把新 JPG 复制到输入文件夹，再选 2 即可。")
    else:
        print(f"已准备 {result['prepared']} 张新照片，跳过 {result['skipped']} 张已发布照片。")
        print("结果目录：" + result["directory"])
        print("当前只生成本地材料，尚未上传 S3 或写入 DynamoDB。")


def publish_latest():
    plan = photo_publish.make_plan(latest_directory())
    if not plan["items"]:
        print(f"本批 {plan['alreadyPublished']} 张已在本地发布记录中，不重复发布，也没有查询AWS。")
        return
    print("正在只读核对登录身份、目标和本批已完成项……", flush=True)

    def confirm(review):
        target = review["target"]
        print("\n本次发布目标")
        print("账号：********" + target["account"][-4:] + "；身份：clc-admin；区域：" + target["region"])
        print("S3桶：" + target["bucket"])
        print("照片目录表：" + target["table"])
        print(f"本批 {review['newCount']} 张；待上传 {review['filesToUpload']} 文件，待登记 {review['recordsToRegister']} 条。")
        print("确认后会写入上述AWS资源；不会替换不同内容、删除照片或修改权限。")
        return input("输入 PUBLISH 开始；直接回车取消：").strip() == "PUBLISH"

    result = photo_publish.publish(plan, confirm)
    if result["status"] == "cancelled":
        print("已取消，没有写入AWS。")
    elif result["status"] == "verified":
        count = len(core.load_baseline(photo_publish.PUBLISHED))
        print(f"本批 {result['newCount']} 张发布并核对完成；本地已发布记录共 {count} 张。")
        print("现在可在原获邀浏览器刷新线上相册。")


def ask_location(filename, known_locations, previous_location="", *, required=False):
    print("\n照片：" + filename)
    if known_locations:
        print("已有地点：" + "、".join(f"{i+1} {name}" for i, name in enumerate(known_locations)))
    while True:
        prompt = "拍摄地点（必填，输入地点名或编号；=沿用上一张）：" if required else "拍摄地点（输入地点名或编号；回车=未分类；=沿用上一张）："
        value = input(prompt).strip()
        if value in ("未分类", "未分類", "unassigned"):
            value = ""
        if value == "=":
            value = previous_location
        if value.isdigit() and 1 <= int(value) <= len(known_locations):
            return known_locations[int(value) - 1]
        try:
            value = clean_location(value)
            if required and not value:
                print("新增照片必须填写拍摄地点；输入已有编号或地点名即可。")
                continue
            return value
        except ValueError as error:
            print(error)


def ask_new_location(filename, known_locations, previous_location=""):
    return ask_location(filename, known_locations, previous_location, required=True)


def maintain_locations(assignments_path=None):
    from photo_location_maintenance import edit_locations
    items = core.load_baseline(core.DEFAULT_BASELINE)
    if not items:
        print("还没有已发布照片。")
        return
    if assignments_path:
        assignments_path = Path(assignments_path).resolve(strict=True)
        if not assignments_path.is_relative_to(core.LOCAL.resolve()):
            raise ValueError("地点清单须位于项目 .local 内。")
        assignments = core.read_json(assignments_path)
        if not isinstance(assignments, dict) or not assignments or set(assignments) - {p["id"] for p in items}:
            raise ValueError("地点清单须使用已发布照片ID。")
        assignments = {key: clean_location(value) for key, value in assignments.items()}
    else:
        assignments = None
    known = sorted({p.get("location", "") for p in items} - {""})
    if assignments:
        print(f"\n已读取保存的分组清单，共 {len(assignments)} 张（以下为本次待发布地点）：")
        for item in items:
            if item["id"] in assignments:
                print(item["filename"] + " → " + (assignments[item["id"]] or "未分类"))
    else:
        for number, item in enumerate(items, 1):
            print(f"{number}  {item['filename']}  [{item.get('location') or '未分类'}]")
    value = "" if assignments else input("选择要维护的照片编号（空格分隔；all=全部；回车取消）：").strip()
    if not value and not assignments:
        return
    try:
        numbers = [] if assignments else list(range(1, len(items)+1)) if value == "all" else [int(n) for n in value.split()]
    except ValueError as error:
        raise ValueError("请输入编号、all或回车取消。") from error
    if not assignments and (not numbers or len(set(numbers)) != len(numbers) or any(n < 1 or n > len(items) for n in numbers)):
        raise ValueError("照片编号无效或重复。")
    assignments, previous_location = assignments or {}, ""
    for number in numbers:
        item = items[number-1]
        previous_location = ask_location(item["filename"], known, previous_location)
        assignments[item["id"]] = previous_location
        if previous_location and previous_location not in known:
            known.append(previous_location)

    def confirm(review):
        print("\n将修改既有 cj-photo-catalog 表的拍摄地点目录：")
        print("账号：********" + review["target"]["account"][-4:] + "；区域：" + review["target"]["region"])
        for item in review["photos"]:
            print(item["filename"] + " → " + (item["location"] or "未分类"))
        print("只修改照片资料及地点查询条目；不上传/删除图片，不改权限。")
        return input("输入 LOCATIONS 确认；回车取消：").strip() == "LOCATIONS"

    print("\n正在只读核对AWS身份和照片资料，请稍候；输入LOCATIONS之前不会写入。", flush=True)
    result = edit_locations(assignments, confirm)
    print("地点目录已写入并核对完成，本地记录已更新。" if result["status"] == "verified" else "已取消，未写入AWS。")


def menu():
    while True:
        info = status()
        print("\n照片维护")
        print(f"已发布照片：{info['knownPublishedCount']} 张（本地记录）；输入文件夹：{info['inputJpegCount']} 张 JPG")
        print("1  打开选图文件夹")
        print("2  准备新照片并看图批量选地点（仅本地）")
        print("3  查看最近材料 / 继续新照片分组")
        print("4  登录并检查 AWS 身份（不发布）")
        print("5  查看并发布最近新批次（确认后写入AWS）")
        print("6  看图批量分组（只保存本地地点清单）")
        print("7  查看并发布已保存的地点清单（确认后写入AWS）")
        print("0  退出")
        choice = input("输入编号并按回车：").strip()
        if choice == "0":
            return
        try:
            if choice == "1":
                INPUT.mkdir(parents=True, exist_ok=True)
                open_directory(INPUT)
            elif choice == "2":
                print("正在准备预览和材料；随后打开页面批量选择地点，不用逐张输入……", flush=True)
                result = prepare_new()
                describe_result(result)
                if result["directory"]:
                    from photo_location_picker import run
                    run(batch=result["directory"])
            elif choice == "3":
                directory = latest_directory()
                current_ids = {p["id"] for p in core.load_baseline(core.DEFAULT_BASELINE)}
                if any(p["id"] not in current_ids for p in core.load_baseline(directory / "catalog.json")):
                    from photo_location_picker import run
                    run(batch=directory)
                else:
                    open_directory(directory)
            elif choice == "4":
                login_and_check_identity()
            elif choice == "5":
                publish_latest()
            elif choice == "6":
                from photo_location_picker import run
                run()
            elif choice == "7":
                from photo_location_picker import saved_assignments
                maintain_locations(saved_assignments())
            else:
                print("请输入 0、1、2、3、4、5、6 或 7。")
        except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
            print(f"本次操作未完成：{error}")
            print("请保留提示；若发布中断，已完成项会保留，可重试同一批。工具不会自动删除原图或云端对象。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--status", action="store_true", help="只打印本地状态，不打开窗口")
    actions.add_argument("--prepare", action="store_true", help="准备固定输入目录中的新照片，不打开窗口")
    actions.add_argument("--locations", type=Path, help="读取已确认的地点清单，只读核对后仍需本人输入LOCATIONS才写入")
    args = parser.parse_args()
    try:
        if args.status:
            print(json.dumps(status(), ensure_ascii=False))
        elif args.prepare:
            describe_result(prepare_new())
        elif args.locations:
            maintain_locations(args.locations)
        else:
            menu()
    except (ValueError, OSError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"无法完成：{error}\n")
    except (EOFError, KeyboardInterrupt):
        print("\n已退出；如曾发起发布，可在最近材料中的publish-result.json查看结果。")


if __name__ == "__main__":
    main()
