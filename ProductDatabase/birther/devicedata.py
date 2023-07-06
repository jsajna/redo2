"""
Comprehensive list of all the types of devices & their information

If a new device is made, add a new devicedata to the list below!
"""
from dataclasses import dataclass
from typing import Union
from fnmatch import fnmatch

@dataclass
class devicedata:
    name: str  # Part number
    mcu: str  # STM or EFM
    hwrev: Union[None, str]
    ranges: dict
    flips: dict


devs = [devicedata('S?-D16', 'STM', hwrev=None, ranges={32: 16}, flips={32: (1, 1, 1)}),
        devicedata('S?-D40', 'STM', hwrev=None, ranges={80: 40}, flips={80: (-1, -1, 1)}),
        devicedata('S?-E25D40', 'STM', hwrev=None, ranges={8: 25, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E100D40', 'STM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E2000D40', 'STM', hwrev=None, ranges={8: 2000, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R100D40', 'STM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R500D40', 'STM', hwrev=None, ranges={8: 500, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R2000D40', 'STM', hwrev=None, ranges={8: 2000, 80: 40},
                   flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E25D40', 'STM', hwrev=None, ranges={8: 25, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E100D40', 'STM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E2000D40', 'STM', hwrev=None, ranges={8: 2000, 80: 40},
                   flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R100D40', 'STM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R500D40', 'STM', hwrev=None, ranges={8: 500, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R2000D40', 'STM', hwrev=None, ranges={8: 2000, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-D8D16', 'EFM', hwrev=None, ranges={80: 8, 32: 16}, flips={80: (-1, -1, 1), 32: (1, 1, 1)}),
        devicedata('S?-D40D200', 'EFM', hwrev=None, ranges={80: 40, 32: 200}, flips={80: (-1, -1, 1), 32: (1, 1, 1)}),
        devicedata('S?-D16', 'EFM', hwrev=None, ranges={32: 16}, flips={32: (1, 1, 1)}),
        devicedata('S?-D200', 'EFM', hwrev=None, ranges={32: 200}, flips={32: (1, 1, 1)}),
        devicedata('S?-D40', 'EFM', hwrev=None, ranges={80: 40}, flips={80: (-1, -1, 1)}),
        devicedata('S?-E25D40', 'EFM', hwrev=None, ranges={8: 25, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E100D40', 'EFM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E500D40', 'EFM', hwrev=None, ranges={8: 500, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E2000D40', 'EFM', hwrev=None, ranges={8: 2000, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-E6000D40', 'EFM', hwrev=None, ranges={8: 6000, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R100D40', 'EFM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R500D40', 'EFM', hwrev=None, ranges={8: 500, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('S?-R2000D40', 'EFM', hwrev=None, ranges={8: 2000, 80: 40},
                   flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E25D40', 'EFM', hwrev=None, ranges={8: 25, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E100D40', 'EFM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-E2000D40', 'EFM', hwrev=None, ranges={8: 2000, 80: 40}, flips={8: (1, 1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R100D40', 'EFM', hwrev=None, ranges={8: 100, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R500D40', 'EFM', hwrev=None, ranges={8: 500, 80: 40}, flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('W?-R2000D40', 'EFM', hwrev=None, ranges={8: 2000, 80: 40},
                   flips={8: (-1, -1, -1), 80: (-1, -1, 1)}),
        devicedata('LOG-0002-100G', 'EFM', hwrev=None, ranges={8: 100}, flips={8: (1, 1, -1)}),
        devicedata('LOG-0002-025G', 'EFM', hwrev=None, ranges={8: 25}, flips={8: (1, 1, -1)}),
        devicedata('LOG-0002-500G', 'EFM', hwrev=None, ranges={8: 500}, flips={8: (1, 1, -1)}),
        devicedata('LOG-0002-02kG', 'EFM', hwrev=None, ranges={8: 2000}, flips={8: (1, 1, -1)}),
        devicedata('LOG-0002-06kG', 'EFM', hwrev=None, ranges={8: 6000}, flips={8: (1, 1, -1)}),
        devicedata('LOG-0002-100G-DC', 'EFM', hwrev=None, ranges={8: 100, 32: 16}, flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-025G-DC', 'EFM', hwrev=None, ranges={8: 25, 32: 16}, flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-500G-DC', 'EFM', hwrev=None, ranges={8: 500, 32: 16}, flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-02kG-DC', 'EFM', hwrev=None, ranges={8: 2000, 32: 16},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-06kG-DC', 'EFM', hwrev=None, ranges={8: 6000, 32: 16},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-100G-200DC', 'EFM', hwrev=None, ranges={8: 100, 32: 200},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-025G-200DC', 'EFM', hwrev=None, ranges={8: 25, 32: 200},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-500G-200DC', 'EFM', hwrev=None, ranges={8: 500, 32: 200},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-02kG-200DC', 'EFM', hwrev=None, ranges={8: 2000, 32: 200},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0002-06kG-200DC', 'EFM', hwrev=None, ranges={8: 6000, 32: 200},
                   flips={8: (1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0004-02kG-DC', 'EFM', hwrev=None, ranges={8: 2000, 32: 16},
                   flips={8: (-1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0004-100G-DC', 'EFM', hwrev=None, ranges={8: 100, 32: 16},
                   flips={8: (-1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0004-500G-DC', 'EFM', hwrev=None, ranges={8: 500, 32: 16},
                   flips={8: (-1, 1, -1), 32: (1, 1, 1)}),
        devicedata('LOG-0004-500G-200DC', 'EFM', hwrev=None, ranges={8: 500, 32: 200},
                   flips={8: (-1, 1, -1), 32: (1, 1, 1)})
        ]


def get_device(partNumber, mcu):
    if not mcu:
        mcu = 'EFM'  # Hack: if no mcu can be found from the device, it'll be an old one using an EFM
    for devdata in devs:
        if fnmatch(partNumber, devdata.name) and mcu.startswith(devdata.mcu):
            # add matching for the hwrev?? would mean adding hwrev parse to calibration.py
            return devdata
