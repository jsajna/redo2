"""
Utility for generating 'fake' device userpages.
"""

import argparse
import logging
import os.path
from typing import Optional
import warnings

from . import generate_userpage  # Python paths will be set up after importing generate_userpage
from . import template_generator as tg

# Set `True` to prevent update command and show more debugging messages
__DEBUG__ = False


def parseRev(revStr: str) -> tuple[int, Optional[int]]:
    """ Parse a version/revision/BOM string into a number.

        :param revStr: A revision string, either just a number (old style),
            "v#r#", or "#.#" format. May have a BOM letter suffix. Numeric
            versions may or may not contain the BOM rev (e.g., 201 or 20100).
        :return: The version number (combining version and revision) and
            the BOM version number (if in the `revStr`, else `None`).
    """
    if not revStr:
        return None, None

    revStr = str(revStr).strip()
    if revStr[-1].isalpha():
        bom = ord(revStr[-1].upper()) - 65
        revStr = revStr[:-1]
    else:
        bom = None

    revStr = revStr.lower().replace('v', '').replace('r', '.').rstrip(' -._')
    if '.' in revStr:
        # Dotted version string (or v#r# format)
        vers, rev = [int(num.strip()) for num in revStr.split('.')]
        return (vers * 100) + rev, bom
    else:
        # Just a number, presumably VVRR[BB]
        rev = int(revStr)
        if rev >= 10000:
            bom = rev % 100
            rev = rev // 100
        return rev, bom


def findExemplar(partNumber: str,
                 hwRev: Optional[int]=None,
                 bom: Optional[int]=None,
                 serialNumber=None):
    """ Find an exemplar based on part number, and (optionally) hwRev and
        (more optionally) BOM rev.

        :param partNumber: The base part number.
        :param hwRev: The base hardware version (version * 100 + revision)
        :param bom: The BOM version. Can't be used without `hwRev`.
        :param serialNumber: A specific serial number (defaults to < 0).
        :return: The last exemplar Birth matching the parameters.
    """
    results = tg.models.Birth.objects.filter(product__partNumber=partNumber)

    if serialNumber is not None:
        results = results.filter(serialNumber=serialNumber)
    else:
        results = results.filter(serialNumber__lt=0)

    if hwRev is not None:
        results = results.filter(device__hwType__hwRev=hwRev)
        if bom is not None:
            results = results.filter(device__bomRev=bom)

    if results.count() > 1:
        warnings.warn(f'{results.count()} exemplars matched the search parameters, returning last.')

    return results.last()


def makeFakeUserpage(exemplar: tg.models.Birth,
                     serialNumber: int,
                     filename: str = "userpage.bin",
                     xml: bool = False,
                     **kwargs):
    """ Create a userpage for the given Exemplar, using keyword arguments to
        replace certain values.

        :param exemplar: The exemplar `Birth` object.
        :param serialNumber: The fake serial number.
        :param filename: The output filename.
        :param xml: If `True`, write XML files as well as EBML. XML is
            written first (good for debugging a value that won't encode).

        :param productName: Optional replacement product name.
        :param partNumber: Optional replacement part number.
        :param hwRev: Optional replacement hardware rev (should include BOM,
            e.g., "v2r0 B" -> 20001).
        :param minFwRev: Optional replacement minimum FW version
        :return: The `ManifestTemplater` and `DefaultCalTemplater` used to
            make the userpage. Mainly for testing; you don't *need* to do
            anything with them..
    """
    mt = tg.ManifestTemplater(exemplar, serialNumber=serialNumber, **kwargs)
    ct = tg.DefaultCalTemplater(exemplar)

    if xml:
        path, name = os.path.split(filename)
        mt.writeXML(f"{os.path.splitext(name)[0]}_manifest.xml")
        ct.writeXML(f"{os.path.splitext(name)[0]}_calibration.xml")

    with open(filename, 'wb') as f:
        up = generate_userpage.makeUserpage(mt.dumpEBML(), ct.dumpEBML())
        f.write(up)

    return mt, ct


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description=__doc__.strip())
    group1 = argparser.add_argument_group('Query',
            description="Arguments used to find the base Birth exemplar")
    group1.add_argument('partNumber',
                        help="The part number.")
    group1.add_argument('--hwRev', '-h',
                        help="The hardware version. Can be the literal numeric "
                             "form, or the written form (e.g., 'v2r1B')")
    group1.add_argument('--exemplarSerial', '-e',
                        type=int,
                        help="A specific serial number to use as the exemplar. "
                             "Defaults to any less than zero.")

    group2 = argparser.add_argument_group('Manifest Info',
            description="Instance-specific manifest parameters")
    group2.add_argument('--serialNumber', '-s', type=int,
                        help="The device serial number.")
    # group2.add_argument('--accelSerial', '-a', nargs="*",
    #                     help="The accelerometer serial number (may be used multiple times)")
    group2.add_argument('--minFwRev', '-m',
                        help="The minimum compatible firmware version.")
    group2.add_argument('--devicePartNumber', '-P',
                        help="An alternative part number to write to the manifest, "
                             "overriding the one in the exemplar.")
    group2.add_argument('--deviceProductName', '-N',
                        help="An alternative product name to write to the manifest, "
                             "overriding the one in the exemplar.")
    group2.add_argument('--deviceHwRev', '-H',
                        help="An alternative hardware version (numeric, including BOM), "
                             "overriding the one in the exemplar.")

    argparser.add_argument('--output', '-o',
                           default="userpage.bin",
                           help="Output filename.")
    argparser.add_argument('--xml', '-x',
                           action="store_true",
                           help="Generate XML files as well as EBML. "
                                "Uses the base output name.")
    argparser.add_argument('--debug', '-d',
                           action="store_true",
                           help="Show additional debugging information")

    args = argparser.parse_args()

    tg.logger.setLevel(logging.DEBUG if __DEBUG__ or args.debug
                       else logging.ERROR)

    hwRev, bom = parseRev(args.hwRev)
    exemplar = findExemplar(args.partNumber, hwRev, bom, args.exemplarSerial)

    if exemplar is None:
        print("Could not find exemplar matching query!")
        exit(1)

    kwargs = {'partNumber': args.devicePartNumber,
              'productName': args.deviceProductName,
              'minFwRev': args.minFwRev}

    if args.deviceHwRev:
        devRev, devBom = parseRev(args.deviceHwRev)
        kwargs['hwRev'] = devRev * 100 + (devBom or 0)

    kwargs = {k: v for k, v in kwargs.items() if v is not None}
    makeFakeUserpage(exemplar, args.serialNumber, filename=args.output,
                     xml=args.xml, **kwargs)
