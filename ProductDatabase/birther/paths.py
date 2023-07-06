"""
Created on Jun 4, 2020

@author: dstokes
"""

import os.path
import sys

import idelib

# =============================================================================
# The roots. Changing paths for testing happens here.
# =============================================================================

BIRTHER_PATH = os.path.dirname(__file__)
REAL_PRODUCT_ROOT_PATH = r"\\MIDE2007\Products\LOG-Data_Loggers\LOG-0002_Slam_Stick_X"
FAKE_PRODUCT_ROOT_PATH = "C:\\Users\\jsajna\\Documents\\BirtherData\\LOG-Data_Loggers\\LOG-0002_Slam_Stick_X"
PRODUCT_ROOT_PATH = FAKE_PRODUCT_ROOT_PATH

if os.environ.get('MIDE_DEV', '0') == '1':
    PRODUCT_ROOT_PATH = os.environ.get('MIDE_DEV_BIRTHDATA',
                                       os.path.expanduser(FAKE_PRODUCT_ROOT_PATH))
    print(f"**** USING TEST DIRECTORY: {PRODUCT_ROOT_PATH}")

# =============================================================================
# 
# =============================================================================

DB_PATH = os.path.join(PRODUCT_ROOT_PATH, "Product_Database")
CONTENT_PATH = os.path.join(DB_PATH, '_Copy_Folder')

SOFTWARE_PATH = os.path.join(PRODUCT_ROOT_PATH, "Design_Files",
                             "Firmware_and_Software")
FW_LOCATION = os.path.join(SOFTWARE_PATH, "Release", "Firmware")
BL_LOCATION = os.path.join(SOFTWARE_PATH, "Release", "Firmware")

# =============================================================================
# Resources used by GUI tools
# =============================================================================

RESOURCES_PATH = os.path.realpath(os.path.join(__file__, '..', 'resources'))

# =============================================================================
# Calibration-related (mostly)
# =============================================================================

CAL_PATH = os.path.join(DB_PATH, '_Calibration')

TEMP_DIR = os.path.realpath(os.path.expanduser('~/Documents/BirtherTemp'))
LOG_DIR = os.path.join(DB_PATH, 'Birther_Logs')

# Template-related paths
TEMPLATE_PATH = os.path.join(BIRTHER_PATH, "templates")
CERTIFICATE_PATH = os.path.join(TEMPLATE_PATH, 'Certificates')

for p in (r"C:\Program Files\Inkscape\bin\inkscape.exe",
          r"C:\Program Files\Inkscape\inkscape.exe",
          r"C:\Program Files (x86)\Inkscape\inkscape.exe",
          r"inkscape.exe"):
    INKSCAPE_PATH = p
    if os.path.exists(p):
        break

CWD = os.path.realpath(BIRTHER_PATH)
if CWD not in sys.path:
    sys.path.insert(0, CWD)

DJANGO_PATH = os.path.realpath(os.path.join(CWD, '..'))
if DJANGO_PATH not in sys.path:
    sys.path.insert(0, DJANGO_PATH)
 
# =============================================================================
# External libraries
# =============================================================================

IDELIB_PATH = os.path.dirname(idelib.__file__)
SCHEMA_PATH = os.path.join(IDELIB_PATH, 'schemata')

# NOTE: This is temporary, and will be removed after `endaqlib` (or whatever it
#  it ends up getting called) gets released and can be installed via `pip`.
# sys.path.insert(0, os.path.realpath(os.path.join(BIRTHER_PATH, '../../endaqlib')))

