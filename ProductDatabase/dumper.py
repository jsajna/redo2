from datetime import datetime
import os.path
import sys

import pytz

if __name__ != "__main__":
    from products import models

UTC = pytz.timezone('utc')


def dump(year, month=1, day=1, end=None, filename=None):
    """ Dump devices with BMM150 and/or BMG250.
    """
    dt = datetime(year, month, day, tzinfo=UTC)
    if end:
        end = datetime(*end, tzinfo=UTC)
    else:
        end = datetime.now(UTC)

    devs = models.Device.objects.filter(created__gte=dt, created__lte=end).extra(order_by=['created'])

    if filename is None:
        filename = f"{dt.date()}_{end.date()}.csv"

    print(f"Found {devs.count()} devices made between {dt.date()} and {end.date()}, filtering those with BMG and/or BMM.")
    with open(filename, 'w') as f:
        n = 0
        f.write('"Date","SN", "PN", "HasBMG", "HasBMM"\n')
        for d in devs:
            hasbmg = d.getSensors(info__name__contains='BMG').count() > 0
            hasbmm = d.getSensors(info__name__contains='NoBMM').count() == 0
            if hasbmg or hasbmm:
                b = d.getLastBirth()
                f.write(f"{b.date.date()},{b.serialNumber},{b.product.partNumber},{hasbmg},{hasbmm}\n")
                n += 1

    return n, filename


if __name__ == "__main__":
    from colorama import Fore, Back, Style, init
    init()

    # Django setup
    BIRTHER_PATH = os.path.dirname(__file__)

    CWD = os.path.realpath(BIRTHER_PATH)
    if CWD not in sys.path:
        sys.path.insert(0, CWD)

    DJANGO_PATH = os.path.realpath(os.path.join(CWD, '..'))
    if DJANGO_PATH not in sys.path:
        sys.path.insert(0, DJANGO_PATH)

    os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

    import django.db
    django.setup()

    # My Django components
    # NOTE: Django import paths are weird. Get `products.models` from Django itself instead of importing.
    from django.apps import apps
    models = apps.get_app_config('products').models_module

    def datesplit(d):
        d = d.replace('/', '-').replace(' ', '-').strip()
        if d:
            return [int(x) for x in d.split('-')]

    print(Style.BRIGHT)
    print(Fore.LIGHTBLUE_EX + "==============================")
    print(Fore.WHITE +        "BMG/BMM Usage Report Generator")
    print(Fore.LIGHTBLUE_EX + "==============================")
    print(Style.RESET_ALL + Fore.RESET)

    now = datetime.now()
    defaultStart = str(datetime(now.year, now.month, 1).date())
    defaultEnd = str(now.date())

    try:
        start = input(f"{Fore.YELLOW}Start date (YYYY-MM-DD, default {defaultStart}): {Fore.RESET}").strip()
        end = input(f"{Fore.YELLOW}End date (YYYY-MM-DD, default {defaultEnd}): {Fore.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        print(Fore.RED)
        print("Cancelled!")
        print(Fore.RESET)
        exit(0)

    start = datesplit(start or defaultStart)
    end = datesplit(end or defaultEnd)

    print(Style.BRIGHT + Fore.LIGHTGREEN_EX)
    result = dump(*start, end)
    print(f"{Fore.LIGHTBLUE_EX}Wrote {result[0]} lines to {result[1]}")
    print(Style.RESET_ALL + Fore.RESET)
