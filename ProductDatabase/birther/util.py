"""
Various handy utility functions, used in both birthing and calibration.

Created on Jan 31, 2019
"""

__author__ = "dstokes"
__copyright__ = "Copyright 2019 Mide Technology Corporation"

import errno
from math import ceil
import os.path
import shutil
import string
import time

import ebmlite
import endaq.device
import git
from win32com.client import Dispatch
import wx

try:
    import paths
except ModuleNotFoundError:
    from . import paths

from shared_logger import logger

from typing import Union

#===============================================================================
# 
#===============================================================================

class XYZ(list):
    """ Helper for making arrays of XYZ less ugly. A mutable named tuple.
        Used for calibration numbers, files associated with axes, etc.
    """

    def __init__(self, *args, **kwargs):
        if len(args) == 1 and args[0] is None:
            super(XYZ, self).__init__((None, None, None))
        elif len(args) == 3:
            super(XYZ, self).__init__(args)
        else:
            super(XYZ, self).__init__(*args)
        if len(self) == 1:
            self.extend([self[0]] * 2)
        elif len(self) < 3:
            self.extend([0]*(3-len(self)))

        if kwargs:
            for n, axis in enumerate('xyz'):
                if axis in kwargs:
                    self[n] = kwargs[axis]


    def __repr__(self):
        return "(x: %r, y: %r, z: %r)" % tuple(self)
    
    def __bool__(self):
        return any(self)

    def __nonzero__(self):
        return self.__bool__()
    
    def __getitem__(self, idx):
        try:
            return list.__getitem__(self, idx)
        except TypeError:
            if isinstance(idx, str):
                idx = idx.upper()
                if idx in "XYZ":
                    return list.__getitem__(self, "XYZ".index(idx))
            raise KeyError("Bad XYZ index: %r" % idx)

    def __mul__(self, other: Union['XYZ', list]):
        return XYZ(self[i] * other[i] for i in range(3))

    def __sub__(self, other: Union['XYZ', list]):
        return XYZ([self[i] - other[i] for i in range(3)])
    @property
    def x(self):
        return self[0]

    @x.setter
    def x(self, val):
        self[0] = val

    @property
    def y(self):
        return self[1]

    @y.setter
    def y(self, val):
        self[1] = val

    @property
    def z(self):
        return self[2]

    @z.setter
    def z(self, val):
        self[2] = val


#===============================================================================
# 
#===============================================================================

def inRange(v, minVal, maxVal, absolute=False):
    if absolute:
        v = abs(v)
    return minVal <= v <= maxVal


def allInRange(vals, minVal, maxVal, absolute=False):
    return all((inRange(x, minVal, maxVal, absolute) for x in vals))


#===============================================================================
# 
#===============================================================================

def changeFilename(filename, ext=None, path=None):
    """ Modify the path or extension of a filename. 
    """
    if ext is not None:
        ext = ext.lstrip('.')
        filename = "%s.%s" % (os.path.splitext(filename)[0], ext)
    if path is not None:
        filename = os.path.join(path, os.path.basename(filename))
    return os.path.abspath(filename)


#===============================================================================
#--- Backup files
#===============================================================================

def makeBackup(filename):
    """ Create a backup copy of the given file. For use in conjunction with
        `restoreBackup()`.
    """
    backupFilename = filename + "~"
    if os.path.exists(filename):
        shutil.copy2(filename, backupFilename)
        return True
    return False


def restoreBackup(filename, remove=False):
    """ Restore a backup copy of a file, overwriting the file. For use in 
        conjunction with `makeBackup()`.
    """
    backupFilename = filename + "~"
    if os.path.exists(backupFilename):
        shutil.copy2(backupFilename, filename)
        if remove:
            os.remove(backupFilename)
        return True
    return False


#===============================================================================
#--- File copying
#===============================================================================

def safeRemove(filename):
    """ Attempt to remove a file, failing silently.
    
        @param filename: The name of the file to delete.
        @return: `True` if the file was deleted or doesn't exist, `False` if
            `filename` isn't a file or an error occurred.
    """
    try:
        if os.path.isfile(filename):
            os.remove(filename)
        elif os.path.exists(filename):
            return False
        return True
    except (IOError, WindowsError):
        return False


def safeRmtree(dirname):
    """ Attempt to remove a directory, failing silently.
    
        @param dirname: The name of the file to delete.
        @return: `True` if the directory was deleted or doesn't exist, `False`
            if `dirname` isn't a directory or an error occurred.
    """
    try:
        if os.path.isdir(dirname):
            shutil.rmtree(dirname)
        elif os.path.exists(dirname):
            return False
        return True
    except (IOError, WindowsError):
        return False


def safeCopy(source, dest):
    """ Copy a file from `source` to `dest`, if `dest` does not already exist.
        Does not raise `IOError` or `TypeError` exceptions; just returns
        success or failure.
        
        @param source: The source filename.
        @param dest: The destination filename or directory.
        @return: `True` for success, `False` for failure.
    """
    try:
        if not os.path.exists(dest):
            shutil.copy2(source, dest)
            return True
    except (IOError, TypeError):
        pass
    return False


def safeMakedirs(path, **kwargs):
    """ Safer version of `os.makedirs()`; create a leaf directory and all
        intermediate ones, but fail gracefully if the directory already exists.
    """
    try:
        os.makedirs(path, **kwargs)
        return True
    except (IOError, WindowsError) as err:
        if err.errno != errno.EEXIST:
            raise
    return False


def deepCopy(source, dest, clobber=False):
    """ Copy a file from one location to another, creating intermediate
        directories as required. A convenient combination of `os.makedirs()`
        and `shutil.copy2()`.
        
        @param source: The source filename.
        @param dest: The destination filename.
        @param clobber: If `True`, existing files will get overwritten (but
            a backup will be preserved). If `False`, attempting to copy over
            an existing file will raise an `IOError`.
    """
    if os.path.exists(dest):
        if clobber:
            makeBackup(dest)
            os.remove(dest)
        else:
            raise IOError(errno.EEXIST, "File already exists: '%s'" % dest)
        
    safeMakedirs(os.path.dirname(dest))
    return shutil.copy2(source, dest)


def getContent(dev, sourcePath=paths.DB_PATH):
    """ Get the names of the default content items that will be copied to
        the root directory of the recorder.
        
        @param dev: The device to copy to. An instance of a 
            `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
        @param sourcePath: The original content directory.
        @return: A list of two-item tuples: the source filename and the
            destination filename.
    """
    # XXX: TODO: WILL NEED TO CHANGE WITH NEW enDAQ PART NUMBERS!
    contentPath = os.path.join(sourcePath, '_%s_Contents' % dev.partNumber[:8])
    if not os.path.isdir(contentPath):
        contentPath = os.path.join(sourcePath, '_Copy_Folder')
        
    ignore = shutil.ignore_patterns('.*', '*.lnk', 'Thumbs.db')
    
    files = os.listdir(contentPath)
    files = set(files).difference(ignore(contentPath, files))
    
    return [(os.path.realpath(os.path.join(contentPath, c)),
             os.path.realpath(os.path.join(dev.path, c))) for c in files]


def copyContent(dev, sourcePath=paths.DB_PATH):
    """ Copy the default Slam Stick X content (i.e. the documentation and 
        application folders) to a recorder. Files are copied from the
        either the product's copy folder or the generic ``_Copy_Folder``
        to the root directory of the device.
        
        @todo: Manually crawl the directories and explicitly copy each
            item, calling the `callback` function for each, so the progress
            dialog can actually show something.
        
        @param dev: The device to copy to. An instance of a 
            `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
        @param sourcePath: The original content directory.
    """
    ignore = shutil.ignore_patterns('.*', '*.lnk', 'Thumbs.db')
    
    for c, dest in getContent(dev, sourcePath): 
    # Copy the contents of the 'contents' folder to the root of the device
        if os.path.isdir(dest):
#             logger.info("Removing old content: %s" % dest)
            shutil.rmtree(dest)
        
#         logger.info('Copying content: %s' % dest)
        if os.path.isdir(c):
            shutil.copytree(c, dest, ignore=ignore)
        elif os.path.isfile(c):
            shutil.copy2(c, dest)


def makeContentDirs(dev, sourcePath=paths.DB_PATH):
    """ Create the directories for the default content (i.e. the
        documentation and application folders), but do not copy content.
        Primarily for Navy orders, since some script they use looks for
        these directories in order to identify a Slam Stick.

        @todo: Add a `callback` function, like `copyContent()` will have?

        @param dev: The device to copy to. An instance of a
            `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
        @param sourcePath: The original content directory.
    """
    for c, dest in getContent(dev, sourcePath):
        if os.path.isdir(c):
            try:
                os.mkdir(dest)
            except (IOError, WindowsError) as err:
                if err.errno != errno.EEXIST:
                    logger.error('Error creating directory: %r' % err)


#===============================================================================
#--- Windows stuff (shortcut access, etc.)
#===============================================================================

def makeShortcut(path, target):
    """ Create a Windows Shortcut.
    
        @param path: The location in which to create the shortcut file.
        @param target: Where the shortcut leads.
    """
    scName = os.path.realpath(os.path.join(path, os.path.basename(target)+".lnk"))
    shell = Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(scName)
    sc.Targetpath = os.path.realpath(target)
    sc.save()
    return scName


def getShortcut(shortcut):
    """ Get the target of a Windows Shortcut.
    """
    scName = os.path.realpath(shortcut)
    if not os.path.exists(scName):
        raise IOError(errno.ENOENT, 'No such shortcut: %s' % shortcut)
    shell = Dispatch("WScript.Shell")
    sc = shell.CreateShortcut(scName)
    return sc.Targetpath
    

#===============================================================================
# 
#===============================================================================

def renameVolume(path, volumeName):
    """ Change the volume name of a mounted disk, mapped to a drive letter.
    """
    path = path.strip(string.whitespace + '\\')
    volumeName = volumeName.strip(string.whitespace)
    return os.system('label %s %s' % (path, volumeName)) == 0


#===============================================================================
#--- File read/write convenience functions
#    They save a few lines of code elsewhere.
#===============================================================================

def writeFileLine(filename, val, mode='w', newline=True, safe=False):
    """ Open a file and write a line as text.

        @param filename: Output filename.
        @param val: The data to write. Cast to string.
        @param mode: File mode. Defaults to 'w'.
        @param newline: If `True`, ensure line ends with a newline.
        @param safe: If `True`, don't raise an exception if the file is already
            open; write to the log and retry after a delay.
    """
    s = str(val)
    if newline and not s.endswith('\n'):
        s += "\n"

    while True:
        try:
            with open(filename, mode) as f:
                return f.write(s)
        except IOError as err:
            if err.errno == errno.EACCES:
                f = os.path.basename(filename)
                msg = f"Could not write to {f}: make sure it is not open in another application!"
                if safe:
                    logger.info(f"{msg} Retrying...")
                else:
                    raise IOError(msg)
            else:
                raise

        time.sleep(2)
        

def readFile(filename, mode="rb"):
    """ Simple helper to read all of a file.

        @param filename: Input filename.
        @param mode: File mode. Defaults to 'rb'.
    """
    with open(filename, mode) as f:
        return f.read()


def writeFile(filename, data, mode='wb', safe=False):
    """ Write data to a file.

        @param filename: Output filename.
        @param data: The data to write. Cast to string.
        @param mode: File mode. Defaults to 'w'.
        @param safe: If `True`, don't raise an exception if the file is already
            open; write to the log and retry after a delay.
    """
    while True:
        try:
            with open(filename, mode) as f:
                return f.write(str(data))
        except IOError as err:
            if err.errno == errno.EACCES:
                f = os.path.basename(filename)
                msg = f"Could not write to {f}: make sure it is not open in another application!"
                if safe:
                    logger.info(f"{msg} Retrying...")
                else:
                    raise IOError(msg)
            else:
                raise
        time.sleep(2)


#===============================================================================
# 
#===============================================================================

def levenshtein(a, b):
    """ Calculate the Levenshtein distance between `a` and `b` (the number of
        single-character differences, additions, subtractions, etc.).
    """
    n, m = len(a), len(b)
    if n > m:
        # Make sure n <= m, to use O(min(n,m)) space
        a, b = b, a
        n, m = m, n
        
    current = range(n+1)
    for i in range(1, m+1):
        previous, current = current, [i]+[0]*n
        for j in range(1, n+1):
            add, delete = previous[j]+1, current[j-1]+1
            change = previous[j-1]
            if a[j-1] != b[i-1]:
                change = change + 1
            current[j] = min(add, delete, change)
            
    return current[n]


#===============================================================================
# 
#===============================================================================

def validateConfig(filename):
    """ Perform basic validation of a config file's structure. Failure will
        raise an exception of one type or another. Failing conditions include
        basic IO errors, the root element not being the correct type 
        (`RecorderConfigurationList`), the presence of `UnknownElement`s, or
        the file simply not being readable EBML.
        
        @param filename: The path and name of the config file.
    """
    def _crawl(el):
        # print(el)
        if el.name == "UnknownElement":
            raise ValueError("Config contained an unknown element")
        elif el.dtype == list:
            for chel in el:
                _crawl(chel)
            
    schema = ebmlite.loadSchema('mide_ide.xml')
    doc = schema.load(filename)
    assert(doc[0].name in ("RecorderConfiguration", "RecorderConfigurationList"))
    _crawl(doc)


#===============================================================================
# 
#===============================================================================

def getCardSize(drive):
    """ Get the approximate size of the recorder's SD card.
    """
    fso = Dispatch("Scripting.FileSystemObject")
    drv = fso.GetDrive(drive)
    total = drv.TotalSize/2.0**30
    return int(ceil(total))


#===============================================================================
# 
#===============================================================================

def ejectDrive(drive):
    """ Attempt to 'eject' a USB drive, like the "Safely Remove Hardware"
        tool tray icon. It will stay visible, but (hopefully) its filesystem
        has been flushed for safe removal.
    """
    drive = os.path.splitdrive(drive)[0].upper()
    if not os.path.exists(drive):
        raise IOError(errno.ENOENT, 'Drive "%s" not attached' % drive)
    
    d = Dispatch("Shell.Application").Namespace(17).ParseName(drive)
    if d is not None:
        d.InvokeVerb("Eject")
    else:
        raise IOError(errno.ENOENT, 'Could not remove "%s"; may not exist' % drive)
    

#===============================================================================
#
#===============================================================================

def getGitInfo(filename, root='..'):
    """ Get the current commit information.

        @param filename: The name of the Python file that called the function.
        @param root: The repo root.
        @return: A string for the log.
    """
    repo = git.Repo(root)

    filename = filename or __file__
    commit = next(repo.iter_commits())
    return (u"%s: branch %s, commit %s (%s)" % (os.path.basename(filename),
                                                repo.active_branch.name,
                                                commit.hexsha[:7],
                                                commit.authored_datetime))


def getCommitDifference(root=None, branch=None, origin=None):
    """
    Get the number of git commits by which this repo is behind the (remote)
    origin. For warning of outdated scripts.

    :param root: The repo's root directory. If `None`, the function will
        check from "../.." (rel. to this file's location) and work downward.
    :param branch: The name of the branch. Defaults to the active branch.
    :param origin: The remote branch to which to compare. Defaults to the
        same as `branch`.
    :return: A tuple containing the number of commits the local is behind
        the (remote) origin, the date of the local's last commit, and the
        date of the remote's last commit.
    """
    repo = git.Repo(root) if root else None
    if not repo:
        here = os.path.dirname(__file__)
        for p in ('../..', '..', '.'):
            try:
                root = os.path.realpath(os.path.join(here, p))
                repo = git.Repo(root)
                break
            except git.InvalidGitRepositoryError:
                if p == '.':
                    raise

    branch = branch or repo.active_branch.name
    origin = origin or branch

    lastRemoteCommit = None
    behind = 0
    for behind, c in enumerate(repo.iter_commits(f'{branch}..origin/{origin}'), 1):
        lastRemoteCommit = lastRemoteCommit or c.authored_datetime

    try:
        lastLocalCommit = next(repo.iter_commits(branch)).authored_datetime
    except StopIteration:
        lastLocalCommit = None

    return behind, lastLocalCommit, (lastRemoteCommit or lastLocalCommit)


def cleanOldUpdates(device):
    """ Remove any old update files. Used during birth.
    """
    logger.info('Cleaning up...')

    updates = [getattr(device, f, None) for f in ('USERPAGE_UPDATE_FILE',
                                                  'FW_UPDATE_FILE',
                                                  'BOOTLOADER_UPDATE_FILE')]

    for f in updates:
        if not f:
            continue
        filename = os.path.join(device.path, f)
        try:
            if os.path.exists(filename):
                logger.info('Removing old file: %s' % filename)
                os.remove(filename)
        except (IOError, WindowsError):
            logger.error('Could not remove file %s' % filename)
            return False

    return True


#===============================================================================
#
#===============================================================================

def retryLoop(desc, func, caption="Error", suggestion='This may be temporary. Retry?',
              parent=None, ok="Retry", cancel="Abort", fatal=True):
    """ Attempt to run a function, and give the user an option to retry
        if it fails.

        @param desc: Description of the action attempted (as fits the
            sentence "an error occurred when...").
        @param func: A 'partial' function to run, takes no arguments.
        @param caption: Error dialog title.
        @param suggestion: An additional suggestion for what to do before
            retrying.
        @param parent: The window parent, mainly for dialog placement.
        @param ok: Text to use on the 'OK' button (instead of 'OK').
        @param cancel: Text to use on the 'Cancel' button (instead of 'Cancel').
        @param fatal: If `True`, cancel/abort will raise the exception.
        @return: Whatever `func` returns.
    """
    tries = 0
    while True:
        try:
            tries += 1
            return func()
        except Exception as err:
            name = type(err).__name__
            logger.error(f"Error when {desc} (try {tries}): {err!r}")
            msg = f"An error occurrred when {desc}\n\n{name}: {err}\n\n{suggestion}"
            with wx.MessageDialog(parent, msg, caption,
                                  style=wx.OK | wx.CANCEL | wx.CENTER | wx.ICON_ERROR) as mb:
                mb.SetOKCancelLabels(ok, cancel)
                if mb.ShowModal() == wx.ID_CANCEL:
                    logger.error(f"User chose {cancel!r} (cancel)")
                    if fatal:
                        raise
                    else:
                        return None


#===============================================================================
#
#===============================================================================

def getRecorder(serialNumber, timeout=120):
    """ Wait for a recorder to reboot and appear as a USB disk. Intended for
        use in/with a GUI.

        @param serialNumber: The serial number of the expected device.
        @param timeout: Time (seconds) to wait for device to appear.
        @return: An `endaq.device.Recorder` instance or `None` if it
            could not be found before timeout.
    """
    # Force cache of known drive letters to clear (recorder may already be
    # present as a USB disk).
    # endaq.device._LAST_RECORDERS = None

    deadline = time.time() + timeout

    while time.time() < deadline:
        if endaq.device.deviceChanged():
            for dev in endaq.device.getDevices():
                if dev.serialInt == serialNumber:
                    return dev
        wx.Yield()
        time.sleep(.25)


#===============================================================================
#
#===============================================================================

def setTime(dev, retries=3, maxDrift=2):
    """ Attempt to set a device's clock, verifying each try.

        :param dev: The `enadq.device.Recorder` to set.
        :param retries: The number of retries before failure.
        :param maxDrift: The maximum allowable difference in system vs.
            device clocks. Note: this is relatively high due to a possible
            bug in  `SerialCommandInterface` (seems to be adding 1 second).
            A failure to set the clock will result in a much greater
            difference.
    """
    # Check that device is available and still the same path (it could have
    # rebooted or been power cycled).
    if not os.path.exists(dev.path):
        logger.debug(f'{str(dev).strip("<>")} not present; calling getRecorder()')
        newdev = getRecorder(dev.serialInt)

        if newdev is None:
            raise endaq.device.DeviceTimeout(f'Could not find {dev.partNumber} {dev.serial} (timed out)')
        else:
            dev = newdev

    t = 0
    while t < retries:
        drift = None
        try:
            dev.command.setTime(retries=3)
            drift = abs(dev.command.getClockDrift())
            if drift < maxDrift:
                return True
        except (IOError, endaq.device.DeviceError) as error:
            t += 1
            logger.error(f'Failed to set clock on {dev.serial} '
                         f'(try {t} of {retries}), {drift=}, {error=!r}')

    raise endaq.device.ConfigError(f'Could not set clock on {dev.serial} after {t} attempts')
