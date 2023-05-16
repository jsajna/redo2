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

    from birther.birth_wizard import BirtherApp, logger

    logger.info("** Starting Birth-o-Matic: the Birth Wizard! **")

    try:
        from git.repo import Repo

        repo = Repo('..')
        commit = next(repo.iter_commits())
        logger.info(u"%s: branch %s, commit %s" % (os.path.basename(__file__),
                                                   repo.active_branch.name,
                                                   commit.hexsha[:7]))
        logger.info(u"Commit date: %s" % commit.authored_datetime)
    except Exception as err:
        logger.error("Could not get git information! Exception: %s" % err)

    app = BirtherApp(False)
    app.MainLoop()

