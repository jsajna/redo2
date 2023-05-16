import numpy as np
import pandas as pd
import plotly.graph_objs as go
from plotly.offline import iplot
from scipy.signal import butter, sosfilt
import endaq.calc as ec
import idelib.dataset


# set the number of data points and the frequency of the sine wave
frequency = 100
hp = 10
lp = 2.55
num_points = 25000
sampRate = num_points / 5
print(sampRate, " is SAMPLE RATE")


def Filter(data, cutoff, fs, btype, order=5):
    nyq = 0.5 * fs
    normalCutoff = cutoff / nyq
    sos = butter(order, normalCutoff, btype=btype, analog=False, output='sos')
    y = sosfilt(sos, data)
    return y


def generate_random_data(xrange, numpoints, fs, amplifier=1, centerVal=2):
    x = np.linspace(xrange[0], xrange[1], numpoints)
    y = (amplifier * np.sin(np.pi * fs * (x*10))) + np.random.normal(0, 0.5, numpoints) + centerVal
    return x[:-1], y[:-1]


def get_gain(data, axisflip=1, targetAmp=1):
    data = np.array(data)[:, 1]
    data = Filter(data, hp, frequency, "high")
    print(data)
    currAmp = get_rms(data)
    print(f"CURRENT RMS2: {currAmp}")
    refRMS = targetAmp * (2 ** .5) / 2
    return axisflip * refRMS / currAmp


def get_rms(data):
    data = np.array(data)
    midpt = np.mean(data)
    print(f"MIDPT IS {midpt} (not subtracted)")
    return np.sqrt(np.mean(np.square(data), axis=0))


deadTime1, dead1 = generate_random_data((0, .5), num_points, frequency)
shakeTime, shake = generate_random_data((.5, 1), num_points, frequency, amplifier=6)
deadTime2, dead2 = generate_random_data((1, 1.5), num_points, frequency)

time = np.concatenate((deadTime1, shakeTime, deadTime2))
data = np.concatenate((dead1, shake, dead2))
df = pd.DataFrame({'timestamp': time, 'y': data}, index=time)
fig = go.Figure()
fig.add_trace(go.Scatter(x=df['timestamp'], y=df['y'], mode='lines', name='sine wave with noise', line=dict(color='red')))


fig.add_trace(go.Scatter(x=time, y=Filter(data, hp, sampRate, "high"), mode='lines', name=f'Filtered, Cutoff={hp}', line=dict(color='pink')))
fig.add_trace(go.Scatter(x=time, y=Filter(data, lp, sampRate, "low"), mode='lines', name=f'Filtered, Cutoff={lp}', line=dict(color='purple')))
"""
lowcutoff = 0.01
df_highpass = ec.filters.butterworth(df, low_cutoff=lowcutoff, high_cutoff=None)
fig.add_trace(go.Scatter(x=time, y=df_highpass['y'], mode='lines', name=f'High Pass, Low Cutoff={lowcutoff}', line=dict(color='blue')))

highcutoff = 0.2
df_lowpass = ec.filters.butterworth(df, low_cutoff=None, high_cutoff=highcutoff)
fig.add_trace(go.Scatter(x=time, y=df_lowpass['y'], mode='lines', name=f'Low Pass, High Cutoff={highcutoff}', line=dict(color='green')))
"""
fig.show()



