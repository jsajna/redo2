import argparse
import os.path
import sys

if __name__ == "__main__":
    sys.path.insert(0, '.')

    parser = argparse.ArgumentParser("enDAQ Birth-o-matic")
    parser.add_argument('-D', '--debug', action='store_true',
                        help=("Run in debug mode (needs the OS environment variable MIDE_DEV_BIRTHDATA) "
                              "to be set to a path to 'fake' birth data. Directory should be structured "
                              r"like `\\MIDE2007\Products\LOG-Data_Loggers\LOG-0002_Slam_Stick_X`."))
    parser.add_argument('-n', '--nodebug', action='store_true',
                        help="Override the value set in the MIDE_DEV environment variable and run in non-debug mode.")
    args = parser.parse_args()
    if args.debug:
        os.environ['MIDE_DEV'] = '1'
    elif args.nodebug:
        os.environ['MIDE_DEV'] = '0'

    import birther.birth_wizard
    birther.birth_wizard.main()
