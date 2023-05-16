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

import numpy as np
import pylab 
from scipy.signal import butter, sosfilt

from . import paths  # Just importing should set things
from .shared_logger import logger
from idelib.importer import importFile

import endaq.device

from . import util
from .util import XYZ

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


#===============================================================================
# 
#===============================================================================

# The current user (for logging in database)
USER = getpass.getuser()

# Default humidity. Used if the recorder didn't record humidity, or if the
# last calibration had no humidity recorded.
DEFAULT_HUMIDITY = 22.3

# schema_mide = loadSchema('mide_ide.xml')

#===============================================================================
# 
#===============================================================================


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


#===============================================================================
# 
#===============================================================================

class AccelCalFile(object):
    """ One analyzed IDE file containing data recorded on the shaker. Only one
        axis per file is relevant (shaker moves in one direction).
    """
    # XXX: THIS IS ALL GETTING REWRITTEN USING NEW STUFF IN  `endaq.device`!
    # Known channel/subchannel IDs of pressure sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_PRESSURE_CHANNELS = ((36, 0), (59, 0))
    
    # Known channel/subchannel IDs of temperature sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_TEMP_CHANNELS = ((36, 1), (59, 1))

    # Known channel/subchannel IDs of humidity sensors, in preferred order
    # of use (going left to right, if the file has the channel, use it).
    KNOWN_HUMIDITY_CHANNELS = ((59, 2), )
    
    # The channel IDs used by any accelerometer we might calibrate.
    KNOWN_HI_ACCEL_CHANNELS = (0, 8, 80)
    KNOWN_LO_ACCEL_CHANNELS = (32, 80)
    
    # Mapping of _analyze() kwargs for each accelerometer channel ID, so 
    # everything can be automated (instead of explicitly doing lo/hi-G).
    # FOR FUTURE USE. Currently, hardcoded arguments used.
    # XXX: Is this really necessary? Can it be calculated from sample rate?
    ANALYSIS_SETTINGS = {8:  dict(),
                         32: dict(thres=6, start=1000, length=1000)}
    
    # RMS value of closed loop calibration
    REFERENCE_RMS_10g = 7.075       # 10*(2**.5)/2
    REFERENCE_RMS_4g = 4*(2**.5)/2  # 4*(2**.5)/2
    REFERENCE_OFFSET = 1.0


    def __init__(self, filename, dev=None, acOnly=False, dcOnly=False,
                 skipSamples=None, validate=True):
        """ Constructor.
        
            @param filename: The IDE file to read.
            @param dev: The recorder. If `None`, the device will be
                instantiated from the recording.
            @param acOnly: If `True`, only calibrate the AC (primary)
                accelerometer.
            @param dcOnly:  If `True`, only calibrate the low/digital
                (secondary) accelerometer.
            @param skipSamples: The number of samples to skip before the data
                used in the calibration. Used to work around sensor settling
                time.
            @param validate: If `True`, make sure the IDE is usable.
        """
        self.doc = None
        self.dev = dev
        
        self.filename = filename
        self.basename = os.path.basename(filename)
        self.name = os.path.splitext(self.basename)[0]
        self.skipSamples = skipSamples
        self.acOnly = acOnly
        self.dcOnly = dcOnly

        # The relevant axis' subchannel IDs on each accelerometer (0-2).
        # Computed later.
        self.subchannel = None
        self.subchannelLo = None

        _print(f"importing {os.path.basename(self.filename)}... ")
        self.doc = importFile(self.filename)
        self.timestamp = self.doc.lastUtcTime
        
        if self.dev is None:
            self.dev = endaq.device.fromRecording(self.doc)
            
        self.serialNum = self.dev.serial

        self.hasHiAccel = False
        self.hasLoAccel = False

        # The starting *times* of the two shakes in the recording. Use
        # `EventList.getEventIndexNear()` to get actual indices for the
        # specific `EventList` at its sample rate.
        self.start10g = self.start4g = None

        # Channel sample rates, keyed by channel ID.
        self.sampleRates = {}

        # All the other instance variables used (for convenient reference)
        self.accel = None
        self.accelChannel = self.accelChannelLo = None
        self.accelLo = self.axisIds = None
        self.cal = self.calLo = None
        self.cal_humid = None
        self.cal_press = None
        self.cal_temp = None
        self.means = self.meansLo = None
        self.rms = self.rmsLo = None
        self.times = self.timesLo = None

        if validate:
            self.validate()
        
        self.analyze()


    def __str__(self):
#         raise NotImplementedError("Refactor AccelCalFile.__str__()!")
    
        try:
            cols = " ".join(f"{v:10.4f}" for v in (self.rms + self.cal))
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

    
    #===========================================================================
    # 
    #===========================================================================

    @staticmethod
    def lowpassFilter(data, cutoff, fs, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        sos = butter(order, normal_cutoff, btype='low', analog=False, output='sos')
        y = sosfilt(sos, data)
        return y
    
    
    @staticmethod
    def highpassFilter(data, cutoff, fs, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        sos = butter(order, normal_cutoff, btype='high', analog=False, output='sos')
        y = sosfilt(sos, data)
        return y

    
    #===========================================================================
    # 
    #===========================================================================
    
    @classmethod
    def _getFirstIndex(cls, a, thres, col):
        """ Return the index of the first item in the given column that passes
            the given test.
            Note that since this uses an iter it does not react well to using reversed data for some reason

            @param a: A 2D numpy array.
            @param thres: The threshold value
            @param col: The column of the data to check.
            @return: The index of the first item to pass the test.
        """
        it = np.nditer(a[:, col], flags=['f_index'])
        while not it.finished:
            if abs(it[0]) > thres:
                return it.index
            it.iternext()
        return 0


    @classmethod
    def _getFirstIndexNoIter(cls, a, thres, col):
        """ Return the index of the first item in the given column that passes
            the given test.
            Note that this uses a simple for loop so it can go through a reversed array

            @param a: A 2D numpy array.
            @param thres: The threshold value
            @param col: The column of the data to check.
            @return: The index of the first item to pass the test.
        """
        for index, number in enumerate(a[:, col]):
            if abs(number) > thres:
                return index
        return 0


    @classmethod
    def getFirstIndices(cls, data, thres, axisIds):
        """ Find the index of the first valid data.
        """
        # Column 0 is the time, so axis columns are offset by 1
        indices = XYZ(cls._getFirstIndex(data, thres, axisIds.x+1),
                      cls._getFirstIndex(data, thres, axisIds.y+1),
                      cls._getFirstIndex(data, thres, axisIds.z+1))

        # Indices used to be calculated for each axis, but this seems to have
        # been a cargo cult artifact from the original MATLAB and/or ancient
        # data. New data all starts at the same time.
        indices.x = indices.y = indices.z = max(indices)

        return indices


    @classmethod
    def getFirstIndex(cls, data, thres, axisIds):
        """ Find the index of the first valid data.
        """
        # Column 0 is the time, so axis columns are offset by 1
        indices = XYZ(cls._getFirstIndex(data, thres, axisIds.x + 1),
                      cls._getFirstIndex(data, thres, axisIds.y + 1),
                      cls._getFirstIndex(data, thres, axisIds.z + 1))

        # Indices used to be calculated for each axis, but this seems to have
        # been a cargo cult artifact from the original MATLAB and/or ancient
        # data. New data all starts at the same time.
        return max(indices)


    @classmethod
    def getLastIndex(cls, data, thres, axisIds):
        """ Find the index of the last point above thres
        """
        print(f"getLastIndex {data.shape=}")
        # Column 0 is the time, so axis columns are offset by 1
        reverseData = np.flipud(data)
        length = data.shape[0]
        indices = XYZ(cls._getFirstIndexNoIter(reverseData, thres, axisIds.x + 1),
                      cls._getFirstIndexNoIter(reverseData, thres, axisIds.y + 1),
                      cls._getFirstIndexNoIter(reverseData, thres, axisIds.z + 1))

        # Indices used to be calculated for each axis, but this seems to have
        # been a cargo cult artifact from the original MATLAB and/or ancient
        # data. New data all starts at the same time.
        return length-max(indices)


    @classmethod
    def calculateRMS(cls, data, axis=None):
        """ Compute the root mean square of data in a numpy array.
        """
        return np.sqrt(np.mean(data**2, axis=axis))


    def getAccelerometers(self, knownIds=None):
        """ Get all known accelerometer channels, using a list of known
            channel IDs.
        """
        knownIds = knownIds or (self.KNOWN_HI_ACCEL_CHANNELS +
                                self.KNOWN_LO_ACCEL_CHANNELS)
        return [ch for ch in self.doc.channels.values() if ch.id in knownIds]


    def getChannelMean(self, knownIds=KNOWN_TEMP_CHANNELS):
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
        

    def _getAccel(self, channelIds, exclude=None):
        """ Get the first accelerometer that appears in the given list of IDs.
        
            @param channelIds: A list of accelerometer channel IDs.
            @keyword exclude: A list of channel IDs to ignore.
        """
        # TODO: Actually check sensor descriptions to get channel ID
        exclude = exclude or []
        for chid in set(channelIds).difference(exclude):
            if chid in self.doc.channels:
                return self.doc.channels[chid]


    def getHighAccelerometer(self, exclude=None):
        """ Get the high-G accelerometer channel.
        
            @keyword exclude: A list of channel IDs to ignore.
        """
        exclude = exclude or []

        if self.dcOnly or self.dev.partNumber.startswith('LOG-0003'):
            return None
        
        pn = str(self.dev.partNumber).upper()
        if fnmatch(pn, "[SW]?-D*") and not fnmatch(pn, "S?-D*D*"):
            return None

        ch = self._getAccel(self.KNOWN_HI_ACCEL_CHANNELS, exclude)
        if ch is not None:
            return ch

        raise CalibrationError("Primary accelerometer channel not where expected!",
                               self.doc)


    def getLowAccelerometer(self, exclude=None):
        """ Get the high-G accelerometer channel.
        
            @keyword exclude: A list of channel IDs to ignore.
        """
        exclude = exclude or []

        # Handle old SSCs. The following len(self.doc.channels) == 2: check skips old SSC units
        # Wish I understood the logic better here ~PJS
        if self.dev.partNumber.startswith('LOG-0003'):
            ch = self._getAccel(self.KNOWN_LO_ACCEL_CHANNELS, exclude)
            if ch is not None:
                return ch

        if self.acOnly or len(self.doc.channels) == 2:
            return None
        
        ch = self._getAccel(self.KNOWN_LO_ACCEL_CHANNELS, exclude)
        if ch is not None:
            return ch

        raise CalibrationError("Secondary accelerometer channel not where expected!",
                               self.doc)


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


    def _getSensorName(self, channel):
        return channel[0].sensor.name.upper()


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


    def analyze(self):
        """ An attempt to port the analysis loop of SSX_Calibration.m to Python.

            @return: The calibration constants tuple and the mean temperature.
        """

        accelChannel = self.getHighAccelerometer()
        skipTime = None
        if self.skipSamples is None:
            skipTime = 0.5

        if accelChannel:
            self.hasHiAccel = True
            
            # HACK: Fix typo in template the hard way
            accelChannel.transform.references = (0,)
            accelChannel.updateTransforms()

            _print("\nAnalyzing primary accelerometer data")
            self.accel, self.times, self.rms, self.cal, self.means = \
                self._analyze(accelChannel, skipSamples=self.skipSamples,
                              skipTime=skipTime)
                
        else:
            self.hasHiAccel = False

        exclude_id = []
        if accelChannel is not None:
            exclude_id = [accelChannel.id]
        accelChannelLo = self.getLowAccelerometer(exclude=exclude_id)
        if accelChannelLo:
            self.hasLoAccel = True
            
            _print("\nAnalyzing secondary accelerometer data")
            self.accelLo, self.timesLo, self.rmsLo, self.calLo, self.meansLo = \
                self._analyze(accelChannelLo, thres=6, start=1000, length=1000,
                              skipTime=skipTime)

            if not self.hasHiAccel:
                _println("no hi accelerometer, using lo as main")
                self.accel = XYZ(self.accelLo)
                self.times = XYZ(self.timesLo)
                self.rms = XYZ(self.rmsLo)
                self.cal = XYZ(self.calLo)
                self.means = XYZ(self.meansLo)
        else:
            self.hasLoAccel = False

        self.accelChannel = accelChannel
        self.accelChannelLo = accelChannelLo
        self.cal_temp = self.getChannelMean(self.KNOWN_TEMP_CHANNELS)
        self.cal_press = self.getChannelMean(self.KNOWN_PRESSURE_CHANNELS)
        self.cal_humid = self.getChannelMean(self.KNOWN_HUMIDITY_CHANNELS)

        _println()


    def getMeans(self, data, starts, span, sampRate, lowpass=2.55):
        """ Calculate offsets (means).
            
            @param data: time + xyz data for analysis
            @param starts: start index of span for calculating
            @param span: size of slice to calculate
            @param sampRate: sample rate of data, used in filtering
            @param lowpass: filter frequency, 0 for no filtering

            @return: An `XYZ` containing the mean of the selected segment.
        """
        # I no longer have any idea why this is implemented this way.
        means = XYZ()
        if lowpass:
            # Apply filter. This also (effectively) removes the mean.
#             _print("Applying low pass filter... ")
            for i in range(1, min(4, data.shape[1])):
                filtered = self.lowpassFilter(data[:, i], lowpass, sampRate)
#                 means[i-1] = np.abs(filtered[int(sampRate*2):int(sampRate*3)]).mean()
                start = starts[i-1]
                means[i-1] = filtered[start:start+span].mean()
        else:
            # No filter. Explicitly remove the mean.
#             _print("Calculating means... ")
            for i in range(1, min(4, data.shape[1])):
                start = starts[i - 1]
                means[i-1] = data[start:start+span].mean()
        return means


    @classmethod
    def _findQuietTime(cls, data, span, searchOverlap=0.5):
        minStandardDeviation = None
        bestStartIndex = None
        dataLength = len(data)
        if searchOverlap > 0.9:       # Too large an overlap would mean we move backwards
            searchOverlap = 0.9
        for startIndex in range(0, dataLength-span, int(span*(1-searchOverlap))):
            thisStandardDeviation = np.std(data[startIndex:startIndex+span])
            if minStandardDeviation is None or thisStandardDeviation < minStandardDeviation:
                minStandardDeviation = thisStandardDeviation
                bestStartIndex = startIndex
            # print(f"Index {startIndex}, StdDev {thisStandardDeviation:0.4f}")
        print(f"Selecting index {bestStartIndex} ({minStandardDeviation=:0.4f})")
        return bestStartIndex


    @classmethod
    def findQuietTimes(cls, data, span, searchOverlap=0.5):
        """ find the area with the lowest noise
            
            @param data: time + xyz data for analysis
            @param span: size of slice for analysis
            @param searchOverlap: Start index of search increments by span*(1-searchOverlap)

            @return: An `XYZ` containing the start index of the quietest spans
        """
        bestStartIndices = XYZ()
        for i in range(1, min(4, data.shape[1])):
            _print(f"Finding quiet times for axis {i-1}: ")
            bestStartIndices[i-1] = cls._findQuietTime(data[:, i], span, searchOverlap=searchOverlap)
        return bestStartIndices


    def _analyze(self, accelChannel, thres=4, start=5000, startTime=None, length=5000, lengthTime=None,
                 skipSamples=0, skipTime=None, highpass=10, lowpass=2.55, timeBetweenShakes=3):
        """ Analyze one accelerometer channel.

            An attempt to port the analysis loop of SSX_Calibration.m to
            Python.

            @param accelChannel: The accelerometer channel to calibrate.
            @type accelChannel: `dataset.Channel`
            @keyword thres: (gs) acceleration detection threshold (trigger for
                finding which axis is calibrated).
            @keyword start: Look # data points ahead of first index match after
                finding point that exceeds threshold.
            @keyword startTime: if start is None, start = sampRate * startTime
            @keyword length: The number of samples to use for gain.
            @keyword lengthTime: if length is None, length = sampRate * lengthTime
            @keyword skipSamples: # of points to skip at start and end of record, 
                to account for warm up or jostling
            @keyword skipTime: if skipSamples is None, skipSamples = sampRate * skipTime
            @keyword timeBetweenShakes: Time between the large and small shakes
                used for finding quiet region for offset calculation
        """
        self.axisIds = self.getAxisIds(accelChannel)

        # Turn off existing per-channel calibration (if any)
        for c in accelChannel.children:
            c.setTransform(None)
        accelChannel.updateTransforms()

        a = accelChannel.getSession()
        a.removeMean = False
        sampRate = self.sampleRates[accelChannel.id] = a.getSampleRate()
        
        if sampRate < 1000:
            raise CalibrationError(f"Channel {accelChannel.id} ({accelChannel.name}) had a low sample rate: {sampRate} Hz",
                                   self.doc, accelChannel)

        if lengthTime is not None:
            length = int(sampRate * lengthTime)
        if startTime is not None:
            start = int(sampRate * startTime)
        if skipTime is not None:
            skipSamples = int(sampRate * skipTime)

        # `a` is now an EventArray, which is "flat". Slices are numpy arrays.
        # The 'shape' of a sliced EventArray is different, though, so fix.
        data = np.flip(np.rot90(a[:]), axis=0)
        _print(f"({len(data)} samples).")

        lowAccelRange = self.is8gOrLess(accelChannel)
        totalLength = a.session.lastTime - a.session.firstTime
        expectedLength = 2*start + 2*skipSamples + (5 + 5 + 2)*sampRate     # 2 5 second shakes + 2 second wait

        if lowAccelRange:
            if totalLength < expectedLength:
                raise CalibrationError(f"Secondary shake not found. "
                                       f"Expected length {expectedLength}, got length {totalLength}",
                                       self.doc, accelChannel)
            referenceRMS = self.REFERENCE_RMS_4g
        else:
            referenceRMS = self.REFERENCE_RMS_10g

        stop = start + length  # Look # of data points ahead of first index match
        times = data[:, 0] * .000001

        hp_data = np.copy(data)

        if highpass:
            # _print("Applying high pass filter... ")
            for i in range(1, min(4, hp_data.shape[1])):
                hp_data[:, i] = self.highpassFilter(hp_data[:, i], highpass, sampRate)

        # HACK: Some  devices have a longer delay before Z settles.
        if skipSamples:
            data = data[skipSamples:-skipSamples]   # Shave off skipSamples points from the beginning and end
            hp_data = hp_data[skipSamples:-skipSamples]   # Shave off skipSamples points from the beginning and end

        # _print("getting indices... ")

        # Find the start and end of the shaking
        smallShakeThreshold = 3
        shakeStartIndex = self.getFirstIndex(hp_data, thres, self.axisIds)
        shakeEndIndex = self.getLastIndex(hp_data, smallShakeThreshold, self.axisIds)

        offsetCalcSpan = 1.0        # Length of time to grab for offset calculations
        offsetCalcSpan = int(offsetCalcSpan * sampRate)
        spanBetweenShakes = int(timeBetweenShakes*sampRate)
        if spanBetweenShakes > offsetCalcSpan:
            quietSearchFudgeFactor = 1*sampRate
            quietStart = int((shakeStartIndex + shakeEndIndex)/2 - spanBetweenShakes/2 - quietSearchFudgeFactor)
            quietEnd = int(quietStart + spanBetweenShakes + 2*quietSearchFudgeFactor)
        else:
            quietStart = 0
            quietEnd = len(data)    # support for old files, just search everywhere for some peace and quiet in this noise filled world

        quietestOffsets = self.findQuietTimes(data[quietStart:quietEnd], offsetCalcSpan)
        quietStarts = [quietStart + offset for offset in quietestOffsets]

        means = self.getMeans(data, quietStarts, offsetCalcSpan, sampRate, lowpass)

        if lowAccelRange:
            print(f"{accelChannel} using 4g shake")
            validDataStart = int((shakeStartIndex + shakeEndIndex)/2)
            shakeStartIndex = validDataStart +\
                              self.getFirstIndex(hp_data[validDataStart:], smallShakeThreshold, self.axisIds)
            # start = shakeStartIndex + start
            # stop = start + length
            # if stop > shakeEndIndex:
            #     raise CalibrationError("Bad calculation, small shake appears to be too short. first sample %i, last sample %i, need length %i" %
            #                        (shakeStartIndex, shakeEndIndex, length+start), self.doc, accelChannel)
            # means = self.getMeans(data[start:, :], sampRate, lowpass)

        _println(f"Shake Start Index: {shakeStartIndex + skipSamples}. ")

        shakeRegionStart = shakeStartIndex + start
        shakeRegionEnd = shakeStartIndex + stop

        accel = XYZ(hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.x + 1],
                    hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.y + 1],
                    hp_data[shakeRegionStart:shakeRegionEnd, self.axisIds.z + 1])

        times = XYZ(times[shakeRegionStart:shakeRegionEnd],
                    times[shakeRegionStart:shakeRegionEnd],
                    times[shakeRegionStart:shakeRegionEnd])

        _print("computing RMS... ")
        rms = XYZ(self.calculateRMS(accel.x),
                  self.calculateRMS(accel.y),
                  self.calculateRMS(accel.z))
        _println(f"{rms = !r}")

        cal = XYZ(referenceRMS / rms.x,
                  referenceRMS / rms.y,
                  referenceRMS / rms.z)

        return accel, times, rms, cal, means


    #===========================================================================
    # 
    #===========================================================================
    
    def render(self, imgPath, baseName='vibe_test_', imgType="png", show=False):
        """ Create a plot of each axis. The resulting filenames are based on
            the IDE filename.
            
            @param imgPath: The save path.
            @param baseName: The prefix of the filename.
            @param imgType: The type (file extension) of the image.
            @param show: If `True`, show the plot in a window.
            @return: The name of the file generated.
        """
        fileName = os.path.splitext(os.path.basename(self.filename))[0]
        if imgPath is not None:
            imgName = f'{baseName}{fileName}.{imgType}'
            saveName = os.path.join(imgPath, imgName)
        else:
            saveName = None
 
        # Generate the plot
#         _print("plotting...")
        plotXMin = min(self.times.x[0], self.times.y[0], self.times.z[0])
        plotXMax = max(self.times.x[-1], self.times.y[-1], self.times.z[-1])
        plotXPad = (plotXMax-plotXMin) * 0.01
        fig = pylab.figure(figsize=(8, 6), dpi=80, facecolor="white")
        pylab.suptitle(f"File: {os.path.basename(self.filename)}, SN: {self.serialNum}",
                       fontsize=24)
        pylab.subplot(1, 1, 1)
        pylab.xlim(plotXMin-plotXPad, plotXMax+plotXPad)
        pylab.plot(self.times.x, self.accel.x, color="red",   label="X Axis",
                   linewidth=1.5, linestyle="-")
        pylab.plot(self.times.y, self.accel.y, color="green", label="Y Axis",
                   linewidth=1.5, linestyle="-")
        pylab.plot(self.times.z, self.accel.z, color="blue",  label="Z Axis",
                   linewidth=1.5, linestyle="-")
        pylab.legend(loc='upper right')
 
        axes = fig.gca()
        axes.set_xlabel('Time (seconds)')
        axes.set_ylabel('Amplitude (g)')
 
        if saveName is not None:
            pylab.savefig(saveName)
            
        if show:
            pylab.show()
 
        return saveName


    #===========================================================================
    # 
    #===========================================================================
    
    def validate(self):
        """ Perform some basic 'sanity check' validation on the recording
            prior to starting the calibration process.
        """
        for ch in self.doc.channels.values():
            if len(ch.getSession()) == 0:
                raise CalibrationError("Channel contained no data!",
                                       self.doc, ch)


#===============================================================================
# 
#===============================================================================

class Calibrator(object):
    """ Thing that calculates the calibration polynomials.
    
        @ivar workDir: The local 'working' directory. Used by GUI.
        @ivar calDir: The network calibration directory. Used by GUI.
        @ivar failed: Did the calibration fail? Used by GUI.
        @ivar failure: The calibration failure message. Used by GUI.
        @ivar cancelled: Was the calibration cancelled? Used by GUI.
    """

    # Default calibration IDs for each channel/subchannel pair
    # TODO: Refactor this w/ new stuff in `endaq.device`!
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

    DEFAULT_CERTIFICATE = "Slam Stick X+DC"


    def __init__(self, dev=None, sessionId=None, calHumidity=None,
                 calTempComp=-0.30, certificate=None, reference=None,
                 skipSamples=None, user=USER, workDir=None):
        """ Constructor.
            
            @param dev: A `endaq.device.Recorder` instance (a 'real' one). Can be
                `None` if a list of recording files is provided (see below).
            @param sessionId: The calibration session/certificate ID, or
                `None` to create a new one.
            @param calHumidity: The humidity at the time of calibration,
                if the recorder being calibrated didn't measure it.
            @param calTempComp:
            @param certificate:
            @param reference: The reference accelerometer.
            @param skipSamples: The number of samples to ignore from the
                beginning of a recording.
            @param user: The name of the technician doing the calibration.
                Defaults to the name of the computer's logged in user account.
        """
        self.dev = dev
        if dev:
            self.devPath = dev.path
        else:
            self.devPath = None

        self.sessionId = sessionId
        self.meanCalHumid = calHumidity
        self.calTempComp = calTempComp
        self.certificate = certificate
        self.reference = reference
        self.skipSamples = skipSamples
        self.user = user

        self.isUpdate = False

        # For use by the GUI
        self.workDir = workDir  # The local 'working' directory
        self.calDir = None      # The product calibration directory (server)
        self.failed = False     # Did the calibration fail?
        self.failure = None     # Failure message, if above is True
        self.cancelled = False  # Was the calibration session cancelled?

        self.calFilesUnsorted = self.calFiles = None
        self.hasHiAccel = self.hasLoAccel = None

        self.meanCalPress = self.meanCalTemp = None
        self.channels = XYZ(None, None, None)
        self.channelsLo = XYZ(None, None, None)
        self.cal = XYZ(None, None, None)
        self.calLo = XYZ(None, None, None)
        self.offsets = XYZ(None, None, None)
        self.offsetsLo = XYZ(None, None, None)

        # The latest database `Birth` record for the device being calibrated.
        # Set when the database is updated. 
        self.birth = None

        # The database record for this session. Set when the database is updated.
        self.session = None

        # All the other instance variables used (for convenient reference)
        self.basenames = None
        self.calDate = None
        self.calTimestamp = None
        self.filenames = None
        self.trans = None
        self.transLo = None


    #===========================================================================
    #--- File management. Most was moved to `cal_util.py`
    #===========================================================================
    
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


    def closeFiles(self):
        """ Close all calibration recordings.
        """
        if self.calFiles:
            for c in self.calFiles:
                try:
                    c.doc.close()
                except Exception:
                    pass


    def sortCalFiles(self, calFiles):
        """ Get the calibration recordings, sorted by the axis shaken.
        
            @param calFiles: A list of three `AccelCalFile` instances.
            @return: An `XYZ` containing the files corresponding to each axis.
        """
        self.calFilesUnsorted = calFiles
        sortedFiles = XYZ()

        try:
            for i in range(3):
                sortedFiles[i] = min(calFiles, key=lambda c: c.cal[i])
                sortedFiles[i].axis = i
        except AttributeError:
            # Presumably, there's no 'hi' accelerometer; use 'lo'.
            for i in range(3):
                sortedFiles[i] = min(calFiles, key=lambda c: c.calLo[i])
                sortedFiles[i].axis = i

        self.calFiles = sortedFiles


    #===========================================================================
    #
    #===========================================================================

    @classmethod
    def getAxisFlips(cls, dev, calAxes=None, calAxesLo=None):
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
        pn = str(dev.partNumber).upper()
        mcu = str(dev.mcuType).upper()

        if mcu.startswith('STM32'):
            # Analog accelerometer orientation varies by model
            if fnmatch(pn, "S?-E*"):
                calAxes = calAxes or ( 1,  1, -1)  # Channel 8
            elif fnmatch(pn, "S?-R*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(pn, "W?-E*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(pn, "W?-R*"):
                calAxes = calAxes or ( 1,  1, -1)  # Channel 8
            else:
                if not calAxes and calAxesLo:
                    logger.warning(f"Using default axis flips for unknown STM32 device type {pn!r}")
                calAxes = calAxes or ( 1,  1, -1)  # Channel 8

            # ADXL357 is the same for all STM32 S and W (as of HwRev 2.0.0 - 2.0.1)
            calAxesLo = calAxesLo or (-1, -1,  1)  # Channel 80

        elif pn.startswith(('S1', 'S2')):
            # "Mini" with 2 digital accelerometers
            calAxes = calAxes or     (-1, -1,  1)  # Channel 80
            calAxesLo = calAxesLo or ( 1,  1,  1)  # Channel 32
        elif fnmatch(pn, "S?-D16") or fnmatch(pn, "S?-D200"):
            # One digital accelerometer, old hardware (e.g., SSC equivalents for NAVAIR)
            calAxes = calAxes or     ( 1,  1, -1)  # Does not really exist for this device
            calAxesLo = calAxesLo or ( 1,  1,  1)  # Channel 32
        elif pn.startswith(('S3', 'S4', 'S5', 'S6', 'W5', 'W8')):
            if "-R" in pn:                         # Piezoresistive device has axis flips
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif '-E' in pn:
                calAxes = calAxes or ( 1,  1, -1)  # Channel 8
            else:
                calAxes = calAxes or (-1, -1,  1)  # Channel 80 (the 'main' accelerometer for an Sx-D40)
            calAxesLo = calAxesLo or (-1, -1,  1)  # Channel 80
        elif pn.startswith('LOG-0004'):
            calAxes = calAxes or     (-1,  1, -1)  # Channel 8
            calAxesLo = calAxesLo or ( 1,  1,  1)  # Channel 32
        elif pn.startswith('LOG-0002'):
            calAxes = calAxes or     ( 1,  1, -1)  # Channel 8
            calAxesLo = calAxesLo or ( 1,  1,  1)  # Channel 32
        else:
            if not calAxes and calAxesLo:
                logger.warning(f"Could not get axis flips for device type {pn!r}")
            calAxes = calAxes or     ( 1,  1,  1)
            calAxesLo = calAxesLo or ( 1,  1,  1)

        return XYZ(calAxes), XYZ(calAxesLo)

    @classmethod
    def getGravity(cls, dev, calFiles):
        """ Get the gravity directions of the data provided.

            @parameter dev: Device being looked at, so we know the accelerometers and inversions
            @parameter calFiles: x,y,z calibration data. main and low accelerometers
            @return: XYZ of the direction of gravity in each file
        """
        # FUTURE: Less hardcoding.
        pn = str(dev.partNumber).upper()
        flips, flipsLo = cls.getAxisFlips(dev, None, None)
        # On Mini, use the 40 or 8 g accelerometer. Otherwise use the secondary (which is always 40g)
        if pn.startswith(('S1', 'S2')):
            activeFlips = flips
            activeMeans = [calFiles[i].means[i] for i in range(3)]
        else:
            if not calFiles[0].hasLoAccel:
                print("No DC accelerometer found!")
                return XYZ([1, 1, 1])
            activeFlips = flipsLo
            activeMeans = [calFiles[i].meansLo[i] for i in range(3)]
        measurement = [activeFlips[i]*activeMeans[i] for i in range(3)]
        gravity = [m/abs(m) for m in measurement]
        if gravity[2] != 1:
            raise CalibrationError("Got the wrong gravity vector on Z for some dumb reason")
        return XYZ(gravity)

    #===========================================================================
    # 
    #===========================================================================

    def calculateTrans(self, calFiles, cal, low=False):
        """ Calculate the transverse sensitivity.

            @param calFiles: An `XYZ` containing sorted `AccelCalFile` objects.
            @param cal: An `XYZ` containing calibration values for the axes.
            @param low: `True` if this is the secondary accelerometer.
        """
        def calc_trans(a, b, c, a_corr, b_corr, c_corr):
            a_cross = a * a_corr
            b_cross = b * b_corr
            c_ampl =  c * c_corr
            Stab = np.sqrt((a_cross**2)+(b_cross**2))
            Stb = 100 * (Stab/c_ampl)
            return Stb

        if low:
            xRms = calFiles.x.rmsLo
            yRms = calFiles.y.rmsLo
            zRms = calFiles.z.rmsLo
        else:
            xRms = calFiles.x.rms
            yRms = calFiles.y.rms
            zRms = calFiles.z.rms

        Sxy = calc_trans(zRms.x, zRms.y, zRms.z, cal.x, cal.y, cal.z)
        Syz = calc_trans(xRms.y, xRms.z, xRms.x, cal.y, cal.z, cal.x)
        Sxz = calc_trans(yRms.z, yRms.x, yRms.y, cal.z, cal.x, cal.y)

        return (Sxy, Syz, Sxz)

    
    def calculateOffset(self, gain, mean, gravity):
        """
        """
        gm = gain * mean
        return gravity - gm


    def calculate(self, filenames=None, calAxes=None, calAxesLo=None):
        """ Calculate the high-g accelerometer!
            
            @param filenames: A set of IDE calibration recording filenames.
                If `None`, the device will be scanned.
            @param calAxes: A set of three values, -1 or 1, indicating any
                flipped axes on the primary accelerometer. Overrides the axis
                flips for the specific device being calibrated.
            @param calAxesLo: A set of three values, -1 or 1, indicating any
                flipped axes on the secondary accelerometer. Overrides the axis
                flips for the specific device being calibrated.
        """
        # TODO: Check for correct number of files?
        self.calDate = datetime.now()
        self.calTimestamp = int(time.mktime(time.gmtime()))

        self.filenames = filenames

        if filenames is None:
            if self.dev is None:
                raise ValueError("No recorder or recording files specified!")
            filenames = self.getFiles()

        # Read calibration recordings. Sets `calFiles` and `calFilesUnsorted`
        calFiles = [AccelCalFile(f, self.dev, skipSamples=self.skipSamples) 
                                 for f in filenames]
        self.sortCalFiles(calFiles)

        # If only working from files (e.g. just recalculating calibration from
        # existing data), get the device from the recordings.
        if self.dev is None:
            self.dev = self.calFiles[0].dev

        # Handle inverted axes
        calAxes, calAxesLo = self.getAxisFlips(self.dev, calAxes, calAxesLo)

        self.basenames = XYZ(os.path.basename(c.filename) for c in self.calFiles)
        self.cal = XYZ(self.calFiles[i].cal[i] * calAxes[i] for i in range(3))
        
        # This is probably overkill (all files should be the same)
        self.hasHiAccel = all(c.hasHiAccel for c in self.calFiles)
        self.hasLoAccel = all(c.hasLoAccel for c in self.calFiles)
        
        # All CalFiles will have 'non-Lo' calibration values. For SSC, these
        # will be the same as the DC accelerometer values.
        self.trans = self.calculateTrans(self.calFiles, self.cal)

        self.meanCalTemp = np.mean([cal.cal_temp for cal in self.calFiles])
        self.meanCalPress = np.mean([cal.cal_press for cal in self.calFiles])
        
        if all(cal.cal_humid for cal in self.calFiles):
            self.meanCalHumid = np.mean([cal.cal_humid for cal in self.calFiles])

        self.offsets = XYZ()
        gravity = self.getGravity(self.dev, self.calFiles)
        print("Calibration values:")
        for i, axis in enumerate('XYZ'):
            self.offsets[i] = self.calculateOffset(self.cal[i], self.calFiles[i].means[i], gravity[i])
            print(f"  {axis}: cal={self.cal[i]!r},\tmean={self.calFiles[i].means[i]!r},\toffset={self.offsets[i]}")

        if self.hasHiAccel and not self.hasLoAccel:
            self.offsetsLo = XYZ(None, None, None)
            self.calLo = XYZ(None, None, None)
            self.transLo = None
            return

        self.calLo = XYZ([self.calFiles[i].calLo[i] * calAxesLo[i] for i in range(3)])
        self.transLo = self.calculateTrans(self.calFiles, self.calLo, low=True)

        self.offsetsLo = XYZ()
        for i in range(3):
            self.offsetsLo[i] = self.calculateOffset(self.calLo[i], self.calFiles[i].meansLo[i], gravity[i])

        print()

    #===========================================================================
    #
    #===========================================================================

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
        
        name = kwargs.pop('name', (self.dev.productName or self.dev.partNumber))
        
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
            sessionId=self.sessionId, defaults=calArgs)

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
            calId = self.CAL_IDS[(subchannel.parent.id, subchannel.id)]
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
    
    
    #===========================================================================
    # 
    #===========================================================================

    def createCalLogEntry(self, filename, chipId, mode='at'):
        """ Record this calibration session in the log file.
        """
        entry = map(str, (time.asctime(), self.calTimestamp, chipId,
                      self.dev.serialInt, self.isUpdate, self.sessionId))
        util.writeFileLine(filename, ','.join(entry), mode=mode)
