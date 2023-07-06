"""
GUI for selecting a connected device and regenerating its USERPAGE.
"""
import argparse
import logging

from endaq.device import getDevices
from . import generate_userpage  # Python paths will be set up after importing generate_userpage

# Set `True` to prevent update command and show more debugging messages
__DEBUG__ = False

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--debug', '-d',
                           action="store_true",
                           help="Show additional debugging information")
    argparser.add_argument('--noapply', '-n',
                           action="store_true",
                           help="Don't send the 'Update Userpage' command ('up') after building userpage.bin "
                                "(intended for testing)")
    args = argparser.parse_args()

    if __DEBUG__ or args.debug:
        generate_userpage.template_generator.logger.setLevel(logging.DEBUG)
    else:
        generate_userpage.template_generator.logger.setLevel(logging.ERROR)

    good = bad = 0

    try:
        print("\n\n**** Device USERPAGE updater ****")
        input("Connect one or more enDAQ recorders and hit return. ")
        while True:
            print("Gathering devices...")
            devices = getDevices()
            if not devices:
                q = input("No devices found. Try again [Y/n]?" )
                if q.upper() in ('', 'Y'):
                    continue
                else:
                    break

            print(f'Found {len(devices)} device(s): {", ".join(d.serial for d in devices)}')

            for dev in devices:
                print(f"Updating {dev}")

                try:
                    generate_userpage.updateDevice(dev.path, apply=not args.noapply)
                    print(f"Updated {dev}")
                    good += 1
                except Exception as err:
                    print(f"Failed to update {dev}: {err!r}")
                    bad += 1
            q = input("Update more devices [Y/n]?")
            if q.upper() in ('', 'Y'):
                continue
            else:
                break

    except KeyboardInterrupt:
        print('\n!!! Received keyboard interrupt/ctrl+c, quitting...')

    print(f'Finished after successfully updating {good} device(s), {bad} failure(s)')

    exit(0)
