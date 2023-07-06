"""
Make a SQL backup of the entire production database. Requires MySQL Server to
have been installed!

:todo: Rework `findMysqldump()` (and default paths) to work under Linux, if
    we ever want to get this running as a cron job or something.
"""

from datetime import datetime
import errno
from glob import glob
import json
import os.path
import subprocess

MYSQL_PATH = r"C:\Program Files\MySQL\MySQL Server*"
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), '..', 'ProductDatabase', 'local_settings.json')


# ===========================================================================
#
# ===========================================================================

def findMysqldump(path=MYSQL_PATH):
    """ Locate the `mysqldump` executable.

        :param path: The MySQL Server install path.
        :returns: The full path and name of the `mysqldump` executable.
    """
    dirs = glob(path)
    if not dirs:
        raise FileNotFoundError(errno.ENOENT, 'Could not find MySQL Server', path)
    filename = os.path.join(dirs[-1], 'bin', 'mysqldump.exe')
    if not os.path.exists(filename):
        raise FileNotFoundError(filename)
    return filename


def getDatabaseInfo(filename=SETTINGS_FILE):
    """ Retrieve the 'secret' info needed to log into the database.

        :param filename: The name of the JSON file (typically `local_settings.json` in the
            Django 'app' directory.
        :returns: A dictionary of database info.
    """
    filename = os.path.abspath(filename)
    if not os.path.isfile(filename):
        raise FileNotFoundError(errno.ENOENT, 'Could not find local settings file', filename)
    with open(filename, 'r') as f:
        info = json.load(f)
        return info['databases']['default']


def makeBackup(outpath=None, filename=None, mysqlPath=None, settingsFile=None, clobber=False):
    """ Make a backup of the database using `mysqldump`.

        :param outpath: The output path.
        :param filename: The base name of the output file. Defaults to `<database name>_YYYYMMDD.sql`
        :param mysqlPath: The location of the MySQL Server install.
        :param settingsFile: The Django `local_settings.json` file.
        :param clobber: If `True`, clobber (overwrite) existing output files. If `False`,
            append an incremental number to the filename, making it unique.
        :return: The full path and name of the backup file.
    """
    outpath = outpath or '.'
    exe = findMysqldump(mysqlPath)
    info = getDatabaseInfo(settingsFile)
    filename, ext = os.path.splitext(filename or datetime.now().strftime("{NAME}_%Y%m%d.sql".format(**info)))
    outfile = os.path.abspath(os.path.join(outpath, filename))
    info['outfile'] = f"{outfile}{ext}"

    if not clobber:
        i = 1
        while os.path.exists(info['outfile']):
            info['outfile'] = f"{outfile}_{i}{ext}"
            i += 1

    params = [p.format(**info) for p in (exe, "--host={HOST}", "--port={PORT}",
                                         "--user={USER}", "--password={PASSWORD}",
                                         "--result-file={outfile}", "{NAME}")]
    if not subprocess.call(params):
        return info['outfile']


# ===========================================================================
#
# ===========================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser("enDAQ Production Database Backup")
    parser.add_argument('-f', '--filename',
                        help='The output file base name')
    parser.add_argument('-m', '--mysqlPath', default=MYSQL_PATH,
                        help='The path to the MySQL Server installation')
    parser.add_argument('-s', '--settingsFile', default=SETTINGS_FILE,
                        help="The secret Django 'local settings' JSON file")
    parser.add_argument('-c', '--clobber', action='store_true',
                        help='Clobber (overwrite) existing files')
    parser.add_argument('outpath',
                        help="The path into which to write the backup")
    args = parser.parse_args()

    print("(Note: You will see a mysqldump password security warning and maybe an 'access denied' error. Ignore these.)")
    outname = makeBackup(**vars(args))
    if not outname:
        print("!!! Calling mysqldump failed for some reason; report this!")
        exit(1)
    elif not os.path.exists(outname):
        print("!!! Database backup was not written for some reason; report this!")
        exit(1)

    print(f'Database backed up to "{outname}"')
