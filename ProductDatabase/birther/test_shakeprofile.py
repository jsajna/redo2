import pytest
from .calibration import Calibrator
from .test_cal import W0011620, S0012565, SSC0008781, S0011157, S0012716, S0009553, SSX0001837
from .shakeprofile import ShakeProfile, order_10g, order_10g_4g
import endaq.ide as ei

W0011620Z = ei.get_doc('testing/DAQ11620_000006.IDE')
W0011620Z_sp = ShakeProfile(order_10g_4g).adjustProfile(W0011620Z.channels[8].subchannels[2])

S0012565Y = ei.get_doc('testing/DAQ12565_000000.IDE')
S0012565Y_sp = ShakeProfile(order_10g_4g).adjustProfile(S0012565Y.channels[32].subchannels[1])

SSC0008781X = ei.get_doc('testing/SSC08781_006.IDE')
SSC0008781X_sp = ShakeProfile(order_10g_4g).adjustProfile(SSC0008781X.channels[32].subchannels[0])

S0012716Y = ei.get_doc('testing/DAQ12716_00023.IDE')
S0012716Y_sp = ShakeProfile(order_10g_4g).adjustProfile(S0012716Y.channels[8].subchannels[1])

S009553X = ei.get_doc('testing/SSX09553_004.IDE')
S009553X_sp = ShakeProfile(order_10g_4g).adjustProfile(S009553X.channels[8].subchannels[0])

S0011157Z = ei.get_doc('testing/DAQ11157_000001.IDE')
S0011157X_sp = ShakeProfile(order_10g_4g).adjustProfile(S0011157Z.channels[8].subchannels[2])

SSX0001837Z = ei.get_doc('testing/SSX00318.IDE')
SSX0001837Z_sp = ShakeProfile(order_10g).adjustProfile(SSX0001837Z.channels[8].subchannels[2])



