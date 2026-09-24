#!/usr/bin/env python3
"""Water-depth annotation site for MyCoast flood photos.

Serves web/ and a small JSON API. Annotations are an append-only JSONL log;
the current state is the last event per record_id. See CLAUDE.md.
"""
import argparse
import json
import math
import os
import sys
import threading
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(ROOT, "data", "mycoast.json")
LOG_FILE = os.path.join(ROOT, "annotations", "annotations.jsonl")
INSTRUCTIONS_FILE = os.path.join(ROOT, "instructions.txt")
INSTRUCTIONS_ANNOTATED_FILE = os.path.join(ROOT, "instructions_annotated.txt")
WEB_DIR = os.path.join(ROOT, "web")

UNITS_TO_CM = {"inch": 2.54, "cm": 1.0}
STATUSES = {"depth", "cant_tell", "cleared"}
SCHEMA_VERSION = 1
APP_ID = "flood-image-annotation"
PORT_TRIES = 20


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
        self.current = {}  # record_id -> latest event
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
                self.current[ev["record_id"]] = ev
        if orphans:
            print(f"WARNING: {orphans} log events refer to record_ids not in {self.data_path}; "
                  "kept in the log and the export", file=sys.stderr)
        print(f"replayed {self.path}: {len(self.active())} current annotations"
              + (f", {bad} bad lines" if bad else ""))

    def active(self):
        return [ev for ev in self.current.values() if ev["status"] != "cleared"]

    def by_image(self):
        return {ev["record_id"]: ev for ev in self.active()}

    def append(self, record_id, status, value=None, unit=None, reasoning=None):
        img = self.images[record_id]
        ev = {
            "record_id": record_id,
            "report_id": img["report_id"],
            "source_url": img["source_url"],
            "image_url": img["image_url"],
            "image_sha256": img["image_sha256"],
            "status": status,
            "depth_value": value,
            "depth_unit": unit,
            "depth_cm": round(value * UNITS_TO_CM[unit], 3) if status == "depth" else None,
            "reasoning": reasoning,
            "annotated_at": now_iso(),
        }
        line = json.dumps(ev, ensure_ascii=False) + "\n"
        with self.lock:
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self.current[record_id] = ev
        return ev

    def export(self):
        rows = []
        for ev in sorted(self.active(), key=lambda e: (e["report_id"], e["record_id"])):
            img = self.images.get(ev["record_id"], {})
            row = dict(ev)
            row.setdefault("reasoning", None)  # events logged before the field existed
            for k in ("lat", "lon", "local_time", "report_type", "reporter_estimated_depth"):
                row[k] = img.get(k)
            rows.append(row)
        return {
            "schema_version": SCHEMA_VERSION,
            "exported_at": now_iso(),
            "source_file": os.path.relpath(self.data_path, ROOT),
            "counts": {
                "images_total": len(self.images),
                "images_annotated": len(rows),
            },
            "annotations": rows,
        }


def validate(body, images):
    """Return (record_id, status, value, unit, reasoning) or raise ValueError."""
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
    # Optional free text, no length limit. Kept exactly as typed; a blank box
    # is stored as null. A Clear retracts the reasoning with the answer.
    reasoning = body.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, str):
        raise ValueError("reasoning must be a string")
    if status == "cleared" or not (reasoning or "").strip():
        reasoning = None
    return record_id, status, value, unit, reasoning


def read_instructions():
    """Read on every request, so edits show up on a page refresh.

    One file per view: instructions.txt for "To do"/"All",
    instructions_annotated.txt for the "Annotated" tab.
    """
    out = {}
    for key, path in (("todo", INSTRUCTIONS_FILE), ("done", INSTRUCTIONS_ANNOTATED_FILE)):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                out[key] = f.read().strip()
        except FileNotFoundError:
            out[key] = ""
    return out


def running_instance(host, port, log_path):
    """True if OUR site already serves this port with the same log file.

    A second server on the same log would append to a file it did not read;
    the two would disagree about what is annotated.
    """
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/ping", timeout=1.0) as r:
            info = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return False
    return info.get("app") == APP_ID and info.get("log") == os.path.abspath(log_path)


def bind_server(host, port, tries, log_path, handler):
    """Bind `port`, or the next free one. Returns (server, port).

    Raises SystemExit if our own site already holds the port, or nothing is
    free in the range.
    """
    for candidate in range(port, port + tries):
        try:
            return ThreadingHTTPServer((host, candidate), handler), candidate
        except OSError:
            probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
            if running_instance(probe_host, candidate, log_path):
                url = f"http://localhost:{candidate}"
                print(f"The annotation site is already running at {url} -- opening it.", flush=True)
                webbrowser.open(url)
                raise SystemExit(0)
    raise SystemExit(f"No free port between {port} and {port + tries - 1}. "
                     "Close some programs or pass --port.")


def make_handler(store):
    class Handler(SimpleHTTPRequestHandler):
        # Python reads MIME types from the Windows registry, which some
        # installs have wrong (e.g. .js as text/plain). Pin the ones we serve.
        extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                          ".html": "text/html", ".js": "text/javascript",
                          ".css": "text/css", ".json": "application/json"}

        def __init__(self, *a, **kw):
            super().__init__(*a, directory=WEB_DIR, **kw)

        def end_headers(self):
            # Never cache: a stale app.js against a newer server breaks the
            # page in ways that look like a bug ("cannot read ... of
            # undefined"). Nothing here is big enough for caching to matter.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            super().end_headers()

        def log_message(self, fmt, *args):
            if not self.path.startswith("/api/") or self.command == "POST":
                super().log_message(fmt, *args)

        def send_json(self, obj, status=200, headers=None):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/items":
                by_image = store.by_image()
                items = [dict(img, annotation=by_image.get(rid)) for rid, img in store.images.items()]
                return self.send_json({"items": items, "instructions": read_instructions()})
            if path == "/api/ping":
                return self.send_json({"app": APP_ID, "log": os.path.abspath(store.path)})
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
                record_id, status, value, unit, reasoning = validate(body, store.images)
            except (ValueError, json.JSONDecodeError) as e:
                return self.send_json({"error": str(e)}, 400)
            ev = store.append(record_id, status, value, unit, reasoning)
            return self.send_json({"ok": True, "annotation": store.by_image().get(record_id)})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8780,
                    help="preferred port; the next free one is used if it is taken")
    ap.add_argument("--data", default=DATA_FILE)
    ap.add_argument("--log", default=LOG_FILE)
    ap.add_argument("--export", metavar="OUT.json", help="write the export and exit")
    ap.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    args = ap.parse_args()

    # Windows consoles may not be UTF-8; never crash just printing a path.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    store = Store(args.log, load_images(args.data), args.data)

    if args.export:
        out = store.export()
        with open(args.export, "w", encoding="utf-8", newline="\n") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"wrote {args.export}: {out['counts']}")
        return

    server, port = bind_server(args.host, args.port, PORT_TRIES, args.log, make_handler(store))
    url = f"http://localhost:{port}"
    if port != args.port:
        print(f"Port {args.port} was busy; using {port} instead.", flush=True)
    print(f"{len(store.images)} images; serving {url}", flush=True)
    print("Leave this window open while annotating. Press Ctrl+C (or close it) to stop.", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
