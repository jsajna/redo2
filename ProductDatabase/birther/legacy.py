"""
Create directories and files compatible with the old Birthomatic.

Created on Feb 26, 2019
"""
from __future__ import absolute_import, print_function

__author__ = "dstokes"
__copyright__ = "Copyright 2019 Mide Technology Corporation"

from collections import OrderedDict
import csv
import errno
import os.path
import time

from .shared_logger import logger
from .paths import CAL_PATH, DB_PATH
from . import util


#===============================================================================
# 
#===============================================================================

RECORDER_NAME = "SlamStick X"

DEV_SN_FILE = os.path.join(DB_PATH, 'last_sn.txt')
CAL_SN_FILE = os.path.join(DB_PATH, 'last_cal_sn.txt')

BIRTH_LOG_FILE = os.path.join(DB_PATH, "product_log.csv")
CAL_LOG_FILE = os.path.join(CAL_PATH, 'SSX_Calibration_Sheet.csv') 
CAL_BAD_LOG_FILE = os.path.join(CAL_PATH, 'SSX_Bad_Calibration.csv') 

#===============================================================================
#--- Birthing functions
#===============================================================================


def makeDirectories(birth, shortcuts=True):
    """ Create the old-style directories for the birthed product's chip ID
        and serial number. Also generates shortcuts between them.
        
        @param birth: The `Birth` record for which to create directories.
        @param shortcuts: If `True`, create shortcuts from the chip ID
            directory to the calibration directory, and vise versa.
    """
    # 6. Create chip ID directory in product_database
    chipDirName = os.path.realpath(os.path.join(DB_PATH, birth.device.chipId))
    if not os.path.exists(chipDirName):
        logger.info("Creating chip ID folder '%s'..." % chipDirName)
        os.mkdir(chipDirName)
        
    calDirName = os.path.realpath(os.path.join(CAL_PATH, birth.serialNumberString))
    if not os.path.exists(calDirName):
        logger.info("Creating calibration folder '%s'..." % calDirName)
        os.mkdir(calDirName)

    # Make convenience shortcuts
    if shortcuts:
        logger.info("Creating shortcuts between directories...")
        try:
            util.makeShortcut(chipDirName, calDirName)
            util.makeShortcut(calDirName, chipDirName)
        except Exception:
            # Naked exceptions are bad medicine. 
            logger.error("Failed to create shortcut(s)!")
    
    return chipDirName, calDirName


def writeTemplates(manTemplater, calTemplater):
    """ Write the manifest and default calibration data to the birthed device's
        chipID directory.
        
        @param manTemplater: The `ManifestTemplater` for the birth.
        @param calTemplater: The `DefaultCalTemplater` for the birth.
    """
    # 7. Generate manifest and generic calibration list for model
    birth = manTemplater.birth
    chipDirName = os.path.realpath(os.path.join(DB_PATH, birth.device.chipId))

    if not os.path.isdir(chipDirName):
        raise IOError(errno.ENOENT, 'No such chip ID directory', chipDirName)
    
    logger.info("Creating manifest and default calibration files...")
    manXmlFile = os.path.join(chipDirName, 'manifest.xml')
    calXmlFile = os.path.join(chipDirName, 'cal.template.xml')
    manTemplater.writeXML(manXmlFile)
    calTemplater.writeXML(calXmlFile)
    
    manEbmlFile = os.path.join(chipDirName, 'manifest.ebml')
    calEbmlFile = os.path.join(chipDirName, 'cal.template.ebml')
    manTemplater.writeEBML(manEbmlFile)
    calTemplater.writeEBML(calEbmlFile)

    # Copy template as 'current' if one doesn't already exist (the original
    # script did this).
    curCalXmlFile = os.path.join(chipDirName, 'cal.current.xml')
    curCalEbmlFile = os.path.join(chipDirName, 'cal.current.ebml')
    util.safeCopy(calXmlFile, curCalXmlFile)
    util.safeCopy(calEbmlFile, curCalEbmlFile)


def findOldCal(chipId):
    """ Find a previous ``cal.current.ebml``  file for a `Device` using its
        unique chip ID.
    """
    chipDirName = os.path.realpath(os.path.join(DB_PATH, chipId))
    calFile = os.path.join(chipDirName, 'cal.current.ebml')
    if os.path.isfile(calFile):
        return calFile
    return None


def makeBirthLogEntry(chipid, device_sn, rebirth, bootver, hwrev, fwrev, 
                      device_accel_sn, partnum, batchnum=''):
    """
    """
    if isinstance(device_accel_sn, list):
        device_accel_sn = " ".join(device_accel_sn)
    data = [str(x).replace(',', ' ') for x in
               (time.asctime(), 
                int(time.mktime(time.gmtime())), 
                chipid, 
                device_sn, 
                int(rebirth), 
                bootver, 
                hwrev, 
                fwrev, 
                device_accel_sn, 
                partnum,
                batchnum)]
    return ','.join(data)+'\n'


def updateLogs(birth, chipDirName, calDirName, newSerialNumber=True):
    """ Update the legacy CSV log files. Writing of each file is done
        'safely' (i.e. allowed to fail if the file is open). These are
        legacy files, so it's acceptable; they will likely be completely
        deprecated at some point.
    """
    # 9. Update birth log
    device = birth.device
    serials = [str(x.serialNumber) for x in device.getSensors(info__hasSerialNumber=True)
               if "Communication" not in x.info.name]  # Exclude WiFi MAC
    accelSerialNum = ' '.join(serials)
    batchId = device.batch.batchId if device.batch else ""

    logger.info("Legacy: Updating birthing logs...")
    logline = makeBirthLogEntry(device.chipId, birth.serialNumber,
                                birth.rebirth, birth.bootRev,
                                device.hwRev, birth.fwRev, accelSerialNum,
                                birth.partNumber, batchId)
    util.makeBackup(BIRTH_LOG_FILE)
    util.writeFileLine(BIRTH_LOG_FILE, logline, mode='at', safe=True)
    util.writeFileLine(os.path.join(calDirName, 'birth_log.txt'), logline, safe=True)

    if newSerialNumber:
        logger.info("Legacy: Writing serial number to master file: %s" % birth.serialNumber)
        util.makeBackup(DEV_SN_FILE)
        util.writeFileLine(DEV_SN_FILE, birth.serialNumber, safe=True)
        
    logger.info("Legacy: Writing *sn_txt files...")
    util.writeFileLine(os.path.join(chipDirName, 'mide_sn.txt'), birth.serialNumber, safe=True)
    util.writeFileLine(os.path.join(chipDirName, 'accel_sn.txt'), accelSerialNum, safe=True)


#===============================================================================
#--- Calibration functions
#===============================================================================

def writeCalibrationLog(cal, save=True, writeCalNumber=True):
    """ Generate the data for the calibration 'product log' or 'error log' CSV
        file.
         
        Note: this function leaves out some of the less useful columns written
        by the original calibration script. The data is still available in the
        database.
        
        @param cal: Calibration data, as a `CalSession` instance.
        @param save: `True` to write to a file. If the calibration failed,
            the `CAL_BAD_LOG_FILE` (the error log) is written to, otherwise
            the file written is `CAL_LOG_FILE` (the 'good' calibration log).
        @param writeCalNumber:
        @return: The dictionary of log data.
    """
    session = cal.session
    birth = cal.birth
    device = birth.device
    
    caldate = str(session.date)
    mandate = str(birth.date)
    serialNumber = birth.serialNumberString
    hardwareVersion = cal.dev.hardwareVersion
    firmwareVersion = cal.dev.firmwareVersion
    productName = cal.dev.productName
    partNumber = cal.dev.partNumber

    sensors = list(device.getSensors(info__hasSerialNumber=True))
    accelSerialNum = ' '.join(str(x.serialNumber) for x in sensors)

    data = OrderedDict([("Cal #",                cal.sessionId),
                        ("Rev",                  None),
                        ("Cal Date",             caldate),
                        ("Serial #",             serialNumber),
                        ("Hardware",             hardwareVersion),
                        ("Firmware",             firmwareVersion),
                        ("Product Name",         productName),
                        ("Part Number",          partNumber),
                        ("Date of Manufacture",  mandate),
                        ("Ref Manufacturer",     None),
                        ("Ref Model #",          None),
                        ("Ref Serial #",         None),
                        ("NIST #",               None),
                        ("832M1 Serial #",       accelSerialNum),
                        ("Temp. (C)",            session.temperature),
                        ("Rel. Hum. (%)",        session.humidity),
                        ("Temp Comp. (%/C)",     None),
                        ("X-Axis",               cal.cal.x),
                        ("Y-Axis",               cal.cal.y),
                        ("Z-Axis",               cal.cal.z),
                        ("Pressure (Pa)",        cal.meanCalPress),
                        ("X-Axis (DC)",          cal.calLo.x),
                        ("Y-Axis (DC)",          cal.calLo.y),
                        ("Z-Axis (DC)",          cal.calLo.z),
                        ("X Offset (DC)",        cal.offsetsLo.x),
                        ("Y Offset (DC)",        cal.offsetsLo.y),
                        ("Z Offset (DC)",        cal.offsetsLo.z),
                        ("X Offset",             cal.offsets.x),
                        ("Y Offset",             cal.offsets.y),
                        ("Z Offset",             cal.offsets.z),
                        ])
    
    if cal.failed:
        data['Error Message'] = cal.failure
    
    if save:
        if cal.failed:
            saveTo = CAL_BAD_LOG_FILE
        else:
            saveTo = CAL_LOG_FILE
        
        newFile = not os.path.exists(saveTo)
        with open(saveTo, 'ab') as f:
            writer = csv.writer(f)
            if newFile:
                writer.writerow(data.keys())
            writer.writerow(data.values())

    if writeCalNumber and not cal.failed:
        logger.info("Legacy: Writing calibration number to master file: %s" 
                    % cal.sessionId)
        util.makeBackup(CAL_SN_FILE)
        util.writeFileLine(CAL_SN_FILE, cal.sessionId)

    return data
