"""
Testing calibration.py
Checks that calibration.py finds values similar to EXISTING, known-to-be-correct calibration values
To add a set of calibration recordings:
- Add folder of 3 recordings to working directory & create a pytest.fixture similar to the devices below
- add to parametrized inputs- the device's pytest.lazy_fixture & an XYZ containing the expected gains/offsets
- expected gains and offsets can be found from calibrated devices on the Lab, or on the calibration certificate

"""
import pytest
# pytest-lazy-fixture must be installed
from util import XYZ
from math import isclose
from .calibration import Calibrator
import os

Cal = Calibrator()
filenames = lambda folder: [str(folder) + "\\" + file for file in os.listdir(folder)]


##### DEVICES FIXTURES
@pytest.fixture(scope='session')
def W0011620():
    """ W8-E100D40 """
    cal = Calibrator()
    cal.calculate(filenames=filenames('W0011620'))
    return cal


@pytest.fixture(scope='session')
def S0012565():
    """ S2-D8D16, 8g Accel w/ Another Accel """
    cal = Calibrator()
    cal.calculate(filenames=filenames('S0012565'))
    return cal


@pytest.fixture(scope='session')
def S0011157():
    """ S4-R100D40, Piezo Resistive """
    cal = Calibrator()
    cal.calculate(filenames=filenames('S0011157'))
    return cal


@pytest.fixture(scope='session')
def S0012716():
    """ S4-E6000D40, Piezo-Electric """
    cal = Calibrator()
    cal.calculate(filenames=filenames('S0012716'))
    return cal


@pytest.fixture(scope='session')
def SSX0001837():
    """ LOG-0002-100G-DC, Series 0 No 16g or 200g """
    cal = Calibrator()
    cal.calculate(filenames=filenames('SSX0001837'))
    return cal


@pytest.fixture(scope='session')
def SSC0002799():
    """ LOG-0002-100G-DC, Series 0, 16g"""
    cal = Calibrator()
    cal.calculate(filenames=filenames('SSC0002799'))
    return cal


@pytest.fixture(scope='session')
def SSC0002118():
    """ LOG-0002-100G-DC, Series 0, 200g"""
    cal = Calibrator()
    cal.calculate(filenames=filenames('SSC0002118'))
    return cal

# TODO: get a GG11 Device


@pytest.mark.parametrize("cal, gains",
                         [(pytest.lazy_fixture('W0011620'),
                           XYZ(1.3489956861999413, 1.387956296694804, -1.333064952848069)),
                          (pytest.lazy_fixture('S0012565'),
                           XYZ(-1.0090690379462333, -1.005364071730659, 0.9588599387749018)),
                          (pytest.lazy_fixture('S0011157'),
                           XYZ(-1.2580219758750786, -1.315548339718475, -1.2793452971636414)),
                          (pytest.lazy_fixture('S0012716'),
                           XYZ(1.234296116439286, 1.9962195129040874, -1.1484210402946584)),
                          (pytest.lazy_fixture('SSX0001837'),
                           XYZ(1.1064623836809087, 1.1753668193180897, -1.2969958383918954)),
                          (pytest.lazy_fixture('SSC0002118'),
                           XYZ(0.9860312869708541, 1.0031094041755895, 0.9728068129777033)),
                          (pytest.lazy_fixture('SSC0002799'),
                           XYZ(0.9919709290832088, 0.9873576099098839, 1.004017052914896))])
def test_HiCals_gains(cal, gains):
    assert isclose(cal.cal.x, gains.x)
    assert isclose(cal.cal.y, gains.y)
    assert isclose(cal.cal.z, gains.z)


@pytest.mark.parametrize("cal, offsets",
                         [(pytest.lazy_fixture("W0011620"),
                           XYZ(2.796744405372153, 0.826333465845958, 1.7832495793707084)),
                          (pytest.lazy_fixture('S0012565'),
                           XYZ((0.0314392316544595, 0.004249199959896699, 0.03699801245152701))),
                          (pytest.lazy_fixture('S0011157'),
                           XYZ(1.2610292638161225, -3.268360377726582, -3.483592645416529)),
                          (pytest.lazy_fixture('S0012716'),
                           XYZ(170.07452290393493, 71.16653297446773, -107.18735682618036)),
                          (pytest.lazy_fixture('SSX0001837'),
                           XYZ(-2.2595104389253433, -2.340885808886492, 1.304373591908605)),
                          (pytest.lazy_fixture('SSC0002118'),
                           XYZ(-0.19927337992020355, -0.33329770591898444, -0.7936029202263153)),  # cert. mismatch
                          (pytest.lazy_fixture('SSC0002799'),
                           XYZ(-0.015399101235527235, -0.030864965286856116, -0.18090443247396282))  # cert. mismatch
                          ])
def test_HiCals_offsets(cal, offsets):
    assert isclose(cal.offsets.x, offsets.x)
    assert isclose(cal.offsets.y, offsets.y)
    assert isclose(cal.offsets.z, offsets.z)


@pytest.mark.parametrize("cal, gains",
                         [(pytest.lazy_fixture("W0011620"),
                           XYZ(-1.064713653072725, -1.0531583193585683, 0.9935640419214467)),
                          (pytest.lazy_fixture("S0012565"),
                           XYZ(0.9962544432496938, 0.9884398696361401, 1.0026202919937552)),
                          (pytest.lazy_fixture("S0011157"),
                           XYZ(-1.0353091175423768, -1.0257988938692861, 1.0120922293965333)),
                          (pytest.lazy_fixture('S0012716'),
                           XYZ(-0.9955080803518909, -0.9991766928009014, 0.976554178207498)),
                          (pytest.lazy_fixture('SSX0001837'),
                           XYZ(0.9756977115227964, 0.9949834089845425, 1.0267191994117688))])
def test_LoCals_gains(cal, gains):
    assert isclose(cal.calLo.x, gains.x)
    assert isclose(cal.calLo.y, gains.y)
    assert isclose(cal.calLo.z, gains.z)


@pytest.mark.parametrize("cal, offsets",
                         [(pytest.lazy_fixture("W0011620"),
                           XYZ(-0.08393346228105591, -0.05718995792004811, -0.02675693317626915)),
                          (pytest.lazy_fixture("S0012565"),
                           XYZ(-0.008070779425374264, 0.022635454473550753, 0.10856496543113825)),
                          (pytest.lazy_fixture('S0011157'),
                           XYZ(0.04545608136647716, 0.03243356620454907, -0.060148724452803615)),
                          (pytest.lazy_fixture('S0012716'),
                           XYZ(0.03612071601951328, -0.008673982551172799, 0.030999315028862884)),
                          (pytest.lazy_fixture('SSX0001837'),
                           XYZ(-0.015564216365990813, -0.0430186258549099, -0.25023658498818624))])
def test_LoCals_offsets(cal, offsets):
    assert isclose(cal.offsetsLo.x, offsets.x)
    assert isclose(cal.offsetsLo.y, offsets.y)
    assert isclose(cal.offsetsLo.z, offsets.z)
