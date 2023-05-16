# ProductDatabase_Django

Birthing/calibration database for data recorder products. Built on Django (primarily as an ORM layer). Also includes
wxPython-based desktop utilities.

<!-- See the wiki for more information. -->

> **WARNING:**
> Work in progress! These aren't installation instructions (yet), just notes about what's required (which needs to
> be fleshed out).

## Requirements
Everything should be installed for all users (where applicable). The repo should be cloned somewhere that any user can access
(e.g., `C:\ProductDatabase_Django`). 

### For all utilities
* **Python 3.9.** As of 2021-11-05, Python 3.10 does not work; binaries in some packages haven't yet been built for
that version.
* The 'secret' Django settings JSON (copied from `\\mide2007\products\LOG-Data_Loggers\Secrets`).
* Brother printer drivers and SDK (for birth and calibration labels)

### For Calibration
* [Inkscape](https://inkscape.org) (used to generate calibration certificate PDFs)
* Fonts used in the calibration certificate


## Installation Instructions
Notes:
* These will be changing.
* The first 3 steps are only necessary if the components mentioned aren't already installed.
* Installation must be done with admin privileges. This includes running `powershell` as Administrator for the later steps.
* When prompted, install *for all users* whenever possible.
1. Install the label printer drivers and SDK. Both are in the folder of installers. Install the drivers first (a readme in the folder says which one it is).
2. Install Inkscape. Version 1.0 or later recommended, but versions after 0.93 will work.
3. Install the latest revision of **Python 3.9**. Any version from 3.7 to 3.9 should work, but Python 3.10 will not (as of 2021-11-12)!
4. Clone the repo: In `powershell`, do `git clone https://github.com/MideTechnology/ProductDatabase_Django.git c:\ `
   1. If installing alongside the old version, replace `c:\ ` with a directory name, like `c:\ProductDatabase_Django_py3`
5. Install dependencies: still in `powershell`, `cd` to the cloned repo directory and do `python -m pip install -r requirements.txt`
6. Copy the 'secret' settings file (`\\mide2007\products\LOG-Data_Loggers\Secrets\local_settings.json`) to `<repo root>\ProductDatabase\ProductDatabase\ `

## Running things
There are two main files, both in `<repo root>\ProductDatabase`: `run_birth_wizard.py` and `run_cal_wizard.py`. 

