import pandas as pd

df2 = pd.read_excel("Device_Info.xlsx", sheet_name="Sheet2", header=0)
print(df2)

def get_range_dict(row):
    dct = {}
    if not pd.isna(row['Accel 8 Range']):
        dct[8] = int(row['Accel 8 Range'])
    if not pd.isna(row['Accel 80 Range']):
        dct[80] = int(row['Accel 80 Range'])
    if not pd.isna(row['Accel 32 Range']):
        dct[32] = int(row['Accel 32 Range'])
    return dct

def get_flips_dict(row):
    dct = {}
    if not pd.isna(row['Accel 8']):
        dct[8] = f"({row['Accel 8']})"
    if not pd.isna(row['Accel 80']):
        dct[80] = f"({row['Accel 80']})"
    if not pd.isna(row['Accel 32']):
        dct[32] = f"({row['Accel 32']})"
    return dct

for index, row in df2.iterrows():
    print(f"devicedata("
          f"'{row['Part']}', "
          f"'{row['MCU']}', "
          f"hwrev={None if row['HW Rev'] == 'All' else repr(row['HW Rev'])}, "
          f"accelrange={get_range_dict(row)}, "
          f"axisflips={get_flips_dict(row)}), ")
