#!/usr/bin/env python3
"""Water-depth annotation site for MyCoast flood photos.

Serves web/ and a small JSON API. Annotations are an append-only JSONL log;
the current state is the last event per (record_id, annotator). See CLAUDE.md.
"""
import argparse
import getpass
import json
import math
import os
import sys
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "mycoast.json")
LOG_FILE = os.path.join(ROOT, "annotations", "annotations.jsonl")
INSTRUCTIONS_FILE = os.path.join(ROOT, "instructions.txt")
WEB_DIR = os.path.join(ROOT, "web")

UNITS_TO_CM = {"inch": 2.54, "cm": 1.0}
STATUSES = {"depth", "cant_tell", "cleared"}
SCHEMA_VERSION = 1


def default_annotator():
    """Identifies whose log this is once several are merged; --annotator wins."""
    try:
        name = getpass.getuser().strip()
    except Exception:
        name = ""
    return (name or "anonymous")[:64]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_images(path):
    """Flatten reports into one dict per image, keyed by record_id."""
    with open(path, encoding="utf-8") as f:
        reports = json.load(f)
    images = {}
    for r in reports:
        n = len(r["images"])
        for i, img in enumerate(r["images"]):
            rid = img["record_id"]
            if rid in images:
                raise ValueError(f"duplicate record_id {rid} in {path}")
            images[rid] = {
                "record_id": rid,
                "report_id": r["report_id"],
                "source_url": r["source_url"],
                "image_url": img["image_url"],
                "thumbnail_url": img.get("thumbnail_url") or img["image_url"],
                "image_sha256": img.get("image_sha256"),
                "image_index": i + 1,
                "image_count": n,
                "report_type": r.get("report_type"),
                "place": r.get("place"),
                "county": r.get("county"),
                "local_time": r.get("local_time"),
                "local_time_text": r.get("local_time_text"),
                "lat": r.get("lat"),
                "lon": r.get("lon"),
                "description": r.get("description"),
                "text": r.get("text"),
                "reporter_estimated_depth": (r.get("submitted") or {}).get("Estimated water depth"),
            }
    return images


class Store:
    """Append-only annotation log with an in-memory current-state index."""

    def __init__(self, path, images, data_path):
        self.path = path
        self.data_path = data_path
        self.images = images
        self.lock = threading.Lock()
        self.current = {}  # (record_id, annotator) -> latest event
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._replay()

    def _replay(self):
        if not os.path.exists(self.path):
            return
        # An interrupted save leaves a partial last line with no newline; the
        # next append would be glued onto it and lost too. Terminate it first.
        with open(self.path, "rb+") as f:
            f.seek(0, os.SEEK_END)
            if f.tell() and (f.seek(-1, os.SEEK_END), f.read(1))[1] != b"\n":
                f.write(b"\n")
        bad = orphans = 0
        with open(self.path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    bad += 1
                    print(f"WARNING: {self.path}:{lineno} is not valid JSON, skipped "
                          "(a truncated last line means a save was interrupted)", file=sys.stderr)
                    continue
                if ev["record_id"] not in self.images:
                    orphans += 1
                self.current[(ev["record_id"], ev["annotator"])] = ev
        if orphans:
            print(f"WARNING: {orphans} log events refer to record_ids not in {self.data_path}; "
                  "kept in the log and the export", file=sys.stderr)
        print(f"replayed {self.path}: {len(self.active())} current annotations"
              + (f", {bad} bad lines" if bad else ""))

    def active(self):
        return [ev for ev in self.current.values() if ev["status"] != "cleared"]

    def by_image(self):
        out = {}
        for ev in self.active():
            out.setdefault(ev["record_id"], []).append(ev)
        return out

    def append(self, record_id, annotator, status, value=None, unit=None):
        img = self.images[record_id]
        ev = {
            "record_id": record_id,
            "report_id": img["report_id"],
            "source_url": img["source_url"],
            "image_url": img["image_url"],
            "image_sha256": img["image_sha256"],
            "annotator": annotator,
            "status": status,
            "depth_value": value,
            "depth_unit": unit,
            "depth_cm": round(value * UNITS_TO_CM[unit], 3) if status == "depth" else None,
            "annotated_at": now_iso(),
        }
        line = json.dumps(ev, ensure_ascii=False) + "\n"
        with self.lock:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self.current[(record_id, annotator)] = ev
        return ev

    def export(self):
        rows = []
        for ev in sorted(self.active(), key=lambda e: (e["report_id"], e["record_id"], e["annotator"])):
            img = self.images.get(ev["record_id"], {})
            row = dict(ev)
            for k in ("lat", "lon", "local_time", "report_type", "reporter_estimated_depth"):
                row[k] = img.get(k)
            rows.append(row)
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": now_iso(),
            "source_file": os.path.relpath(self.data_path, ROOT),
            "counts": {
                "images_total": len(self.images),
                "images_annotated": len({r["record_id"] for r in rows}),
                "annotations": len(rows),
            },
            "annotations": rows,
        }


def validate(body, images):
    """Return (record_id, status, value, unit) or raise ValueError."""
    record_id = body.get("record_id")
    if record_id not in images:
        raise ValueError("unknown record_id")
    status = body.get("status")
    if status not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}")
    value = unit = None
    if status == "depth":
        try:
            value = float(body.get("depth_value"))
        except (TypeError, ValueError):
            raise ValueError("depth_value must be a number")
        if not math.isfinite(value) or value < 0:
            raise ValueError("depth_value must be a finite number >= 0")
        unit = body.get("depth_unit")
        if unit not in UNITS_TO_CM:
            raise ValueError(f"depth_unit must be one of {sorted(UNITS_TO_CM)}")
    return record_id, status, value, unit


def read_instructions():
    """Read on every request, so edits show up on a page refresh."""
    try:
        with open(INSTRUCTIONS_FILE, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def make_handler(store, annotator):
    class Handler(SimpleHTTPRequestHandler):
        # Python reads MIME types from the Windows registry, which some
        # installs have wrong (e.g. .js as text/plain). Pin the ones we serve.
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                          ".html": "text/html", ".js": "text/javascript",
                          ".css": "text/css", ".json": "application/json"}

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=WEB_DIR, **kw)

        def log_message(self, fmt, *args):
            if not self.path.startswith("/api/") or self.command == "POST":
                super().log_message(fmt, *args)

        def send_json(self, obj, status=200, headers=None):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/items":
                by_image = store.by_image()
                items = [dict(img, annotations=by_image.get(rid, [])) for rid, img in store.images.items()]
                return self.send_json({"items": items, "annotator": annotator,
                                       "instructions": read_instructions()})
            if path == "/api/export":
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                return self.send_json(store.export(), headers={
                    "Content-Disposition": f'attachment; filename="mycoast_annotations_{stamp}.json"'})
            return super().do_GET()

        def do_POST(self):
            if self.path != "/api/annotate":
                return self.send_json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length) or b"{}")
                record_id, status, value, unit = validate(body, store.images)
            except (ValueError, json.JSONDecodeError) as e:
                return self.send_json({"error": str(e)}, 400)
            ev = store.append(record_id, annotator, status, value, unit)
            return self.send_json({"ok": True, "event": ev,
                                   "annotations": store.by_image().get(ev["record_id"], [])})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--data", default=DATA_FILE)
    ap.add_argument("--log", default=LOG_FILE)
    ap.add_argument("--export", metavar="OUT.json", help="write the export and exit")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    ap.add_argument("--annotator", help="name recorded on every annotation "
                                        "(default: this computer's user name)")
    args = ap.parse_args()

    # Windows consoles may not be UTF-8; never crash just printing a path.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    annotator = (args.annotator or "").strip() or default_annotator()
    store = Store(args.log, load_images(args.data), args.data)

    if args.export:
        out = store.export()
        with open(args.export, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"wrote {args.export}: {out['counts']}")
        return

    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(store, annotator))
    except OSError as e:
        sys.exit(f"Could not start on port {args.port} ({e.strerror}). The site may already be "
                 f"running -- open http://localhost:{args.port} -- or pick another: --port 8790")
    url = f"http://localhost:{args.port}"
    print(f"{len(store.images)} images; annotating as \"{annotator}\"; serving {url}", flush=True)
    print("Leave this window open while annotating. Press Ctrl+C (or close it) to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
