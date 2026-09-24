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
- **Ports pick themselves.** 8780 is preferred; if it is taken, the next
  free port up to 8799 is used. Starting always works, so the launchers never
  need arguments.
- Before falling back, the busy port is probed with `GET /api/ping`. If it
  answers with our `APP_ID` **and the same log path**, the site is already
  running: that browser tab is opened and the second start exits 0 instead of
  serving a duplicate. Two servers over one log would each hold a state built
  from a read the other no longer matches -- appends from one are invisible to
  the other, and its export would miss them. A different log path is a
  different job, so that case does start a second server.

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
instructions.txt           free text above the cards in To do / All
instructions_annotated.txt free text above the cards in the Annotated tab
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
 "reasoning": "water reaches the car's hubcap",
 "annotated_at": "2026-09-22T15:04:05+00:00"}
```

- `status` is `depth` (value + unit required), `cant_tell` (no value), or
  `cleared` (retracts the earlier answer; used by Undo and the Clear button).
- `reasoning` is optional free text (no length limit), kept exactly as typed;
  blank is stored as `null`, and a `cleared` event always has `null`. Events
  logged before the field existed have no key; the export fills in `null`.
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
                    status, depth_value, depth_unit, depth_cm, reasoning,
                    annotated_at, lat, lon, local_time, report_type,
                    reporter_estimated_depth } ]}
```

Only current, non-`cleared` state is exported, one row per image. The full
history stays in the JSONL.

**The export holds SAVED annotations only.** A depth or reasoning typed into a box but
never saved exists nowhere but that input element. The UI hints at this --
the card is outlined amber, the top bar counts such cards, and Export
confirms before downloading. Nothing is gated on it otherwise, by the owner's
request: no `beforeunload`, and saving one card never depends on any other.

The count (`dirtyCount()`) is `grid.querySelectorAll(".card.dirty").length`, read from the
cards on screen. It was a `Set` of record_ids and that was a bug: switching
tabs rebuilds every card, so an id left in the Set reported unsaved work for
an input box that no longer existed, and the count could never return to
zero. Anything tracking per-card UI state must die with the card.

## UI behaviour

- **View filter**: `To do` (default) / `Annotated` / `All`. An image counts
  as annotated once it has a current `depth` or `cant_tell` answer, so by
  default finished images disappear.
- Card: thumbnail (click -> full-resolution image in a lightbox), report type,
  place, lat/lon (5 dp, ~1 m; full precision in the title attribute; every
  report in the corpus has coordinates), local time, "image i of n",
  reporter's own estimated depth, the
  description, the full report text (collapsed), and a link to the MyCoast
  report page.
- Input: number (>= 0, decimals allowed) + unit dropdown + Save + Can't tell,
  with an optional "Reasoning" textarea on its own line below them. The reasoning is sent with Save / Can't
  tell (Enter in it is a newline, not a save). Enter in the number box saves
  and moves focus to the next card. To change a reasoning in the Annotated
  tab, edit it and press Save again; on a can't-tell card, Save with the
  depth left empty re-saves it as can't tell. The last-used unit is
  remembered.
- After saving in `To do`, the card leaves the list; a toast offers Undo
  (restores the previous state by appending a new event).
- Two instruction files, one per view: `instructions.txt` for To do and All,
  `instructions_annotated.txt` for Annotated. Shown as an "Instructions"
  panel above the cards, switched when the tab changes. Both are read on
  every `/api/items` request, so editing either needs a page refresh, not a
  restart. Rendered with `textContent` and `white-space:
  pre-wrap`: line breaks survive, HTML is never parsed. An empty or missing
  file hides the panel for that view.
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
