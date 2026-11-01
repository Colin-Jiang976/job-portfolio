"""Python 后端及本地文件读取测试。所有 AWS 调用都用替身，不接触云端。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/photo-api"))
import lambda_function as api
from photo_dev_server import create_server

CATALOG = json.loads((ROOT / ".local/photo-app/catalog.json").read_text(encoding="utf-8-sig"))
SOURCE = json.loads((ROOT / ".local/photo-app/source.json").read_text(encoding="utf-8-sig"))


def event(query="", method="GET"):
    return {"rawPath": "/api/photos", "rawQueryString": query, "requestContext": {"http": {"method": method}}}


class PhotoTests(unittest.TestCase):
    def test_optional_titles(self):
        for title in (None, "", "  ", {}):
            item = {**CATALOG[0], "title": title}
            self.assertNotIn("title", api.public_photo(item, "main"))
        item = dict(CATALOG[0]); item.pop("title", None)
        self.assertNotIn("title", api.public_photo(item, "main"))
        self.assertEqual(api.public_photo({**item, "title": "一个名称"}, "main")["title"], "一个名称")
        self.assertEqual(api.public_photo({**item, "title": {"zh": "仅中文"}}, "main")["title"], {"zh": "仅中文"})
        with self.assertRaises(ValueError):
            api.public_photo({**item, "title": ["wrong"]}, "main")
        with self.assertRaises(ValueError):
            api.public_photo({**item, "title": "x" * 301}, "main")

    def test_pagination_without_required_titles(self):
        items = []
        for number in range(1, 54):
            photo_id = f"test-{number:03d}"
            item = {**CATALOG[0], "id": photo_id, "SK": f"PHOTO#{number:09d}#{photo_id}",
                    "originalKey": f"photo-originals/main/{photo_id}.jpg", "internalOnly": "not-for-the-browser"}
            item.pop("title", None)
            items.append(item)

        def read_page(*, partition, after, limit):
            self.assertEqual(partition, "ALBUM#main"); self.assertEqual(limit, 24)
            matching = [item for item in items if not after or item["SK"] > after["SK"]]
            last = matching[limit - 1] if len(matching) > limit else None
            return {"items": matching[:limit], "lastKey": {"PK": last["PK"], "SK": last["SK"]} if last else None}

        sizes, ids, cursor = [], [], None
        while True:
            response = api.handle_request(event("cursor=" + cursor if cursor else ""), read_page)
            self.assertEqual(response["statusCode"], 200)
            data = json.loads(response["body"])
            sizes.append(len(data["photos"])); ids.extend(photo["id"] for photo in data["photos"])
            self.assertFalse(any("internalOnly" in photo for photo in data["photos"]))
            cursor = data["nextCursor"]
            if not cursor:
                break
        self.assertEqual(sizes, [24, 24, 5]); self.assertEqual(len(set(ids)), 53)

    def test_invalid_requests_do_not_read(self):
        read = Mock()
        cross_album = api.encode_cursor({"PK": "ALBUM#private", "SK": CATALOG[0]["SK"]})
        for query in ("cursor=!", "cursor=A", "cursor=" + "A" * 513, "cursor=" + cross_album,
                      "cursor=a&cursor=b", "limit=999999"):
            self.assertEqual(api.handle_request(event(query), read)["statusCode"], 400)
        for method in ("POST", "PUT", "DELETE", "OPTIONS"):
            self.assertEqual(api.handle_request(event(method=method), read)["statusCode"], 405)
        read.assert_not_called()

    def test_errors_empty_and_head(self):
        with self.assertLogs(api.LOGGER, level="WARNING"):
            response = api.handle_request(event(), Mock(side_effect=RuntimeError("private detail")))
        self.assertEqual(response["statusCode"], 503); self.assertNotIn("private detail", response["body"])
        with self.assertLogs(api.LOGGER, level="WARNING"):
            response = api.handle_request(event(), lambda **kw: {"items": [{**CATALOG[0], "originalKey": "outside.jpg"}]})
        self.assertEqual(response["statusCode"], 503)
        read = lambda **kw: {"items": [], "lastKey": None}
        self.assertEqual(json.loads(api.handle_request(event(), read)["body"]), {"photos": [], "nextCursor": None})
        self.assertEqual(api.handle_request(event(method="HEAD"), read)["body"], "")

    def test_lambda_adapter_with_old_and_missing_title_records(self):
        batches = json.loads((ROOT / ".local/photo-app/batch-001.json").read_text(encoding="utf-8-sig"))
        items = [deepcopy(row["PutRequest"]["Item"]) for row in batches["cj-photo-catalog"]]
        items[0].pop("title", None)
        items[1]["title"] = {"S": "单一名称"}
        items[2]["title"] = {"M": {"zh": {"S": "中文标题"}}}
        items[3]["title"] = {"NULL": True}
        last = {"PK": {"S": "ALBUM#main"}, "SK": {"S": CATALOG[-1]["SK"]}}
        client = Mock(); client.query.side_effect = lambda **kw: {} if kw["Limit"] == 1 else {"Items": items, "LastEvaluatedKey": last}
        factory = Mock(return_value=client)
        with patch.dict(sys.modules, {"boto3": SimpleNamespace(client=factory)}), patch.object(api, "_client", None), \
                patch.dict(os.environ, {"PHOTO_TABLE": "cj-photo-catalog", "PHOTO_ALBUM": "main"}):
            response = api.lambda_handler(event(), None)
            self.assertEqual(response["statusCode"], 200)
            data = json.loads(response["body"])
            self.assertNotIn("title", data["photos"][0]); self.assertEqual(data["photos"][1]["title"], "单一名称")
            self.assertEqual(data["photos"][2]["title"], {"zh": "中文标题"})
            self.assertNotIn("title", data["photos"][3]); self.assertEqual(len(data["photos"]), 5)
            api.lambda_handler(event("cursor=" + data["nextCursor"]), None)
            factory.assert_called_once_with("dynamodb")
            query = [call.kwargs for call in client.query.call_args_list if call.kwargs["Limit"] == 24][-1]
            self.assertEqual(query["TableName"], "cj-photo-catalog"); self.assertEqual(query["Limit"], 24)
            self.assertEqual(query["ExpressionAttributeValues"][":album"], {"S": "ALBUM#main"})
            self.assertEqual(query["ExclusiveStartKey"], last)

    def start(self, scenario="normal"):
        server = create_server(CATALOG, SOURCE["directory"], port=0, scenario=scenario)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        def stop():
            server.shutdown(); server.server_close(); worker.join(timeout=2)
        self.addCleanup(stop)
        return f"http://127.0.0.1:{server.server_port}"

    def request(self, url, method="GET", headers=None):
        try:
            response = urlopen(Request(url, method=method, headers=headers or {}), timeout=5)
        except HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def test_local_original_downloads_preserve_bytes(self):
        origin = self.start()
        status, _, body = self.request(origin + "/api/photos")
        data = json.loads(body); self.assertEqual(status, 200); self.assertEqual(data["mode"], "local")
        self.assertEqual(len(data["photos"]), 5)
        for photo in data["photos"]:
            self.assertEqual(self.request(origin + photo["previewUrl"])[0], 200)
            code, headers, content = self.request(origin + photo["downloadUrl"])
            self.assertEqual(code, 200); self.assertIn("attachment", headers["content-disposition"])
            self.assertEqual(len(content), photo["sizeBytes"])
            self.assertEqual(hashlib.sha256(content).hexdigest(), photo["sha256"])

    def test_local_range_and_access_boundaries(self):
        origin = self.start(); url = origin + "/" + CATALOG[0]["originalKey"]
        code, _, content = self.request(url, headers={"Range": "bytes=0-99"})
        self.assertEqual(code, 206); self.assertEqual(len(content), 100)
        self.assertEqual(self.request(url, method="HEAD")[2], b"")
        self.assertEqual(self.request(url, headers={"Range": "bytes=999999999999-"})[0], 416)
        self.assertEqual(self.request(origin + "/.local/cloudfront/private-key.pem")[0], 404)
        self.assertEqual(self.request(origin + "/api/photos", headers={"Origin": "https://outside.example"})[0], 403)

    def test_local_error_scenarios(self):
        for scenario, code in (("expired", 403), ("unavailable", 503)):
            self.assertEqual(self.request(self.start(scenario) + "/api/photos")[0], code)


if __name__ == "__main__":
    unittest.main(verbosity=2)
