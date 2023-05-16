from birther.generate_userpage import *

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
