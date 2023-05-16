'''
THIS IS TEMPORARY, A HACK TO WORK AROUND COMPATIBILITY WITH LAB 2.0, AND WILL
BE REMOVED LATER!

Tool for updating the firmware on a EFM32-based data recorder (GG0 or GG11).
The (old) serial bootloader version requires the EFM32 CDC USB Serial driver
for Windows.

@author: dstokes
'''

from collections import Sequence
import errno
from fnmatch import fnmatch
# from glob import glob
import io
import json
# import locale
import os.path
import struct
import time
import zipfile

import serial  # @UnusedImport
import serial.tools.list_ports


import xmodem

# import endaqlib as devices
from endaq import device

from ebmlite import loadSchema


# TODO: Better way of identifying valid devices, probably part of the class.
RECORDER_TYPES = [device.EndaqS, device.SlamStickC, device.SlamStickS,
                  device.SlamStickX]


from shared_logger import logger

#===============================================================================
#
#===============================================================================


def roundUp(x, increment):
    """ Round up to the next increment.
    """
    n = x//increment
    if x % increment != 0:
        n += 1
    return n * increment



def findItem(container, path):
    """ Retrieve an item in a nested dictionary, list, or combination of
        the two.

        @param container: A list or dictionary, possibly containing other
            lists/dictionaries.
        @param path: The 'path' of the item to find, with keys/indices
            delimited by a slash (``/``).
    """
    d = container
    for key in path.strip("\n\r\t /").split('/'):
        if isinstance(d, Sequence):
            key = int(key)
        d = d[key]
    return d


def changeItem(container, path, val):
    """ Replace an item in a nested dictionary, list, or combination of
        the two.

        @param container: A list or dictionary, possibly containing other
            lists/dictionaries.
        @param path: The 'path' of the item to find, with keys/indices
            delimited by a slash (``/``).
        @param val: The replacement value.
    """
    p, k = os.path.split(path.strip("\n\r\t /"))
    parent = findItem(container, p)
    if isinstance(parent, Sequence):
        k = int(k)
    parent[k] = val


def isNewer(v1, v2):
    """ Compare two sets of version numbers `(major, minor, micro, [build])`.
    """
    try:
        for v, u in zip(v1,v2):
            if v == u:
                continue
            else:
                return v > u
    except TypeError:
        return False

    # Numbers are equal, but the release version trumps the debug version
    # since the debug versions have the same number. The JSON will not be
    # updated until release.
    return False


#===============================================================================
#
#===============================================================================

class ValidationError(ValueError):
    """ Exception raised when the firmware package fails validation. Mainly
        provides an easy way to differentiate from other exceptions that can
        be raised, as several failure conditions natively raise the same type.
    """
    def __init__(self, msg, exception=None):
        super(ValidationError, self).__init__(msg)
        self.exception = exception


#===============================================================================
#
#===============================================================================

class FirmwareUpdater(object):
    """ Object to handle validating firmware files and uploading them to a
        recorder in bootloader mode. A cleaned up version of the code used
        in the birthing script.

        Firmware files are zips containing the firmware binary plus additional
        metadata.
    """

    PACKAGE_FORMAT_VERSION = 1

    MIN_FILE_SIZE = 1024
    PAGE_SIZE = 2048

    MAX_FW_SIZE = 507 * 1024
    MAX_BOOT_SIZE = 16 * 1024

    # Default serial communication parameters. Same as keyword arguments to
    # `serial.Serial`.
    SERIAL_PARAMS = {
        'baudrate':     115200,
        'parity':       'N',
        'bytesize':     8,
        'stopbits':     1,
        'timeout':      5.0,
        'writeTimeout': 2.0,
    }

    # Double-byte string: "MIDE Technology Corp". Should be found in firmware.
    MIDE_STRING = (b'M\x00I\x00D\x00E\x00 \x00T\x00e\x00c\x00h\x00n\x00'
                   b'o\x00l\x00o\x00g\x00y\x00 \x00C\x00o\x00r\x00p\x00')

    ZIPPW = None

    #===========================================================================
    #
    #===========================================================================

    def __init__(self, device=None, filename=None, strict=True, **kwargs):
        """ Constructor.

            @keyword device: The `device.base.Recorder` object to update.
            @keyword filename: The name of the ._FW file to use.
            @keyword strict: If `True`, perform more rigorous validation.
        """
        self.strict = strict
        self.device = device
        self.filename = filename
        self.password = kwargs.pop('password', self.ZIPPW) # allows None and ''

        self.info = None
        self.releaseNotes = None
        self.releaseNotesHtml = None
        self.fwBin = None
        self.bootBin = None
        self.signature = None
        self.lastResponse = None

        self.schema_mide = loadSchema('mide_ide.xml')
        self.schema_manifest = loadSchema('mide_manifest.xml')

#         if self.device is not None:
#             self.manifest = device.getManifest()
#             self.cal = device.getFactoryCalPolynomials()
#             self.props = device.getProperties()
#         else:
#             self.manifest = self.cal = self.props = None

        if filename is not None:
            self.openFirmwareFile()


    #===========================================================================
    #
    #===========================================================================

    def validateFirmware(self, fwBin, **kwargs):
        """ Perform basic firmware validation (file size, etc.).

            @param fwBin: The firmware binary's data.
            @keyword strict:  If `True`, use more stringent validation tests.
                Overrides the object's `strict` attribute if supplied.
        """
        strict = kwargs.get('strict', self.strict)

        fwLen = len(fwBin)
        if fwLen < self.MIN_FILE_SIZE:
            raise ValueError("Firmware binary too small (%d bytes)" % fwLen)
        elif fwLen > self.MAX_FW_SIZE:
            raise ValueError("Firmware binary too large (%d bytes)" % fwLen)

        # Sanity check: Make sure the binary contains the expected string
        if strict and self.MIDE_STRING not in fwBin:
            raise ValidationError("Could not verify firmware binary's origin")

        return True


    def validateBootloader(self, bootBin, **kwargs):
        """ Perform basic bootloader validation (file size, etc.).

            @param bootBin: The bootloader binary's data.
            @keyword strict:  If `True`, use more stringent validation tests.
                Overrides the object's `strict` attribute if supplied.
        """
        bootLen = len(bootBin)
        if bootLen < self.MIN_FILE_SIZE:
            raise ValueError("Bootloader binary too small (%d bytes)" % bootLen)
        elif bootLen > self.MAX_BOOT_SIZE:
            raise ValueError("Bootloader binary too large (%d bytes)" % bootLen)

        # FUTURE: Additional bootloader validation (raising `ValidationError`)?
        return True


    def validateUserpage(self, payload, **kwargs):
        """ Perform basic firmware validation (file size, etc.).

            @param payload: The userpage EBML data.
            @keyword strict:  If `True`, use more stringent validation tests.
                Overrides the object's `strict` attribute if supplied.
        """
        if len(payload) != self.PAGE_SIZE:
            raise ValueError("Userpage block was %d bytes; should be %d" % \
                             (len(payload), self.PAGE_SIZE))

        # FUTURE: Additional userpage validation (raising `ValidationError`)?
        return True


    def openFirmwareFile(self, **kwargs):
        """ Open a firmware package, and read and test its contents.

            @keyword filename: The name of the firmware package. Overrides
                the object's `filename` attribute if supplied.
            @keyword password: The firmware package's zip password (if any).
                Overrides the object's `password` attribute if supplied.
            @keyword strict:  If `True`, use more stringent validation tests.
                Overrides the object's `strict` attribute if supplied.

            @raise IOError: If the file doesn't exist, or other such issues
            @raise KeyError: If a file couldn't be found in the zip
            @raise RuntimeError: If the password is incorrect
            @raise ValidationError: If the `info.json` file can't be parsed,
                or the firmware binary fails validation.
            @raise ValueError: If the firmware or bootloader are an invalid
                size.
            @raise zipfile.BadZipfile: If the file isn't a zip
        """
        filename = kwargs.get('filename', self.filename)
        password = kwargs.get('password', self.password)
        strict = kwargs.get('strict', self.strict)

        bootBin = None
        sigBin = None

        with zipfile.ZipFile(filename, 'r') as fwzip:
            try:
                fwzip.testzip()
            except RuntimeError as err:
                raise ValidationError('File failed CRC check', err)

            self.contents = fwzip.namelist()

            try:
                info = json.loads(fwzip.read('fw_update.json', password))
            except ValueError as err:
                raise ValidationError('Could not read firmware info', err)

            packageFormat = info.get('package_format_version', 0)
            if packageFormat > self.PACKAGE_FORMAT_VERSION:
                raise ValueError("Can't read package format version %d" %
                                 packageFormat)

            appName = info.get('app_name', 'app.bin')
            fwBin = fwzip.read(appName, password)
            self.validateFirmware(fwBin, strict=strict)

            sigName = info.get('sig_name', filename+'.sig')
            if sigName in self.contents:
                with zipfile.ZipFile(self.filename, 'r') as fwzip:
                    sigBin = fwzip.read(sigName, password)
            else:
                logger.info("Could not find signature file %s, continuing." %
                            sigName)

            bootName = info.get('boot_name', 'boot.bin')
            if bootName in self.contents:
                bootBin = fwzip.read(bootName, password)
                self.validateBootloader(bootBin, strict=strict)

            if 'release_notes.txt' in self.contents:
                self.releaseNotes = fwzip.read('release_notes.txt', password)
            if 'release_notes.html' in self.contents:
                self.releaseNotesHtml = fwzip.read('release_notes.html', password)

        self.info = info
        self.fwBin = fwBin
        self.bootBin = bootBin
        self.signature = sigBin
        self.filename = filename


    def isNewerBootloader(self, vers):
        """ Is the update package's bootloader newer than the one installed?
        """
        try:
            bootVers = self.info.get('boot_version', None)
            if self.bootBin is None or not bootVers:
                return False
            return isNewer(map(int, bootVers.replace('m','.').split('.')),
                           map(int, vers.replace('m','.').split('.')))
        except TypeError:
            return False


    def checkCompatibility(self, device=None):
        """ Determine if the loaded firmware package is compatible with a
            recorder.

            @keyword device: A `Recorder` object. Defaults to the one specified
                when the `FirmwareUpdater` was instantiated.
        """
        device = device if device is not None else self.device

        if "mcu_type" in self.info:
            mcu = device.getInfo().get('McuType', '').upper()
            if not fnmatch(mcu, self.info['mcu_type']):
                raise ValidationError('Device MCU type %s not supported' %
                                      mcu)

        if not any((device.partNumber in d for d in self.contents)):
            raise ValidationError('Device type %s not supported' %
                                  device.partNumber)

        template = 'templates/%s/%d/*' % (self.device.partNumber,
                                          self.device.hardwareVersion)

        if not any((fnmatch(x, template) for x in self.contents)):
            raise ValidationError("Device hardware revision %d not supported" %
                                  self.device.hardwareVersion)


    def openRawFirmware(self, filename, boot=None, signature=None):
        """ Explicitly load a .bin file, skipping all the checks. For Mide use.
        """
        with open(filename, 'rb') as f:
            fwBin = f.read()

        if len(fwBin) < self.MIN_FILE_SIZE:
            raise ValueError("Firmware binary too small (%d bytes)" %
                             len(fwBin))

        if boot is not None:
            with open(boot, 'rb') as f:
                bootBin = f.read()
                if len(bootBin) < self.MIN_FILE_SIZE:
                    raise ValueError("Bootloader binary too small (%d bytes)" %
                                     len(bootBin))

        sigfile = signature or filename + ".sig"
        try:
            with open(sigfile, 'rb') as f:
                sigBin = f.read()
        except IOError as err:
            if err.errno != errno.ENOENT or signature is not None:
                raise
            sigBin = None

        self.fwBin = fwBin
        self.bootBin = bootBin
        self.signature = sigBin
        self.filename = filename


    #===========================================================================
    #
    #===========================================================================

    @classmethod
    def findBootloader(cls):
        """ Check available serial ports for a Slam Stick in bootloader mode.
            @return: The name of the port, or `None` if no device was found.
        """
        ports = [x for x in serial.tools.list_ports.comports() if 'USB VID:PID=2544:0003' in x[2]]
        if len(ports) > 0:
            return ports[0][0]


    def connect(self, portName, **kwargs):
        """ Attempt to establish a connection to a recorder in bootloader mode.
            Takes same keyword arguments as `serial.Serial`.
        """
        portParams = self.SERIAL_PARAMS.copy()
        portParams.update(kwargs)
        self.myPort = serial.Serial(portName, **portParams)
        self.modem = xmodem.XMODEM(self.myPort)

        self.flush()
        vers = self.getVersionAndId()
        if vers is None:
            raise IOError('Could not get ID data from bootloader!')

        self.flush()
        return vers


    def disconnect(self):
        """ Reset the device and close out the port.
        """
        self.myPort.write(b"r")  # reset
        self.myPort.close()


    #===============================================================================
    # Low-level bootloader communication stuff
    #===============================================================================

    def flush(self):
        """ Flush the serial port.
        """
        if self.myPort.inWaiting():
            return self.myPort.read(self.myPort.inWaiting())


    def sendCommand(self, command, response=b'Ready'):
        """ Send a command byte.

            @param command: The bootloader command character, one of
                `bcdilmnprtuv`. See SiLabs EFM32 Bootloader docs.
            @keyword response: The expected response. Can be a glob-style
                wildcard.
            @return: `True` if the response matches `response`, `False`
                if the command gets a different response.
        """
        if isinstance(command, str):
            command = bytes(command, "utf8")
        if isinstance(response, str):
            response = bytes(response, "utf8")

        self.myPort.write(command[0])  # make sure it is 1 character.
        self.myPort.readline() # sent character echo
        instring = self.myPort.readline()  # 'Ready' response
        self.lastResponse = instring
        if response in instring:  # or fnmatch(instring, response):
            return instring or True
        logger.error('Bootloader: Sent command %r, expected %r but received %r' % (command, response, instring))
        return False


    def _uploadData(self, command, payload, response=b'Ready'):
        """ Helper method to upload data.
            @see: `FirmwareUpdater.uploadData()`
        """
        self.flush()
        if self.sendCommand(command, response):
            time.sleep(1.0) # HACK: give bootloader some time to catch its breath?

            if not self.modem.send(io.BytesIO(payload)):
                logger.error("Bootloader: File upload failed!")
                return False
            logger.info("Bootloader: Data payload uploaded successfully.")
            return True

        return False


    def uploadData(self, command, payload, response=b'Ready', retries=5):
        """ Helper method to upload data. Will try repeatedly before failing.

            @param command: The bootloader command character.
            @param payload: The binary data to upload.
            @keyword response: The expected response from the bootloader.
            @keyword retries: The number of attempts to make.
        """
        ex = None
        for i in range(retries):
            try:
                return self._uploadData(command, payload)
            except serial.SerialTimeoutException as ex:
                logger.info('upload got serial timeout on try %d' % (i+1))
                time.sleep(1)
        if ex is not None:
            raise ex
        else:
            raise IOError("Upload failed!")


    def uploadBootloader(self, payload=None):
        """ Upload a new bootloader binary.

            @keyword payload: An alternative payload, to be used instead of the
                object's `bootBin` attribute.
        """
        if payload is None:
            payload = self.bootBin
        else:
            self.validateBootloader(payload, strict=self.strict)

        if not payload:
            logger.info('No bootloader binary, continuing...')
            return False

        return self.uploadData("d", payload)


    def uploadApp(self, payload=None):
        """ Upload new firmware.

            @keyword payload: An alternative payload, to be used instead of the
                object's `fwBin` attribute.
        """
        if payload is None:
            payload = self.fwBin
        else:
            self.validateFirmware(payload, strict=self.strict)

        if not payload:
            logger.info('No firmware binary, continuing...')
            return False

        return self.uploadData(b"u", payload)


    def uploadUserpage(self, payload=None):
        """ Upload the userpage data.

            @keyword payload: An alternative payload, to be used instead of the
                object's `payload` attribute.
        """
        if payload is None:
            payload = self.userpage
        else:
            self.validateUserpage(payload, strict=self.strict)

        if not payload:
            logger.info('No USERPAGE data, continuing...')
            return False

        return self.uploadData(b"t", payload)


    def uploadDebugLock(self):
        if not self.sendCommand(b"l", b"OK"):
            logger.error("Bootloader: Bad response when setting debug lock!")
            return False
        return True


    def finalize(self):
        """ Apply the finishing touches to the firmware/bootloader/userpage
            update.
        """
        # Bootloader serial connection doesn't need to do anything extra.
        self.disconnect()


    #===========================================================================
    #
    #===========================================================================

    @classmethod
    def makeUserpage(self, manifest, caldata, recprops=b''):
        """ Combine a binary Manifest, Calibration, and (optionally) Recorder
            Properties EBML into a unified, correctly formatted userpage block.

            USERPAGE memory map:
                0x0000 (2): Offset of manifest, LE
                0x0002 (2): Length of manifest, LE
                0x0004 (2): Offset of factory calibration, LE
                0x0006 (2): Length of factory calibration, LE
                0x0008 (2): Offset of recorder properties, LE
                0x000A (2): Length of recorder properties, LE
                0x000C ~ 0x000F: (RESERVED)
                0x0010: Data (Manifest, calibration, recorder properties)
                0x07FF: End of userpage data (2048 bytes total)
        """

        manSize = len(manifest)
        manOffset = 0x0010  # 16 byte offset from start
        calSize = len(caldata)
        calOffset =  manOffset + manSize  # 0x0400 # 1k offset from start
        propsSize = len(recprops)

        if propsSize > 0:
            propsOffset = calOffset + calSize
        else:
            propsOffset = 0

        data = struct.pack("<HHHHHH",
                           manOffset, manSize,
                           calOffset, calSize,
                           propsOffset, propsSize)
        data = bytearray(data.ljust(self.PAGE_SIZE, b'\x00'))
        data[manOffset:manOffset+manSize] = manifest
        data[calOffset:calOffset+calSize] = caldata
        data[propsOffset:propsOffset+propsSize] = recprops

        if len(data) != self.PAGE_SIZE:
            # Probably can never happen, but just in case...
            raise ValueError("Userpage block was %d bytes; should be %d" %
                             (len(data), self.PAGE_SIZE))

        return data


    def getVersionAndId(self):
        """ Get the bootloader version and the EFM32 chip UID.

            @return: A tuple containing the bootloader version and chip ID.
        """
        self.myPort.write(b"i")
        # Hack: FW echoes this character (with \n), then another \n, THEN the
        # string.
        for _i in range(3):
            instring = self.myPort.readline()
            if b"BOOTLOADER" in instring:
                break

        if b"BOOTLOADER" not in instring:
            return None

        # Grab any salient information from the bootloader string (mainly
        # CHIPID, but also bootloader version).
        # Example output: "BOOTLOADER version 1.01m2, Chip ID 2483670050B7D82F"
        (bootverstring, chipidstring) = instring.strip().split(b",")
        return (bootverstring.rsplit(b" ", 1)[-1],
                chipidstring.rsplit(b" ", 1)[-1])


    #===========================================================================
    #
    #===========================================================================

    def readTemplate(self, z, name, schema, **kwargs):
        """ Read an EBML template from a compressed file.

            @param z: The archive (zip) file to read.
            @param name: The name of the EBML file within the zip.
            @param schema: The EBML file's schema.
            @keyword password: The archive password (if any).
        """
        password = kwargs.pop('password', self.password)

        if name not in self.contents:
            return None

        try:
            return schema.loads(z.read(name, password)).dump()
        except (IOError, TypeError):
            logger.info("Error reading %s; probably okay, ignoring.")
            return {}


    def updateUserpage(self):
        """ Generate a new, updated set of USERPAGE data (manifest,
            calibration, and (optionally) userpage) by inserting this device's
            information into the templates.
        """
        templateBase = 'templates/%s/%d' % (self.device.partNumber,
                                            self.device.hardwareVersion)
        manTempName = "%s/manifest.template.ebml" % templateBase
        calTempName = "%s/cal.template.ebml" % templateBase
        propTempName = "%s/recprop.template.ebml" % templateBase

        with zipfile.ZipFile(self.filename, 'r') as fwzip:
            manTemplate = self.readTemplate(fwzip, manTempName,
                                            self.schema_manifest)
            calTemplate = self.readTemplate(fwzip, calTempName,
                                            self.schema_mide)
            propTemplate = self.readTemplate(fwzip, propTempName,
                                             self.schema_mide)

        if not all((manTemplate, calTemplate)):
            raise ValueError("Could not find template")

        # Collect sensor serial numbers (which are now 'multiple' elements)
        accelSerials = []
        manifest = self.device.getManifest()
        for s in manifest.get('AnalogSensorInfo', []):
            accelSerials.append(s.get('AnalogSensorSerialNumber', None))

        manChanges = [
            ('DeviceManifest/SystemInfo/SerialNumber', self.device.serialInt),
            ('DeviceManifest/SystemInfo/DateOfManufacture', self.device.birthday),
        ]
        propChanges = []

        # Add (analog) sensor serial numbers to change lists for the manifest
        # and recorder properties.
        for i, sn in enumerate(accelSerials):
            if sn is None:
                continue
            manChanges.append(('DeviceManifest/AnalogSensorInfo/%d/AnalogSensorSerialNumber' % i, sn))
            propChanges.append(('RecordingProperties/SensorList/Sensor/%d/TraceabilityData/SensorSerialNumber' %i, sn))


        # Apply manifest changes
        for k,v in manChanges:
            try:
                changeItem(manTemplate, k, v)
            except (KeyError, IndexError):
                logger.info("Missing manifest item %s, probably okay." %
                            os.path.basename(k))
                pass

        # Apply recorder properties changes
        if propTemplate is not None:
            for k,v in propChanges:
                try:
                    changeItem(propTemplate, k, v)
                except (KeyError, IndexError):
                    logger.info("Missing props item %s, probably okay." %
                                os.path.basename(k))
                    pass

        # Update transform channel IDs and references
        calTemplate = self.updateCalibration(calTemplate)

        # Build it.
        manData = {'DeviceManifest': manTemplate['DeviceManifest']}
        self.manifest = self.schema_manifest.encodes(manData)

        calData = {'CalibrationList': calTemplate['CalibrationList']}
        self.cal = self.schema_mide.encodes(calData)

        if propTemplate is not None:
            propData = {'RecordingProperties': propTemplate['RecordingProperties']}
            self.props = self.schema_mide.encodes(propData)
        else:
            self.props = ''

        self.userpage = self.makeUserpage(self.manifest, self.cal, self.props)


    def updateCalibration(self, calTemplate):
        """ Update the calibration template using the device's existing values.

            @param calTemplate: The calibration template, as nested
                lists/dicts. Note: the template will get modified in place!
        """
        # XXX: REVISE THIS! MERGE POLYNOMIALS FROM FILE!
        # Update transform channel IDs and references
        cal = self.device.getFactoryCalPolynomials()
        calEx = self.device.getFactoryCalExpiration()
        calDate = self.device.getFactoryCalDate()
        calSer = self.device.getFactoryCalSerial()

        try:
            polys = findItem(calTemplate, 'CalibrationList/BivariatePolynomial')
        except (KeyError, IndexError):
            polys = None

        if polys is not None:
            for p in polys:
                calId = p['CalID']
                if calId in cal:
                    p['PolynomialCoef'] = cal[calId].coefficients
                    p['CalReferenceValue'] = cal[calId].references[0]
                    p['BivariateCalReferenceValue'] = cal[calId].references[1]
        else:
            logger.info("No Bivariate polynomials; expected for SSC.")

        try:
            polys = findItem(calTemplate, 'CalibrationList/UnivariatePolynomial')
        except (KeyError, IndexError):
            polys = None

        if polys is not None:
            for p in polys:
                calId = p['CalID']
                if calId in cal:
                    p['PolynomialCoef'] = cal[calId].coefficients
                    p['CalReferenceValue'] = cal[calId].references[0]
        else:
            logger.warning("No Univariate polynomials: this should not happen!")

        if calEx:
            calTemplate['CalibrationList']['CalibrationSerialNumber'] = calSer
        if calDate:
            calTemplate['CalibrationList']['CalibrationDate'] = int(calDate)
        if calEx:
            calTemplate['CalibrationList']['CalibrationExpiry'] = int(calEx)

        return calTemplate


#===============================================================================
#
#===============================================================================

class FirmwareFileUpdater(FirmwareUpdater):
    """ Object to handle validating firmware files and uploading them to a
        recorder via files copied to the device.

        Firmware files are zips containing the firmware binary plus additional
        metadata.
    """

    def getSpace(self):
        """ Get the space required for the update and the device's free space,
            both rounded up to the device filesystem's block size.
        """
        blockSize = device.os_specific.getBlockSize(self.device.path)[0]

        needed = roundUp(self.PAGE_SIZE, blockSize)
        if self.bootBin:
            needed += roundUp(len(self.bootBin), blockSize)
        if self.fwBin:
            needed += roundUp(len(self.fwBin), blockSize)

        return needed, self.device.getFreeSpace()


    def isNewerBootloader(self, vers):
        """ Is the update package's bootloader newer than the one installed?
        """
        # There is currently no way to get the bootloader version without
        # entering the bootloader.
        return True


    @classmethod
    def findBootloader(self, first=False):
        """ Check attached recorders for a device capable of file-based update.
            EFMGG11 devices are excluded.

            @keyword first: If `True` and multiple recorders are found,
                return the first one. If `False` and multiple recorders are
                found, return None. To help prevent the wrong recorder being
                updated.
            @return: The recorder found (a `device.Recorder` subclass
                instance), or `None` if no device was found. Also returns
                `None` if more than one device was discovered and `first` is
                `False`.
        """
        devs = [d for d in device.getDevices() if (d.canCopyFirmware and
                            "EFM32GG11" not in d.getInfo().get('McuType', ''))]
        if devs and (len(devs) == 1 or first):
            return devs[0]


    def connect(self, dev=None, **kwargs):
        """ Do preparation for the firmware update.
        """

        if dev is not None:
            self.device = dev

        info = self.device.getInfo()
        bootRev = info.get('BootRev', None) # Not currently in info!
        chipId = info.get('UniqueChipID', None)

        if chipId is not None:
            chipId = "%16X" % chipId

        self.clean()

        return bootRev, chipId


    def clean(self):
        """ Remove any old update files.
        """
        logger.info('Cleaning up...')
        for f in (self.device._BOOTLOADER_UPDATE_FILE,
                  self.device._FW_UPDATE_FILE,
                  self.device._USERPAGE_UPDATE_FILE):

            filename = os.path.join(self.device.path, f)
            try:
                if os.path.exists(filename):
                    logger.info('Removing old file: %s' % filename)
                    os.remove(filename)
            except (IOError, WindowsError):
                logger.error('Could not remove file %s' % filename)
                return False

        return True


    def _writeFile(self, filename, content):
        """ Helper method to write to a file on the current device.
        """
        filename = os.path.join(self.device.path, filename)
        try:
            logger.info("Writing %s" % filename)
            with open(filename, 'wb') as f:
                f.write(content)
            return True
        except (IOError, WindowsError) as err:
            logger.error(str(err))
            return False


    def uploadBootloader(self, payload=None):
        """ Install a new bootloader binary via an update file (specified in
            the device's `BOOTLOADER_UPDATE_FILE`).

            @keyword payload: An alternative payload, to be used instead of the
                object's `bootBin` attribute.
        """
        if payload is None:
            payload = self.bootBin
        else:
            self.validateBootloader(payload)

        if not payload:
            logger.info('No bootloader binary, continuing...')
            return False

        return self._writeFile(self.device._BOOTLOADER_UPDATE_FILE, payload)


    def uploadApp(self, payload=None):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`).

            @keyword payload: An alternative payload, to be used instead of the
                object's `fwBin` attribute.
        """
        if payload is None:
            payload = self.fwBin
        else:
            self.validateFirmware(payload)

        if not payload:
            logger.info('No firmware binary, continuing...')
            return False

        # HACK: The S3-D16 are the format of the S-series but are GG0.
        #  Fix after refactoring to Py3 and using endaqlib
        if not self.device.getInfo('McuType', '').startswith("EFM32GG11"):
            self.device._FW_UPDATE_FILE = os.path.join("SYSTEM", 'firmware.bin')

        return self._writeFile(self.device._FW_UPDATE_FILE, payload)


    def uploadUserpage(self, payload=None):
        """ Install new userpage data via an update file (specified in the
            device's `USERPAGE_UPDATE_FILE`).

            @keyword payload: An alternative payload, to be used instead of the
                object's `userpage` attribute.
        """
        if payload is None:
            payload = self.userpage
        else:
            self.validateUserpage(payload)

        if not payload:
            logger.info('No USERPAGE data, continuing...')
            return False

        return self._writeFile(self.device._USERPAGE_UPDATE_FILE, payload)


    def finalize(self):
        """ Apply the finishing touches to the firmware/bootloader/userpage
            update.
        """
        logger.info("Sending 'update all' command...")
        with open(self.device.commandFile, 'wb') as f:
            f.write(b'ua')


    def disconnect(self):
        """ Reset the device.
        """
        # Doesn't actually reset, since the device isn't in bootloader mode.
        self.clean()


#===============================================================================
#
#===============================================================================

class FirmwareFileUpdaterGG11(FirmwareFileUpdater):
    """ Subclass of `FirmwareFileUpdater` with special provisions for the new,
        GG11-based devices (e.g. S1/S2/S3/S4 series).
    """

    def validateFirmware(self, fwBin, **kwargs):
        val = super(FirmwareFileUpdaterGG11, self).validateFirmware(fwBin,
                                                                strict=False)
        # Additional validation could/should happen here.
        return val


    @classmethod
    def findBootloader(cls, first=False):
        """ Check attached recorders for a GG11-based device capable of
            file-based update.

            @keyword first: If `True` and multiple recorders are found,
                return the first one. If `False` and multiple recorders are
                found, return None. To help prevent the wrong recorder being
                updated.
            @return: The recorder found (a `device.Recorder` subclass
                instance), or `None` if no device was found. Also returns
                `None` if more than one device was discovered and `first` is
                `False`.
        """
        devs = [d for d in device.getDevices() if (d.canCopyFirmware and
                            "EFM32GG11" in d.getInfo().get('McuType', ''))]
        if devs and (len(devs) == 1 or first):
            return devs[0]


    def uploadBootloader(self, payload=None):
        """ Install a new bootloader binary via an update file. Not applicable
            to GG11 devices.
        """
        logger.warning("%s does not support uploadBootloader(), ignoring." %
                       type(self).__name__)
        return False


    def uploadApp(self, payload=None, signature=None):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`).

            @keyword payload: An alternative payload, to be used instead of the
                object's `fwBin` attribute.
        """
        signature = signature or self.signature

        # Set a flag if the firmware was updated; changes what finalize() does
        sigfile = self.device._FW_UPDATE_FILE + ".sig"
        uploaded = (super(FirmwareFileUpdaterGG11, self).uploadApp(payload)
                    and self._writeFile(sigfile, signature))

        return uploaded


#     def uploadAppFile(self, filename, signature=None):
#         """ Install new firmware via an update file (specified in the device's
#             `FW_UPDATE_FILE`). Overrides data in the object's `fwBin`
#             attribute. Also uploads the "signature" file, which is expected to
#             be the same name plus ".sig".
#
#             @param filename: The name of the binary file to upload.
#             @keyword signature: The name of the 'signature' file. Defaults to
#                 the same as `filename`, plus `".sig"`.
#         """
#         signature = signature or (filename + ".sig")
#
#         payload = readFile(filename)
#         sig = readFile(signature)
#
#         uploaded = (self.uploadApp(payload) and
#                     self._writeFile(self.device._FW_UPDATE_FILE+".sig", sig))
#         return uploaded


    def finalize(self):
        """ Apply the finishing touches to the firmware/userpage
            update.
        """
        logger.info("Sending 'secure update all' command ('sa')...")
        with open(self.device.commandFile, 'wb') as f:
            f.write(b'sa')



class FirmwareFileUpdaterSTM32(FirmwareFileUpdaterGG11):
    """ Subclass of `FirmwareFileUpdaterGG11` with special provisions for the
        new, STM32-based devices.
    """

    @classmethod
    def findBootloader(cls, first=False):
        """ Check attached recorders for a STM32-based device capable of
            file-based update.

            @keyword first: If `True` and multiple recorders are found,
                return the first one. If `False` and multiple recorders are
                found, return None. To help prevent the wrong recorder being
                updated.
            @return: The recorder found (a `device.Recorder` subclass
                instance), or `None` if no device was found. Also returns
                `None` if more than one device was discovered and `first` is
                `False`.
        """
        devs = [d for d in device.getDevices() if (d.canCopyFirmware and
                            "STM32" in d.getInfo('McuType', ''))]
        if devs and (len(devs) == 1 or first):
            return devs[0]
