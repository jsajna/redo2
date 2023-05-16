import numpy as np
import plotly.graph_objects as go

# Generate some example accelerometer data
sampling_rate = 100  # Hz
duration = 5  # seconds
time = np.arange(0, duration, 1/sampling_rate)
signal = np.zeros_like(time)
signal[(time >= 4) & (time <= 9)] = 10  # simulate a 10g shake between 4th and 9th second
signal += 2  # shift the central value of the signal to around 2g

# Plot the original data
fig1 = go.Figure(data=go.Scatter(x=time, y=signal, mode='lines', name='Original Signal'))

# Calculate the required gain and offset
current_central_value = np.mean(signal)
required_offset_to_centralize = 4 - current_central_value
current_max_value = np.max(np.abs(signal))
required_gain_to_double_10g_shake = 20 / (current_max_value * 2)
required_offset_to_shift_10g_shake = (4.5 - current_central_value / 10) * sampling_rate

# Apply the gain and offset to the signal
signal = (signal + required_offset_to_centralize) * required_gain_to_double_10g_shake - required_offset_to_shift_10g_shake

# Add the required offset to shift the central value to 4g to the signal
signal += 4 - np.mean(signal)

# Plot the adjusted data
fig2 = go.Figure(data=go.Scatter(x=time, y=signal, mode='lines', name='Adjusted Signal'))

# Display both charts side by side
fig1.update_layout(title='Original Signal', xaxis_title='Time (s)', yaxis_title='Acceleration (g)')
fig2.update_layout(title='Adjusted Signal', xaxis_title='Time (s)', yaxis_title='Acceleration (g)')
fig1.show()
fig2.show()
