#!/usr/bin/env python3
"""Download every image in data/mycoast.json and write a manifest.csv beside them.

    python3 tools/download_images.py                  # -> images/
    python3 tools/download_images.py --out /some/dir --workers 4

Files are named <record_id><ext>, the same id the annotations use, in one flat
folder. Each download must be a JPEG/PNG (checked by its magic bytes, so an
HTML error page is never saved as a photo) and is only then moved into place;
re-running skips existing files and retries the rest. Standard library only,
like server.py.

image_sha256 in mycoast.json is not checked: it does NOT match the CDN bytes
(the CDN returns identical bytes every time, but not that hash; the scraper
must have hashed something else).
"""
import argparse
import csv
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from server import DATA_FILE, ROOT, load_images  # noqa: E402

MANIFEST_COLUMNS = [
    "file", "record_id", "report_id",
    "report_type", "place", "county", "local_time", "lat", "lon",
    "reporter_estimated_depth", "description", "text", "source_url",
]
IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")
RETRIES = 3


def file_name(img):
    ext = os.path.splitext(urlparse(img["image_url"]).path)[1].lower() or ".jpg"
    return img["record_id"] + ext


def download(img, dest):
    """Return None on success (or already present), else an error string."""
    if os.path.exists(dest):
        return None
    tmp = dest + ".part"
    err = None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(img["image_url"], headers={"User-Agent": "flood_image_annotation"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
                for chunk in iter(lambda: resp.read(1 << 16), b""):
                    f.write(chunk)
            with open(tmp, "rb") as f:
                head = f.read(8)
            if not head.startswith(IMAGE_MAGIC):
                os.remove(tmp)
                return f"not a JPEG/PNG (starts with {head!r})"
            os.replace(tmp, dest)
            return None
        except Exception as e:  # network errors: retry with backoff
            err = f"{type(e).__name__}: {e}"
            time.sleep(2 ** attempt)
    if os.path.exists(tmp):
        os.remove(tmp)
    return err


def write_manifest(images, out_dir):
    path = os.path.join(out_dir, "manifest.csv")
    # utf-8-sig so Excel shows non-ASCII text correctly; Google Sheets ignores the BOM.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_COLUMNS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        for img in images:
            w.writerow(dict(img, file=file_name(img)))
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DATA_FILE)
    ap.add_argument("--out", default=os.path.join(ROOT, "images"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    images = sorted(load_images(args.data).values(),
                    key=lambda i: (i["local_time"] or "", i["report_id"], i["image_index"]))
    os.makedirs(args.out, exist_ok=True)

    failed = {}
    done = 0
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(download, img, os.path.join(args.out, file_name(img))): img for img in images}
        for fut in as_completed(futures):
            img = futures[fut]
            err = fut.result()
            done += 1
            if err:
                failed[img["record_id"]] = err
                print(f"\nFAILED {img['record_id']} {img['image_url']}: {err}", file=sys.stderr)
            print(f"\r{done}/{len(images)} images, {len(failed)} failed", end="", flush=True)
    print()

    manifest = write_manifest(images, args.out)
    print(f"Manifest: {manifest} ({len(images)} rows)")
    if failed:
        print(f"{len(failed)} images failed; run again to retry them.", file=sys.stderr)
        sys.exit(1)
    print(f"All {len(images)} images in {args.out}")


if __name__ == "__main__":
    main()
