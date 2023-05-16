from io import BytesIO
import struct

from ebmlite import loadSchema
from ebmlite.util import xml2ebml

calSchema = loadSchema('mide_ide.xml')
manSchema = loadSchema('mide_manifest.xml')


def makeUserpage(manFile, calFile, propsFile='', pageSize=4096):
    """ Combine a binary Manifest, Calibration, and (optionally) Recorder
        Properties EBML into a unified, correctly formatted userpage block.

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
    ms = BytesIO()
    xml2ebml(manFile, ms, manSchema)
    ms.seek(0)
    manifest = ms.read()

    cs = BytesIO()
    xml2ebml(calFile, cs, calSchema)
    cs.seek(0)
    caldata = cs.read()

    if propsFile:
        ps = BytesIO()
        xml2ebml(propsFile, ps, manSchema)
        ps.seek(0)
        recprops = ps.read()
    else:
        recprops = ''

    manSize = len(manifest)
    manOffset = 0x0010  # 16 byte offset from start
    calSize = len(caldata)
    calOffset =  manOffset + manSize  # 0x0400 # 1k offset from start
    propsSize = len(recprops)

    if propsSize > 0:
        propsOffset = calOffset + calSize
    else:
        propsOffset = 0

    data = struct.pack("<HHHHHH",
                       manOffset, manSize,
                       calOffset, calSize,
                       propsOffset, propsSize)
    data = bytearray(data.ljust(pageSize, '\x00'))
    data[manOffset:manOffset+manSize] = manifest
    data[calOffset:calOffset+calSize] = caldata
    data[propsOffset:propsOffset+propsSize] = recprops

    if len(data) != pageSize:
        # Probably can never happen, but just in case...
        raise ValueError("Userpage block was %d bytes; should be %d" %
                         (len(data), pageSize))

    return data


#===============================================================================
#
#===============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    argparser = argparse.ArgumentParser(description="""
        USERPAGE building tool!
        """)

    argparser.add_argument('manifest',
                           metavar="MANIFEST.xml",
                           help="The manifest XML file.")
    argparser.add_argument('calibration',
                           metavar="CALIBRATION.xml",
                           help="The 'factory' calibration XML file.")
    argparser.add_argument('-r', '--recprops',
                           metavar="RECPROPS.xml",
                           help="The recorder properties XML. Legacy; you probably want to ignore this.")
    argparser.add_argument('-p', '--pagesize', type=int, default=4096,
                           help="The USERPAGE size, in bytes.")
    argparser.add_argument('-o', '--output',
                           metavar="USERPAGE.ebml",
                           help="The output file. Will default to stdout.")

    args = argparser.parse_args()

    data = makeUserpage(args.manifest, args.calibration, propsFile=args.recprops,
                        pageSize=args.pagesize)

    if args.output:
        with open(args.output, 'wb') as f:
            f.write(data)
    else:
        sys.stdout.write(data)
