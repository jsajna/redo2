"""
Database-backed calibration script!

@todo: Get rid of old 'high' and 'low' accelerometer stuff, replace with
    'primary' and 'secondary'. This was originally done this way because the
    digital accelerometer always used to be lower g than the analog one, but
    in almost half of the new devices, that's not the case.

@todo: Clean this up! It has a lot of code debt, specifically how the 'high'
    and 'low' accelerometers are handled separately. It should really just
    handle any number of accelerometers the same way, using the same code.
@todo: Get rid of how the 'low' accelerometer becomes the 'high' one if it is
    the only accelerometer. It was a hack put in when the 'low' accelerometer
    was originally added. The previous TODO probably makes this moot.
"""

from datetime import datetime
from fnmatch import fnmatch
import getpass
from numbers import Number
import os.path
import sys
import time
import plotly.graph_objs as go
import numpy as np
from scipy.signal import butter, sosfilt

# from . import paths  # Just importing should set things
# from . import __version__
from shared_logger import logger
from idelib.importer import importFile
from shakeprofile import ShakeProfile, exp_order, order_10g, order_10g_4g

import endaq.device as ed
import endaq.ide as ei

import util
from util import XYZ
#===============================================================================
#--- Django setup
#===============================================================================

os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

# import django
import django.db
from django.db.utils import InterfaceError, OperationalError
django.setup()

# My Django components
# NOTE: Django import paths are weird. Get `products.models` from Django itself.
# from ProductDatabase.products import models
from django.apps import apps
models = apps.get_app_config('products').models_module
from math import ceil

# ===============================================================================
#
# ===============================================================================

# The current user (for logging in database)
USER = getpass.getuser()

# Default humidity. Used if the recorder didn't record humidity, or if the
# last calibration had no humidity recorded.
DEFAULT_HUMIDITY = 22.3


# schema_mide = loadSchema('mide_ide.xml')

# ===============================================================================
#
# ===============================================================================


def reconnect():
    """ Test the database connection; disconnect if timed out, to force a
        new connection. This feels like a hack, though.
    """
    try:
        # Arbitrary simple query to 'ping' the database connection
        models.Product.objects.count()

    except (InterfaceError, OperationalError):
        django.db.connection.close()

        # Try again, just in case there was some other InterfaceError that
        # closing the connection didn't fix.
        models.Product.objects.count()


def get_center_indexes(start, end, range):
    total = end - start
    if end <= start:
        raise(ValueError(f"End index {end} not after start index {start}"))

    if range > total:
        print("Using approx. middle third")
        return get_center_indexes(start, end, round(total / 3))
    else:
        start = ceil((total / 2) - (range / 2)) + start
        return start, start + range - 1


#===============================================================================
#
#===============================================================================


class CalibrationError(ValueError):
    """ Exception raised when some part of calibration fails.
    """
    def __init__(self, *args):
        if args:
            self.message = str(args[0])
        super(CalibrationError, self).__init__(*args)


class CalibrationWarning(CalibrationError, UserWarning):
    """ Exception raised when some calibration function fails non-fatally.
    """


#==============================================================================
#
#==============================================================================

def _print(*args, **kwargs):
    msg = ' '.join(str(arg) for arg in args)
    if kwargs.get('newline', False):
        msg = f"{msg}\n"
    else:
        msg = f"{msg} "
    sys.stdout.write(msg)
    sys.stdout.flush()


def _println(*args):
    _print(*args, newline=True)



class DeviceLibrary(object):

    CAL_IDS = {
        # Analog primary
        (8, 0): 1,
        (8, 1): 2,
        (8, 2): 3,
        # S1/S2 Digital primary
        (80, 0): 81,
        (80, 1): 82,
        (80, 2): 83,
        # SSX/SSS Digital secondary
        (32, 0): 33,
        (32, 1): 34,
        (32, 2): 35,
    }

    # XXX: THIS IS ALL GETTING REWRITTEN USING NEW STUFF IN  `endaq.device`!
    # Known channel/subchannel IDs of pressure sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_PRESSURE_CHANNELS = ((36, 0), (59, 0))

    # Known channel/subchannel IDs of temperature sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_TEMP_CHANNELS = ((36, 1), (59, 1))

    # Known channel/subchannel IDs of humidity sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_HUMIDITY_CHANNELS = ((59, 2),)

    # The channel IDs used by any accelerometer we might calibrate.
    KNOWN_HI_ACCEL_CHANNELS = (0, 8, 80)
    KNOWN_LO_ACCEL_CHANNELS = (32, 80)

    # Mapping of _analyze() kwargs for each accelerometer channel ID, so
    # everything can be automated (instead of explicitly doing lo/hi-G).
    # FOR FUTURE USE. Currently, hardcoded arguments used.
    # XXX: Is this really necessary? Can it be calculated from sample rate?
    ANALYSIS_SETTINGS = {8: dict(),
                         32: dict(thres=6, start=1000, length=1000)}

    def __init__(self, calibrator, dev, pn=None, mcu=None, skipTime=0.5, acOnly=False, dcOnly=False):
        from devicedata import get_device

        self.calibrator = calibrator
        self.dev = dev

        if not pn and (devpn := dev.partNumber):
            pn = str(devpn).upper()
        if not mcu and (devmcu := dev.mcuType):
            mcu = str(devmcu).upper()
        self.partNumber = pn
        self.mcu = mcu

        devdata = get_device(self.partNumber, self.mcu)
        print(f"part number is {self.partNumber}, mcu is {self.mcu}")
        print(f"devdata found is {devdata.name}, mcu is {devdata.mcu}")
        self.gravities = XYZ(None)
        self.axesFlips = devdata.flips
        self.ranges = devdata.ranges
        self.skipTime = skipTime
        self.accelIds = []
        self.hiAccelId = None
        self.loAccelId = None
        self.acOnly = acOnly
        self.dcOnly = dcOnly

    def setAccelIds(self, calFiles):
        common_keys_list = [key for key in calFiles[0].accels if key in calFiles[1].accels and key in calFiles[2].accels]
        self.accelIds = common_keys_list

    def setFlips(self, calFiles):
        for calFile in calFiles:
            for accel, flip in self.axesFlips.items():
                print(flip, " flip for ", accel)
                calFile.accels[accel].gain *= flip[calFile.shaken]

    def setHiLoAccels(self, doc, hiExclude=None, loExclude=None):
        self.hiAccelId = self.setHighAccelerometer(doc, hiExclude)
        self.loAccelId = self.setLowAccelerometer(doc, loExclude)
        """
        self.hiAccelId = hiId or loId
        self.loAccelId = loId or hiId
        if self.hiAccelId == self.loAccelId:
            _println("High and low accels are same")
        _println()
        """
        return self.hiAccelId, self.loAccelId


    def setHighAccelerometer(self, doc, exclude=None):
        """ Get the high-G accelerometer channel.

            @keyword exclude: A list of channel IDs to ignore.
        """
        exclude = exclude or []

        if self.dcOnly or self.partNumber.startswith('LOG-0003'):
            return None

        pn = str(self.dev.partNumber).upper()
        if fnmatch(pn, "[SW]?-D*") and not fnmatch(pn, "S?-D*D*"):
            return None

        ch = self._getAccel(self.KNOWN_HI_ACCEL_CHANNELS, doc, exclude)
        if ch is not None:
            self.hiAccelId = ch.id
            return ch.id

        raise CalibrationError("Primary accelerometer channel not where expected!",
                               doc)

    def setLowAccelerometer(self, doc, exclude=None):
        """ Get the high-G accelerometer channel.

            @keyword exclude: A list of channel IDs to ignore.
        """
        exclude = exclude or []

        # Handle old SSCs. The following len(self.doc.channels) == 2: check skips old SSC units
        # Wish I understood the logic better here ~PJS
        if self.dev.partNumber.startswith('LOG-0003'):
            ch = self._getAccel(self.KNOWN_LO_ACCEL_CHANNELS, doc, exclude)
            if ch is not None:
                self.loAccelId = ch.id
                return ch.id

        if self.acOnly or len(doc.channels) == 2:
            return None

        ch = self._getAccel(self.KNOWN_LO_ACCEL_CHANNELS, doc, exclude)
        if ch is not None:
            self.loAccelId = ch.id
            return ch.id

        raise CalibrationError("Secondary accelerometer channel not where expected!",
                               doc)

    def _getAccel(self, channelIds, doc, exclude=None):
        """ Get the first accelerometer that appears in the given list of IDs.

            @param channelIds: A list of accelerometer channel IDs.
            @keyword exclude: A list of channel IDs to ignore.
        """
        # TODO: Actually check sensor descriptions to get channel ID
        exclude = exclude or []
        for chid in set(channelIds).difference(exclude):
            if chid in doc.channels:
                return doc.channels[chid]

    def getGravities(self, calFiles):
        """ Get the gravity directions of the data provided.

            @parameter dev: Device being looked at, so we know the accelerometers and inversions
            @parameter calFiles: x,y,z calibration data. main and low accelerometers
            @return: XYZ of the direction of gravity in each file
        """
        # On Mini, use the 40 or 8 g accelerometer. Otherwise use the secondary (which is always 40g)
        if self.partNumber.startswith(('S1', 'S2')):
            activeFlips = self.axesFlips[self.hiAccelId]
            activeMeans = [calFiles[i].accels[self.hiAccelId].means for i in range(3)]
        else:
            if not self.loAccelId:
                print("No DC accelerometer found!")
                self.gravities = XYZ([1, 1, 1])
                return
            activeFlips = self.axesFlips[self.loAccelId]
            activeMeans = [calFiles[i].accels[self.loAccelId].means for i in range(3)]
        measurement = [activeFlips[i] * activeMeans[i] for i in range(3)]
        gravity = [m / abs(m) for m in measurement]
        print("GRAVITU OS ", gravity)
        if gravity[2] != 1:
            raise CalibrationError("Got the wrong gravity vector on Z for some dumb reason")

        self.gravities = XYZ(gravity)

    def getAxisFlips(self, calAxes=None, calAxesLo=None):
        """ Get the inverted axes specific to the device type.

            @param dev: The recording device
            @param calAxes: A set of three values, -1 or 1, indicating any
                flipped axes on the primary accelerometer. Overrides the axis
                flips for the specific device being calibrated.
            @param calAxes: A set of three values, -1 or 1, indicating any
                flipped axes on the secondary accelerometer. Overrides the axis
                flips for the specific device being calibrated.
            @param calAxesLo
            @return: A tuple containing two `XYZ` objects: the flips for each
                accelerometer.
        """
        # FUTURE: Less hardcoding.

        print(f"Calibrating as {self.partNumber} with {self.mcu} MCU")
        if self.mcu.startswith('STM32'):
            # Special case: SlamStick C replacement for NAVAIR, etc.
            if self.partNumber == "S3-D16":
                calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
                calAxes = calAxes or calAxesLo  # Does not really exist for this device
                return XYZ(calAxes), XYZ(calAxesLo)

            # Analog accelerometer orientation varies by model
            if fnmatch(self.partNumber, "S?-E*"):
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            elif fnmatch(self.partNumber, "S?-R*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(self.partNumber, "W?-E*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(self.partNumber, "W?-R*"):
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            else:
                if not calAxes and calAxesLo:
                    logger.warning(f"Using default axis flips for unknown STM32 device type {self.partNumber!r}")
                calAxes = calAxes or (1, 1, -1)  # Channel 8

            # ADXL357 is the same for all STM32 S and W (as of HwRev 2.0.0 - 2.0.1)
            calAxesLo = calAxesLo or (-1, -1, 1)  # Channel 80

        elif self.partNumber.startswith(('S1', 'S2')):
            # "Mini" with 2 digital accelerometers
            calAxes = calAxes or (-1, -1, 1)  # Channel 80
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif fnmatch(self.partNumber, "S?-D16") or fnmatch(self.partNumber, "S?-D200"):
            # One digital accelerometer, old hardware (e.g., SSC equivalents for NAVAIR)
            calAxes = calAxes or (1, 1, -1)  # Does not really exist for this device
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif self.partNumber.startswith(('S3', 'S4', 'S5', 'S6', 'W5', 'W8')):
            if "-R" in self.partNumber:  # Piezoresistive device has axis flips
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif '-E' in self.partNumber:
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            else:
                calAxes = calAxes or (-1, -1, 1)  # Channel 80 (the 'main' accelerometer for an Sx-D40)
            calAxesLo = calAxesLo or (-1, -1, 1)  # Channel 80
        elif self.partNumber.startswith('LOG-0004'):
            calAxes = calAxes or (-1, 1, -1)  # Channel 8
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif self.partNumber.startswith('LOG-0002'):
            calAxes = calAxes or (1, 1, -1)  # Channel 8
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        else:
            if not calAxes and calAxesLo:
                logger.warning(f"Could not get axis flips for device type {self.partNumber!r}")
            calAxes = calAxes or (1, 1, 1)
            calAxesLo = calAxesLo or (1, 1, 1)

        return XYZ(calAxes), XYZ(calAxesLo)

class AccelerometerData(object):

    def __init__(self, doc, accel, shaken, skipTime=0.5):
        self.doc = doc
        self.accel = accel
        self.accelRange = None
        self.axisIds= self.getAxisIds(accel)
        self.subchannel = None
        self.shake = None  # figure
        self.shaken = shaken
        self.gain = None
        self.means = None
        self.offset = None
        self.referenceRMS = None
        self.rms = None
        self.trans = None
        self.sampRate = None
        self.skipTime = skipTime
        self.skipSamples = None
        self.shakeProfile = None

    def organizeShakeProfile(self, shakeProfile):

        # Turn off existing per-channel calibration (if any)
        for c in self.accel.children:
            c.setTransform(None)
        self.accel.updateTransforms()
        self.subchannel = self.accel.subchannels[self.shaken]

        a = self.subchannel.getSession()
        a.removeMean = False
        self.sampRate = a.getSampleRate()

        shakeProfile.adjustProfile(self.subchannel)  # set up correct times of the shakes and delays
        start = a.getInterval()[0] * 1e-6
        shakeProfile.shiftIndices(self.sampRate, start)  # make indices refer to correct time
        self.skipSamples = int(self.skipTime * self.sampRate)
        shakeProfile.shave(self.skipSamples)  # do not consider the first and last n=skipSamples points

        lowAccelRange = self.is8gOrLess(self.accel)
        if lowAccelRange:  # TODO: make this use the shake with an amp. less than the accelRange
            for shake in shakeProfile.shakes:
                if shake.amp <= 4:
                    self.shake = shake
                    break
        else:

            for shake in shakeProfile.shakes:
                if shake.amp > 4:
                    self.shake = shake
                    break

        print(f"using {self.shake.amp}g shake")
        self.shakeProfile = shakeProfile


    def is8gOrLess(self, channel):
        """ Was the given channel recorded by a sensor that rails at 8g?
            Used to avoid calibrating against railed data.
        """
        try:
            # XXX:HACK:TODO: use better method to get sensor range, maybe
            # the parent channel's calibration coefficients.
            return "ADXL355" in self._getSensorName(channel)
        except (AttributeError, TypeError):
            raise
            # return False

    def calcTrans(self, gains):
        nonShaken = [0, 1, 2]
        nonShaken.remove(self.shaken)

        a_cross = self.rms[nonShaken[0]] * gains[nonShaken[0]]
        b_cross = self.rms[nonShaken[1]] * gains[nonShaken[1]]
        c_ampl = self.rms[self.shaken] * gains[self.shaken]
        Stab = np.sqrt((a_cross ** 2) + (b_cross ** 2))
        Stb = 100 * (Stab / c_ampl)
        self.trans = Stb
        return Stb

    def calcDataRegions(self, length=5000):
        a = self.accel.getSession()
        a.removeMean = False
        if self.sampRate < 1000:
            raise CalibrationError(
                f"Channel {self.accel.id} ({self.accel.name}) had a low sample rate: {self.sampRate} Hz",
                self.doc, self.accel)

        data = np.flip(np.rot90(a[:]), axis=0)
        _print(f"\t{len(data)} samples\n")
        hp_data = np.copy(data)
        times = data[:, 0] * .000001
        # apply highpass=10 filter to the data
        for i in range(1, min(4, hp_data.shape[1])):
            hp_data[:, i] = self.highpassFilter(hp_data[:, i], 10, self.sampRate, 'high')

        data = data[self.skipSamples: -self.skipSamples]
        hp_data = hp_data[self.skipSamples:-self.skipSamples]

        return data, hp_data

    def calcRMSXYZ(self, hp_data, length=5000):

        def calculateRMS(data, axis=None):
            """ Compute the root mean square of data in a numpy array.
                    """
            return np.sqrt(np.mean(data ** 2, axis=axis))

        _println(f"\tShake Start Index: {self.shake.startIndex}.")
        _println(f"\tShake End Index: {self.shake.endIndex}.")

        shakeRegionStart, shakeRegionEnd = get_center_indexes(self.shake.startIndex, self.shake.endIndex, length)
        accel = XYZ(hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.x + 1],
                    hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.y + 1],
                    hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.z + 1])

        self.rms = XYZ(calculateRMS(accel.x),
                      calculateRMS(accel.y),
                      calculateRMS(accel.z))
        _println(f"\t{self.rms = !r}")

    def calcGain(self):
        referenceRMS = self.shake.amp * (2 ** .5) / 2
        self.gain = referenceRMS / self.rms[self.shaken]

    def calcQuietMean(self, data):
        """ find the mean of the quietest area (used for offset)
                    @param sampRate: sample rate of channel
                    @param data: 1d array of signal values for the shaken subchannel
                    @param lowpass: the cutoff frequency for the lowpass filter
                """
        def getMeans(data, start, span):
            """ Calculate offsets (means).

                        @param data: time + shaken axis data for analysis
                        @param start: start index of span for calculating
                        @param span: size of slice to calculate
                        @param sampRate: sample rate of data, used in filtering
                        @param lowpass: filter frequency, 0 for no filtering

                        @return: the average value of the region given
                    """
            avg = data[start:start + span].mean()
            return avg

        data = data[:, self.shaken+1]
        offsetCalcSpan = 2 if data.shape[0] / self.sampRate > 12 else 0.5  # originally set to 1
        searchOverlap = 0.8
        offsetCalcSpan = int(offsetCalcSpan * self.sampRate)

        quietestStart = self.findQuietTime(data, self.shakeProfile.delays, offsetCalcSpan, searchOverlap=searchOverlap)
        means = getMeans(data, quietestStart, offsetCalcSpan)
        self.means = means

    def calcOffset(self, gravities):
        gm = self.gain * self.means
        self.offset = gravities[self.shaken] - gm

    @staticmethod
    def highpassFilter(data, cutoff, fs, btype, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        sos = butter(order, normal_cutoff, btype=btype, analog=False, output='sos')
        y = sosfilt(sos, data)
        return y

    def _getSensorName(self, channel):
        return channel[0].sensor.name.upper()

    def _getSensorRange(self, channel):
        pass

    def getAxisIds(self, channel):
        """ Get the IDs for the accelerometer X, Y, and Z subchannels. The
            order differs on old revisions of SSX's analog channel.

            @param channel: An accelerometer `dataset.Channel` instance.
            @return: An `XYZ` containing the correct subchannel IDs.
        """
        ids = XYZ(-1, -1, -1)
        for subc in channel.subchannels:
            errmsg = "Found multiple %%s axes: %%r and %r" % subc.id
            if 'X' in subc.name:
                if ids.x == -1:
                    ids.x = subc.id
                else:
                    raise KeyError(errmsg % ('X', ids.x))
            elif 'Y' in subc.name:
                if ids.y == -1:
                    ids.y = subc.id
                else:
                    raise KeyError(errmsg % ('Y', ids.y))
            elif 'Z' in subc.name:
                if ids.z == -1:
                    ids.z = subc.id
                else:
                    raise KeyError(errmsg % ('Z', ids.z))
        if -1 in ids:
            raise CalibrationError("Channel did not contain X, Y, and Z subchannels!",
                                   self.doc, channel)
        return ids

    def findQuietTime(self, data, allDelays, span, searchOverlap=0.5):
        """ find the region that is the quietest out of the delays given
            @param data: 1d data for the shaken subchannel
            @param allDelays: list of the Delay objects in the shakeProfile
            @param span: int size of the area to be grabbed
            @param searchOverlap: percent to overlap scanning of sections
            @return: int for the index where the quietest region starts """
        minStandardDeviation = None
        bestStartIndex = None
        _print(f"\tFinding quiet times of shaken axis {'XYZ'[self.shaken]}: ")

        for delay in allDelays:
            if delay.endIndex - delay.startIndex > span:
                if searchOverlap > 0.9:  # Too large an overlap would mean we move backwards
                    searchOverlap = 0.9
                for startIndex in range(delay.startIndex, min(delay.endIndex, data.shape[0]),
                                        int(span * (1 - searchOverlap))):
                    if startIndex + span < data.shape[0]:
                        thisStandardDeviation = np.std(data[startIndex:startIndex + span])
                        if minStandardDeviation is None or thisStandardDeviation < minStandardDeviation:
                            minStandardDeviation = thisStandardDeviation
                            bestStartIndex = startIndex
            # print(f"Index {startIndex}, StdDev {thisStandardDeviation:0.4f}")
        print(f"Selecting index {bestStartIndex} ({minStandardDeviation=:0.4f})")
        return bestStartIndex


class Calibrator(object):

    def __init__(self, dev=None, sessionId=None, calHumidity=None, certificate=None, reference=None,
                 skipTime=0.5, user=USER, workDir=None, shakeOrder=exp_order):
        """ Constructor """
        self.dev = dev
        self.user = user
        self.workDir = workDir
        self.basenames = None
        self.calTimestamp = None
        self.failure = None
        self.birth = None
        self.certificate = certificate
        self.reference = reference
        self.session = None
        self.sessionId = sessionId
        self.cancelled = None
        self.calDir = None
        self.skipTime = skipTime
        self.shakeOrder = exp_order

        self.hasHiAccel = None
        self.hasLoAccel = None
        self.deviceLibrary = None
        self.calFiles = XYZ(None)

        self.allGains = {}
        self.cal = XYZ(None, None, None)
        self.calLo = XYZ(None, None, None)

        self.allOffsets = {}
        self.offsets = XYZ(None, None, None)
        self.offsetsLo = XYZ(None, None, None)

        self.allTrans = {}
        self.trans = XYZ(None, None, None)
        self.transLo = XYZ(None, None, None)

        self.meanCalHumid = calHumidity
        self.meanCalPress = None
        self.meanCalTemp = None

    def calculate(self, filenames, pn=None, mcu=None):
        self.calTimestamp = int(time.mktime(time.gmtime()))

        if filenames is None:
            if self.dev is None:
                raise ValueError("No recorder or recording files specified!")
            filenames = self.getFiles()

        firstDoc = ei.get_doc(filenames[0])

        if self.dev is None:
            self.dev = ed.fromRecording(firstDoc)


        self.deviceLibrary = DeviceLibrary(self, self.dev, pn, mcu)
        hiId, loId = self.deviceLibrary.setHiLoAccels(firstDoc)

        calFiles = [AccelCalFile(f, hiId, loId, self.shakeOrder, skipTime=self.skipTime)
                    for f in filenames]
        self.deviceLibrary.setAccelIds(calFiles)
        for calFile in calFiles:
            _print(f"\nWorking on Gains and Means of {calFile.basename}...\n")
            calFile.getGainsAndMeans()

        self.deviceLibrary.setFlips(calFiles)
        self.sortCalFiles(calFiles)
        self.deviceLibrary.getGravities(self.calFiles)

        for calFile in calFiles:
            calFile.getOffsets(self.deviceLibrary.gravities)
            calFile.setCalTempPressHumid()

        for accelId in self.deviceLibrary.accelIds:
            self.allGains[accelId] = XYZ(self.calFiles.x.accels[accelId].gain,
                                         self.calFiles.y.accels[accelId].gain,
                                         self.calFiles.z.accels[accelId].gain)
            self.allOffsets[accelId] = XYZ(self.calFiles.x.accels[accelId].offset,
                                         self.calFiles.y.accels[accelId].offset,
                                         self.calFiles.z.accels[accelId].offset)

        self.allTrans = {}
        for id in self.deviceLibrary.accelIds:
            sYZ  = self.calFiles.x.accels[id].calcTrans(self.allGains[id])
            sXZ = self.calFiles.y.accels[id].calcTrans(self.allGains[id])
            sXY = self.calFiles.z.accels[id].calcTrans(self.allGains[id])
            self.allTrans[id] = XYZ(sXY, sYZ, sXZ)

        self.assignHiLoThings()
        self.meanCalTemp = np.mean([cal.cal_temp for cal in self.calFiles])
        self.meanCalPress = np.mean([cal.cal_press for cal in self.calFiles])

        if all(cal.cal_humid for cal in self.calFiles):
            self.meanCalHumid = np.mean([cal.cal_humid for cal in self.calFiles])

        print(self)


    def updateDatabase(self, calHi=True, calLo=True, transHi=True, transLo=True,
                       **kwargs):
        """ Create a new `models.CalSession` record and all its associated
            children (axes, transverse, etc.).

            @param calHi: If `True`, create `CalAxis` records for the
                primary accelerometer.
            @param calLo: If `True`, create `CalAxis` records for the
                secondary accelerometer.
            @param transHi: If `True`, create `CalTransverse` records for
                the primary accelerometer.
            @param transLo: If `True`, create `CalTransverse` records for
                the secondary accelerometer.

            @keyword sessionId: The calibration session ID. Overrides any
                specified at `Calibrator` creation time. `None` will create
                a new ID.
            @keyword humidity: The calibration humidity, if not recorded.
            @keyword reference: The session's reference accelerometer.
                Overrides any specified at `Calibrator` creation time.
                Its type is `products.models.CalReference`.
            @keyword certificate: The session's calibration certificate.
                Overrides any specified at `Calibrator` creation time.
                Its type is `products.models.CalCertificate`.

            Additional keyword arguments (e.g. `notes`) are passed to the
            new `CalSession` constructor.
        """
        self.birth = models.Birth.objects.filter(serialNumber=self.dev.serialInt
                                                 ).latest('date')

        self.sessionId = kwargs.pop('sessionId', self.sessionId)
        newId = self.sessionId is None
        if newId:
            self.sessionId = models.newSerialNumber("Calibration")

        if kwargs.setdefault('certificate', self.certificate) is None:
            self.certificate = self.getCertificateRecord()
            kwargs['certificate'] = self.certificate

        kwargs.setdefault('humidity', self.meanCalHumid)
        self.reference = kwargs.pop('reference', self.reference)

        calArgs = {'device': self.birth.device,
                   'user': self.user,
                   'temperature': self.meanCalTemp,
                   'pressure': self.meanCalPress,
                   'completed': False}

        calArgs.update(kwargs)

        session, _created = models.CalSession.objects.get_or_create(
            sessionId=self.sessionId, birtherVersion=__version__, defaults=calArgs)

        logger.info(f"{'Created' if _created else 'Updating'} CalSession #{self.sessionId}")

        # Create CalAxis records
        for idx, f in enumerate(self.calFiles):
            filename = self.basenames[idx]
            if self.hasHiAccel and calHi:
                subchannel = f.accelChannel[f.axis]
                self.makeAxis(session, subchannel,
                              value=self.cal[idx],
                              offset=self.offsets[idx],
                              rms=f.rms[f.axis],
                              filename=filename,
                              reference=self.reference)

            if self.hasLoAccel and calLo:
                subchannel = f.accelChannelLo[f.axis]
                self.makeAxis(session, subchannel,
                              value=self.calLo[idx],
                              offset=self.offsetsLo[idx],
                              rms=f.rmsLo[f.axis],
                              filename=filename,
                              reference=self.reference)

        # Create CalTransverse records
        for idx, transAxis in enumerate(("XY", "YZ", "XZ")):
            # filename = self.basenames[idx]
            f = self.calFiles[idx]

            if self.hasHiAccel and transHi:
                trans = self.trans[idx]
                chId = f.accelChannel.id
                subChId1 = f.accelChannel[f.axisIds[transAxis[0]]].id
                subChId2 = f.accelChannel[f.axisIds[transAxis[1]]].id
                self.makeTransverse(session, trans, chId, subChId1, subChId2,
                                    axis=transAxis)

            if self.hasLoAccel and transLo:
                trans = self.transLo[idx]
                chId = f.accelChannelLo.id
                subChId1 = "XYZ".index(transAxis[0])
                subChId2 = "XYZ".index(transAxis[1])
                self.makeTransverse(session, trans, chId, subChId1, subChId2,
                                    axis=transAxis)

        # TODO: Cleanup; try to roll back `sessionId` if cal failed (and this
        # isn't a recalibration). Semi-pseudocode:
        failed = False
        if newId and failed:
            models.revertSerialNumber(self.sessionId, "Calibration")

        self.session = session
        return session

    def makeAxis(self, session, subchannel, value=0, offset=0, rms=None,
                 filename="", reference=None):
        """ Create a `CalAxis` record.

            @param session: The `models.CalSession` of this calibration.
            @param subchannel: The `dataset.SubChannel` being calibrated.
            @param value: This axis' calibration value.
            @param offset: This axis' calibration offset.
            @param rms: This axis' RMS.
            @param filename: The name of the calibration recording IDE.
            @param reference: The reference sensor.
        """
        logger.debug(f'Creating CalAxis for {subchannel!r}')

        reference = reference or self.reference
        axisName = subchannel.displayName or ""
        sensor = self.getSensorRecord(session.device, subchannel.sensor)

        if subchannel.transform is None:
            # Use default calibration IDs. May not happen.
            calId = DeviceLibrary.CAL_IDS[(subchannel.parent.id, subchannel.id)]
        elif isinstance(subchannel.transform, Number):
            # Polynomial wasn't defined; `transform` is just the ID.
            calId = subchannel.transform
        else:
            # Use transform ID from recording
            calId = subchannel.transform.id

        # Values to set, not used to find an existing `CalAxis`.
        axisArgs = {'sensor': sensor,
                    'value': value,
                    'offset': offset,
                    'rms': rms,
                    'filename': filename,
                    'reference': reference,
                    'axis': axisName,
                    'sourceChannelId': subchannel.parent.id,
                    'sourceSubchannelId': subchannel.id}

        # Temperature-dependent analog sensors need temperature channel IDs
        # for their bivariate polynomials.
        if sensor.info.tempComp:
            # Default to 36.1 (the old standard) if null in database
            axisArgs['channelId'] = sensor.info.compChannelId or 36
            axisArgs['subchannelId'] = (1 if sensor.info.compSubchannelId is None
                                        else sensor.info.compSubchannelId)

        axis, _created = models.CalAxis.objects.update_or_create(
            session=session,
            calibrationId=calId,
            defaults=axisArgs)

        return axis

    def makeTransverse(self, session, value, channelId, subchannelId1=None,
                       subchannelId2=None, axis=""):
        """ Create a `CalTransverse` record.

            @param session: The `models.CalSession` of this calibration.
            @param value: The transverse value.
            @param channelId: The ID of the two axes parent channel.
            @param subchannelId1: The first transverse subchannel.
            @param subchannelId2: The second transverse subchannel.
            @param axis: The combined name of the transverse axes, e.g. "XY"
        """
        logger.debug(f"Creating CalTransverse for axis {axis!r}")

        # Values to set, not used to find an existing `CalTransverse`.
        transArgs = {'value': value,
                     'axis': axis}

        trans, _created = models.CalTransverse.objects.update_or_create(
            session=session,
            channelId=channelId,
            subchannelId1=subchannelId1,
            subchannelId2=subchannelId2,
            defaults=transArgs)

        return trans

    def getFiles(self, path=None):
        """ Get the filenames from the device's last recording directory with
            3 IDE files. These are presumably the shaker recordings.
        """
        path = self.dev.path if path is None else path

        ides = []
        for root, dirs, files in os.walk(os.path.join(path, 'DATA')):
            ides.extend(map(lambda x: os.path.join(root, x),
                            filter(lambda x: x.upper().endswith('.IDE'), files)))
            for d in dirs:
                if d.startswith('.'):
                    dirs.remove(d)
        return sorted(ides)[-3:]

    def sortCalFiles(self, calFiles):
        for calFile in calFiles:
            self.calFiles[calFile.shaken] = calFile

    def assignHiLoThings(self):
        hiId = self.deviceLibrary.hiAccelId
        loId = self.deviceLibrary.loAccelId

        if hiId: self.hasHiAccel = True
        if loId: self.hasLoAccel = True

        if self.hasHiAccel:
            self.cal = self.allGains[hiId]
            self.offsets = self.allOffsets[hiId]
            self.trans = self.allTrans[hiId]

        if self.hasLoAccel:
            self.calLo = self.allGains[loId]
            self.offsetsLo = self.allOffsets[loId]
            self.transLo = self.allTrans[loId]

        self.cal = self.cal or self.calLo
        self.calLo = self.calLo or self.cal
        self.offsets = self.offsets or self.offsetsLo
        self.offsetsLo = self.offsetsLo or self.offsets
        self.trans = self.trans or self.transLo
        self.transLo = self.transLo or self.trans

    def getCertificateRecord(self, **kwargs):
        """ Get the appropriate `models.CalCertificate` record for the current
            device. Keyword arguments are passed to the query.

            If an exact match to the device name or part number is not found,
            the closest match (by its name's Levenshtein distance) is returned.
            Note: In the long run, this may not be the best solution.

            @return: The `models.CalCertificate` record most likely to match.
        """
        if self.birth and self.birth.product:
            if self.birth.product.calCertificate:
                return self.birth.product.calCertificate

        name = kwargs.pop('name', (self.dev.productName or self.dev.partNumber))  # TODO-j: change this to the given pN

        # Try for exact match
        cq = models.CalCertificate.objects.filter(name=name, **kwargs)
        c = cq.extra(order_by=["-documentNumber", "-revision"]).first()
        if c:
            return c

        # Get the closest name via Levenshtein distance (fewest differences,
        # additions, and/or subtractions between the strings)
        certs = []
        for c in models.CalCertificate.objects.filter(**kwargs):
            cn = c.name.split('+')[0]
            certs.append((c, util.levenshtein(name, cn)))
        certs.sort(key=lambda x: x[1])

        cq = models.CalCertificate.objects.filter(name=certs[0][0].name)
        return cq.extra(order_by=["-documentNumber", "-revision"]).first()

    def closeFiles(self):
        """ Close all calibration recordings.
        """
        if self.calFiles:
            for c in self.calFiles:
                try:
                    c.doc.close()
                except Exception:
                    pass

    @classmethod
    def getSensorRecord(cls, device, sensor, **kwargs):
        """ Given a `dataset.Sensor` instance from a file, retrieve the
            corresponding `models.Sensor` record from the database. Keyword
            arguments are passed to the query.

            @param device: The database `models.Device` record.
            @param sensor: The `dataset.Sensor` object.
            @return: The associated `models.Sensor` record (or `None`).
        """
        rec = None
        sensorSn = None
        if sensor.traceData:
            sensorSn = sensor.traceData.get('serialNum', None)

        if sensorSn:
            # Find by serial number. Most accurate; no duplicate SNs.
            rec = device.getSensors(serialNumber=sensorSn, **kwargs).last()
        elif sensor.id is not None:
            # Find by sensor ID.
            rec = device.getSensors(sensorId=sensor.id, **kwargs).last()

        if rec is None:
            # Find by sensor part number. String matching is problematic.
            # Probably digital, and there should be only 1 of each digital.
            partNum = sensor.name.strip().split()[0]
            rec = device.getSensors(info__partNumber=partNum, **kwargs).last()

        return rec

    def __str__(self):
        result = "\nCALIBRATION VALUES:\n"
        for id in self.deviceLibrary.accelIds:
            result += f"{self.dev.channels[id].name}{' - Low ' if id == self.deviceLibrary.loAccelId else ''}{' - High ' if id == self.deviceLibrary.hiAccelId else ''}\n"
            result += f"Gain: {self.allGains[id]}\n"
            result += f"Offsets: {self.allOffsets[id]}\n"
            result += f"Transverse Sensitivity: {self.allTrans[id]}\n"
            result += f"Mean: {XYZ(self.calFiles.x.accels[id].means, self.calFiles.y.accels[id].means, self.calFiles.z.accels[id].means)}\n\n"
        return result


class AccelCalFile(object):

    def __init__(self, filename, hiId, loId, shakeOrder=exp_order, skipTime=0.5):
        self.filename = filename
        self.basename = os.path.basename(filename)
        self.name = os.path.splitext(self.basename)[0]
        self.doc = importFile(filename)
        self.timestamp = self.doc.lastUtcTime
        accels = ei.get_channels(self.doc, 'ACCELERATION', subchannels=False)

        if loId:
            self.loId = loId
            self.accelChannelLo = self.doc.channels[loId]
            lowest = self.accelChannelLo
        if hiId:
            self.hiId = hiId
            self.accelChannel = self.doc.channels[hiId]
            lowest = self.accelChannel

        self.cal_temp = None
        self.cal_press = None
        self.cal_humid = None

        self.axisFlip = None

        self.shakeOrder = shakeOrder
        self.shaken = self.determineShaken(lowest)

        self.accels = {accel.id: AccelerometerData(self.doc, accel, self.shaken, skipTime) for accel in accels}

    def getAxisIds(self):
        pass

    def getGainsAndMeans(self):

        for id, accel in self.accels.items():
            _print(f"Analyzing {accel.accel.name} data")
            accel.organizeShakeProfile(ShakeProfile(self.shakeOrder))
            data, hp_data = accel.calcDataRegions()
            accel.calcRMSXYZ(hp_data)
            accel.calcGain()
            accel.calcQuietMean(data)


    def getOffsets(self, gravities):
        for id, accel in self.accels.items():
            accel.calcOffset(gravities)

    def getChannelMean(self, knownIds):
        """ Get the mean of a subchannel, using the first existing IDs from
            the list of `knownIds` that can be found. For getting the average
            temperature/humidity.
        """
        for chId, subChId in knownIds:
            if chId in self.doc.channels:
                if subChId < len(self.doc.channels[chId]):
                    channel = self.doc.channels[chId][subChId]
                    return channel.getSession()[:].mean(axis=1)[1]

        return None

    def setCalTempPressHumid(self):
        self.cal_temp = self.getChannelMean(DeviceLibrary.KNOWN_TEMP_CHANNELS)
        self.cal_press = self.getChannelMean(DeviceLibrary.KNOWN_PRESSURE_CHANNELS)
        self.cal_humid = self.getChannelMean(DeviceLibrary.KNOWN_HUMIDITY_CHANNELS)

    def determineShaken(self, accel):
        """ using the lowest range accel, find the shaken axis """
        data = accel.getSession().arrayRange()[1:min(4, len(accel.children) + 1)]
        stdevs = np.std(data, axis=1)
        return stdevs.argmax()

    def __str__(self):
        #         raise NotImplementedError("Refactor AccelCalFile.__str__()!")

        try:
            cols = " ".join(f"{v:10.4f}" for v in self.accels[self.loId].rms)
            return f'{self.name} {cols}'
        except (TypeError, AttributeError):
            return super(self, AccelCalFile).__str__()

    def __repr__(self):
        try:
            return "<%s %s at 0x%08x>" % (self.__class__.__name__,
                                          os.path.basename(self.filename),
                                          id(self))
        except (AttributeError, TypeError):
            return super(AccelCalFile, self).__repr__()


# """
dev = None
Cal = Calibrator(dev, shakeOrder=order_10g_4g)
filenames = lambda folder: [str(folder) + "\\" + file for file in os.listdir(folder)]
print(os.getcwd())
Cal.calculate(filenames=filenames("..\\testing\\S0012851"))
"""

if __name__ == "__main__":
    import argparse
    from .shakeprofile import order_10g, order_10g_4g
    from . import cal_util

    # run in ProductDatabase via python -m birther.calibration

    parser = argparse.ArgumentParser("Database-less Calibration")
    parser.add_argument('-p', '--partNumber', default=None, help='Device Part Number to calibrate as.\n'
                                                                 'Defaults to Device on the recordings')
    parser.add_argument('-m', '--MCU', default=None, choices=['STM', 'EFM'], help='Select MCU Type\n'
                                                                                  'Defaults to MCU on the recordings')
    parser.add_argument('-s', '--shakeProfile', choices=['10g_4g', '10g'], default='exp_order',
                        help='Select Shake Profile as in shakeprofile.py.\n'
                             'Defaults to the exp_order in shakeprofile.py: 10g_4g')
    parser.add_argument('-f', '--filesPath', type=str, help='Path to folder with 3 Calibration IDEs')

    args = parser.parse_args()

    try:
        dev = ed.getDevices()[0]
    except:
        dev=None

    shake_profiles = {'10g': order_10g,
                      '10g_4g': order_10g_4g,
                      'exp_order': exp_order}

    cal = Calibrator(dev, shakeOrder=shake_profiles[args.shakeProfile])

    if not args.filesPath:
        cal_util.makeWorkDir(cal)
        ideFiles = cal_util.copyToWorkDir(cal)
    else:
        ideFiles = [str(args.filesPath) + "\\" + file for file in os.listdir(args.filesPath)]

    if len(ideFiles) == 3:
        cal.calculate(ideFiles, pn=args.partNumber, mcu=args.MCU)
    else:
        raise CalibrationError("Improper number of IDE Files")
"""