# flood_image_annotation
Use this website to annotate flood images. 


## Starting the Website - Method 1
From a terminal in this folder: `python3 server.py` (macOS/Linux) or
`py server.py` (Windows).  It should open up a port and show on your default browser. 

### Method 2 
- **Windows:** double-click `start.bat`.
- **macOS:** double-click `start.command`. The first time, macOS may refuse
  because it was downloaded: right-click it -> **Open** -> **Open**.
  If it says it isn't executable, run `chmod +x start.command` in Terminal once.

A browser tab opens at <http://localhost:8780>. **Keep the black window open**
while you annotate; closing it stops the site.

## Potential Requirements 
- Download python and run `python3 --version` (macOS) or `py --version` (Windows) to make sure 

## Downloading Annotations 

Click **Export JSON** and the file contains everything that's downloaded as a json file. You can keep that file to submit as work. 

## Important 
- `annotations/annotations.jsonl` carries your work in progress and tracks everything you have annotated so far. Make sure to **not delete that file**  

## Saving

Each photo is saved the moment you press Enter or click **Save** -- there is
no separate submit step. A saved photo disappears from **To do** and a short
"Undo" appears at the bottom of the screen.

A depth you type but never save is **not** recorded: the card stays outlined
in amber, the top bar counts how many are unsaved, and the site warns you if
you export or close the page with any left over.
