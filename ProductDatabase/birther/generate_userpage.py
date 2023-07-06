"""
This file contains two things: a function for combining manifest and
calibration data into 'USERPAGE' data; and a utility script to build a new
'USERPAGE' file for a given device's serial number. The latter will
(optionally) make a zip file containing the USERPAGE, a README, and
ready-to-copy COMMAND file.

As a utility, this should be run from the parent directory via:
`python -m birther.generate_userpage <args>`
"""
from __future__ import print_function

import os
import struct
import sys
from zipfile import ZipFile

# Django setup
sys.path.insert(0, os.path.realpath('../ProductDatabase'))
os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

import django.db
django.setup()

from . import paths  # Not used directly, but sets things up.
from . import template_generator
from .template_generator import models  # `products.models`

from endaq.device import getRecorder

# This text is the README that is included in zipped userpage updates.
README = """
NOTE: This custom device data update file is exclusively for recorder serial number {serial}!
It contains information specific to the individual unit which will have adverse effects if
installed on a different device.

To install the updated device description/calibration data:

 0. Be sure enDAQ Lab is not running, and do not start it during the update process.
 1. Disconnect/unplug the recorder if it is already connected via USB.
 2. Reconnect the recorder via USB.
 3. Copy userpage.bin to the recorder's SYSTEM directory.
 4. Copy COMMAND to the recorder's SYSTEM/DEV directory. A COMMAND file will already be present in
    SYSTEM/DEV; if prompted, select the option to replace/overwrite the existing file.
 
Once the COMMAND file has been copied, the recorder will unmount (i.e., disappear as a USB drive).
Its red LED will blink 6 times. After a brief delay, the recorder will reappear as a USB drive.
 
When the recorder reappears, the update has been installed, and the recorder is ready for use.

For additional assistance, please contact enDAQ Customer Success.
Email: success@endaq.com
Phone: +1 781-306-0634
"""

COMMAND = b"sa"


def makeUserpage(manifest, caldata, recprops=b'\x00', pageSize=2048):
    """ Combine a binary Manifest, Calibration, and (optionally) Recorder
        Properties EBML into a unified, correctly formatted update file. This
        format matches the EFM32 'userpage' data, but this format is used on
        all recorders, including STM32.

        USERPAGE memory map:
            0x0000 (2): Offset of manifest, LE
            0x0002 (2): Length of manifest, LE
            0x0004 (2): Offset of factory calibration, LE
            0x0006 (2): Length of factory calibration, LE
            0x0008 (2): Offset of recorder properties, LE
            0x000A (2): Length of recorder properties, LE
            0x000C ~ 0x000F: (RESERVED)
            0x0010: Data (Manifest, calibration, recorder properties)
            0x07FF: End of userpage data (2048 bytes total)
    """

    manSize = len(manifest)
    manOffset = 0x0010  # 16 byte offset from start
    calSize = len(caldata)
    calOffset =  manOffset + manSize  # 0x0400 # 1k offset from start

    propsOffset = calOffset + calSize
    propsSize = 1

    data = struct.pack("<HHHHHH",
                       manOffset, manSize,
                       calOffset, calSize,
                       propsOffset, propsSize)
    data = bytearray(data.ljust(pageSize, b'\x00'))
    data[manOffset:manOffset+manSize] = manifest
    data[calOffset:calOffset+calSize] = caldata
    data[propsOffset:propsOffset+propsSize] = recprops

    if len(data) != pageSize:
        # Probably can never happen, but just in case...
        raise ValueError("Userpage block was %d bytes; should be %d" %
                         (len(data), pageSize))

    return data


def generateUserpage(birth, filename=None, zipit=False, cal=None, **kwargs):
    """ Generate a USERPAGE file for a device specified by serial number.

        @param birth: The `models.Birth` of the device for which to generate the data.
        @param filename: A filename to write. Defaults to ``userpage_<serial>.bin``.
        @param zipit: If `True`, generate a zip file with a README, etc.
        @param cal: A `models.CalSession` to write. Defaults to the latest one
            for the device.
    """
    print("Generating USERPAGE for %s," % birth, end=" ")
    mt = template_generator.ManifestTemplater(birth, **kwargs)

    cal = cal or birth.device.getLastCal()
    if cal:
        print("calibration serial number %s" % cal)
        ct = template_generator.CalTemplater(cal)
    else:
        print("default calibration.")
        ct = template_generator.DefaultCalTemplater(birth)

    mandata = mt.dumpEBML()
    caldata = ct.dumpEBML()
    userpage = makeUserpage(mandata, caldata)

    if not filename:
        serialNumberString = str(kwargs.get('serialNumber', birth.serialNumberString))
        ext = "zip" if zipit else "bin"
        filename = "userpage_%s.%s" % (serialNumberString, ext)

    print("-> Writing %s (data is %s bytes total; %s manifest, %s calibration)" %
          (filename, len(userpage), len(mandata), len(caldata)))

    if zipit:
        with ZipFile(filename, 'w') as z:
            z.writestr('userpage.bin', bytes(userpage))
            z.writestr('COMMAND', COMMAND)
            z.writestr('readme.txt', README.format(serial=birth.serialNumberString))
    else:
        with open(filename, 'wb') as f:
            f.write(userpage)


def updateDevice(path, apply=True):
    """ Directly update a device's userpage.

        @param path: The path of the device.
        @param apply: If `True`, write the 'update userpage' command to the device.
    """
    dev = getRecorder(path)
    if not dev or not getattr(dev, 'path'):
        raise RuntimeError("Not a recorder: %s" % path)

    birth = models.Birth.objects.filter(serialNumber=dev.serialInt).latest('date')

    generateUserpage(birth, filename=os.path.join(dev.path, "SYSTEM", "userpage.bin"))

    if apply:
        with open(dev.commandFile, 'wb') as f:
            print("-> Writing 'Update Userpage' command ({!r}) to device {}".format(COMMAND, dev.commandFile))
            f.write(COMMAND)
    else:
        print("-> 'Update Userpage' command was (deliberately) not written to %s" % dev.commandFile)


#===============================================================================
#
#===============================================================================

if __name__ == "__main__":
    import argparse
    import string
    import logging

    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('serialNumber',
                           metavar="SERIAL_NUMBER",
                           nargs='+',
                           help=("One or more serial numbers of devices for which to build userpage.bin files. "
                                 "Can be the formatted version (e.g., S0012345) or just the numeric part."))
    argparser.add_argument('--out', '-o',
                           metavar="USERPAGE.BIN",
                           help=("The name of the generated file. Defaults to 'userpage_<serial>.bin'. "
                                 "Only applicable if one serial number is supplied!"))
    argparser.add_argument('--verbose', '-v',
                           action="store_true",
                           help="Show extra (debugging) information when running.")
    argparser.add_argument('--zip', '-z',
                           action="store_true",
                           help="Create a zip file (containing userpage and COMMAND), ready to send out.")

    args = argparser.parse_args()
    out = args.out if args.out else None
    if out and len(args.serialNumber) != 1:
        sys.stderr.write("Error: --out option only applicable if 1 serial number specified.")
        exit(1)

    if not args.verbose:
        template_generator.logger.setLevel(logging.ERROR)

    # Get all births before starting the generation, so a bad SN will make the run
    # fail before some unknown subset of the serial numbers are processed.
    births = []
    for sn in args.serialNumber:
        sn = int(sn.strip(string.ascii_letters + string.punctuation))
        births.append(models.Birth.objects.filter(serialNumber=sn).latest('date'))

    for birth in births:
        generateUserpage(birth, out, zipit=args.zip)
