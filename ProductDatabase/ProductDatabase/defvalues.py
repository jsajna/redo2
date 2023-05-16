"""
These are sample values for default sample rates of channels
if a channel has no default, a value may be None (or not included)
a channel element may also have a function-type value to change how the rate is checked
"""

defRates = {"8": 5000,
            "80": 500,
            "84": 400,
            "36": 1,
            "47": 100,
            "59": 10,
            "76": 4,
            "32": 400,
            "43": 100,
            "51": 100,
            "65": 100,
            "70": 100,
            "20": 10,
            "10": None,
            "88": None
            }

defRates = {key: value for key, value in defRates.items() if value}
