"""只监听本机的看图分组页面；仅保存本地地点清单，不导入AWS客户端。"""
import argparse
from datetime import datetime, timezone
import hmac
import json
from pathlib import Path
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
import webbrowser

import prepare_photos as core
from photo_locations import clean_location

DEFAULT_PLACES = ["伊豆", "富士山", "箱根", "东京", "内蒙古"]
LATEST = core.LOCAL / "photo-app/latest-location-draft.json"
ASSETS = Path(__file__).with_name("photo-location-picker")


def saved_assignments(baseline_path=core.DEFAULT_BASELINE, latest_path=LATEST):
    """发布前核对清单及其原基准；允许同一清单已部分发布后的重试。"""
    if not Path(latest_path).is_file():
        raise ValueError("尚未保存地点清单，请先选择菜单6看图分组并保存。")
    directory = Path(core.read_json(latest_path)["directory"]).resolve(strict=True)
    if not directory.is_relative_to((core.LOCAL / "photo-app/location-drafts").resolve()):
        raise ValueError("地点清单不在指定本地目录。")
    before = core.load_baseline(directory / "baseline-before.json")
    current = core.load_baseline(baseline_path)
    assignments = core.read_json(directory / "assignments.json")
    if not isinstance(assignments, dict) or set(assignments) != {p["id"] for p in before}:
        raise ValueError("地点清单中的照片发生变化，请重新看图保存。")
    assignments = {key: clean_location(value) for key, value in assignments.items()}
    old_by_id = {p["id"]: p for p in before}
    if {p["id"] for p in current} != set(old_by_id):
        raise ValueError("已发布照片数量发生变化，请重新看图保存。")
    for item in current:
        old = old_by_id[item["id"]]
        if item not in (old, {**old, "location": assignments[item["id"]]}):
            raise ValueError("照片或地点已经另行修改，请重新看图保存，未覆盖。")
    return directory / "assignments.json"


def find_previews(catalog):
    roots = [core.ROOT / "dist", core.LOCAL / "photo-app/s3"]
    batches = core.LOCAL / "photo-app/batches"
    if batches.is_dir():
        roots += [p / "s3" for p in sorted(batches.iterdir()) if p.is_dir()]
    result = {}
    for photo in catalog:
        for root in roots:
            candidate = (root / photo["previewKey"]).resolve()
            if candidate.is_relative_to(core.ROOT.resolve()) and candidate.is_file():
                result[photo["id"]] = candidate
                break
    return result


def create_server(*, baseline_path=core.DEFAULT_BASELINE, port=0, latest_path=LATEST, previews=None, draft_root=None,
                  on_save=None, require_locations=False):
    baseline_path = Path(baseline_path).resolve(strict=True)
    catalog = core.load_baseline(baseline_path)
    if not catalog:
        raise ValueError("还没有已发布照片。")
    baseline_hash = core.digest(baseline_path)
    draft_root = Path(draft_root or core.LOCAL / "photo-app/location-drafts").resolve()
    if not draft_root.is_relative_to((core.LOCAL / "photo-app/location-drafts").resolve()):
        raise ValueError("清单保存位置须位于指定本地目录。")
    previews = find_previews(catalog) if previews is None else previews
    session = secrets.token_urlsafe(24)
    prefix = "/" + session + "/"
    initial = {p["id"]: clean_location(p.get("location")) for p in catalog}
    if Path(latest_path).is_file():
        try:
            initial = core.read_json(saved_assignments(baseline_path, latest_path))
        except (ValueError, OSError, KeyError, TypeError):
            pass  # 旧清单不覆盖新基准，页面重新从当前记录开始。
    places = list(dict.fromkeys(DEFAULT_PLACES + [label for label in initial.values() if label]))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # 不记录含本地会话地址的请求。

        def reply(self, status, payload, content_type="application/json; charset=utf-8"):
            if not isinstance(payload, bytes):
                payload = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            for key, value in {"Content-Type": content_type, "Content-Length": str(len(payload)),
                "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer", "Content-Security-Policy":
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"}.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def serve(self):
            nonlocal baseline_hash
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if (self.headers.get("Host") != origin.removeprefix("http://")
                    or self.headers.get("Origin", origin) != origin
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                return self.reply(403, {"error": "仅限本机页面。"})
            pathname = urlsplit(self.path).path
            if not hmac.compare_digest(pathname[:len(prefix)].encode("utf-8"), prefix.encode("ascii")):
                return self.reply(404, {"error": "本地会话无效。"})
            route = pathname[len(prefix):]
            if self.command in ("GET", "HEAD"):
                if route in ("", "app.js", "styles.css"):
                    name = route or "index.html"
                    content_type = {"index.html": "text/html; charset=utf-8", "app.js": "text/javascript; charset=utf-8", "styles.css": "text/css; charset=utf-8"}[name]
                    return self.reply(200, (ASSETS / name).read_bytes(), content_type)
                if route == "api/catalog":
                    return self.reply(200, {"baselineHash": baseline_hash, "places": places,
                        "requireLocations": require_locations,
                        "photos": [{"id": p["id"], "filename": p["filename"], "location": initial[p["id"]],
                                    "preview": "preview/" + p["id"] if p["id"] in previews else None} for p in catalog]})
                if route.startswith("preview/"):
                    image = previews.get(route.removeprefix("preview/"))
                    if image is not None:
                        return self.reply(200, Path(image).read_bytes(), "image/webp")
                return self.reply(404, {"error": "本地文件不存在。"})
            if self.command != "POST" or route != "api/save":
                return self.reply(405, {"error": "不支持此操作。"})
            if self.headers.get("X-Photo-Picker") != "local-save" or self.headers.get("Content-Type") != "application/json":
                return self.reply(403, {"error": "请使用本地选图页面保存。"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 65536:
                    raise ValueError("清单大小无效。")
                data = json.loads(self.rfile.read(size))
                assignments = data["assignments"]
                if data.get("baselineHash") != baseline_hash or core.digest(baseline_path) != baseline_hash:
                    return self.reply(409, {"error": "已发布记录发生变化，请重新打开分组页面。"})
                if not isinstance(assignments, dict) or set(assignments) != {p["id"] for p in catalog}:
                    raise ValueError("照片清单不完整，请重新打开页面。")
                assignments = {key: clean_location(value) for key, value in assignments.items()}
                directory = draft_root / secrets.token_hex(12)
                directory.mkdir(parents=True, exist_ok=False)
                core.write_json(directory / "baseline-before.json", catalog)
                core.write_json(directory / "assignments.json", assignments)
                pointer = {"directory": str(directory), "status": "saved-local-only", "count": len(assignments),
                    "savedAt": datetime.now(timezone.utc).isoformat(), "baselineHash": baseline_hash}
                latest = Path(latest_path).resolve()
                if not latest.is_relative_to(core.LOCAL.resolve()):
                    raise ValueError("本地记录路径无效。")
                latest.parent.mkdir(parents=True, exist_ok=True)
                temporary = latest.with_name(latest.name + ".tmp-" + secrets.token_hex(8))
                core.write_json(temporary, pointer); temporary.replace(latest)
                saved = on_save(assignments) if on_save else {}
                baseline_hash = core.digest(baseline_path)
                initial.clear(); initial.update(assignments)
                places[:] = list(dict.fromkeys(places + [label for label in assignments.values() if label]))
                return self.reply(200, {"saved": True, "count": len(assignments), "awsCalled": False,
                                        "baselineHash": baseline_hash, **saved})
            except (ValueError, KeyError, TypeError, OSError):
                return self.reply(400, {"error": "无法保存，请检查地点文字及本地目录后重试。"})

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = serve

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.picker_url = f"http://127.0.0.1:{server.server_port}" + prefix
    return server


def new_batch_server(batch, port=0):
    from photo_new_batch import finish_locations
    batch = Path(batch).resolve(strict=True)
    if not batch.is_relative_to(core.LOCAL.resolve()):
        raise ValueError("新批次须位于项目.local内。")
    return create_server(baseline_path=batch / "catalog.json", port=port,
        latest_path=batch / "latest-location-draft.json", require_locations=True,
        on_save=lambda assignments: finish_locations(batch, assignments))


def run(open_browser=True, port=0, batch=None):
    server = new_batch_server(batch, port) if batch else create_server(port=port)
    print("本地看图分组：" + server.picker_url, flush=True)
    print("勾选照片 → 选择地点 → 应用到已选照片 → 保存本地清单。没有连接AWS。", flush=True)
    print("页面使用期间请保留此窗口；完成后按Ctrl+C返回维护菜单。", flush=True)
    if open_browser:
        webbrowser.open(server.picker_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--batch", type=Path, help="为已准备的新批次看图批量选择必填地点")
    args = parser.parse_args()
    run(not args.no_open, args.port, args.batch)
