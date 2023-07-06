"""
Script for handling shake profiles, used by calibration.py
"""

from dataclasses import dataclass
from enum import Enum
import numpy as np
from typing import List, Union, Optional, Tuple
from endaq.ide import to_pandas
from endaq.calc.filters import butterworth


class DelayType(Enum):
    """ Delay types for organizing the delays of a shakeprofile """
    START = "start"
    MIDDLE = "middle"
    END = "end"

@dataclass
class Peak:
    """ Represents a peak out of a dataset - used after the derivative is taken of a profile recording """
    time_series: List[float]
    values: List[float]

    def __post_init__(self):
        if len(self.time_series) != len(self.values):
            raise ValueError("Time series and values arrays must have the same length.")
        maxidx = np.argmax(np.abs(self.values))
        self.max_val = self.values[maxidx]
        self.peak_time = self.time_series[maxidx]
        self.ramp_up = self.max_val > 0
        self.first_time = self.time_series[0]
        self.last_time = self.time_series[-1]


class Shake:
    """ A single shake of a shake profile """
    def __init__(self, amp: Union[int, float], length: Union[int, float],
                 ramp_up: Union[int, float], ramp_down: Union[int, float], freq: int):
        self.amp = amp
        self.length = length
        self.ramp_up = ramp_up
        self.ramp_down = ramp_down
        self.freq = freq
        self.start = None  # will be in microseconds
        self.end = None
        self.startIndex = None
        self.endIndex = None
        self.next = None  # reference to the next section
        self.prev = None  # reference to the previous section

    def determineStartEnd(self, offsetTime: Union[int, float]) -> Union[int, float]:
        """ initial placement of expected timings
            @param offsetTime: the time covered so far
            @return: new time covered so far after this shake """
        self.start = offsetTime + self.ramp_up
        self.end = self.start + self.length
        return self.end + self.ramp_down

    def setIndices(self, sampRate: Union[int, float], shift: Union[int, float]):
        """ determine the index placements compared to the full set of data
            @param sampRate: sample rate of channel
            @param shift: the starting value of the channel """
        # shift is assumed to be in SECONDS
        self.startIndex = int(sampRate * (self.start - shift))
        self.endIndex = int(sampRate * (self.end - shift))

    def setPrev(self, prevSection):
        """  connect the previous section to this section
            @param prevSection: Shake or Delay (most likely Delay)
        """
        if prevSection:
            prevSection.next = self
        self.prev = prevSection

    def setPrevEnd(self, time: Union[int, float]):
        """ adjust the end time of the section before this one
            @param time: time in microseconds for the last's end
        """
        if self.prev:
            self.prev.end = time

    def setNextStart(self, time: Union[int, float]):
        """ adjust the start time of the section after this one
            @param time: time in microseconds for the next's start
        """
        if self.next:
            self.next.start = time

    def __repr__(self):
        return f"{self.start} - SHAKE - {self.end}"


class Delay:
    """ A Delay section out of a shake profile """
    def __init__(self, min_len: Union[int, float], delay_type: Union[int, float]):
        self.min_len = min_len
        self.delay_type = delay_type
        self.start = None
        self.end = None
        self.startIndex = None
        self.endIndex = None
        self.next = None
        self.prev = None

    def determineStartEnd(self, offsetTime: Union[int, float]) -> Union[int, float]:
        """ initial placement of expected timings
            @param offsetTime: the time covered so far
            @return: new time covered so far after this shake """
        self.start = offsetTime
        self.end = self.start + self.min_len
        return self.end

    def setPrev(self, prevSection):
        """  connect the previous section to this section
            @param prevSection: Shake or Delay (most likely Shake)
        """
        if prevSection:
            prevSection.next = self
        self.prev = prevSection

    def setIndices(self, sampRate: Union[int, float], shift: Union[int, float]):
        """ determine the index placements compared to the full set of data
            @param sampRate: sample rate of channel
            @param shift: the starting value of the channel """
        # shift is assumed to be in SECONDS
        self.endIndex = int(sampRate * (self.end - shift))
        if self.delay_type == DelayType.START:
            shift = 0
        self.startIndex = int(sampRate * (self.start - shift))

    def __repr__(self):
        return f"{self.start} - DELAY - {self.end}"


class ShakeProfile:
    """ Describe the shakes and delays used in the calibration """
    def __init__(self, shakes_delays):
        """ Constructor
        @param shakes_delays: List of Delays, Shakes in the order they occur """

        self.shakes_delays = shakes_delays
        self.organizeOrder()
        self.shakes = [section for section in self.shakes_delays if type(section) == Shake]
        self.delays = [section for section in self.shakes_delays if type(section) == Delay]
        self.time = sum(shake.ramp_up + shake.length + shake.ramp_down for shake in self.shakes) + \
                    sum(delay.min_len for delay in self.delays)

        self.setTimesForAll(shakes_delays)

    def setTimesForAll(self, shakes_delays):
        """ initial placement of expected timings for all sections
            @param shakes_delays: list of Shakes, Delays in order """
        timeSoFar = 0
        for item in shakes_delays:
            timeSoFar = item.determineStartEnd(timeSoFar)

    def organizeOrder(self):
        """ establish the connection between all sections so they may be referenced from each other """
        prev = None
        for section in self.shakes_delays:
            section.setPrev(prev)
            prev = section

    def adjustProfile(self, shakenSCH):
        """ adjust the placement of the shakes and delays by actually looking at data
        @param shakenSCH: Dataset.Subchannel that was shaken
        """

        data = to_pandas(shakenSCH, 'seconds')
        peaks = []
        for shake in self.shakes:
            only_shake = butterworth(data, low_cutoff=shake.freq - 5, high_cutoff=shake.freq + 5)

            # grab an outline of the data
            outline = self.get_outline(only_shake)  # first row is time, second is values

            # take the derivative of the outline, peaks occur where ramping up/down
            deriv = np.gradient(outline[1], outline[0])

            if peaks:
                # isolate the peaks themselves into separate objects in a list
                peaks.extend(self.get_peaks(outline[0], deriv, data.index[-1]))
            else:
                peaks = self.get_peaks(outline[0], deriv, data.index[-1])

        # using the found peaks, adjust the placement of the shakes by the times of the peaks
        num_peaks = len(peaks)
        if num_peaks / 2 == len(self.shakes):  # peaks[i] should be ramp up & i+1 next is ramp down
            # The first peak is assumed to signal the start of the first shake
            for i in range(0, num_peaks, 2):
                self.shakes[i // 2].start = peaks[i].last_time
                self.shakes[i // 2].end = peaks[i + 1].first_time
                self.shakes[i // 2].setPrevEnd(peaks[i].first_time)
                self.shakes[i // 2].setNextStart(peaks[i + 1].last_time)

        if self.delays[-1].delay_type == DelayType.END:
            self.delays[-1].end = data.index[-1]

    def get_outline(self, values: np.ndarray) -> np.ndarray:
        """ grab the outline of the shake
        @param values: raw data array
        @param sampleRate: sample rate of channel """

        # organize data into even sections of 500 (disregard leftovers)
        n = values.shape[0]
        num_sections = n // 500
        leftovers = n % 500

        # shave off an equal amt from the beginning and end so the data is a multiple of 500
        if leftovers:
            values = values.iloc[int(leftovers / 2) + int(leftovers % 2 != 0): -int(leftovers / 2)]

        # reshaping the data so that the max of each can be found using the axis instead of a for loop
        signaldata = values.values.reshape(num_sections, 500)
        timedata = values.index.values.reshape(num_sections, 500)
        idxmax = signaldata.argmax(axis=1)

        # store the max value (from the lowpass filter) and time of max value
        new_values = np.empty((2, num_sections))
        new_values[0] = timedata[np.arange(timedata.shape[0]), idxmax]
        new_values[1] = signaldata[np.arange(timedata.shape[0]), idxmax]
        return new_values

    def get_peaks(self, time: np.ndarray, deriv: np.ndarray, lastTime: Union[int, float]) -> list:
        """ Find the two peaks associated with a single shake's derivative
            Peaks will be at the ramp-up and the ramp-down
            @param time: time series of the deriv
            @param deriv: derivative values from the shake
            @param lastTime: the end time of the recording """
        def cut_off_time(time: np.ndarray, deriv: np.ndarray,
                         thresh: Union[float, int]=1.5) -> Tuple[np.ndarray, np.ndarray]:
            """ determine the section that corresponds to a shake
                @param time: time series
                @param deriv: the derivative of the events at the times
                @param thresh: the cutoff for determining that a peak exists
                @return: the time and derivative series that holds a peak """
            start_idx = 0
            end_idx = -1
            # check the first point that passes the deriv. threshold
            for i, value in enumerate(time):
                if value >= thresh:
                    start_idx = i
                    break
            # check the last point that passes the deriv. threshold
            for i, value in enumerate(np.flip(time)):
                if lastTime - value >= thresh:
                    end_idx = time.shape[0] - i
                    break

            # The shake exists between these two points
            return time[start_idx:end_idx], deriv[start_idx:end_idx]

        time, deriv = cut_off_time(time, deriv)
        max = deriv.argmax()
        min = deriv.argmin()
        rampup = Peak([time[max]], [deriv[max]])  # derivative is increasing
        rampdown = Peak([time[min]], [deriv[min]])  # derivative is decreasing
        return [rampup, rampdown]

    def shiftIndices(self, sampRate, shift=0):
        """ shift the indices according to the start of the recording
        @param sampRate: sample rate of the data
        @param shift: the starting time of the data """
        for section in self.shakes_delays:
            section.setIndices(sampRate, shift)

    def shave(self, shift: int):
        """ shave the shift off from the beginning and end & adjust the indices accordingly
        @param shift: the number of samples being shaved off to shift by """
        for shake in self.shakes:
            shake.startIndex -= shift
            shake.endIndex -= shift
        for delay in self.delays:
            if delay.delay_type != DelayType.START:
                delay.startIndex -= shift
            if delay.delay_type == DelayType.END:
                shift = 2 * shift
            delay.endIndex -= shift


order_10g_4g = [Delay(min_len=1e6, delay_type=DelayType.START),
                Shake(amp=10.0, length=5e6, ramp_up=3e6, ramp_down=3e6, freq=100),  # 5s 10g shake, 3s start-up/cool
                Delay(min_len=3e6, delay_type=DelayType.MIDDLE),
                Shake(amp=4.0, length=5e6, ramp_up=2e6, ramp_down=2e6, freq=150),  # 5s 4g shake, with 2s start-up/cool
                Delay(min_len=1e6, delay_type=DelayType.END)]

order_10g = [Delay(min_len=1e6, delay_type=DelayType.START),
            Shake(amp=10.0, length=5e6, ramp_up=3e6, ramp_down=3e6, freq=100),
            Delay(min_len=1e6, delay_type=DelayType.END)]


profile_10g_4g = ShakeProfile(order_10g_4g)
profile_10g = ShakeProfile(order_10g)

exp_profile = profile_10g_4g
exp_order = order_10g_4g

