import os

from calibration_retrial import Calibrator2
from calibration2 import Calibrator
import pytest
from util import XYZ
from apply_transforms import checkCalibration
import math
import endaq.device as ed
import idelib

filenames = lambda folder: {str(folder) + "\\" + file for file in os.listdir(folder)}

W0011620 = Calibrator2(idefileLocation="jas_calibrationex")
lowW0011620 = W0011620.loAccelLibrary
hiW0011620 = W0011620.hiAccelLibrary
OGW0011620 = Calibrator()
OGW0011620.calculate(filenames=filenames("jas_calibrationex"))

W0011379 = Calibrator2(idefileLocation="jas_calibrationex2")
lowW0011379 = W0011379.loAccelLibrary
hiW0011379 = W0011379.hiAccelLibrary
OGW0011379 = Calibrator()
OGW0011379.calculate(filenames=filenames("jas_calibrationex2"))

DAQ11940 = Calibrator2(idefileLocation="jas_calibrationex3")
lowDAQ11940 = DAQ11940.loAccelLibrary
hiDAQ11940 = DAQ11940.hiAccelLibrary
OGDAQ11940 = Calibrator()
OGDAQ11940.calculate(filenames=filenames("jas_calibrationex3"))

SSS09617 = Calibrator2(idefileLocation="jas_calibrationex4")
lowSSS09617 = SSS09617.loAccelLibrary
hiSSS09617 = SSS09617.hiAccelLibrary
OGSSS09617 = Calibrator()
OGSSS09617.calculate(filenames=filenames("jas_calibrationex4"))

SSX09546 = Calibrator2(idefileLocation="jas_calibrationex5")
lowSSX09546 = SSX09546.loAccelLibrary
hiSSX09546 = SSX09546.hiAccelLibrary
OGSSX09546 = Calibrator()
OGSSX09546.calculate(filenames=filenames("jas_calibrationex5"))

def test_Calibrator2_Constructor():
    assert W0011620.dev == W0011620.dev
    assert W0011620.devPath == W0011620.dev.path
    assert W0011620.lowAccelID == 80
    assert W0011620.highAccelID == 8
    assert W0011620.ideshakes == XYZ("jas_calibrationex\\DAQ11620_000007.IDE",
                                     "jas_calibrationex\\DAQ11620_000005.IDE",
                                     "jas_calibrationex\\DAQ11620_000006.IDE")

    assert W0011379.dev == W0011379.dev
    assert W0011379.devPath == W0011379.dev.path
    assert W0011379.lowAccelID == 80
    assert W0011379.highAccelID == 8
    assert W0011379.ideshakes == XYZ("jas_calibrationex2\\DAQ11379_000014.IDE",
                                     "jas_calibrationex2\\DAQ11379_000012.IDE",
                                     "jas_calibrationex2\\DAQ11379_000013.IDE")

    assert DAQ11940.dev == DAQ11940.dev
    assert DAQ11940.devPath == DAQ11940.dev.path
    assert DAQ11940.lowAccelID == 80
    assert DAQ11940.highAccelID == 8
    assert DAQ11940.ideshakes == XYZ("jas_calibrationex3\\DAQ11940_000006.IDE",
                                     "jas_calibrationex3\\DAQ11940_000004.IDE",
                                     "jas_calibrationex3\\DAQ11940_000005.IDE")

    assert SSS09617.dev == SSS09617.dev
    assert SSS09617.devPath == SSS09617.dev.path
    assert SSS09617.lowAccelID == 80
    assert SSS09617.highAccelID == 8
    assert SSS09617.ideshakes == XYZ("jas_calibrationex4\\SSS09617_004.IDE",
                                     "jas_calibrationex4\\SSS09617_006.IDE",
                                     "jas_calibrationex4\\SSS09617_005.IDE")

    assert SSX09546.dev == SSX09546.dev
    assert SSX09546.devPath == SSX09546.dev.path
    assert SSX09546.lowAccelID == 80
    assert SSX09546.highAccelID == 8
    assert SSX09546.ideshakes == XYZ("jas_calibrationex5\\SSX09546_015.IDE",
                                     "jas_calibrationex5\\SSX09546_017.IDE",
                                     "jas_calibrationex5\\SSX09546_016.IDE")


def test_calAxes():
    axesHi, axesLo = Calibrator.getAxisFlips(OGW0011620.dev)
    assert (lowW0011620.calAxes, hiW0011620.calAxes) == (axesLo, axesHi)

    axesHi, axesLo = Calibrator.getAxisFlips(OGW0011379.dev)
    assert (lowW0011379.calAxes, hiW0011379.calAxes) == (axesLo, axesHi)

    axesHi, axesLo = Calibrator.getAxisFlips(OGDAQ11940.dev)
    assert (lowDAQ11940.calAxes, hiDAQ11940.calAxes) == (axesLo, axesHi)

    axesHi, axesLo = Calibrator.getAxisFlips(OGSSS09617.dev)
    assert (lowSSS09617.calAxes, hiSSS09617.calAxes) == (axesLo, axesHi)

    axesHi, axesLo = Calibrator.getAxisFlips(OGSSX09546.dev)
    assert (lowSSX09546.calAxes, hiSSX09546.calAxes) == (axesLo, axesHi)

def test_gains():
    assert lowW0011620.gains == pytest.approx(OGW0011620.calLo, rel=1e-1)
    assert hiW0011620.gains == pytest.approx(OGW0011620.cal, rel=1e-1)
    assert lowW0011379.gains == pytest.approx(OGW0011379.calLo, rel=1e-1)
    assert hiW0011379.gains == pytest.approx(OGW0011379.cal, rel=1e-1)
    assert lowDAQ11940.gains == pytest.approx(OGDAQ11940.calLo, rel=1e-1)
    assert hiDAQ11940.gains == pytest.approx(OGDAQ11940.cal, rel=1e-1)
    assert lowSSS09617.gains == pytest.approx(OGSSS09617.calLo, rel=1e-1)
    assert hiSSS09617.gains == pytest.approx(OGSSS09617.cal, rel=1e-1)
    assert lowSSX09546.gains == pytest.approx(OGSSX09546.calLo, rel=1e-1)
    assert hiSSX09546.gains == pytest.approx(OGSSX09546.cal, rel=1e-1)


def test_library_gravities():
    assert lowW0011620.gravities == hiW0011620.gravities
    assert lowW0011379.gravities == hiW0011379.gravities
    assert lowDAQ11940.gravities == hiDAQ11940.gravities
    assert lowSSS09617.gravities == hiDAQ11940.gravities
    assert lowSSX09546.gravities == hiSSX09546.gravities

def test_library_means():
    assert lowW0011620.means == pytest.approx([OGW0011620.calFiles[i].meansLo[i] for i in range(3)], rel=1e-1)
    # assert hiW0011620.means == pytest.approx([OGW0011620.calFiles[i].means[i] for i in range(3)], rel=1e-1)
    assert lowW0011379.means == pytest.approx([OGW0011379.calFiles[i].meansLo[i] for i in range(3)], rel=1e-1)
    assert hiW0011379.means == pytest.approx([OGW0011379.calFiles[i].means[i] for i in range(3)], rel=1e-1)
    assert lowDAQ11940.means == pytest.approx([OGDAQ11940.calFiles[i].meansLo[i] for i in range(3)], rel=1e-1)
    assert hiDAQ11940.means == pytest.approx([OGDAQ11940.calFiles[i].means[i] for i in range(3)], rel=1e-1)
    assert lowSSS09617.means == pytest.approx([OGSSS09617.calFiles[i].meansLo[i] for i in range(3)], rel=1e-1)
    assert hiSSS09617.means == pytest.approx([OGSSS09617.calFiles[i].means[i] for i in range(3)], rel=1e-1)
    assert lowSSX09546.means == pytest.approx([OGSSX09546.calFiles[i].meansLo[i] for i in range(3)], rel=1e-1)
    assert hiSSX09546.means == pytest.approx([OGSSX09546.calFiles[i].means[i] for i in range(3)], rel=1e-1)
def test_offsets():
    assert lowW0011620.offsets == pytest.approx(OGW0011620.offsetsLo, rel=1e-1)
    assert hiW0011620.offsets == pytest.approx(OGW0011620.offsets, rel=1e-1)
    assert lowW0011379.offsets == pytest.approx(OGW0011379.offsetsLo, rel=1e-1)
    assert hiW0011379.offsets == pytest.approx(OGW0011379.offsets, rel=1e-1)
    assert lowDAQ11940.offsets == pytest.approx(OGDAQ11940.offsetsLo, rel=1e-1)
    assert hiDAQ11940.offsets == pytest.approx(OGDAQ11940.offsets, rel=1e-1)
    assert lowSSS09617.offsets == pytest.approx(OGSSS09617.offsetsLo, rel=1e-1)
    assert hiSSS09617.offsets == pytest.approx(OGSSS09617.offsets, rel=1e-1)
    assert lowSSX09546.offsets == pytest.approx(OGSSX09546.offsetsLo, rel=1e-1)
    assert hiSSX09546.offsets == pytest.approx(OGSSX09546.offsets, rel=1e-1)


def test_final_placement():

    expX = XYZ(1, 0, 0)
    expY = XYZ(0, 1, 0)
    expZ = XYZ(0, 0, 1)
    tol = 0.3
    avgs = checkCalibration(lowW0011620)
    assert XYZapprox(avgs.x, expX, tol)
    assert XYZapprox(avgs.y, expY, tol)
    assert XYZapprox(avgs.z, expZ, tol)
    avgs = checkCalibration(lowW0011379)
    assert XYZapprox(avgs.x, expX, tol)
    assert XYZapprox(avgs.y, expY, tol)
    assert XYZapprox(avgs.z, expZ, tol)
    avgs = checkCalibration(lowDAQ11940)
    assert XYZapprox(avgs.x, expX, tol)
    assert XYZapprox(avgs.y, expY, tol)
    assert XYZapprox(avgs.z, expZ, tol)
    avgs = checkCalibration(lowSSX09546)
    assert XYZapprox(avgs.x, expX, tol)
    assert XYZapprox(avgs.y, expY, tol)
    assert XYZapprox(avgs.z, expZ, tol)
    avgs = checkCalibration(lowSSS09617)
    assert XYZapprox(avgs.x, expX, tol)
    assert XYZapprox(avgs.y, expY, tol)
    assert XYZapprox(avgs.z, expZ, tol)

def XYZapprox(XYZ1, XYZ2, rel_tol):
    approx = True
    for i in range(3):
        approx = approx and (abs(XYZ1[i])-abs(XYZ2[i]) < rel_tol)
        if not approx:
            raise AssertionError(f"{i}: {(abs(XYZ1[i])-abs(XYZ2[i]))} not within {rel_tol}")
    return approx