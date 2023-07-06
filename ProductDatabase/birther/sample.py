import os
import endaq.ide as ei

folders = ['S0009553', 'S0011157', 'S0012565', 'S0012716', 'SSC0002118', 'SSC0002799', 'SSC0008781', 'SSX0001837', 'W0011620']
for folder in folders:
    folderpath = os.path.join('../testing', folder)
    idefile = os.listdir(folderpath)[0]
    filepath = os.path.join(folderpath, idefile)
    doc = ei.get_doc(filepath)
    print("\n", doc)
    accels = ei.get_channels(doc, measurement_type="ACCELERATION", subchannels=False)
    for accel in accels:
        print(accel.id, " : ", accel[0].sensor.name, " - ", accel.name)


"""
In sensor names:
- Low-g is <=8
- High-g is > 8  (ADC?)
"""

Ranges = {
    "ADXL345": 16,
    "ADXL375": 200,
    "ADXL355": 8,
    "ADXL357": 40
}

def _getSensorRange(accel):
    import re
    print(accel.id, " : ", accel[0].sensor.name, " - ", accel.name)

    match = re.search(r"^\d+(?=g)", accel.name)
    if match:
        number = match.group()
        return number
    else:
        for range,  in Ranges:
            if range in accel[0].sensor.name:

