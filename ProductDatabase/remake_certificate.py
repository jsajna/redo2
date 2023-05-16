"""
Utility to re-generate calibration certificates for one or more device,
specified by serial number.
"""
import argparse
import logging
import os

# Django setup
os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"
import django
django.setup()

from birther.template_generator import logger, models, remakeCertificate

#===============================================================================
#
#===============================================================================


if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description=__doc__.strip())
    argparser.add_argument('serialNumber',
                           metavar="SERIAL_NUMBER",
                           nargs='+',
                           help=("One or more serial numbers of devices for which to build certificates. "
                                 "Can be the formatted version (e.g., S0012345) or just the numeric part."))
    argparser.add_argument('--verbose', '-v',
                           action="store_true",
                           help="Show extra (debugging) information when running.")
    args = argparser.parse_args()

    if not args.verbose:
        logger.setLevel(logging.INFO)

    print(f"\nRegenerating {len(args.serialNumber)} certificate(s): {', '.join(args.serialNumber)}")
    made = 0
    for sn in args.serialNumber:
        try:
            pdf = remakeCertificate(int(sn.strip().upper().lstrip('SXCWH0'), 10))
            made += 1
            print(f"* Generated {pdf}")
        except models.Birth.DoesNotExist:
            logger.error(f"Serial number {sn} does not exist, skipping")
        except models.CalSession.DoesNotExist:
            logger.error(f"No calibration for {sn}, skipping")

    print(f"Successfully regenerated {made} of {len(args.serialNumber)} certificate(s).\n")
