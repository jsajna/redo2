"""
Functions (mostly for file-handling) used in the calibration process, but were
far enough from the actual calibration that they just bloated the actual
`Calibrator` class.

Created on Sep 5, 2019

@author: dstokes
"""

from datetime import datetime
import errno
from glob import glob
import os
import shutil
import string
import time

import paths
import util

#===============================================================================
# 
#===============================================================================

from shared_logger import logger

#===============================================================================
# 
#===============================================================================

# PRODUCT_ROOT_PATH = r"\\MIDE2007\Products\LOG-Data_Loggers\LOG-0002_Slam_Stick_X"
# DB_PATH = os.path.join(PRODUCT_ROOT_PATH, "Product_Database")
# paths.CAL_PATH = os.path.join(DB_PATH, "_Calibration")

# Save location of temporary directory, where things are staged before
# getting copied to the shared folder.
# paths.TEMP_DIR = os.path.realpath(os.path.expanduser('~/Documents/BirtherTemp'))


#===============================================================================
# 
#===============================================================================

def makeWorkDir(cal, new=False, root=paths.TEMP_DIR):
    """ Create a temporary working directory. Within the specified working
        directory root, a unique device subdirectory will be created.
        Note: this will modify the Calibrator's `workDir` attribute.

        @param cal: A `calibration.Calibrator` instance.
        @keyword new: If `False`, don't create a new working directory if
            the `Calibrator` already has a `workDir` defined. If `True`,
            always create a new working directory with a new timestamp.
        @keyword root: An alternate root work directory.
        @return: The working directory's full path.
    """
    if not new:
        try:
            if os.path.isdir(cal.workDir) and cal.workDir.startswith(root):
                logger.debug("Using existing working directory")
                return cal.workDir
        except:
            pass
    
    if cal.dev:
        basename = cal.dev.serial
    else:
        basename = datetime.now().strftime('%Y%m%d%H%M%S')
    
    path = os.path.join(root, basename)
    
    # Create a unique calibration work directory. Adds a numeric
    # suffix if it exists, which shouldn't happen, but might in testing.
    i = 0
    while os.path.exists(path):
        i += 1
        path = os.path.join(root, "%s_%d" % (basename, i))

    util.safeMakedirs(path)
    
    cal.workDir = path
    return path


def copyToWorkDir(cal, ideFiles=None, workRoot=paths.TEMP_DIR):
    """ Copy the relevant files to the local working directory. If
        calibrating an actual device, this method can also be used to
        get a list of recordings (for use with `calculate()`). Real devices
        also get their ``SYSTEM`` folder copied.
    
        @param cal: A `calibration.Calibrator` instance.
        @keyword ideFiles: A list of the IDE files to use for calibration.
            If `None`, the software will attempt to find files on the
            device being calibrated (if any).
        @keyword workRoot: An alternate root work directory.
        @return: The full paths and names of the copied IDE files.
    """
    if not cal.workDir:
        makeWorkDir(cal, workRoot)
        
    if not ideFiles:
        ideFiles = cal.getFiles()
    
    ides = []
    for f in ideFiles:
        newname = util.changeFilename(f, path=cal.workDir)
        
        logger.debug("Copying '%s' to '%s'" % (f, newname))
        
        shutil.copy2(f, newname)
        ides.append(newname)
        
    if cal.dev and cal.dev.path:
        source = os.path.join(cal.dev.path, 'SYSTEM')
        dest = os.path.join(cal.workDir, 'SYSTEM')
        
        logger.debug("Copying directory '%s' to working directory '%s'" % 
                    (source, dest))
        
        shutil.copytree(source, dest,
                        ignore=shutil.ignore_patterns('.*', '*.lnk',
                                                      'Thumbs.db', 'CLOCK',
                                                      '*.bin', 'Command',
                                                      'update.pkg'))
    else:
        logger.warning("Calibrator does not have a 'real' device, "
                       "system folder not copied!")
    
    return ides
    

def copyFromWorkDir(cal, calRoot=paths.CAL_PATH):
    """ Copy the contents of the working directory to the shared
        ``_Calibration`` directory.
        Note: this will modify the Calibrator's `calDir` attribute.

        @param cal: A `calibration.Calibrator` instance.
        @return: The calibration directory. The Calibrator's `calDir` attribute
            also gets set to this.
    """
    if not cal.dev:
        raise AttributeError("Calibrator has no device!")
    
    base = os.path.join(calRoot, cal.dev.serial)
    if not os.path.exists(base):
        os.makedirs(base)
        
    dest = os.path.join(base, "C%05d" % cal.sessionId)
    
    # Create a unique calibration session directory. Adds a numeric
    # suffix if it exists, which shouldn't happen, but might in testing.
    i = 0
    while os.path.exists(dest):
        i += 1
        dest = os.path.join(base, "C%05d_%d" % (cal.sessionId, i))

    logger.debug("copyFromWorkDir(): dest=%s" % dest)
    shutil.copytree(cal.workDir, dest,
                    ignore=shutil.ignore_patterns('.*', '*.lnk', 
                                                  'Thumbs.db'))
    
    cal.calDir = dest
    return dest


def copyCal(cal, dbRoot=paths.DB_PATH):
    """ Copy calibration XML and EBML to the device's chip directory.
        Note: Relies on the calibration having been successful up to now;
        uses the Calibrator's `birth` and `calDir` attributes.

        @param cal: A `calibration.Calibrator` instance.
        @return: Success or failure.
    """
    if not cal.birth:
        logger.error("Calibrator references no database Birth record!")
        return False
    
    chipId = cal.birth.device.chipId
    chipDir = os.path.join(dbRoot, chipId)
    if not os.path.isdir(chipDir):
        # Report error?
        logger.error("No chip directory: %s" % chipDir)
        return False
    
    xmlName = os.path.join(cal.calDir, 'cal.current.xml')
    ebmlName = os.path.join(cal.calDir, 'cal.current.ebml')
    
    xmlName2 = os.path.join(chipDir, 'cal.current.xml')
    ebmlName2 = os.path.join(chipDir, 'cal.current.ebml')

    util.makeBackup(ebmlName2)
    util.makeBackup(xmlName2)

    success = True
    for source, dest in ((ebmlName, ebmlName2), (xmlName, xmlName2)):
        try:
            logger.debug("Copying '%s' to '%s" % (source, dest))
            shutil.copy2(source, dest)
        except (IOError, WindowsError) as err:
            success = False
            logger.error("Failed to copy '%s': %s" % (os.path.basename(source),
                                                      err))

    return success


def cleanWorkDir(cal):
    """ Remove a temporary working directory.
    """
    if not cal or not cal.workDir or not isinstance(cal.workDir, str):
        return False
    if not os.path.isdir(cal.workDir):
        return False
    
    cal.closeFiles()
    
    try:
        logger.debug("Removing working directory %s" % cal.workDir)
        shutil.rmtree(cal.workDir)
        return True
    except (IOError, WindowsError) as err:
        if err.errno != errno.ENOENT:
            raise
    
    return False


def purgeWorkDir(workRoot=paths.TEMP_DIR):
    """ Remove all the subfolders in the temporary working directory. Won't
        fail if any files are (supposedly) open.
    """
    if not os.path.exists(workRoot):
        return []
        
    files = os.listdir(workRoot)
    removed = []
    
    if files:
        logger.debug("Purging contents of working directory...")
        for filename in files:
            filename = os.path.join(workRoot, filename)
            try:
                if os.path.isfile(filename):
                    os.remove(filename)
                elif os.path.isdir(filename):
                    shutil.rmtree(filename)
                removed.append(filename)
            except (IOError, WindowsError) as err:
                logger.error(str(err))
    return removed


def cleanRecorder(dev):
    """ Clean up the device being calibrated. If this is a recalibration,
        the user's original data and configuration will be restored.
    """
    # Get firmware/bootloader/userpage update files
    updates = [getattr(dev, f, None) for f in ('USERPAGE_UPDATE_FILE',
                                               'FW_UPDATE_FILE',
                                               'BOOTLOADER_UPDATE_FILE')]
    if updates[-1]:
        updates.append(f"{updates[-1]}.sig")
    updates = [os.path.join(dev.path, f) for f in updates if f]
    
    # Get S-series log files
    logs = (glob(os.path.join(dev.path, "mfg-test-log.txt*")) +
            glob(os.path.join(dev.path, "SYSTEM", "update_log.txt*")))
    
    # Remove update files and logs
    for filename in (updates + logs):
        if os.path.exists(filename):
            if util.safeRemove(filename):
                logger.info('Removed file: %s' % filename)
            else:
                logger.error('Could not remove file: %s' % filename)

    # Remove calibration data. Kills the whole DATA directory; it is
    # assumed that any existing data was moved prior to calibration.
    dataDir = os.path.join(dev.path, 'DATA')
    if os.path.exists(dataDir):
        logger.debug("Removing current %s" % dataDir)
        shutil.rmtree(dataDir)

    # Restore user's data (if this is a recalibration)  
    backupDir = dataDir + "~"
    try:
        if os.path.exists(backupDir):
            logger.debug("Restoring backup of previous '%s'" % dataDir)
            os.rename(backupDir, dataDir)
    except (IOError, WindowsError) as err:
        if err.errno != errno.ENOENT:
            raise

    # Restore user's configuration (if this is a recalibration)
    if util.restoreBackup(dev.configFile, remove=True):
        logger.debug('Restored previous configuration')
    if util.restoreBackup(dev.userCalFile, remove=True):
        logger.debug('Restored previous user calibration')

    # TODO: Other cleaning?
    return True

#===============================================================================
# 
#===============================================================================


def _channelName(ch):
    """
    """
    if ch is None:
        return "Accelerometer:"
    try:
        # NOTE: This used to extract text from the repr, don't remember why.
        name = ch.name
    except (TypeError, IndexError):
        name = str(ch)

    return name + ":"


def dumpCal(cal, saveTo=None):
    """ Generate the legacy text file for a calibration session. For debugging.
        This will become obsolete and stop working once all the high/lo stuff
        is refactored from Calibrator.
        
        @param cal: The `Calibrator` to dump.
        @param saveTo: The name of a file to which to write.
    """
    if isinstance(saveTo, str):
        if cal.calTimestamp is None:
            cal.calTimestamp = time.time()
        dt = datetime.utcfromtimestamp(cal.calTimestamp)
        saveName = 'calibration_%s.txt' % ''.join(filter(lambda x:x not in string.punctuation, dt.isoformat()[:19]))
        saveTo = os.path.join(saveTo, saveName)

    result = ['Serial Number: %s' % cal.dev.serial,
              'Date: %s' % time.asctime(),
              '    File    X-rms    Y-rms    Z-rms    X-cal    Y-cal    Z-cal']

    filenames = util.XYZ(os.path.basename(f.filename) for f in cal.calFiles)

    result.extend(map(str, cal.calFiles))
    if cal.hasHiAccel:
        result.append(_channelName(cal.calFiles[0].accelChannel))
        result.append("%s, X Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.x, cal.cal.x, cal.offsets.x))
        result.append("%s, Y Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.y, cal.cal.y, cal.offsets.y))
        result.append("%s, Z Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.z, cal.cal.z, cal.offsets.z))
        result.append("%s, Transverse Sensitivity in XY = %5.2f percent" % (filenames.z, cal.trans[0]))
        result.append("%s, Transverse Sensitivity in YZ = %5.2f percent" % (filenames.x, cal.trans[1]))
        result.append("%s, Transverse Sensitivity in ZX = %5.2f percent" % (filenames.y, cal.trans[2]))
        result.append('')

    if cal.hasLoAccel:
        result.append(_channelName(cal.calFiles[0].accelChannelLo))
        result.append("%s, X Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.x, cal.calLo.x, cal.offsetsLo.x))
        result.append("%s, Y Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.y, cal.calLo.y, cal.offsetsLo.y))
        result.append("%s, Z Axis Calibration Constant %9.6f, offset %9.6f" % (filenames.z, cal.calLo.z, cal.offsetsLo.z))
        result.append("%s, Transverse Sensitivity in XY = %5.2f percent" % (filenames.z, cal.transLo[0]))
        result.append("%s, Transverse Sensitivity in YZ = %5.2f percent" % (filenames.x, cal.transLo[1]))
        result.append("%s, Transverse Sensitivity in ZX = %5.2f percent" % (filenames.y, cal.transLo[2]))

    result = '\n'.join(result)

    if isinstance(saveTo, str):
        util.writeFile(saveTo, result)
        return saveTo
    if hasattr(saveTo, 'write'):
        saveTo.write(result)

    return result



