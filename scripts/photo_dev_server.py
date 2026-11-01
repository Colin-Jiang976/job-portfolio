"""只监听本机的 Python 预览。目录资料来自本地文件，不连接 AWS。"""
import argparse
import json
import mimetypes
import os
from pathlib import Path
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/photo-api"))
from lambda_function import handle_request
from photo_locations import location_record, registry


def create_server(catalog, source_directory, port=8766, scenario="normal", asset_root=None):
    # 本地小样本的替身；生产环境由 Lambda Query 分页，不加载全表。
    ordered = sorted(catalog, key=lambda item: item["SK"])
    query_rows = sorted(ordered + [location_record(item) for item in ordered], key=lambda item: item["SK"])
    source_directory = Path(source_directory).resolve()
    dist = (ROOT / "dist").resolve()
    asset_root = Path(asset_root).resolve() if asset_root else None

    def read_page(*, partition, after, limit, prefix="PHOTO#"):
        matching = [item for item in query_rows if item["PK"] == partition and item["SK"].startswith(prefix)
                    and (not after or item["SK"] > after["SK"])]
        items = matching[:limit]
        last = items[-1] if len(matching) > limit else None
        return {"items": items, "lastKey": {"PK": last["PK"], "SK": last["SK"]} if last else None}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # 不记录邀请参数或个人资料路径。

        def reply(self, status, body, headers=None):
            payload = body.encode("utf-8")
            self.send_response(status)
            for key, value in {"content-type": "text/plain; charset=utf-8", "cache-control": "no-store",
                               "x-content-type-options": "nosniff", "content-length": str(len(payload)), **(headers or {})}.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def serve(self):
            host = self.headers.get("Host", "")
            if (not re.fullmatch(r"(localhost|127\.0\.0\.1)(:\d+)?", host)
                    or self.headers.get("Origin", f"http://{host}") != f"http://{host}"
                    or self.headers.get("Sec-Fetch-Site") == "cross-site"):
                return self.reply(403, "Local preview only")
            try:
                url = urlsplit(self.path)
                pathname = unquote(url.path, errors="strict")
            except (ValueError, UnicodeError):
                return self.reply(400, "Invalid path")
            if pathname.startswith("/api/"):
                if scenario in ("expired", "unavailable"):
                    return self.reply(403 if scenario == "expired" else 503, "Local test scenario")
                result = handle_request({"rawPath": pathname, "rawQueryString": url.query,
                                         "requestContext": {"http": {"method": self.command}}}, read_page,
                                        read_locations=lambda _: registry(p.get("location", "") for p in ordered))
                if result["statusCode"] == 200 and result["body"]:
                    data = json.loads(result["body"])
                    data["mode"] = "local"
                    if scenario == "empty":
                        data.update(photos=[], nextCursor=None)
                    result["body"] = json.dumps(data, ensure_ascii=False)
                return self.reply(result["statusCode"], result["body"], result["headers"])
            if self.command not in ("GET", "HEAD"):
                return self.reply(405, "Method not allowed")
            original = None
            if pathname.startswith("/photo-originals/"):
                original = next((item for item in ordered if "/" + item["originalKey"] == pathname), None)
                if not original or Path(original["filename"]).name != original["filename"]:
                    return self.reply(404, "Photo not found")
                original_root = asset_root or source_directory
                filename = (original_root / (original["originalKey"] if asset_root else original["filename"])).resolve()
                if not filename.is_relative_to(original_root):
                    return self.reply(404, "Photo not found")
            else:
                relative = "photos/index.html" if pathname == "/" else pathname.lstrip("/")
                if pathname.endswith("/") and pathname != "/":
                    relative += "index.html"
                static_root = asset_root if asset_root and pathname.startswith("/assets/photos/") else dist
                filename = (static_root / relative).resolve()
                if not filename.is_relative_to(static_root):
                    return self.reply(404, "Not found")
            try:
                if not filename.is_file():
                    raise FileNotFoundError()
                size = filename.stat().st_size
            except (OSError, ValueError):
                return self.reply(404, "File not found")
            start, end, status = 0, size - 1, 200
            headers = {"content-type": "image/jpeg" if original else mimetypes.guess_type(filename)[0] or "application/octet-stream",
                       "accept-ranges": "bytes", "cache-control": "private, no-store"}
            if original:
                headers["content-disposition"] = "attachment; filename*=UTF-8''" + quote(original["filename"], safe="")
            if self.headers.get("Range"):
                match = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers["Range"])
                if match and any(match.groups()):
                    first, last = match.groups()
                    start = int(first) if first else max(0, size - int(last))
                    end = min(int(last), end) if first and last else end
                if not match or not any(match.groups()) or not 0 <= start <= end:
                    return self.reply(416, "", {"content-range": f"bytes */{size}"})
                status = 206
                headers["content-range"] = f"bytes {start}-{end}/{size}"
            self.send_response(status)
            for key, value in {**headers, "content-length": str(end - start + 1), "x-content-type-options": "nosniff"}.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command == "HEAD":
                return
            try:
                with filename.open("rb") as stream:
                    stream.seek(start)
                    remaining = end - start + 1
                    while remaining:
                        chunk = stream.read(min(remaining, 65536))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

        do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = do_OPTIONS = serve

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=int(os.environ.get("PHOTO_PREVIEW_PORT", "8766")))
    parser.add_argument("--catalog", type=Path, default=ROOT / ".local/photo-app/catalog.json")
    parser.add_argument("--scenario", choices=("normal", "expired", "unavailable", "empty"), default="normal")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("预览端口须为 1024–65535。")
    with args.catalog.open(encoding="utf-8-sig") as file:
        catalog = json.load(file)
    with (args.catalog.parent / "source.json").open(encoding="utf-8-sig") as file:
        source = json.load(file)
    server = create_server(catalog, source["directory"], args.port, args.scenario, source.get("assetRoot"))
    print(f"Python 本地预览：http://127.0.0.1:{args.port}/photos/index.html?lang=zh（未连接 AWS）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
