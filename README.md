# flood_image_annotation
Annotation website to annotate myCoast images more efficiently

Runs on macOS, Windows and Linux. The only requirement is **Python 3.8 or
newer** -- no packages to install, no internet setup beyond loading the photos.


## Starting the Website Method 1  
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
- `annotations/annotations.jsonl` also contains everything that's downloaded. 

