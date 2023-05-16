import numpy as np
import idelib
from scipy.signal import butter, sosfilt
from fnmatch import fnmatch
from util import XYZ
import endaq.device as ed

import os
import plotly.graph_objs as go

fig = go.Figure()

class CalibrationFileManager:

    def __init__(self, dev, accelChannel, isLo, calAxes, shakenID=None, skipTime=2):
        self.accelChannel = accelChannel
        self.shakenID = shakenID  # ID represents id of subch in format [time, x1, x2, x3]
        self.dev = dev
        self.rms = None
        self.shakeTimes = None
        self.quietTimes = None
        self.mean = None
        self.gain = None
        self.compensatedGains = None
        self.compensatedOffset = None
        self.isLo = isLo
        self.calAxes = calAxes
        self.span = None
        self.start = None
        self.sampleRate = None
        self.gravity = None
        self.skipTime, self.skipSamples = skipTime, None
        self.shakenAmp = None
        self.shakenOffset = None

    def analyzeUpToGravity(self):
        # TODO: consider determining a start and end analysis of a channel
        self.shakenAmp, self.rms, self.shakeTimes = self.findShakeSegment(self.accelChannel)
        self.gain = self.findSubchannelGain(self.accelChannel.subchannels[self.shakenID - 1], self.calAxes)
        self.quietTimes = self.findFlatSegment(self.accelChannel)
        self.shakenOffset = self.findShakenOffset(self.accelChannel, self.quietTimes, self.gain)

        # self.offset means is currenly calculated when findFlatSegment is called - this should prob be moved out

    def getInitialTimeNarrow(self):
        """using self.accelChannel, abstract out the skip time & shaving calcultions from find shake and findflat"""

        pass

    def findShakeSegment(self, accelChannel, startTime=None, endTime=None, smallThres=3, bigThres=6):
        # this beginning stuff will prob need to be separated, bc findFlatSegment should operate at same level without repeating calculations!
        # Turn off existing per-channel calibration (if any)
        for c in accelChannel.children:
            c.setTransform(None)
        accelChannel.updateTransforms()

        a = accelChannel.getSession()  # using channel event array
        a.removeMean = False

        if not self.sampleRate:
            self.sampleRate = a.getSampleRate()  # store entire channel's sample rate

        if self.sampleRate < 1000:
            raise CalibrationError(
                f"Channel {accelChannel.id} ({accelChannel.name}) had a low sample rate: {self.sampleRate} Hz")

        if not self.shakenID:
            self.shakenID = self.calcShaken(a.arrayRange(startTime, endTime)[0:4])

        print(f"\nSUBCHANNEL SEARCH {self.shakenID} of {self.accelChannel}")
        data = np.flip(np.rot90(a.arrayRange(startTime, endTime)[0:4]),
                       axis=0)  # data has ALL values (not necessarily starting at 0)
        print(f"data rn is {data.shape} sized")

        # TODO: consider passing the highpass filter data instead of the normal data?
        highpass = 10
        hpData = np.copy(np.flip(np.rot90(a[:]), axis=0))  # this is same as data above^ & can use data in loop below

        for i in range(1, min(4, hpData.shape[1])):
            hpData[:, i] = self.Filter(hpData[:, i], highpass, self.sampleRate, "high")

        # not sure why skipSamples is used? this is hardcoded in rn to match up with the gain values
        if self.skipTime and self.sampleRate:
            self.skipSamples = int(self.skipTime * self.sampleRate)
            print(f"skip samples is {self.skipSamples}")

        if self.skipSamples:
            data = data[self.skipSamples:-self.skipSamples]
            hpData = hpData[
                     self.skipSamples:-self.skipSamples]  # Shave off skipSamples points from the beginning and end

        subchSection = hpData[:, self.shakenID]

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=data[:, 0], y=data[:, 1], mode='lines', name=f'OG {accelChannel} {1}'))
        fig.add_trace(go.Scatter(x=hpData[:, 0], y=hpData[:, 1], mode='lines', name=f'HP {accelChannel} {1}'))
        fig.show()
        # only get the start and end index for the axis that has been shaken.
        print(f"smallShakeThresh = {smallThres}, bigShakeThresh = {bigThres}")

        shakeStartIndex = self.getPassingIndex(subchSection, bigThres)
        shakeEndIndex = len(subchSection) - self.getPassingIndex(np.flipud(subchSection), bigThres) - 1
        #TODO: change the shake indices that are used (switches to 1000 after index found & ends 1000 after)
        shakeEndIndex = shakeStartIndex + 2000
        shakeStartIndex = shakeStartIndex + 1000
        print(f"shakeStartIndex is {shakeStartIndex}, EndIndex is {shakeEndIndex}")
        print(f"ShakeStartTime is {hpData[shakeStartIndex][0]} and ends at {hpData[shakeEndIndex][0]}")

        # print(f"STARTERS {shakeStartIndex}: {hpData[shakeStartIndex][0:2]},  {shakeEndIndex}: {hpData[shakeEndIndex][0:2]}")
        # print(f"SHAKE TIME_RANGE TUPLE WILL BE: {data[shakeStartIndex][0], data[shakeEndIndex][0]}")

        hpData = hpData[shakeStartIndex:shakeEndIndex]

        #TODO: maybe change the getRMS to consider the 1st to 99th percentile like the amplitude is found from
        amp_rms = self.getRMS(hpData[:, 1:4])
        amp_factor = self.getReliableAmp(hpData[:, self.shakenID])
        return amp_factor, XYZ(amp_rms), (hpData[0][0], hpData[-1][0])

    def findFlatSegment(self, accelChannel, startTime=None, endTime=None, startidx=0, endidx=-1):
        a = accelChannel.getSession()
        a.removeMean = False
        data = np.flip(np.rot90(a.arrayRange(startTime, endTime)), axis=0)

        if not self.sampleRate:
            self.sampleRate = a.getSampleRate()

        if self.skipTime and self.sampleRate:
            self.skipSamples = int(self.skipTime * self.sampleRate)
            print(f"skip samples is {self.skipSamples}")

        if self.skipSamples:
            data = data[self.skipSamples:-self.skipSamples]

        if not self.shakenID:
            self.shakenID = self.calcShaken(a.arrayRange)
        subchSection = data[startidx:endidx, self.shakenID]  #TODO: why start and endidx if skipSamples & using only defaults??

        iQuietStart, iQuietEnd = self.getQuietestSection(accelChannel.id, subchSection, time=1)
        timeQuietStart, timeQuietEnd = data[iQuietStart][0], data[iQuietEnd][0]
        iQuietStart = iQuietStart + startidx
        self.mean = self.findSubchannelQuietMean(data, iQuietStart, iQuietEnd,
                                                 self.sampleRate)
        print(f"the Quiet Time analyzed is {timeQuietStart} to {timeQuietEnd}")
        return timeQuietStart, timeQuietEnd  # dont think the amplitudes of the silent regions get used

    def findShakenOffset(self, accelChannel, quietTimes, gain):
        for c in accelChannel.children:
            c.setTransform(None)
        accelChannel.updateTransforms()

        a = accelChannel.getSession()  # using channel event array
        a.removeMean = False
        print(f"THIS IS {type(a)}")
        # TODO: section the data to grab the quiet time of the shaken subchannel
        return 0
    def Filter(self, data, cutoff, fs, btype, order=5):
        nyq = 0.5 * fs
        normalCutoff = cutoff / nyq
        sos = butter(order, normalCutoff, btype=btype, analog=False, output='sos')
        y = sosfilt(sos, data)
        return y

    def getReliableAmp(self, data):
        """ Determines the amplitude of the shake """
        lowBound, highBound = np.percentile(data, [1, 99])
        print(f"98% of the data exists between {lowBound} and {highBound}")
        amp = (highBound - lowBound) / 2
        return amp

    def getRMS(self, data):
        return np.sqrt(np.mean(np.square(data), axis=0))  # subtract avg_midpt from data

    def getQuietestSection(self, id, data, time, searchOverlap=0.5):
        span = self.calcIndices(self.sampleRate, 0, time)[0]
        minStandardDeviation = None
        bestStartIndex = None
        dataLength = len(data)
        # print(f"DATA ITSELF has shape {data.shape}: {data}")
        if searchOverlap > 0.9:  # Too large an overlap would mean we move backwards
            # TODO: maybe convert this to comparing the number of samples to the size assessed
            searchOverlap = 0.9
        # TODO: should I triple this? average the standard deviations for all subchannels & grab the lowest?

        for startIndex in range(0, dataLength - span, int(span * (
                1 - searchOverlap))):  # <span> amt of data is checked in overlaps of searchOVerlap %
            thisStandardDeviation = np.std(
                data[startIndex:startIndex + span])  # std of the set span of data from here is taken
            # print(f"STDEV FOR {startIndex} is ", thisStandardDeviation)
            if minStandardDeviation is None or thisStandardDeviation < minStandardDeviation:
                minStandardDeviation = thisStandardDeviation
                bestStartIndex = startIndex
        # print(f"BEST START QS: {bestStartIndex}")
        # print(f"Index {startIndex}, StdDev {thisStandardDeviation:0.4f}")
        return bestStartIndex, bestStartIndex + span

    @classmethod
    def calcShaken(cls, chArr):
        subch = chArr[1:]  # exclude 0th array of time values
        stdevs = np.std(subch, axis=1)
        # the shaken channel id is saved (determined by which has highest stdev)
        return stdevs.argmax() + 1

    def calcIndices(self, sampRate, offset, *args):
        return [int((time - offset) * sampRate) for time in args]

    def getPassingIndex(self, data, thres):
        for index, number in enumerate(data):
            if abs(number) > thres:
                return index
        return None

    def findSubchannelGain(self, subchannel, calAxes):
        """ Find the target gain for the segment of subchannel provided to meet the target_offset
        """
        if self.is8gOrLess(subchannel):  # these target amplitudes are based on what we know the shaker makes
            targetAmplitude = 4
        else:
            targetAmplitude = 10
        return calAxes[self.shakenID - 1] * self.shakenAmp / targetAmplitude

    def findSubchannelQuietMean(self, subchannel, start, end, sampRate, lowpass=2.55):
        """ Find the target offset for the segment of subchannel provided to meet the target_offset
        """
        # print(subchannel)
        if lowpass:
            # Apply lowpass filter
            subchannel = self.Filter(subchannel[:, self.shakenID], lowpass, sampRate, "low")
            # print(f"FILTERED: {subchannel}")
        # no filter, just explicitly remove the mean.
        return subchannel[start:end].mean()

    def is8gOrLess(self, subch):
        """ Was the given channel recorded by a sensor that rails at 8g?
                    Used to avoid calibrating against railed data.
                """
        try:
            # XXX:HACK:TODO: use better method to get sensor range, maybe
            # the parent channel's calibration coefficients.
            return "ADXL355" in subch.sensor.name.upper()
        except (AttributeError, TypeError):
            raise
            # return False


class CalibrationDeviceLibrary(object):
    """ Library class to hold information of a single channel in a calibrating device
    """

    def __init__(self, dev: ed.Recorder, accelID):
        self.dev = dev
        self.accelID = accelID
        if accelID == 8:
            self.targetOffsets = XYZ(0, 0, 0)
        else:
            self.targetOffsets = XYZ(1, 1, 1)
        self.channels = XYZ(None)
        # self.chSession = channel.getSession()  reorganizing library
        self.calAxes = None  # 1 value each, doesn't need to be calculated with each IDE
        self.gravities = XYZ(None)
        self.targetOffsets = XYZ(None)
        self.means = XYZ(None)  # only storing 1 value each for the shaken subch of each IDE
        self.rmsIDEs = XYZ(XYZ(None))  # storing 1 value each for the amp. of ALL subch in the shake
        self.shakeTimes = XYZ(None)
        self.quietTimes = XYZ(None)
        self.offsets = XYZ(None)
        self.gains = XYZ(None)

    def assignFromManager(self, manager: CalibrationFileManager, shakenID: int):
        """ Assign the calibration related values from the accel channel file manager to the
            accelerometer specific library
            @param manager: CalibrationFileManager of a specific accelerometer channel
            @param shakenID: int of the ID to index from values for where to place the shaken values of importance
        """
        self.dev = manager.dev
        self.channels[shakenID] = manager.accelChannel
        self.rmsIDEs[shakenID] = manager.rms
        self.shakeTimes[shakenID] = manager.shakeTimes
        self.quietTimes[shakenID] = manager.quietTimes
        # self.gravities[shakenID] = manager.gravity
        self.calAxes = manager.calAxes
        self.means[shakenID] = manager.mean
        # self.offsets[shakenID] = manager.compensatedOffset
        self.gains[shakenID] = manager.gain

    def getOffsets(self, gravity):
        self.gravities = gravity

        gm = self.gains * self.means
        self.offsets = gravity - gm

    def printer(self):
        print(f"\nA Calibration Device Library of Channel {self.channels[0]}")
        print(f"\t**GAINS: {self.gains}")
        print(f"\t**OFFSETS: {self.offsets}")
        print(f"\tMeans of Shaken Subchannels: {self.means}")
        print(f"\tCalAxes Coefficients: {self.calAxes}")
        print(f"\tGravity Coefficients: {self.gravities}")
        print(f"\tRMS IDEX: {self.rmsIDEs.x}")
        print(f"\tRMS IDEY: {self.rmsIDEs.y}")
        print(f"\tRMS IDEZ: {self.rmsIDEs.z}")
        print(f"\tShake Time Range: {self.shakeTimes}")
        print(f"\tQuiet Time Range: {self.quietTimes}")


class Calibrator2(object):
    """ starting fresh & planning on working this into the Calibrator class
    """
    KNOWN_HI_ACCEL_CHANNELS = (0, 8, 80)
    KNOWN_LO_ACCEL_CHANNELS = (32, 80)

    def __init__(self, idefileLocation, filenames=None, dev=None, sessionId=None, calHumidity=None,
                 calTempComp=-0.30, certificate=None, reference=None,
                 skipSamples=None, user=None, workDir=None):  # USER was temp. removed
        self.dev = dev
        if dev:
            self.devPath = dev.path
        else:
            self.devPath = None

        if idefileLocation and not filenames:
            filenames = [str(idefileLocation) + "\\" + file for file in os.listdir(idefileLocation)]

        with idelib.importFile(filenames[0]) as ds:
            self.dev = ed.fromRecording(ds)
        """
        # I dont understand the getFiles method
        print(f"Getting into getFiles")
        filenames = self.getFiles(path=idefileLocation)  # TODO: need to work around possibility that no location is given.
        print(f"idefilelocation {idefileLocation}, filenames = {filenames}")
        """
        self.idefiles = filenames

        self.ideshakes = XYZ(None)  # ? Do I need to have the ide's in order anywhere?
        self.lowAccelID = None
        self.highAccelID = None

        #TODO: change this to grabA ALL accelerometers (<2 or >2)
        ide = self.idefiles[0]  # grabbing any ide to determine the hi and lo accelerometer
        with idelib.importFile(ide) as ds:
            for chId in ds.channels.keys():
                if chId in self.KNOWN_HI_ACCEL_CHANNELS and not self.highAccelID:
                    self.highAccelID = chId
                elif chId in self.KNOWN_LO_ACCEL_CHANNELS and not self.lowAccelID:
                    self.lowAccelID = chId

        #TODO: make this work with list comprehension maybe-look into creating attributes for each, hashtable/dict,
        self.loAccelLibrary = CalibrationDeviceLibrary(dev, self.lowAccelID)
        self.hiAccelLibrary = CalibrationDeviceLibrary(dev, self.highAccelID)
        self.getShakesInfo()

    def getFiles(self, path=None):
        """ Get the filenames from the device's last recording directory with
            3 IDE files. These are presumably the shaker recordings.
        """
        import os
        # path = self.dev.path if path is None else path
        ides = []
        for root, dirs, files in os.walk(os.path.join(path, 'DATA')):
            ides.extend(map(lambda x: os.path.join(root, x),
                            filter(lambda x: x.upper().endswith('.IDE'), files)))
            for d in dirs:
                if d.startswith('.'):
                    dirs.remove(d)
        return sorted(ides)[-3:]

    def getGravity(self, dev):
        """ Get the gravity directions of the data provided.

            @parameter dev: Device being looked at, so we know the accelerometers and inversions
            @parameter calFiles: x,y,z calibration data. main and low accelerometers
            @return: XYZ of the direction of gravity in each file
        """
        # FUTURE: Less hardcoding.
        pn = str(dev.partNumber).upper()

        # On Mini, use the 40 or 8 g accelerometer. Otherwise use the secondary (which is always 40g)
        if pn.startswith(('S1', 'S2')):
            activeFlips = self.hiAccelLibrary.calAxes
            activeMeans = self.hiAccelLibrary.means
        else:
            # if not self.hasLoAccel:
            #   print("No DC accelerometer found!")
            #  return XYZ([1, 1, 1])
            activeFlips = self.loAccelLibrary.calAxes
            activeMeans = self.loAccelLibrary.means
        measurement = [activeFlips[i] * activeMeans[i] for i in range(3)]
        gravity = [m / abs(m) for m in measurement]
        if gravity[2] != 1:
            raise CalibrationError("Got the wrong gravity vector on Z for some dumb reason")
        return XYZ(gravity)

    def getShakesInfo(self):
        # loop of 3 with inner 2
        # outer loop to handle the three IDE
        self.hiAccelLibrary.calAxes, self.loAccelLibrary.calAxes = self.getAxisFlips()
        for ide in self.idefiles:
            with idelib.importFile(ide) as ds:
                # making a filemanager for the high and low channels of one IDE file.
                managerLo = CalibrationFileManager(self.dev, accelChannel=ds.channels[self.lowAccelID], isLo=True,
                                                   calAxes=self.loAccelLibrary.calAxes)
                managerLo.analyzeUpToGravity()
                self.loAccelLibrary.assignFromManager(managerLo, managerLo.shakenID - 1)

                managerHi = CalibrationFileManager(self.dev, accelChannel=ds.channels[self.highAccelID], isLo=False,
                                                   calAxes=self.hiAccelLibrary.calAxes, shakenID=managerLo.shakenID)
                managerHi.analyzeUpToGravity()
                self.hiAccelLibrary.assignFromManager(managerHi, managerHi.shakenID - 1)

                self.ideshakes[managerLo.shakenID - 1] = ide
        grav = self.getGravity(self.dev)
        self.loAccelLibrary.getOffsets(grav)
        self.hiAccelLibrary.getOffsets(grav)
        self.hiAccelLibrary.printer()
        self.loAccelLibrary.printer()

    def getAxisFlips(self, calAxes=None, calAxesLo=None):
        """ Get the inverted axes specific to the device type.
        """
        dev = self.dev
        # FUTURE: Less hardcoding.
        pn = str(dev.partNumber).upper()
        mcu = str(dev.mcuType).upper()

        # TODO: change temporary complex if-else format!!
        # TODO: getting the channel to work with first instead of separating into hi and lo so only one return value is given!!

        if mcu.startswith('STM32'):
            # Analog accelerometer orientation varies by model
            if fnmatch(pn, "S?-E*"):
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            elif fnmatch(pn, "S?-R*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(pn, "W?-E*"):
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif fnmatch(pn, "W?-R*"):
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            else:
                # if not calAxes and calAxesLo:
                # logger.warning(f"Using default axis flips for unknown STM32 device type {pn!r}")
                calAxes = calAxes or (1, 1, -1)  # Channel 8

            # ADXL357 is the same for all STM32 S and W (as of HwRev 2.0.0 - 2.0.1)
            calAxesLo = calAxesLo or (-1, -1, 1)  # Channel 80

        elif pn.startswith(('S1', 'S2')):
            # "Mini" with 2 digital accelerometers
            calAxes = calAxes or (-1, -1, 1)  # Channel 80
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif fnmatch(pn, "S?-D16") or fnmatch(pn, "S?-D200"):
            # One digital accelerometer, old hardware (e.g., SSC equivalents for NAVAIR)
            calAxes = calAxes or (1, 1, -1)  # Does not really exist for this device
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif pn.startswith(('S3', 'S4', 'S5', 'S6', 'W5', 'W8')):
            if "-R" in pn:  # Piezoresistive device has axis flips
                calAxes = calAxes or (-1, -1, -1)  # Channel 8
            elif '-E' in pn:
                calAxes = calAxes or (1, 1, -1)  # Channel 8
            else:
                calAxes = calAxes or (-1, -1, 1)  # Channel 80 (the 'main' accelerometer for an Sx-D40)
            calAxesLo = calAxesLo or (-1, -1, 1)  # Channel 80
        elif pn.startswith('LOG-0004'):
            calAxes = calAxes or (-1, 1, -1)  # Channel 8
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        elif pn.startswith('LOG-0002'):
            calAxes = calAxes or (1, 1, -1)  # Channel 8
            calAxesLo = calAxesLo or (1, 1, 1)  # Channel 32
        else:
            # if not calAxes and calAxesLo:
            #   logger.warning(f"Could not get axis flips for device type {pn!r}")
            calAxes = calAxes or (1, 1, 1)
            calAxesLo = calAxesLo or (1, 1, 1)
        return XYZ(calAxes), XYZ(calAxesLo)


class CalibrationError(ValueError):
    """ Exception raised when some part of calibration fails.
    """

    def __init__(self, *args):
        if args:
            self.message = str(args[0])
        super(CalibrationError, self).__init__(*args)


"""
List of referenced attributes and methods that must be maintained
CALIBRATOR=============
workDir
birth
dev
calFiles
trans
cal
hasHiAccel
hasLoAccel
failure
session
meanCalHumid
certificate
reference
cancelled
calTimestamp
offsets
sessionID
calDir

calculate()
closefiles()
updateDatabase()
getFiles()
getCertifacteRecord()

ACCELCALFILE=============
__str__()
__repr__()

dev
cal
filename
hasHiAccel
hasLoAccel
cal_temp
cal_press
cal_humid
.means
accelChannel
accelChannelLo
filename
"""

"""
CalManager = CalibrationFileManager(dev, accelChannel=ch, isLo=True)
CalManager.findShakeSegment(ch, startTime=5.162e+6, endTime=5.41187e+6)
# segment = ch.subchannels[0].getSession().arrayRange(startTime=4732439.536806342, endTime=10942348.859569648)
CalManager.findFlatSegment(ch, startidx=40095, endidx=60107)
calAxes, calAxesLo = CalibrationFileManager.getAxisFlips(dev)
gain = CalManager.findSubchannelGain(ch.subchannels[0], 6.6449913, calAxesLo)
grav = CalManager.getGravity(dev, CalManager.offsetmean, XYZ(calAxesLo))
CalManager.compensateGainOffset(gain, CalManager.offsetmean, grav)
"""

clbrtr = Calibrator2(idefileLocation="jas_calibrationex")
from apply_transforms import checkCalibration

loPlacement = checkCalibration(clbrtr.loAccelLibrary)
# checkCalibration(clbrtr.hiAccelLibrary.gains, clbrtr.hiAccelLibrary.offsets, clbrtr.hiAccelLibrary.channels)
