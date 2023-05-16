import idelib.dataset
from idelib.transforms import Univariate, Bivariate
from idelib import importFile
import endaq.device as ed
import openpyxl
from util import XYZ
import endaq.ide as ei


def checkCalibration(lib):
    gains = lib.gains
    offsets = lib.offsets
    channels = lib.channels
    avgs = XYZ()
    for j in range(3):
        avg = XYZ(None)
        for i in range(3):
            cal = Univariate(coeffs=[gains[i], offsets[i]])
            sch = channels[j].subchannels[i]
            sch.setTransform(cal, True)
            df = ei.to_pandas(sch, "seconds")
            avg[i] = float(df.mean(axis=0))
        avgs[j] = avg
    return avgs


