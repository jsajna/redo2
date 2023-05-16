import numpy as np
import idelib
from scipy.signal import butter, sosfilt

class CalibrationFileManager:

    def __init__(self):
        self.sampleRates = {}
        self.shakenID = None

    def findShakeSegment(self, accelChannel, start_time=None, end_time=None, smallThres=3, bigThres=5):
        # this beginning stuff will prob need to be separated, bc findFlatSegment should operate at same level without repeating calculations!
        # Turn off existing per-channel calibration (if any)
        for c in accelChannel.children:
            c.setTransform(None)
        accelChannel.updateTransforms()

        a = accelChannel.getSession()  # using channel event array
        a.removeMean = False

        if accelChannel.id not in self.sampleRates:
            self.sampleRates[accelChannel.id] = a.getSampleRate()  # store entire channel's sample rate

        if self.sampleRates[accelChannel.id] < 1000:
            raise CalibrationError(
                f"Channel {accelChannel.id} ({accelChannel.name}) had a low sample rate: {self.sampleRates[accelChannel.id]} Hz")

        if not self.shakenID:
            self.shakenID = self.calcShaken(a.arrayRange(start_time, end_time))

        data = np.flip(np.rot90(a.arrayRange(start_time, end_time)), axis=0)  # data has ALL values (not necessarily starting at 0)
        # version where Correct indexes are found from the original set of data

        # data is sectioned to the indexes found from the timestamps given

        subch_section = data[:, self.shakenID]
        # only get the start and end index for the axis that has been shaken.
        shakeStartIndex = self.getPassingIndex(subch_section, bigThres)
        shakeEndIndex = len(subch_section) - self.getPassingIndex(np.flipud(subch_section), bigThres) - 1
        # print(f"{shakeStartIndex}: {data[shakeStartIndex][0]},  {shakeEndIndex}: {data[shakeEndIndex][0]}")
        print(f"SHAKE TIME_RANGE TUPLE WILL BE: {data[shakeStartIndex][0], data[shakeEndIndex][0]}")
        # TODO: consider passing the highpass filter data instead of the normal data?
        highpass = 10
        hp_data = np.copy(np.flip(np.rot90(a[:]), axis=0))
        print(hp_data.shape)

        for i in range(1, min(4, hp_data.shape[1])):
            hp_data[:, i] = self.passFilter(hp_data[:, i], highpass, self.sampleRates[accelChannel.id], "high")

        print(f"HP {hp_data}")
        print(hp_data.shape)

        skipSamples = 2001
        if skipSamples:
            hp_data = hp_data[skipSamples:-skipSamples]  # Shave off skipSamples points from the beginning and end
            print(f"\t{skipSamples} skip Samples has been shaved off the beginning + end")
        print(f"HPSHAPE {hp_data.shape}")
        hp_data = hp_data[shakeStartIndex:shakeEndIndex]
        # print(hp_data)
        print(f"SHAKE RMS WILL BE: {self.getRMS(hp_data)}")

    def findFlatSegment(self, accelChannel, start_time=None, end_time=None):
        a = accelChannel.getSession()
        a.removeMean = False
        data = np.flip(np.rot90(a.arrayRange(start_time, end_time)), axis=0)

        if accelChannel.id not in self.sampleRates:
            self.sampleRates[accelChannel.id] = a.getSampleRate()

        if not self.shakenID:
            self.shakenID = self.calcShaken(a.arrayRange)

        subch_section = data[:, self.shakenID]
        iQuietStart, iQuietEnd = self.getQuietestSection(accelChannel.id, subch_section, time=1)
        timeQuietStart, timeQuietEnd = data[iQuietStart][0], data[iQuietEnd][0]
        print(f"QUIET TIME_RANGE TUPLE WILL BE: {timeQuietStart, timeQuietEnd}")
        print(f"QUIET RMS WILL BE: {self.getRMS(data[iQuietStart:iQuietEnd, 1: ])}")

    def passFilter(self, data, cutoff, fs, btype, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        sos = butter(order, normal_cutoff, btype=btype, analog=False, output='sos')
        y = sosfilt(sos, data)
        return y

    def getRMS(self, data):
        avg_midpt = np.mean(data, axis=0)
        # not subtracting midpt
        # print(data, " is accx")
        return np.sqrt(np.mean(np.square(data), axis=0))

    def getQuietestSection(self, id, data, time, searchOverlap=0.5):
        span = self.calcIndices(self.sampleRates[id], 0, time)[0]
        minStandardDeviation = None
        bestStartIndex = None
        dataLength = len(data)
        if not searchOverlap > 0.9:  # Too large an overlap would mean we move backwards
            searchOverlap = 0.9

        # TODO: should I triple this? average the standard deviations for all subchannels & grab the lowest?
        for startIndex in range(0, dataLength - span, int(span * (1-searchOverlap))):  # <span> amt of data is checked in overlaps of searchOVerlap %
            thisStandardDeviation = np.std(data[startIndex:startIndex + span])  # std of the set span of data from here is taken
            if minStandardDeviation is None or thisStandardDeviation < minStandardDeviation:
                minStandardDeviation = thisStandardDeviation
                bestStartIndex = startIndex
            # print(f"Index {startIndex}, StdDev {thisStandardDeviation:0.4f}")
        # print(f"Selecting index {bestStartIndex} ({minStandardDeviation=:0.4f})")
        return bestStartIndex, bestStartIndex + span

    def calcShaken(self, ch_arr):
        subch = ch_arr[1:]  # exclude 0th array of time values
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

    def findSubchannelGain(self, subchannel, target_amplitude):
        """ Find the target gain for the segment of subchannel provided to meet the target_offset
        """
        if self.is8gOrLess(subchannel):
            self.refRMS = 2.82843  # RMS_4g 4*(2**.5)/2
        else:
            self.refRMS = 7.075  # RMS_10g = 10*(2**.5)/2
        print(self.refRMS, " is REFRMS")

        print(f"SUBCHANNEL GAIN FOUND: {self.refRMS / target_amplitude}")
        return self.refRMS / target_amplitude

    def findSubchannelOffset(self, subchannel, target_offset, sampRate, lowpass=2.55):
        """ Find the target offset for the segment of subchannel provided to meet the target_offset
        """
        if lowpass:
            # Apply lowpass filter
            subchannel = self.passFilter(subchannel[:, 1], lowpass, sampRate, "low")

        # no filter, just explicitly remove the mean.
        return subchannel.mean()

    #def compensateGainOffset(self, initial_gain, initial_offset, uncompensated_gain, uncompensated_offset):

#    def getGravity(self, dev, ):

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


class CalibrationError(ValueError):
    """ Exception raised when some part of calibration fails.
    """
    def __init__(self, *args):
        if args:
            self.message = str(args[0])
        super(CalibrationError, self).__init__(*args)


with idelib.importFile("jas_calibrationex\\DAQ11620_000007.IDE") as ds:
    ch = ds.channels[80]  # 80 is 40g (secondary acc)
    for subch in ds.channels[80].subchannels:
        print(subch.sensor.name.upper())
    # print(ch)
    # print(ds.channels)

CalManager = CalibrationFileManager()
CalManager.findShakeSegment(ch, start_time=5.162e+6, end_time=5.41187e+6)
# segment = ch.subchannels[0].getSession().arrayRange(startTime=4732439.536806342, endTime=10942348.859569648)
CalManager.findSubchannelGain(ch.subchannels[0], 6.55441305)
# CalManager.findFlatSegment(ch, start_time=12.1702e+6, end_time=16.0066e+6)
