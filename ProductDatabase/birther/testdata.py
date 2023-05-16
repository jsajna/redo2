"""
python program to determine fake shaker test data
"""
import random
from plotly.subplots import make_subplots
import numpy as np
import plotly.graph_objs as go
from scipy.signal import butter, sosfilt
import numpy as np


def find_reliable_amp(data):
    # calculate the range in which 97% of the values exist in
    lowBound, highBound = np.percentile(np.array(data)[:, 1], [1, 99])
    print(f"98% of the data exists between {lowBound} and {highBound}")
    amp = (highBound - lowBound) / 2
    return amp


def Filter(data, cutoff, fs, btype, order=5):
    nyq = 0.5 * fs
    normalCutoff = cutoff / nyq
    sos = butter(order, normalCutoff, btype=btype, analog=False, output='sos')
    y = sosfilt(sos, data)
    return y


def generate_random_data(start, stop, step, yAmp, midY=0):
    start = start + step
    num_points = int((stop - start) / step) + 1
    x_values = [i * step + start for i in range(num_points)]
    y_min = midY - yAmp
    y_max = midY + yAmp
    y_values = [random.uniform(y_min, y_max) for _ in range(num_points)]
    data = list(zip(x_values, y_values))
    return data


def get_rms(data):
    print(data)
    data = np.array(data)
    midpt = np.mean(data)
    print(f"MIDPT IS {midpt}")
    return np.sqrt(np.mean(np.square(data - midpt), axis=0))


def get_gain(data, axisflip=1, targetAmp=1):
    filteredShake = Filter(data, hp, sampRate, "high")
    currAmp = find_reliable_amp(filteredShake)
    gain = axisflip * targetAmp / currAmp
    return gain


def get_gain2(data, axisflip=1, targetAmp=1):
    data = np.array(data)[:, 1]
    data = Filter(data, hp, sampRate, "high")
    print(data)
    currAmp = get_rms(data)
    print(f"CURRENT RMS2: {currAmp}")
    refRMS = targetAmp * (2 ** .5) / 2
    return axisflip * refRMS / currAmp


shakeAmp = 6
deadAmp = 0.1
centralVal = 2
sampRate = 100
rate = 1 / sampRate
deadzone1 = generate_random_data(0, 5, rate, deadAmp, centralVal)
shake = generate_random_data(5, 10, rate, shakeAmp, centralVal)
deadzone2 = generate_random_data(10, 15, rate, deadAmp, centralVal)
data = np.array(deadzone1 + shake + deadzone2)
hp = 10
filteredData = Filter(data, hp, sampRate, "high")
filteredShake = Filter(shake, hp, sampRate, "high")

expShakeSize = 10
gain = get_gain(shake, targetAmp=expShakeSize)
print(f"THE GAIN IS {gain}")

fig = go.Figure()
fig.add_trace(go.Scatter(x=[d[0] for d in data], y=[d[1] for d in data], mode='markers',
                         name=f'OG: AMP={shakeAmp}, CTR={centralVal}'))

data[:, 1] *= gain
expCentral = 0
currCentral = np.mean(data[:, 1])
offset = expCentral - currCentral
print(f"OFFSET IS {offset} because CENTRAL VAL is {currCentral} & trying to push to {expCentral}")

fig.add_trace(go.Scatter(x=[d[0] for d in filteredData], y=[d[1] for d in filteredData], mode='markers',
                         name=f'Filtered Version of Original Data'))
data[:, 1] += offset
fig.add_trace(go.Scatter(x=[d[0] for d in data], y=[d[1] for d in data], mode='markers',
                         name=f'FINAL: EXP_AMP={expShakeSize}, EXPCTR={expCentral} (not done with filtered)'))

fig.show()

fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=[d[0] for d in shake], y=[d[1] for d in shake], mode='markers',
                         name=f'OG SHAKE ONLY: AMP={shakeAmp}, CTR={centralVal}'))
fig2.add_trace(go.Scatter(x=[d[0] for d in filteredShake], y=[d[1] for d in filteredShake], mode='markers',
                         name=f'Filtered SHAKE ONLY'))
fig2.show()

