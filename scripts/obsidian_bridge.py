#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def run_post_import_hook(hook_cmd: str | None) -> dict | None:
    if not hook_cmd:
        return None
    try:
        completed = subprocess.run(
            hook_cmd,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
        )
        return {
            "ok": True,
            "command": hook_cmd,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "command": hook_cmd,
            "stdout": (exc.stdout or "").strip(),
            "stderr": (exc.stderr or "").strip(),
            "returncode": exc.returncode,
        }


def build_handler(target_dir: Path, post_import_cmd: str | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "XLikesObsidianBridge/0.1"

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send_json(404, {"ok": False, "error": "Not found"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "target_dir": str(target_dir),
                },
            )

        def do_POST(self) -> None:
            if self.path != "/import":
                self._send_json(404, {"ok": False, "error": "Not found"})
                return

            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                payload = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": f"Invalid JSON: {exc}"})
                return

            base_name = str(payload.get("baseName") or "").strip()
            files = payload.get("files")
            if not base_name:
                self._send_json(400, {"ok": False, "error": "Missing baseName"})
                return
            if not isinstance(files, list) or not files:
                self._send_json(400, {"ok": False, "error": "Missing files"})
                return

            target_dir.mkdir(parents=True, exist_ok=True)
            written = []

            for item in files:
                extension = str(item.get("extension") or "txt").strip().lstrip(".")
                content = str(item.get("content") or "")
                out_path = target_dir / f"{base_name}.{extension}"
                out_path.write_text(content, encoding="utf-8")
                written.append(str(out_path))

            hook_result = run_post_import_hook(post_import_cmd)

            self._send_json(
                200,
                {
                    "ok": True,
                    "mode": "obsidian_bridge",
                    "target_dir": str(target_dir),
                    "written": written,
                    "post_import": hook_result,
                },
            )

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            return

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument(
        "--target-dir",
        default=str((Path.cwd() / "x-likes-source").resolve()),
    )
    parser.add_argument(
        "--post-import-cmd",
        default="",
    )
    args = parser.parse_args()

    target_dir = Path(args.target_dir).expanduser()
    server = ThreadingHTTPServer(
        (args.host, args.port),
        build_handler(target_dir, args.post_import_cmd),
    )
    print(f"X Likes Obsidian bridge listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
