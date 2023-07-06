"""
Testing calibration.py
Checks that calibration.py adjusts data appropriately
& finds values similar to EXISTING, known-to-be-correct calibration values

To add a set of calibration recordings:
- Add folder of 3 recordings to testing directory & create a pytest.fixture similar to the devices below

- Use the TestAverages class to verify that after applying the Xform, the data is adjusted appropriately
    - Use test_PrimaryAvg_Gravity & test_SecondaryAvg_Gravity to compare to gravity (needs NO "known-to-be-good" values)
    - Use test_PrimaryAvg, test_SecondaryAvg w/ "known-to-be-good" gains+offsets to compare old results to new results
- Use the TestKnownValues class to compare the gain/offset/rms/means found in calibration with known-to-be-good values
"""

# to be run in ProductDatabase directory via python -m pytest birther\test_cal.py

import pytest
# do pip install pytest-lazy-fixture
from birther.util import XYZ
from birther.calibration import Calibrator
from math import isclose
import os
import endaq.ide as ei
from birther.shakeprofile import order_10g, order_10g_4g

Cal = Calibrator()
filenames = lambda folder: [str(folder) + "\\" + file for file in os.listdir(folder)]


##### DEVICES FIXTURES

@pytest.fixture(scope='session')
def S2_D8D16():
    """ S2_-D8D16, 8g Accel w/ Another Accel """
    cal = Calibrator()
    cal.calculate(filenames=filenames('testing/S0012565'))
    return cal


@pytest.fixture(scope='session')
def S4_R100D40():
    """ S4-R100D40, Piezo Resistive """
    cal = Calibrator()
    cal.calculate(filenames=filenames('testing/S0011157'))
    return cal


@pytest.fixture(scope='session')
def S5_E25D40():
    cal = Calibrator()
    cal.calculate(filenames=filenames('testing/S0010596'))
    return cal


@pytest.fixture(scope='session')
def LOG_0002_100G_DC():
    """ LOG-0002-100G-DC, Series 0, 100g + 16g"""
    cal = Calibrator(shakeOrder=order_10g)
    cal.calculate(filenames=filenames('testing/SSX0001837'))
    return cal


@pytest.fixture(scope='session')
def LOG_0004_500G_200DC():
    cal = Calibrator(shakeOrder=order_10g)
    cal.calculate(filenames=filenames('testing/SSX0001252'))
    return cal


@pytest.fixture(scope='session')
def LOG_0002_25G():
    cal = Calibrator(shakeOrder=order_10g)
    cal.calculate(filenames=filenames('testing/SSX000446'))
    return cal


@pytest.fixture(scope='session')
def S3_D16():
    cal = Calibrator(shakeOrder=order_10g_4g)
    cal.calculate(filenames=filenames('testing/S0012851'))
    return cal


@pytest.fixture(scope='session')
def W5_E2000D40():
    cal = Calibrator(shakeOrder=order_10g_4g)
    cal.calculate(filenames=filenames('testing/W0012326'))
    return cal


@pytest.fixture(scope='session')
def W8_R100D40():
    cal = Calibrator(shakeOrder=order_10g_4g)
    cal.calculate(filenames=filenames('testing/W0011670'))
    return cal


@pytest.fixture(scope='session')  # this one is weird.
def S4_E6000D40():
    """ S4-E6000D40, Piezo-Electric """
    cal = Calibrator()
    cal.calculate(filenames=filenames('testing/S0012716'))
    return cal


S2_D8D16_gains_1 = XYZ(-1.0090690379462333, -1.005364071730659, 0.9588599387749018)
S2_D8D16_offsets_1 = XYZ(0.0314392316544595, 0.004249199959896699, 0.03699801245152701)
S2_D8D16_gains_2 = XYZ(0.9962544432496938, 0.9884398696361401, 1.0026202919937552)
S2_D8D16_offsets_2 = XYZ(-0.008070779425374264, 0.022635454473550753, 0.10856496543113825)

S4_R100D40_gains_1 = XYZ(-1.2580219758750786, -1.315548339718475, -1.2793452971636414)
S4_R100D40_offsets_1 = XYZ(1.2610292638161225, -3.268360377726582, -3.483592645416529)
S4_R100D40_gains_2 = XYZ(-1.0353091175423768, -1.0257988938692861, 1.0120922293965333)
S4_R100D40_offsets_2 = XYZ(0.04545608136647716, 0.03243356620454907, -0.060148724452803615)

S5_E25D40_gains_1 = XYZ(1.2711568902226147, 1.326156374064499, -1.364726698296841)
S5_E25D40_gains_2 = XYZ(-1.0202476716066162, -1.0096439931773356, 1.001004428256408)
S5_E25D40_offsets_1 = XYZ(1.404030718936252, 1.5286084866631002, 0.03983434215610149)
S5_E25D40_offsets_2 = XYZ(0.020899551667029503, 0.04315155406282323, -0.035353549994370015)

LOG_0004_500G_200DC_gains_1 = XYZ(1.232159197060743, 1.3106738853135016, -1.205048141769761)
LOG_0004_500G_200DC_gains_2 = XYZ(0.9586665494277754, 0.9976284872127389, 0.9916212327812889)
LOG_0004_500G_200DC_offsets_1 = XYZ(0, 0, 0)  # from cert.
LOG_0004_500G_200DC_offsets_2 = XYZ(-0.43591540831759934, -0.0001751179628304289, 0.41812107022926726)

SSX1837_gains_1_analog = XYZ(1.1065, 1.1754, 1.2970)
SSX1837_gains_2 = XYZ(0.9757, 0.9950, 1.0267)
SSX1837_offsets_1_analog = XYZ(0, 0, 0)
SSX1837_offsets_2 = XYZ(-0.0056, 0.0436, 0.0298)

LOG_0002_25G_gains_1 = XYZ(1.544549118547128, 1.4510813444029682, -1.4263411419292138)
LOG_0002_25G_offsets_1 = XYZ(0.8822910984788497, 1.0437313920334, 1.0574351770153665)

S3_D16_gains_2 = XYZ(0.9793478745159458, 0.9939966193386918, 0.99254071525686)
S3_D16_offsets_2 = XYZ(-0.03745648267168855, 0.0666037340496094, 0.08755122628389744)

W5_E2000D40_gains_1 = XYZ(1.3666428055173945, 1.3976668044773581, -1.8827048969869506)
W5_E2000D40_gains_2 = XYZ(-0.9829576376859441, -0.9742198364904879, 0.9464064298962541)
W5_E2000D40_offsets_1 = XYZ(3.9780748484481627, 47.454839660121245, -37.472245616565374)
W5_E2000D40_offsets_2 = XYZ(-0.007648565530348872, 0.08764394383564922, 0.12119576499541984)

W8_R100D40_gains_1 = XYZ(-1.2694069330439883, -1.2975270625817679, -1.2147568243202336)
W8_R100D40_gains_2 = XYZ(-1.0520533904303742, -1.0395438398004089, 0.9932312797320032)
W8_R100D40_offsets_1 = XYZ(-0.6315129770757486, -1.7883097995735557, 0.6171703333344227)
W8_R100D40_offsets_2 = XYZ(-0.06125410578571988, -0.04542911435883057, 0.004254451144793059)

S12716_gains_1 = XYZ(1.234296116439286, 1.9962195129040874, -1.1484210402946584)
S12716_offsets_1 = XYZ(170.07452290393493, 71.16653297446773, -107.18735682618036)
S12716_gains_2 = XYZ(-0.9955080803518909, -0.9991766928009014, 0.976554178207498)
S12716_offsets_2 = XYZ(0.03612071601951328, -0.008673982551172799, 0.030999315028862884)


class TestAverages:
    """ Test class for verifying that the transforms appropriately adjust the data.
        After applying the gain and offset to the data, these tests check where the data sits.
    """
    @pytest.mark.parametrize("cal, pdf_gain, pdf_offset, name",
                             [(pytest.lazy_fixture("S2_D8D16"), S2_D8D16_gains_1, S2_D8D16_offsets_1, "S2_D8D16"),
                              (pytest.lazy_fixture("S4_R100D40"), S4_R100D40_gains_1, S4_R100D40_offsets_1, "S4_R100D40"),
                              (pytest.lazy_fixture("S5_E25D40"), S5_E25D40_gains_1, S5_E25D40_offsets_1, "S5_E25D40"),
                              pytest.param(pytest.lazy_fixture("S4_E6000D40"), S12716_gains_1, S12716_offsets_1, "S4_E6000D40",
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_gains_1, LOG_0004_500G_200DC_offsets_1, LOG_0004_500G_200DC),
                              (pytest.lazy_fixture("LOG_0002_100G_DC"), SSX1837_gains_1_analog, SSX1837_offsets_1_analog,
                               "LOG_0002_100G_DC"),
                              pytest.param(pytest.lazy_fixture('LOG_0002_25G'), LOG_0002_25G_gains_1, LOG_0002_25G_offsets_1, LOG_0002_25G,
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_gains_1, W5_E2000D40_offsets_1, W5_E2000D40),
                              (pytest.lazy_fixture('W8_R100D40'), W8_R100D40_gains_1, W8_R100D40_offsets_1, W8_R100D40)
                              ])
    def test_PrimaryAvg(self, cal, pdf_gain, pdf_offset, name):
        """ Compare the averages of the High Accel data after applying the new and old transforms """
        new_means = XYZ(None)
        og_means = XYZ(None)

        for calFile in cal.calFiles:
            ds = ei.get_doc(calFile.filename)
            ch = ds.channels[calFile.accelChannel.id]
            shaken = calFile.shaken
            if len(ch.subchannels[shaken].transform.coefficients) == 2:
                ch.subchannels[shaken].transform.coefficients = (cal.cal[shaken], cal.offsets[shaken])
            else:
                coeffs = ch.subchannels[shaken].transform.coefficients
                ch.subchannels[shaken].transform.coefficients = (
                    coeffs[0], cal.cal[shaken], coeffs[2], cal.offsets[shaken])

            ch.subchannels[shaken].updateTransforms()

            new_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

            if pdf_gain and pdf_offset:
                if len(ch.subchannels[shaken].transform.coefficients) == 2:
                    ch.subchannels[shaken].transform.coefficients = (pdf_gain[shaken], pdf_offset[shaken])
                else:
                    ch.subchannels[shaken].transform.coefficients = (1, pdf_gain[shaken], 1, pdf_offset[shaken])
                ch.subchannels[shaken].updateTransforms()  # doesn't look like this takes??
                og_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

        print(f"\nMEANS OF DATA FOLLOWING HI ACCEL CALIBRATION of {name}")
        print("GRAV: ", cal.deviceLibrary.gravities)
        print("OG: ", og_means)
        print("NEW: ", new_means)
        if pdf_gain and pdf_offset:
            assert isclose(new_means.x, og_means.x, rel_tol=0.1)
            assert isclose(new_means.y, og_means.y, rel_tol=0.1)
            assert isclose(new_means.z, og_means.z, rel_tol=0.1)

    @pytest.mark.parametrize("cal, pdf_gain, pdf_offset, name",
                             [(pytest.lazy_fixture("S2_D8D16"), S2_D8D16_gains_2, S2_D8D16_offsets_2, "S2_D8D16"),
                              (pytest.lazy_fixture("S4_R100D40"), S4_R100D40_gains_2, S4_R100D40_offsets_2, "S4_R100D40"),
                              (pytest.lazy_fixture("S5_E25D40"), S5_E25D40_gains_2, S5_E25D40_offsets_2, "S5_E25D40"),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_gains_2, LOG_0004_500G_200DC_offsets_2, LOG_0004_500G_200DC),
                              (pytest.lazy_fixture('S3_D16'), S3_D16_gains_2, S3_D16_offsets_2, S3_D16),
                              (pytest.lazy_fixture("LOG_0002_100G_DC"), SSX1837_gains_2, SSX1837_offsets_2, "LOG_0002_100G_DC"),
                              (pytest.lazy_fixture("S4_E6000D40"), S12716_gains_2, S12716_offsets_2, "S4_E6000D40"),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_gains_2, W5_E2000D40_offsets_2, W5_E2000D40),
                              (pytest.lazy_fixture('W8_R100D40'), W8_R100D40_gains_2, W8_R100D40_offsets_2, W8_R100D40)
                              ])
    def test_SecondaryAvg(self, cal, pdf_gain, pdf_offset, name):
        """ Compare the averages of the Low Accel data after applying the new and old transforms """
        new_means = XYZ(None)
        og_means = XYZ(None)

        for calFile in cal.calFiles:
            ds = ei.get_doc(calFile.filename)
            ch = ds.channels[calFile.accelChannelLo.id]
            shaken = calFile.shaken

            if len(ch.subchannels[shaken].transform.coefficients) == 2:
                ch.subchannels[shaken].transform.coefficients = (cal.calLo[shaken], cal.offsetsLo[shaken])
            else:
                coeffs = ch.subchannels[shaken].transform.coefficients
                ch.subchannels[shaken].transform.coefficients = (
                    coeffs[0], cal.calLo[shaken], coeffs[2], cal.offsetsLo[shaken])

            ch.subchannels[shaken].updateTransforms()
            new_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

            if pdf_gain and pdf_offset:
                if len(ch.subchannels[shaken].transform.coefficients) == 2:
                    ch.subchannels[shaken].transform.coefficients = (pdf_gain[shaken], pdf_offset[shaken])
                else:
                    ch.subchannels[shaken].transform.coefficients = (1, pdf_gain[shaken], 1, pdf_offset[shaken])
                ch.subchannels[shaken].updateTransforms()  # doesn't look like this takes??
                og_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

        print(f"\nMEANS OF DATA FOLLOWING LO ACCEL CALIBRATION of {name}")
        print("GRAV: ", cal.deviceLibrary.gravities)
        print("OG: ", og_means)
        print("NEW: ", new_means)

        if pdf_gain and pdf_offset:
            assert isclose(new_means.x, og_means.x, rel_tol=0.1)
            assert isclose(new_means.y, og_means.y, rel_tol=0.1)
            assert isclose(new_means.z, og_means.z, rel_tol=0.1)

    @pytest.mark.parametrize("cal",
                             [(pytest.lazy_fixture("S2_D8D16")),
                              (pytest.lazy_fixture("S4_R100D40")),
                              (pytest.lazy_fixture("S5_E25D40")),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC')),
                              (pytest.lazy_fixture("LOG_0002_100G_DC")),
                              (pytest.lazy_fixture('LOG_0002_25G')),
                              pytest.param(pytest.lazy_fixture('S3_D16'), marks=pytest.mark.xfail(strict=True)),
                              # should not have a hi accelChannel
                              (pytest.lazy_fixture("S4_E6000D40")),
                              pytest.param(pytest.lazy_fixture('W5_E2000D40'), marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W8_R100D40'))
                              ])
    def test_PrimaryAvg_Gravity(self, cal):
        """ Compare the average of the High Accel after the new transform to the expected gravity """
        new_means = XYZ(None)

        for calFile in cal.calFiles:
            ds = ei.get_doc(calFile.filename)
            ch = ds.channels[calFile.accelChannel.id]
            shaken = calFile.shaken
            if len(ch.subchannels[shaken].transform.coefficients) == 2:
                ch.subchannels[shaken].transform.coefficients = (cal.cal[shaken], cal.offsets[shaken])
            else:
                coeffs = ch.subchannels[shaken].transform.coefficients
                ch.subchannels[shaken].transform.coefficients = (
                    coeffs[0], cal.cal[shaken], coeffs[2], cal.offsets[shaken])

            ch.subchannels[shaken].updateTransforms()
            new_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

        print("\nNEW: ", new_means)
        print("GRAV: ", cal.deviceLibrary.gravities)
        assert isclose(new_means.x, cal.deviceLibrary.gravities.x, rel_tol=0.12)
        assert isclose(new_means.y, cal.deviceLibrary.gravities.y, rel_tol=0.12)
        assert isclose(new_means.z, cal.deviceLibrary.gravities.z, rel_tol=0.12)

    @pytest.mark.parametrize("cal",
                             [(pytest.lazy_fixture("S2_D8D16")),
                              (pytest.lazy_fixture("S4_R100D40")),
                              (pytest.lazy_fixture("S5_E25D40")),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC')),
                              pytest.param(pytest.lazy_fixture("LOG_0002_100G_DC"), marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('S3_D16')),
                              (pytest.lazy_fixture("S4_E6000D40")),
                              (pytest.lazy_fixture('W5_E2000D40')),
                              (pytest.lazy_fixture('W8_R100D40'))
                              ])
    def test_SecondaryAvg_Gravity(self, cal):
        """ Compare the average of the Low Accel after the new transform to the expected gravity """

        new_means = XYZ(None)

        for calFile in cal.calFiles:
            ds = ei.get_doc(calFile.filename)
            ch = ds.channels[calFile.accelChannelLo.id]
            shaken = calFile.shaken

            if len(ch.subchannels[shaken].transform.coefficients) == 2:
                ch.subchannels[shaken].transform.coefficients = (cal.calLo[shaken], cal.offsetsLo[shaken])
            else:
                coeffs = ch.subchannels[shaken].transform.coefficients
                ch.subchannels[shaken].transform.coefficients = (
                    coeffs[0], cal.calLo[shaken], coeffs[2], cal.offsetsLo[shaken])

            ch.subchannels[shaken].updateTransforms()
            new_means[shaken] = self.mean_of_adjusted_shaken_sess(ch, shaken)

        print("\nNEW: ", new_means)
        print("GRAV: ", cal.deviceLibrary.gravities)

        assert isclose(new_means.x, cal.deviceLibrary.gravities.x, rel_tol=0.12)
        assert isclose(new_means.y, cal.deviceLibrary.gravities.y, rel_tol=0.12)
        assert isclose(new_means.z, cal.deviceLibrary.gravities.z, rel_tol=0.12)

    @staticmethod
    def mean_of_adjusted_shaken_sess(ch, shaken):
        """ Grab the mean after the new transformation is applied """
        sesh = ch.subchannels[shaken].getSession()
        start, end = sesh.getInterval()

        if end - start < 5000000:
            pass
        else:
            start += 3000000
            end -= 2000000
        fig = go.Figure()
        fig.add_scatter(x=sesh.arrayRange(start, end)[0], y=sesh.arrayRange(start, end)[1], mode='lines', name='shaved')
        # fig.show()
        return sesh.arrayRange(start, end)[1].mean()


class TestKnownValues:
    """ Test class for comparing the current calibration values to "known-to-be-good" values """
    @pytest.mark.parametrize("cal, gains",
                             [(pytest.lazy_fixture('S2_D8D16'), S2_D8D16_gains_1),
                              (pytest.lazy_fixture('S4_R100D40'), S4_R100D40_gains_1),
                              (pytest.lazy_fixture('S5_E25D40'), S5_E25D40_gains_1),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_gains_1),
                              (pytest.lazy_fixture('LOG_0002_25G'), LOG_0002_25G_gains_1),
                              pytest.param(pytest.lazy_fixture('S4_E6000D40'),
                                           S12716_gains_1, marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_gains_1),
                              (pytest.lazy_fixture('W8_R100D40'), W8_R100D40_gains_1),
                              (pytest.lazy_fixture('LOG_0002_100G_DC'),
                               XYZ(1.1064623836809087, 1.1753668193180897, -1.2969958383918954)),  # cert. mismatch
                              ])
    def test_PrimaryGains(self, cal, gains):
        """ Compare the high accel's gains """
        print("\nEXP=", gains)
        print("MINE=", cal.cal)
        assert isclose(cal.cal.x, gains.x, rel_tol=0.2)
        assert isclose(cal.cal.y, gains.y, rel_tol=0.2)
        assert isclose(cal.cal.z, gains.z, rel_tol=0.2)


    @pytest.mark.parametrize("cal, offsets",
                             [(pytest.lazy_fixture('S2_D8D16'), S2_D8D16_offsets_1),
                              (pytest.lazy_fixture('S4_R100D40'), S4_R100D40_offsets_1),
                              (pytest.lazy_fixture('S5_E25D40'), S5_E25D40_offsets_1),
                              pytest.param(pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_offsets_1, marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('LOG_0002_25G'), LOG_0002_25G_offsets_1),
                              pytest.param(pytest.lazy_fixture('S4_E6000D40'),
                                           S12716_offsets_1, marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_offsets_1),
                              (pytest.lazy_fixture('W8_R100D40'), W8_R100D40_offsets_1),
                              pytest.param(pytest.lazy_fixture('LOG_0002_100G_DC'),
                                           XYZ(-2.2595104389253433, -2.340885808886492, 1.304373591908605),
                                           marks=pytest.mark.xfail),  # cert. mismatch
                              ])
    def test_PrimaryOffsets(self, cal, offsets):
        """ Compare the high accel's offsets """
        assert isclose(cal.offsets.x, offsets.x, rel_tol=0.25)
        assert isclose(cal.offsets.y, offsets.y, rel_tol=0.25)
        assert isclose(cal.offsets.z, offsets.z, rel_tol=0.25)


    @pytest.mark.parametrize("cal, gains",
                             [(pytest.lazy_fixture("S2_D8D16"), S2_D8D16_gains_2),
                              (pytest.lazy_fixture("S4_R100D40"), S4_R100D40_gains_2),
                              (pytest.lazy_fixture('S5_E25D40'), S5_E25D40_gains_2),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_gains_2),
                              (pytest.lazy_fixture('S3_D16'), S3_D16_gains_2),
                              (pytest.lazy_fixture('S4_E6000D40'), S12716_gains_2),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_gains_2),
                              (pytest.lazy_fixture('W8_R100D40'), W8_R100D40_gains_2),
                              (pytest.lazy_fixture('LOG_0002_100G_DC'), XYZ(0.9756977115227964, 0.9949834089845425,
                                                                      1.0267191994117688))])  # cert. mismatch (slightly diff)
    def test_SecondaryGains(self, cal, gains):
        """ Compare the low accel's gains """
        assert isclose(cal.calLo.x, gains.x, rel_tol=0.25)
        assert isclose(cal.calLo.y, gains.y, rel_tol=0.25)
        assert isclose(cal.calLo.z, gains.z, rel_tol=0.25)


    @pytest.mark.parametrize("cal, offsets",
                             [(pytest.lazy_fixture("S2_D8D16"), S2_D8D16_offsets_2),
                              (pytest.lazy_fixture('S4_R100D40'), S4_R100D40_offsets_2),
                              (pytest.lazy_fixture('S5_E25D40'), S5_E25D40_offsets_2),
                              (pytest.lazy_fixture('S3_D16'), S3_D16_offsets_2),
                              pytest.param(pytest.lazy_fixture('LOG_0004_500G_200DC'), LOG_0004_500G_200DC_offsets_2,
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('S4_E6000D40'), S12716_offsets_2),
                              (pytest.lazy_fixture('W5_E2000D40'), W5_E2000D40_offsets_2),
                              pytest.param(pytest.lazy_fixture('W8_R100D40'), W8_R100D40_offsets_2, marks=pytest.mark.xfail),
                              pytest.param(pytest.lazy_fixture('LOG_0002_100G_DC'),
                                           SSX1837_offsets_2,  # cert. mismatch
                                           marks=pytest.mark.xfail)])
    def test_SecondaryOffsets(self, cal, offsets):
        """ Compare the low accel's offsets """
        assert isclose(cal.offsetsLo.x, offsets.x, rel_tol=0.4)
        assert isclose(cal.offsetsLo.y, offsets.y, rel_tol=0.4)
        assert isclose(cal.offsetsLo.z, offsets.z, rel_tol=0.4)


    @pytest.mark.parametrize("cal, rms",
                             [
                                 (pytest.lazy_fixture('S2_D8D16'),
                                  XYZ(2.8030065519628984, 2.8133361876332668, 2.9497813083733186)),
                                 (pytest.lazy_fixture('S4_R100D40'),
                                  XYZ(5.623908115817006, 5.377985579392725, 5.530172359007026)),
                                 (pytest.lazy_fixture('S5_E25D40'),
                                  XYZ(5.565796051155394, 5.334966628645786, 5.184188166634021)),
                                 (pytest.lazy_fixture('LOG_0004_500G_200DC'),
                                  XYZ(5.74195283927359, 5.397986546674593, 5.871134732932325)),
                                 (pytest.lazy_fixture('LOG_0002_25G'),
                                  XYZ(4.580624801790092, 4.875674287516206, 4.960243936054897)),
                                 (pytest.lazy_fixture('LOG_0002_100G_DC'),
                                  XYZ(6.39425262381116, 6.019397420206816, 5.454913416508777)),
                                 pytest.param(pytest.lazy_fixture('S4_E6000D40'),
                                              XYZ(5.73201187767653, 3.544199400048613, 6.160632513476694),
                                              marks=pytest.mark.xfail),
                                 pytest.param(pytest.lazy_fixture('S3_D16'),
                                              XYZ(7.2241949812745565, 7.117730445307766, 7.128171057616571),
                                              marks=pytest.mark.xfail(strict=True)),  # should not have a high ID
                                 (pytest.lazy_fixture('W5_E2000D40'),
                                  XYZ(5.176919654087295, 5.062007609635987, 3.757891112581006)),
                                 (pytest.lazy_fixture('W8_R100D40'),
                                  XYZ(5.57346885055561, 5.452680105124317, 5.824210951816717))
                             ])
    def test_PrimaryRMS(self, cal, rms):
        """ Compare the RMS of the high accel's selected shake """
        hiId = cal.deviceLibrary.hiAccelId
        assert isclose(cal.calFiles[0].accels[hiId].rms[0], rms.x, abs_tol=0.05)
        assert isclose(cal.calFiles[1].accels[hiId].rms[1], rms.y, abs_tol=0.05)
        assert isclose(cal.calFiles[2].accels[hiId].rms[2], rms.z, abs_tol=0.05)


    @pytest.mark.parametrize("cal, rms",
                             [(pytest.lazy_fixture('S2_D8D16'),
                               XYZ(7.10159944373445, 7.157744459057906, 7.0565098836480225)),
                              (pytest.lazy_fixture('S4_R100D40'),
                               XYZ(6.8337078077653555, 6.897063393501321, 6.990469637553206)),
                              (pytest.lazy_fixture('S5_E25D40'),
                               XYZ(6.934590685082156, 7.007420484655263, 7.067900800722266)),
                              (pytest.lazy_fixture('LOG_0004_500G_200DC'),
                               XYZ(7.380042627150225, 7.0918183378732, 7.134780666359991)),
                              (pytest.lazy_fixture('S3_D16'),
                               XYZ(7.2241949812745565, 7.117730445307766, 7.128171057616571)),
                              (pytest.lazy_fixture('LOG_0002_100G_DC'),
                               XYZ(7.251221271143361, 7.110671329907485, 6.890881171846627)),
                              (pytest.lazy_fixture('S4_E6000D40'),
                               XYZ(7.106923730341936, 7.080829698066009, 7.244861737201749)),
                              (pytest.lazy_fixture('W5_E2000D40'),
                               XYZ(7.197665218468417, 7.2622212513007876, 7.475646589568889)),
                              (
                              pytest.lazy_fixture('W8_R100D40'), XYZ(6.724943871057493, 6.805869775880151, 7.123215050082796))
                              ])
    def test_SecondaryRMS(self, cal, rms):
        """ Compare the RMS of the low accel's selected shake """
        loId = cal.deviceLibrary.loAccelId
        assert isclose(cal.calFiles[0].accels[loId].rms[0], rms.x, abs_tol=0.05)
        assert isclose(cal.calFiles[1].accels[loId].rms[1], rms.y, abs_tol=0.05)
        assert isclose(cal.calFiles[2].accels[loId].rms[2], rms.z, abs_tol=0.05)


    @pytest.mark.parametrize("cal, means",
                             [(pytest.lazy_fixture("S2_D8D16"),
                               XYZ(-0.9598557996753725, -0.9904380194589537, 1.0043197641345443)),
                              (pytest.lazy_fixture("S4_R100D40"),
                               XYZ(0.20749181558179927, -3.2445484889137584, -3.5045993097851134)),
                              (pytest.lazy_fixture("S5_E25D40"),
                               XYZ(-0.3178448876326312, -0.3986019273451011, -0.703558931647026)),
                              pytest.param(pytest.lazy_fixture('LOG_0004_500G_200DC'),
                                           XYZ(-8.117633971423421, 1.6967586838491775, 3.76195695130681),
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('LOG_0002_25G'),
                               XYZ(0.07620923161826838, -0.030137105822549724, 0.04026748954158462)),
                              pytest.param(pytest.lazy_fixture('S4_E6000D40'),
                                           XYZ(-136.9805192223106, -35.14970799598582, -94.20530713928925),
                                           marks=pytest.mark.xfail),
                              pytest.param(pytest.lazy_fixture('S3_D16'),
                                           XYZ(1.0593339809763345, 0.9390336423592479, 0.9193061399803327),
                                           marks=pytest.mark.xfail(strict=True)),  # should not have a high accel Id
                              pytest.param(pytest.lazy_fixture("LOG_0002_100G_DC"),
                                           XYZ(2.945884547906465, 1.1408232620216652, 0.2346758431283699),
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W5_E2000D40'),
                               XYZ(-2.1791172034310016, -33.237420758155956, -20.43455970085153)),
                              (pytest.lazy_fixture('W8_R100D40'),
                               XYZ(-1.285256078729178, -2.148941536545286, -0.31514922081611285))
                              ])
    def test_PrimaryMeans(self, cal, means):
        """ Compare the means of the high accel's quiet area """
        hiId = cal.deviceLibrary.hiAccelId
        assert isclose(cal.calFiles[0].accels[hiId].means, means.x, abs_tol=0.05)
        assert isclose(cal.calFiles[1].accels[hiId].means, means.y, abs_tol=0.05)
        assert isclose(cal.calFiles[2].accels[hiId].means, means.z, abs_tol=0.05)


    @pytest.mark.parametrize("cal, means",
                             [(pytest.lazy_fixture("S2_D8D16"),
                               XYZ(1.0118607613303452, 0.9887951463210728, 0.8891053190198289)),
                              (pytest.lazy_fixture("S4_R100D40"),
                               XYZ(-0.9219892904057728, -0.9432320892312684, 1.0474823278555594)),
                              (pytest.lazy_fixture("S5_E25D40"),
                               XYZ(-0.9596693779179619, -0.9477087492255444, 1.0343146551287419)),
                              pytest.param(pytest.lazy_fixture('LOG_0004_500G_200DC'),
                                           XYZ(1.49782571340858, 1.0025526844739634, 0.5867955531152603),
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('S4_E6000D40'),
                               XYZ(-0.9682284885520728, -1.0095051153801922, 0.9922651570133819)),
                              (pytest.lazy_fixture('S3_D16'),
                               XYZ(1.0593339809763345, 0.9390336423592479, 0.9193061399803327)),
                              pytest.param(pytest.lazy_fixture("LOG_0002_100G_DC"),
                                           XYZ(1.0408594838056695, -0.9618063633058601, 1.217700599837303),
                                           marks=pytest.mark.xfail),
                              (pytest.lazy_fixture('W5_E2000D40'),
                               XYZ(-1.0251190152024574, -0.9364991575731058, 0.9285695946728885)),
                              (pytest.lazy_fixture('W8_R100D40'),
                               XYZ(-1.0087454832986964, -1.00566140102331, 1.002531403485281))
                              ])
    def test_SecondaryMeans(self, cal, means):
        """ Compare the means of the low accel's quiet area """
        loId = cal.deviceLibrary.loAccelId
        assert isclose(cal.calFiles[0].accels[loId].means, means.x, abs_tol=0.05)
        assert isclose(cal.calFiles[1].accels[loId].means, means.y, abs_tol=0.05)
        assert isclose(cal.calFiles[2].accels[loId].means, means.z, abs_tol=0.05)
