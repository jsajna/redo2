import pytest
from birther.util import XYZ
from math import isclose
from birther.calibration import Calibrator
import os

Cal = Calibrator()
filenames = lambda folder: [str(folder) + "\\" + file for file in os.listdir(folder)]
# Cal.calculate(filenames=filenames("W0011620"))


@pytest.mark.parametrize("files, gains, offsets",
                         [("W0011620", XYZ(1.3489956861999413, 1.387956296694804, -1.333064952848069),
                           XYZ(2.796744405372153, 0.826333465845958, 1.7832495793707084))])
def test_HiCals(files, gains, offsets):
    cal = Calibrator()
    cal.calculate(filenames=filenames(files))
    assert isclose(cal.cal.x, gains.x)
    assert isclose(cal.cal.y, gains.y)
    assert isclose(cal.cal.z, gains.z)
    assert isclose(cal.offsets.x, offsets.x)
    assert isclose(cal.offsets.y, offsets.y)
    assert isclose(cal.offsets.z, offsets.z)






