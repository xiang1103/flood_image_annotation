# flood_image_annotation
Use this website to annotate flood images. 

## Starting the Website - Method 1  
- **Windows:** double-click `start.bat`.
- **macOS:** double-click `start.command`. The first time, macOS may refuse
  because it was downloaded: right-click it -> **Open** -> **Open**.
  If it says it isn't executable, run `chmod +x start.command` in Terminal once.

A browser tab opens at <http://localhost:8780>. **Keep the black window open**
while you annotate; closing it stops the site.

### Method 2 
from a terminal in this folder: `python3 server.py` (macOS/Linux) or
`py server.py` (Windows).


## Potential Requirements 
- Download python and run `python3 --version` (macOS) or `py --version` (Windows) to make sure 

## Downloading Annotations 

Click **Export JSON** and the file contains everything that's downloaded as a json file. You can keep that file to submit as work. 

## Important 
- `annotations/annotations.jsonl` carries your work in progress and tracks everything you have annotated so far. Make sure to **not delete that file**  

## Instructions Shown to Annotators

Edit `instructions.txt` in any text editor and refresh the page -- the text
appears in a box above the photos. No restart needed. Leave the file empty to
hide the box.

## Who Annotated What

Each row records an annotator name, taken automatically from the computer's
user name, so several people's files can be combined without clashing. To set
it yourself, start with `python3 server.py --annotator "your name"`.
