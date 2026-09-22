# flood_image_annotation

A local website for annotating the **water depth** visible in MyCoast flood
report photos. Each card shows one image; the annotator types a number and picks
a unit (`inch` / `cm`), or marks the image "can't tell". Annotations are saved
server-side as they are made and can be exported as JSON at any time.

## Git

Only commit or push when the owner asks. Leave work in the working tree and say
what changed.

## Run

Must run on macOS, Windows and Linux with nothing but **Python >= 3.8**
(standard library only). Keep it that way: no pip dependencies, no build
step, no CDN scripts in `web/`.

```bash
start.bat / start.command             # double-click launchers (Windows / macOS)
python3 server.py                     # http://localhost:8780, opens a browser tab
python3 server.py --port 8790 --no-browser
python3 server.py --host 0.0.0.0      # reachable from other machines
python3 server.py --export out.json   # write the export without starting the site
```

Cross-platform details that are deliberate:
- The launchers find Python themselves (`py -3` before `python` on Windows,
  because `python` may be the Microsoft Store stub) and print install
  instructions instead of a cryptic error.
- The log and export are written with `newline="\n"` so they are byte-identical
  on every OS. `.gitattributes` pins LF everywhere except `start.bat` (CRLF;
  cmd.exe misparses LF batch files).
- MIME types for `.js/.css/.html/.json` are pinned in the handler: on Windows
  Python reads them from the registry, which is sometimes wrong.
- A busy port exits with a readable message, not a traceback.

**Each computer keeps its own log.** When people run the site on their own
machines, collect their `annotations.jsonl` (or exports). There is no
annotator field anywhere -- by the owner's decision -- so state is keyed by
`record_id` alone and two logs covering the SAME image conflict: later line
wins on concatenation, arbitrarily. Either give each person a disjoint slice
of the images, or run one shared server (`--host 0.0.0.0` or an ssh tunnel),
which needs no merging at all.

## Layout

```
server.py                  stdlib HTTP server: static files + JSON API
instructions.txt           free text shown above the cards; the owner edits it
web/index.html, app.js, style.css
data/mycoast.json          input: 1,893 reports, 2,948 images (read-only)
annotations/annotations.jsonl   THE annotation store (append-only log)
```

## Data model

**Unit of annotation = one image**, not one report. A report has 1-N photos
taken at different spots, so they can show different depths.

**Image identity = `record_id`** from `mycoast.json`, which is
`sha256(source_url + "\n" + image_url)[:24]` (verified). It is stable and can
be recomputed from the URLs, so annotations survive a re-scrape. Every stored
row ALSO carries `report_id`, `source_url`, `image_url`, `image_sha256` so the
file can be joined without this repo's code.

## Storage design (why an append-only log)

`annotations/annotations.jsonl`: one JSON object per save event, appended,
flushed and fsynced under a lock.

```json
{"record_id": "...", "report_id": 249795, "source_url": "...", "image_url": "...",
 "image_sha256": "...", "status": "depth",
 "depth_value": 7.0, "depth_unit": "inch", "depth_cm": 17.78,
 "annotated_at": "2026-09-22T15:04:05+00:00"}
```

- `status` is `depth` (value + unit required), `cant_tell` (no value), or
  `cleared` (retracts the earlier answer; used by Undo and the Clear button).
- **Current state = the last event per `record_id`.** Re-saving
  is an edit; nothing is ever rewritten in place.
- Why not browser localStorage: it is lost with a cache clear, a different
  browser or a private window, and there is no copy anyone else can see.
- Why not rewriting one JSON file per save: a crash mid-write can lose
  everything; an append can lose at most the one line being written. A
  truncated last line is skipped with a warning on startup, and a newline is
  appended first so the next save is not glued onto the fragment.
- The log is also a full audit trail: every value ever entered for an image
  is still there with its timestamp, even after an edit or a Clear.
- The raw value and unit are kept exactly as typed; `depth_cm` is derived
  (`inch * 2.54`) so consumers never have to convert.

**Commit `annotations/annotations.jsonl`** -- it is the work product, not a
cache. It is deliberately not gitignored.

## Export

`GET /api/export` (the "Export" button) or `python3 server.py --export`.
A single JSON file:

```json
{"schema_version": 1, "exported_at": "...", "source_file": "data/mycoast.json",
 "counts": {"images_total": 2948, "images_annotated": 0, "annotations": 0},
 "annotations": [ { record_id, report_id, source_url, image_url, image_sha256,
                    status, depth_value, depth_unit, depth_cm,
                    annotated_at, lat, lon, local_time, report_type,
                    reporter_estimated_depth } ]}
```

Only current, non-`cleared` state is exported, one row per image. The full
history stays in the JSONL.

**The export holds SAVED annotations only.** A depth typed into a box but
never saved exists nowhere but that input element. The UI therefore tracks
"dirty" inputs: the card is outlined amber, a count shows in the top bar, the
Export button confirms first, and `beforeunload` warns on reload/close.

## UI behaviour

- **View filter**: `To do` (default) / `Annotated` / `All`. An image counts
  as annotated once it has a current `depth` or `cant_tell` answer, so by
  default finished images disappear.
- Card: thumbnail (click -> full-resolution image in a lightbox), report type,
  place, local time, "image i of n", reporter's own estimated depth, the
  description, the full report text (collapsed), and a link to the MyCoast
  report page.
- Input: number (>= 0, decimals allowed) + unit dropdown + Save + Can't tell.
  Enter saves and moves focus to the next card. The last-used unit is
  remembered.
- After saving in `To do`, the card leaves the list; a toast offers Undo
  (restores the previous state by appending a new event).
- `instructions.txt` is shown as an "Instructions" panel above the cards.
  It is read on every `/api/items` request, so editing it needs a page
  refresh, not a restart. Rendered with `textContent` and `white-space:
  pre-wrap`: line breaks survive, HTML is never parsed. An empty or missing
  file hides the panel.
- Saving is one click/Enter and is immediate: POST -> appended to the log
  (fsynced) -> the card leaves the `To do` list -> a toast offers Undo for a
  few seconds. There is no separate submit step and nothing is batched.
- Cards render in pages as you scroll; images use native lazy loading and
  are hotlinked from `cdn.mycoast.photos` (verified to serve without referer
  checks). No pixels are stored in this repo.

## Known considerations

- The report text includes the reporter's own depth estimate, which can bias
  whoever annotates. It is shown because the owner asked for the text; it is
  exported as `reporter_estimated_depth` so the two can be compared.
- 10 reports list `duplicate_images` (exact duplicates already removed from
  `images` by the scraper); they are not shown.

## Status

- [x] Plan (this file)
- [x] Server: load data, replay log, `/api/items`, `/api/annotate`, `/api/export`
- [x] UI: cards, lightbox, filter toggle, save / can't tell / undo, export
- [x] API tested end to end (validation, edit, clear, export,
      truncated-log recovery) against a scratch log
- [x] Launchers + cross-platform fixes (tested on Linux only)
- [ ] Try start.bat on Windows and start.command on macOS
- [ ] UI not yet clicked through in a real browser (no headless browser on
      the server) -- do this first
- [ ] Hand-test with real annotators; adjust fields if more labels are needed
- [ ] If several people annotate at once, decide slices vs one shared server
