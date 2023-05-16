# -*- coding: utf-8 -*-
"""
Models representing devices, their birth, and their calibration.

FUTURE: Reconsider how the defaults are handled. Using fields in the 'Info'
  objects is kind of ugly. Maybe do it in data, keeping a 'prototype' of each
  unit and all its parts; this gets looked up and copied.

FUTURE: Consider using references to a Django user instead of a name strings.
"""

import calendar
import getpass
from threading import RLock

from django.db import models
from django.utils import timezone

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy

# from orders.models import Order

# ==============================================================================
#
# ==============================================================================


def getKwargs(obj, exclude=()):
    """ Generate constructor keyword arguments from a Model's fields. Used for
        duplicating complete records and their related components (e.g.
        `Birth`, `Device`, `Sensor`, etc.).

        :param obj: The object (a `django.db.models.Model` subclass) from which
            to get the arguments.
        :param exclude: A list of attribute names to ignore.
        :returns: A dictionary of keywords and values.
    """
    result = {}
    for k, v in obj.__dict__.items():
        if k == 'id' or k == "pk" or k.startswith('_') or k[0].isupper():
            # (Probably) Django internal Model stuff. Ignore.
            continue

        if k.endswith('_id'):
            # (Probably) a ForeignKey reference. Get the actual object.
            k = k[:-3]
            v = getattr(obj, k, None)

        if k not in exclude:
            result[k] = v

    return result


def duplicate(obj, **kwargs):
    """ Create a duplicate of an object. Works like the `copy()`
        method of unit-specific objects (Birth, Device, etc.), but
        intended for use with classes that don't implement it
        (i.e. the 'common information' classes, like Product and
        DeviceType). Keyword arguments are passed to the new object.

        :returns: The duplicate object.
    """

    copyArgs = getKwargs(obj)
    copyArgs.update(kwargs)

    newObj = type(obj)(**copyArgs)
    newObj.save()

    return newObj


def getBirth(serialNumber, **kwargs):
    """ Convenience function for getting the last birth of a given serial
        number. Keyword arguments will be used to filter (e.g.,
        `completed=True`).
    """
    return Birth.objects.filter(serialNumber=serialNumber, **kwargs).latest('date')


# ==============================================================================
# Auto-incrementing serial numbers, with an arbitrary starting point,
# decoupled from Django's IDs.
# ==============================================================================

def validateNumberFormat(s):
    """ Simple Django validator for serial number formatting strings.
    """
    if not isinstance(s, str):
        raise ValidationError(gettext_lazy('bad type for formatter: %(ftype)s',
                                            params={'ftype': type(s)}))
    try:
        # Dumb way to check that the formatting string works: use it
        return (s % 42)
    except (TypeError, ValueError) as err:
        raise ValidationError(gettext_lazy('%(err)s', params={'err': err}))


class LastSerialNumber(models.Model):
    """ Storage for keeping track of the last serial number. The database
        should only contain one object per 'family' of devices, which gets
        updated every time a new serial number is generated.
    """
    groupName = models.CharField(max_length=40, db_index=True, unique=True,
        help_text="The name of the serial number group. Different groups have "
        "different serial numbers, which are incremented independently.")
    serialNumber = models.IntegerField(default=1,
        help_text="The sensor name or short description.")
    incDate = models.DateTimeField(default=timezone.now,
        help_text="The last time the serial number group was incremented.")

    # Lock as a class variable for easy access. Not sure if this will work in
    # actual deployment; are Django connections threads or processes?
    _lock = RLock()


    def __str__(self):
        return "%s SN:%s" % (self.groupName, self.serialNumber)


def newSerialNumber(groupName="SlamStick"):
    """ Retrieve the next sequential serial number for a named group of items.

        @note: This is not entirely safe; there's a non-zero chance that two
        nearly simultaneous attempts at getting a new serial number could
        conflict. Obviously, that's extraordinarily unlikely in our system.

        :param groupName: The name of the grouping of serial numbers (e.g.
            a device name).
    """
    now = timezone.now()
    with LastSerialNumber._lock:
        sn = LastSerialNumber.objects.get(groupName=groupName)
        sn.serialNumber += 1
        sn.incDate = now
        sn.save()

    return sn.serialNumber


def revertSerialNumber(number, groupName="SlamStick"):
    """ Attempt to decrement a serial number. For use if a birth fails (or
        is aborted) late in the process.

        :param number: The serial number to attempt to roll back. The
            roll-back will fail if the number to revert isn't the last one (i.e.
            another serial number was generated in the meantime). Using ``-1``
            will decrement without checking (not recommended!).
        :param groupName: The name of the grouping of serial numbers (e.g.
            a device type/family name).
        :returns: `True` if the number was successfully reverted, `False` if not.
    """
    with LastSerialNumber._lock:
        sn = LastSerialNumber.objects.get(groupName=groupName)
        if sn.serialNumber == number or number == -1:
            sn.serialNumber -= 1
            sn.save()
            return True
    return False


# ==============================================================================
# Devices and birthing
# ==============================================================================

class Batch(models.Model):
    """ A set of boards received from manufacturing.
    """
    class Meta:
        verbose_name_plural = "batches"

    batchId = models.CharField(max_length=20, db_index=True,
        help_text="The name/ID of this batch of hardware.")
    manufacturer = models.CharField(max_length=20,
        help_text="The manufacturer of the batch.")
    date = models.DateTimeField(null=True, blank=True,
        help_text="The date the batch was received.")
    total = models.IntegerField(null=True, blank=True,
        help_text="The total number of units delivered in the batch.")
    failures = models.IntegerField(null=True, blank=True,
        help_text="The total number of failed units in the batch.")
    notes = models.TextField(blank=True,
        help_text="General notes about the batch.")


    def __str__(self):
        return self.batchId


    @property
    def dateString(self):
        """ The date the batch was received, in US format (M/D/Y).
        """
        return self.date.strftime('%m/%d/%Y')


class Product(models.Model):
    """ Information about a particular model, common to other devices with the
        same part number (e.g. all LOG-0002-100 Slam Sticks).
    """
    name = models.CharField(max_length=40,
        help_text='Product name (e.g. "S3-E100D40" or "Slam Stick X (100g)").')
    partNumber = models.CharField(max_length=40,
        help_text='Product part number (e.g. "S3-E100D40" or "LOG-0002-100").')
    typeUID = models.IntegerField(null=True, blank=True,
        help_text="Product device type UID.")
    templateFile = models.CharField(max_length=100, blank=True,
        help_text="The 'base' XML manifest template for the birthed device. "
                  "Defaults to one based on the part number.")
    calTemplateFile = models.CharField(max_length=100, blank=True,
        help_text="The 'base' XML calibration template for the birthed device. "
                  "Defaults to one based on the part number.")
    calCertificate = models.ForeignKey('CalCertificate', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The default calibration certificate for this Product.")

    serialNumberFormat = models.CharField(max_length=16, default="S%07d",
        validators=[validateNumberFormat],
        help_text="A Python formatting string for the serial number. Use '%0d' "
        "for decimal, '%0x' for hex. Specify the number of digits after the "
        "'%0' (e.g if the serial number is 1, '%04d' would produce '0001')")

    retired = models.BooleanField(default=False,
        help_text="Is this Product no longer in production?")

    notes = models.TextField(blank=True,
        help_text="General notes about the Product.")


    def __str__(self):
        if self.partNumber == self.name:
            return self.partNumber
        return "%s '%s'" % (self.partNumber, self.name)


class Birth(models.Model):
    """ A record of a Device being birthed (getting its data prepared and
        its firmware uploaded). One Device may have multiple Births (e.g.
        a Slam Stick that had its firmware updated when it was sent back for
        recalibration, or a failed device that has been fixed).

        Note: Births with serial number -1 are "examples," used when creating
        new entries.
    """
    # Displayed names of exemplar types. Exemplars have SN < 0.
    EXAMPLE = -1
    RETIRED = -2
    PREVIEW = -3

    TYPES = {EXAMPLE: "(EXAMPLE)",
             RETIRED: "(RETIRED)",
             PREVIEW: "(PREVIEW)"}

    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The Product birthed.")
    device = models.ForeignKey("Device", on_delete=models.CASCADE, null=True, blank=True,
        help_text="The birthed Device (the physical hardware).")
    date = models.DateTimeField(default=timezone.now, null=True, blank=True,
        help_text="Date of device birth (its 'birthday').")
    user = models.CharField(max_length=20, blank=True,
        help_text="Technician who performed the birthing.")

    exemplar = models.ForeignKey("Birth", on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The 'exemplar' from which this unit was birthed.")

    bootRev = models.CharField(max_length=20, blank=True,
        help_text="The bootloader version.")
    bootloader = models.CharField(max_length=200, blank=True,
        help_text="The manually-selected bootloader file installed in this Birth (if any).")
    
    fwRev = models.IntegerField(null=True, blank=True,
        help_text="The firmware version installed at birth.")
    fwRevStr = models.CharField(max_length=16, blank=True,
        help_text="The full firmware version, (e.g. 1.2.3).")
    firmware = models.CharField(max_length=200, blank=True,
        help_text="The manually-selected firmware file installed in this Birth (if any).")
    fwCustomStr = models.CharField(max_length=80, blank=True,
        help_text=("Custom firmware build version and/or short description. "
                   "Firmware is a custom build if present."))
    
    wifiFirmware = models.CharField(max_length=200, blank=True,
        help_text="The manually-selected ESP32 firmware file installed in this Birth (if any).")
    wifiFwRevStr = models.CharField(max_length=16, blank=True,
        help_text="The full ESP32 firmware version, (e.g. 1.2.3).")

    sku = models.CharField(max_length=200, blank=True,
        help_text="The unit's SKU (full part number, with capacity and case "
        "type), if it differs from the Product Name.")
    serialNumber = models.IntegerField(null=True, blank=True,  db_index=True,
        help_text="Device serial number, assigned at birth.")

    test = models.BooleanField(default=False,
        help_text="Was this a test run, rather than actual production?")

    rebirth = models.BooleanField(default=False,
        help_text="Was this device previously birthed?")

    completed = models.BooleanField(default=True,
        help_text=("Did the birthing process complete successfully? "
                   "Note: may not be accurate for old births."))

    orderId = models.CharField(max_length=20, blank=True, db_index=True,
        help_text=("The ID/number of the order that included this device. "
                   "If not built to order, update after sale."))

    notes = models.TextField(blank=True,
        help_text="General notes about the birth.")


    def __str__(self):
        pn = self.product or "[Unspecified Product Type!]"
        if self.device and self.device.hwType:
            pn = "%s HwRev %s" % (pn, self.device.hwType.hwRev)

        if not self.serialNumber or self.serialNumber < 0:
            if self.notes:
                pn = "%s '%s'" % (pn, self.notes)
            sn = self.TYPES.get(self.serialNumber, "(PENDING)")
        else:
            try:
                sn = self.product.serialNumberFormat % self.serialNumber
            except (AttributeError, TypeError):
                sn = self.serialNumber
            sn = "SN:%s" % sn
        return "%s %s" % (pn, sn)


    # ==========================================================================
    # Properties for easy access to formatted values by manifest generator.
    # ==========================================================================


    @property
    def timestamp(self):
        """ The birth date/time as POSIX Epoch time. Will fail with an
            `AttributeError` if the Birth's `date` is `None`.
        """
        return calendar.timegm(self.date.timetuple())


    @property
    def dateString(self):
        """ The device birth date, in US format (M/D/Y).
        """
        return self.date.strftime('%m/%d/%Y')


    @property
    def typeUID(self):
        """ The `typeUID` of the birthed product. Same as `product.typeUID`
            (if the `Birth` references a `Product`). Defaults to 1.
        """
        if self.product:
            uid = self.product.typeUID
        else:
            uid = None

        return uid if uid is not None else 1


    @property
    def serialNumberString(self):
        """ The birthed device's serial number, formatted as a string.
            Formatting info comes from the `Birth`'s associated `Product` (if
            any).
        """
        if self.product:
            return self.product.serialNumberFormat % (self.serialNumber or 0)
        return str(self.serialNumber)


    @property
    def partNumber(self):
        """ The birthed product's part number.

            Originally for compatibility with version of Birth that stored
            the value itself. This should probably get removed later.
        """
        if self.product:
            return self.product.partNumber
        return ""


    @property
    def productName(self):
        """ The birthed product's name.

            Originally for compatibility with version of Birth that stored
            the value itself. This should probably get removed later.
        """
        if self.product:
            return self.product.name
        return ""


    def getSKU(self):
        """ Get the birthed product's SKU. If no special SKU has been defined,
            this is the same as the part number.
        """
        if self.sku:
            return self.sku
        return self.partNumber


    # ==========================================================================
    #
    # ==========================================================================


    def copy(self, recurse=False, **kwargs):
        """ Copy this Birth and its Device, duplicating the general fields
            (i.e. those not applicable to a single Birth, e.g. the serial
            number). Keyword arguments are passed to the new Birth. Some
            instance-specific attributes will not be copied, including `notes`,
            `orderId`, `date`, `rebirth`, etc.

            The Birth's `Device` will also get copied if `recurse` is `True`
            and no `device` has been specified in the keyword arguments.
            Otherwise, the new Birth will reference the same Device (i.e. a
            rebirth). The duplicate `Device` will need to have its instance-
            specific attributes (e.g. `chipId`) explicitly set.

            :param recurse: If `True`, duplicate the Birth's device and all
                its sensors. See `Device.copy()`.  Note: unlike other objects
                with a `copy()` method, the default here is `False`!
            :returns: The duplicate Birth object.
        """
        if recurse and 'device' not in kwargs:
            print('copying device')
            kwargs['device'] = self.device.copy(recurse=recurse)

        if 'exemplar' not in kwargs:
            if (kwargs.get('serialNumber') or 0) >= 0:
                kwargs['exemplar'] = self.getExample()

        copyArgs = getKwargs(self, exclude=('notes', 'orderId', 'date', 'user',
                                            'rebirth', 'exemplar'))
        copyArgs.update(kwargs)

        newBirth = Birth(**copyArgs)
        newBirth.save()

        return newBirth


    def getExample(self, multi=False, search=False, exact=True, **kwargs):
        """ Find the Example unit on which this Birth was based. Returns the
            `exemplar` if one is defined, otherwise it returns the most similar
            Birth (same `Product`, `DeviceType`, and sensors). Keyword arguments
            (other than those listed below) are used in the query. Births
            that are themselves Examples return themselves (see below).

            :param multi: If `True`, allow the return of more than one
                Example.
            :param search: If `True`, perform the search for the closest
                matching example, even if this Birth has an `exemplar`
                defined or is itself an Example.
            :param exact: If `False` and the Birth does not explicitly define
                an `exemplar`, the Example with the most similar set of sensors
                will be returned. If `True`, only the Example with an identical
                set will be returned. Has no effect if `multi` is `True`.
            :return: An "example" Birth, or a QuerySet of Births if `multi`
                is `False`. Births that are exemplars will return themselves
                (unless `search` is `True`). Some special-case devices may
                return `None`.
        """
        if not search:
            ex = self if self.serialNumber < 0 else self.exemplar

            if ex:
                if multi:
                    # for uniformity: if `multi=True`, always return `QuerySet` or `None`
                    return Birth.objects.filter(pk=ex.pk)
                else:
                    return ex

        b = Birth.objects.filter(serialNumber__lt=0, product=self.product,
                                 device__hwType=self.device.hwType, **kwargs)

        if multi:
            return b
        elif b.count() == 0:
            return None
        elif b.count() == 1 and not exact:
            return b.last()

        # Attempt to find the best match based on fewest differences in sensors.
        # Note: This is slow.
        sens = set(s.info.pk for s in self.device.sensor_set.all())
        examples = [(len(set(s.info.pk for s in x.device.sensor_set.all()).symmetric_difference(sens)), x) for x in b]
        examples.sort(key=lambda x: x[0])

        if not exact:
            return examples[0][1]

        return examples[0][1] if examples[0][0] == 0 else None


    def getTemplateName(self):
        """ Get the name of the 'base' manifest XML fragment for this object.
            This is either taken from the object's `Product` or the object's
            part number.
        """
        # FUTURE: Smarter name generation (if needed), including device hardware
        # revision, maybe.
        if self.product:
            return self.product.templateFile or self.partNumber
        return self.partNumber


# ==============================================================================
#
# ==============================================================================

class DeviceType(models.Model):
    """ A device hardware type, e.g. its PCB design. Not specific to a single
        `Device` instance. For differentiating hardware of different families,
        not just minor hardware revisions within a device line. Also stores
        default values used when instantiating a `Device`.
    """

    name = models.CharField(max_length=80, blank=True, db_index=True,
        help_text="The human-readable name of the device line/PCB design.")
    partNumber = models.CharField(max_length=80, blank=True, db_index=True,
        help_text="The PCB part number, as used by the board fabricator.")
    mcu = models.CharField(max_length=80, blank=True,
        help_text="The CPU/MCU in the device.")

    hwRev = models.IntegerField(db_index=True,
        help_text="The board's hardware revision number.")
    hwApi = models.IntegerField(default=0,
        help_text="The required API level of this hardware.")
    minFwRev = models.IntegerField(null=True, blank=True,
        help_text="The hardware's  minimum firmware version.")

    notes = models.TextField(blank=True,
        help_text="General notes about the device type.")


    @property
    def hwRevStr(self):
        """ The hardware's revision number, formatted.
        """
        rev = self.hwRev
        try:
            if rev > 99:
                major = int(rev/10000)
                minor = int((rev % 10000) / 100)
                rev = f"v{major}r{minor}"
        except TypeError:
            pass
        return str(rev)


    def __str__(self):
        return "%s rev %s" % (self.name, self.hwRev)


class Device(models.Model):
    """ A single, specific piece of hardware (e.g. a Slam Stick, ENDAQ hub,
        etc.). Should be created when a batch of boards arrives from
        manufacturing.

        This model represents the properties of the hardware itself, i.e.
        properties that can't change in the birthing process. Device name,
        part number, serial number, firmware version, and device type UUID are
        properties of `Birth` or `Product`. For convenience, properties have
        been defined that fetch this information from the Device's latest
        `Birth` record.
    """
    ENCLOSURE_NONE  = 0
    ENCLOSURE_PC    = 1
    ENCLOSURE_AL    = 2
    ENCLOSURE_S5    = 3
    ENCLOSURE_W5    = 4
    ENCLOSURE_W8    = 5
    ENCLOSURE_OTHER = 99

    ENCLOSURE_TYPES = ((ENCLOSURE_NONE,     "Unknown/None"),
                       (ENCLOSURE_PC,       "Polycarbonate (PC)"),
                       (ENCLOSURE_AL,       "Aluminum (AL)"),
                       (ENCLOSURE_S5,       "S5 Enclosure (AL)"),
                       (ENCLOSURE_W5,       "W5 Enclosure (AL/PC)"),
                       (ENCLOSURE_W8,       "W8 Enclosure (AL/PC)"),
                       (ENCLOSURE_OTHER,    "Other"))

    BOM_REVS = tuple(enumerate(" ABCDEFGHIJKLMNOPQRSTUVWXYZ"))

    # XXX: Should the chipId be forced to be unique? Can I generate the UUID
    #  used in ENDAQ H module EEPROM, or will it come from Pete?
    chipId = models.CharField(max_length=64, blank=True, db_index=True,
        help_text="The device's unique ID, e.g. the MCU hardware ID.")
    batch = models.ForeignKey(Batch, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The batch in which this hardware arrived from manufacturing.")
    hwType = models.ForeignKey(DeviceType, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The base hardware type. Has common info related to the PCB.")
    hwCustomStr = models.CharField(max_length=80, blank=True,
        help_text="Custom hardware identifier. Hardware is a custom version if present.")
    bomRev = models.IntegerField(default=0, choices=BOM_REVS,
        help_text="Bill of Materials (BOM) revision. Shown as a letter, stored as a number (0 = none, 1 = A, etc.)")
    battery = models.ForeignKey('Battery', null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The device's internal battery (if applicable).")
    capacity = models.IntegerField(default=8, null=True, blank=True,
        help_text="The device's internal storage capacity (if applicable).")
    enclosure = models.IntegerField(default=0, choices=ENCLOSURE_TYPES,
        help_text="The type (and/or material) of the case.")

    created = models.DateTimeField(default=timezone.now, null=True, blank=True,
        help_text="Date of device's record creation (usually its birthday).")
    modified = models.DateTimeField(null=True, blank=True,
        help_text="Date of device's last modification (if any).")

    orderId = models.CharField(max_length=20, blank=True, db_index=True,
        help_text="The ID/number of the order that included this device. "
                  "If not built to order, update after sale.")

    notes = models.TextField(blank=True,
        help_text="General notes about the device.")


    def __str__(self):
        # Is including a foreign key in __str__ a bad idea (overhead, etc.)?
        idStr = ("ID:%s" % self.chipId) if self.chipId else "(No ID)"
        typeStr = str(self.hwType) if self.hwType else "[Unknown HW Type!]"
        return "%s %s" % (typeStr, idStr)


    # ==========================================================================
    # Convenience methods/properties for accessing Birth-related data.
    # ==========================================================================


    def getLastBirth(self, **kwargs):
        """ Helper method to get the latest Birth of the Device.
            Keyword arguments will be used to filter (e.g., `completed=True`).
        """
        # FUTURE: Cache this, clear cache if Birth table altered
        try:
            return self.birth_set.filter(**kwargs).latest('date')
        except Birth.DoesNotExist:
            return None

    
    def getLastCal(self, **kwargs):
        """ Helper method to get the latest calibration (CalSession) of the
            Device. Keyword arguments will be used to filter (e.g.,
            `completed=True`).

        """
        try:
            return self.calsession_set.filter(**kwargs).latest('date')
        except CalSession.DoesNotExist:
            return None
        

    @property
    def serialNumber(self):
        """ The latest serial number assigned to the Device (if any).
        """
        birth = self.getLastBirth()
        if birth:
            return birth.serialNumber


    @property
    def partNumber(self):
        """ The latest part number assigned to the Device (if any).
        """
        birth = self.getLastBirth()
        if birth:
            return birth.partNumber


    @property
    def productName(self):
        """ The latest product name assigned to the Device (if any).
        """
        birth = self.getLastBirth()
        if birth:
            return birth.productName


    @property
    def hwRev(self):
        """ The hardware's revision number.
        """
        if self.hwType:
            hwRev = self.hwType.hwRev
            if hwRev > 99:
                # New format hwRev combining version and revision; add BOM Rev to end
                hwRev = hwRev * 100 + self.bomRev
            return hwRev


    @property
    def hwRevStr(self):
        """ The hardware's revision number, formatted. Includes BOM revision.
        """
        rev = self.hwRev
        try:
            if rev > 99:
                major = int(rev/10000)
                minor = int((rev % 10000) / 100)
                bom = rev % 100
                rev = f"v{major}r{minor}{chr(bom+64) if bom > 0 else ''}"
        except TypeError:
            pass
        return str(rev)


    @property
    def minFwRev(self):
        """ The minimum firmware version compatible with this device.
        """
        if self.hwType:
            return self.hwType.minFwRev


    @property
    def batchId(self):
        """ The ID of the batch this device's hardware was in. Basically the
            same as casting the `Batch` to a string, but handles nulls.
        """
        if self.batch and self.batch.batchId:
            return self.batch.batchId
        return ""


    @property
    def timestamp(self):
        """ The date/time of manufacture as POSIX Epoch time. Will fail with an
            `AttributeError` if the Device's `created` is `None`.
        """
        return calendar.timegm(self.created.timetuple())


    def getSensors(self, analog=True, digital=True, **kwargs):
        """ Convenience method to get all the `Sensor` objects referencing
            this device. Keyword arguments other that `analog` and `digital`
            are used in the query.

            :param analog: If `False`, exclude analog sensors.
            :param digital: if `False, exclude digital sensors.
            :returns: a `QuerySet` with the Device's sensors.
        """
        # FUTURE: Cache this, clear cache if Sensor table altered
        sens = self.sensor_set.all().extra(order_by=['sensorId'])

        if analog == digital:
            return sens.filter(**kwargs)
        elif analog:
            return sens.filter(info__analog=True, **kwargs)
        else:
            return sens.filter(info__analog=False, **kwargs)


    def compareSensors(self, other, **kwargs):
        """ Compare the sensors of this Device with those of another. Sensors
            are considered the same if they have the same `info`, `sensorId`,
            and `calibrationId`.

            :param other: The other `Device`, with which to compare.
            :returns: A tuple containing a Boolean (whether or not the two
                devices have matching sensors), and a list of tuples mapping
                this Device's sensors to the corresponding one on the other
                Device. Sensors present in the other but not this Device will
                have `None` as the first tuple item; sensors in this Device but
                not the other will have `None` in the second column.
        """
        sSens = list(self.getSensors(**kwargs))

        if other == self:
            return True, list(zip(sSens, sSens))

        oSens = list(other.getSensors(**kwargs))

        # Sensors are considered the 'same' in this context if they are
        # the same type, have the same SensorID, and the same CalibrationId
        sSensIds = [(s.info.id, s.sensorId, s.calibrationId) for s in sSens]
        oSensIds = [(s.info.id, s.sensorId, s.calibrationId) for s in oSens]

        same = True
        result = []

        for i in sSensIds+oSensIds:
            ss = None
            os = None

            if i in sSensIds:
                idx = sSensIds.index(i)
                ss = sSens.pop(idx)
                sSensIds.pop(idx)
            if i in oSensIds:
                idx = oSensIds.index(i)
                os = oSens.pop(idx)
                oSensIds.pop(idx)

            if not (ss is None and os is None):
                result.append((ss, os))
                same = same and not (ss is None or os is None)

        return same, result


    def sameAs(self, other, capacity=True, battery=True):
        """ Check if this device is the same type as another: same info,
            same channels, etc. Separated from `__eq__()` to avoid interfering
            with Django.

            :param other: The other `Device` to compare against.
            :param capacity: If `True` (default), include device storage
                capacity in the comparison.
            :param battery: If `True` (default), include device battery in
                the comparison.
        """
        if self == other:
            return True

        try:
            if not (self.hwType == other.hwType and
                    self.hwCustomStr == other.hwCustomStr):
                return False

            if capacity and self.capacity != other.capacity:
                return False

            if battery and self.battery != other.battery:
                return False

            mySensors = self.getSensors()
            otherSensors = other.getSensors()
            if len(mySensors) != len(otherSensors):
                return False
            for myS, otherS in zip(mySensors, otherSensors):
                if not myS.sameAs(otherS):
                    return False

            return True

        except AttributeError:
            return False


    # ==========================================================================
    #
    # ==========================================================================


    def copy(self, recurse=True, **kwargs):
        """ Copy this Device and its sensors, duplicating the general fields
            (i.e. those not applicable to a single Device). Keyword arguments
            are passed to the new Device. Some instance-specific attributes
            will not be copied, including `chipId`, `batch`, and `orderId`.

            :param recurse: If `True`, duplicate all the sensors that
                reference this `Device`.
            :returns: The new `Device` instance.
        """
        copyArgs = getKwargs(self, exclude=('chipId', 'batch', 'orderId'))
        copyArgs.update(kwargs)

        newDevice = Device(**copyArgs)
        newDevice.save()

        if recurse:
            for s in self.sensor_set.all():
                s.copy(device=newDevice)

        return newDevice


    def copyFrom(self, device, recurse=True, **kwargs):
        """ Copy all the objects associated with another device, i.e. the
            various sensors and battery info. A basic `Device` record can be
            created for each board in a batch, and then this method can fill
            in the details that are set during manufacture.

            :param device: The source `Device`, from which to copy info.
            :param recurse: If `True`, duplicate all the sensors that
                reference this `Device`.
        """
        copyArgs = getKwargs(device, exclude=('chipId', 'created'))
        copyArgs.update(kwargs)
        copyArgs.setdefault('modified', timezone.now())

        for k, v in copyArgs.items():
            setattr(self, k, v)
        self.save()

        if recurse:
            for s in device.sensor_set.all():
                s.copy(device=self)


# ==============================================================================
#
# ==============================================================================


class Failure(models.Model):
    """ A record of a failed Device. A Device may have multiple Failures
        (e.g. something that had a problem when it was first birthed, had that
        problem corrected, but developed a fault later).
    """

    # Categories of failures.
    DEFECTIVE =    -1
    ACCELEROMETER = 0
    BATTERY =       1
    ENCLOSURE =     2
    ERROR =         3
    MEMBRANE =      4
    STORAGE =       5
    USB =           6
    USER =          7
    UNKNOWN =       8
    OTHER =        99

    FAILURE_TYPES =    ((DEFECTIVE,    'Manufacturing Defect'),
                        (ACCELEROMETER, 'Accelerometer'),
                        (BATTERY,      'Battery/Power'),
                        (ENCLOSURE,    'Enclosure'),
                        (ERROR,        'Mide Mistake'),
                        (MEMBRANE,     'Membrane'),
                        (STORAGE,      'Storage (SD/eMMC)'),
                        (USB,          'USB'),
                        (USER,         'User Damage'),
                        (UNKNOWN,      'Unknown (describe in notes)'),
                        (OTHER,        'Other EE/FW (describe in notes)'))

    # Categories of resolutions. OTHER (99) is also a resolution category.
    UNRESOLVED =   -1
    REPAIRED =      0
    REPLACED =      1
    REFUNDED =      2
    RETURNED =      3
    STOCK =         4
    DESTROYED =     5

    RESOLUTION_TYPES = ((UNRESOLVED,    'Unresolved'),
                        (REPAIRED,      'Repaired'),
                        (REPLACED,      'Replaced'),
                        (REFUNDED,      'Refunded'),
                        (RETURNED,      'Returned to Customer'),
                        (STOCK,         'Returned to Stock'),
                        (DESTROYED,     'Destroyed'),
                        (OTHER,         'Other (describe in Notes)'))

    failureType = models.IntegerField(default=-1, choices=FAILURE_TYPES,
        help_text="The category of failure.")
    device = models.ForeignKey(Device, on_delete=models.SET_NULL, null=True,
        help_text="The defective item.")
    date = models.DateTimeField(default=timezone.now,
        help_text="Date the failure was detected and/or logged.")
    user = models.CharField(max_length=20, blank=True,
        help_text="Technician who reported the issue.")
    resolved = models.BooleanField(default=False,
        help_text="Has this issue been resolved?")
    resolutionDate = models.DateTimeField(null=True, blank=True,
        help_text="Date the issue was resolved.")
    resolvedBy = models.CharField(max_length=20, blank=True,
        help_text="Technician who resolved the issue.")  # Maybe a ForeignKey to Django User?
    resolutionType = models.IntegerField(default=-1, choices=RESOLUTION_TYPES,
         help_text="The category of resolution.")

    orderId = models.CharField(max_length=20, blank=True, db_index=True,
        help_text="The return order that included this device (if any).")

    notes = models.TextField(blank=True,
        help_text="General notes about the failure. Update if resolved.")


    def __str__(self):
        return self.device


    @property
    def dateString(self):
        """
        """
        return self.date.strftime('%m/%d/%Y')


# ==============================================================================
# Sensors
# ==============================================================================


class SensorInfo(models.Model):
    """ Information about a model of `Sensor`. Not exclusive to a single
        device.

        Note: "Sensor" is somewhat of a misnomer, since this covers various
        components (battery charger, membrane LEDs, etc.), but most
        peripherals' EBML element names originally contains the word 'Sensor',
        so it stuck.    
    """
    class Meta:
        verbose_name_plural = "sensor info"

    name = models.CharField(max_length=100,
        help_text="The sensor name or short description.")
    partNumber = models.CharField(max_length=100,
        help_text="The sensor type, e.g. its manufacturer's part number.")
    manufacturer = models.CharField(max_length=100,
        help_text="The sensor's manufacturer.")
    analog = models.BooleanField(default=False,
        help_text="Is this an analog sensor?")
    hasSerialNumber = models.BooleanField(default=False,
        help_text="Does this sensor have its own serial number?")
    scaleHint = models.FloatField(null=True, blank=True,
        help_text="The maximum value generated by the sensor.")

    tempComp = models.FloatField(default=0,
        help_text="The sensor's temperature compensation (if applicable).")
    tempOffset = models.FloatField(default=0,
        help_text="The sensor's temperature offset (if applicable).")
    compChannelId = models.IntegerField(null=True,
        help_text="The ID of the channel used for temperature compensation in bivariate polynomial calibration.")
    compSubchannelId = models.IntegerField(null=True,
        help_text="The ID of the subchannel used for temperature compensation in bivariate polynomial calibration.")

    templateFile = models.CharField(max_length=100, blank=True,
        help_text="Manifest XML fragment template. Defaults to name.")
    calTemplateFile = models.CharField(max_length=100, blank=True,
        help_text="Calibration XML fragment template.")
    birthCalTemplateFile = models.CharField(max_length=100, blank=True,
        help_text="Generic calibration XML fragment template (used at birth).")
    
    deviceCode = models.IntegerField(default=1,
        help_text="The analog sensor's identifying device code.")
    usesFilter = models.BooleanField(default=True,
        help_text="Does this sensor use the antialiasing filter?")
    settlingTime = models.IntegerField(default=16384,
        help_text="The analog sensor's identifying device code.")
    # sensorConfig = models.IntegerField(default=0,
    #     help_text="Optional configuration data. Varies by sensor type.")
        
    notes = models.TextField(blank=True,
        help_text="General notes about the model of sensor.")


    def __str__(self):
        if self.notes:
            return "%s: %s" % (self.name, self.notes)
        return self.name


class Sensor(models.Model):
    """ A peripheral (such as a sensor) on a specific Device. 
    
        Note: "Sensor" is somewhat of a misnomer, since this covers various
        components (battery charger, membrane LEDs, etc.), but most
        peripherals' EBML element names originally contains the word 'Sensor',
        so it stuck.    
    """
    sensorId = models.IntegerField(default=8, blank=True, null=True,
        help_text="The sensor's ID number. Not required for digital sensors.")
    device = models.ForeignKey(Device, on_delete=models.CASCADE, blank=True, null=True,
        help_text="The device with this sensor.")
    serialNumber = models.CharField(max_length=20, blank=True,
        help_text="The sensor's serial number.")
    info = models.ForeignKey(SensorInfo, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The component type.")
    calibrationId = models.IntegerField(null=True, blank=True,
        help_text="The channel's calibration ID.")
    notes = models.TextField(blank=True,
        help_text="General notes about this specific component.")


    def __repr__(self):
        if self.sensorId is None:
            return "<%s: %s>" % (type(self).__name__, self)

        return "<%s: %s (ID %s)>" % (type(self).__name__, self, self.sensorId)


    def __str__(self):
        # Is including a foreign key in __str__ a bad idea (overhead, etc.)?
        if self.serialNumber:
            return "%s SN:%s" % (self.info.name, self.serialNumber)
        return self.info.name


    @property
    def partNumber(self):
        """ The sensor's part number, retrieved from its `SensorInfo`.
        """
        if self.info:
            return self.info.partNumber


    def addChannel(self, **kwargs):
        """ Add a new `SensorChannel` to the `Sensor`. Keyword arguments are
            passed to the `SensorChannel` constructor. By default, the
            `channelId` is incremented automatically.
        """
        if 'channelId' not in kwargs:
            kwargs['channelId'] = self.sensorchannel_set.count()

        return SensorChannel(sensor=self, **kwargs)


    def getChannels(self, **kwargs):
        """ Convenience method to get all the `SensorChannel` objects
            referencing this Sensor. Keyword arguments are used in the query.

            :returns: a `QuerySet` with the Sensor's channels.
        """
        # FUTURE: Cache this, clear cache if SensorChannel table altered
        return self.sensorchannel_set.filter(**kwargs).extra(
                                     order_by=['channelId', 'calibrationId'])


    def copy(self, recurse=True, **kwargs):
        """ Copy this Sensor and its channels, duplicating the general fields
            (i.e. those not applicable to a single Sensor). Keyword arguments
            (other than `recurse`) are passed to the new Sensor. Some instance-
            specific attributes will not be copied, including `device`,
            'serialNumber`, and `notes`.

            :param recurse: If `True`, copy all sensor subchannels as well.
            :returns: The duplicate Sensor object.
        """
        copyArgs = getKwargs(self, exclude=("device", "serialNumber", "notes"))
        copyArgs.update(kwargs)

        newSensor = Sensor(**copyArgs)
        newSensor.save()

        if recurse:
            for channel in self.sensorchannel_set.all():
                channel.copy(sensor=newSensor)

        return newSensor


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed)
        if self.info.templateFile:
            return self.info.templateFile

        return self.info.name


    def getCalTemplateName(self):
        """ Get the name of the calibration XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed)
        return self.info.calTemplateFile


    def sameAs(self, other):
        """ Check if this sensor is the same type as another: same info,
            same channels, etc. Separated from `__eq__()` to avoid interfering
            with Django.
        """
        if self == other:
            return True

        try:
            if not (self.info == other.info and
                    self.sensorId == other.sensorId and
                    self.calibrationId == other.calibrationId):
                return False

            myChannels = self.getChannels()
            otherChannels = other.getChannels()
            if len(myChannels) != len(otherChannels):
                return False
            for myS, otherS in zip(myChannels, otherChannels):
                if not myS.sameAs(otherS):
                    return False

            return True

        except AttributeError:
            return False


class SensorChannelInfo(models.Model):
    """ General information about a single type of sensor channel. Not
        exclusive to a single `SensorChannel`. Also keeps default values that
        get copied to the instantiated `SensorChannel` (makes it easier to add
        a channel when birthing a custom unit).
    """
    class Meta:
        verbose_name_plural = "sensor channel info"

    name = models.CharField(max_length=100,
        help_text="The sensor channel name or short description. Not the name "
                  "given to the channel in the manifest.")

    defaultChannelId = models.IntegerField(default=0, null=True, blank=True,
        help_text="The default channel ID.")
    defaultAdcChannel = models.IntegerField(null=True, blank=True,
        help_text="The default ADC channel (if applicable).")
    defaultAxisName = models.CharField(max_length=16, blank=True,
        help_text="The channel's default axis name (e.g. 'X', 'Temperature').")
    defaultLabel = models.CharField(max_length=16, blank=True,
        help_text="The channel's default label (e.g. 'Acceleration').")
    defaultUnits = models.CharField(max_length=16, blank=True,
        help_text="The channel's default units (e.g. 'g').")

    ctf = models.IntegerField(default=1,
        help_text="The sensor channel's CTF (Capacitor Tuned Filter).")

    templateFile = models.CharField(max_length=100, blank=True,
        help_text="Manifest XML fragment template. Defaults to name.")
    calTemplateFile = models.CharField(max_length=100, blank=True,
        help_text="Calibration XML fragment template.")
    birthCalTemplateFile = models.CharField(max_length=100, blank=True,
        default="Cal_SensorChannel_Default.xml",
        help_text="Generic calibration XML fragment template (used at birth).")

    notes = models.TextField(blank=True,
        help_text="General notes about the model of sensor.")


    def __str__(self):
        return self.name


class SensorChannel(models.Model):
    """ A single sensor channel on a specific Device's Sensor. Currently, only
        analog sensors specify subchannels.
    """
    channelId = models.IntegerField(default=0,
        help_text="The channel ID. Should be sequential.")
    adcChannel = models.IntegerField(null=True, blank=True,
        help_text="The associated ADC channel (if applicable).")
    sensor = models.ForeignKey(Sensor, on_delete=models.CASCADE, null=True,
        help_text="The sensor that generates this channel.")
    axisName = models.CharField(max_length=16, blank=True,
        help_text="The channel's axis name (e.g. 'X', 'Temperature').")
    label = models.CharField(max_length=16, blank=True,
        help_text="The channel's label (e.g. 'Acceleration').")
    units = models.CharField(max_length=16, blank=True,
        help_text="The channel's units (e.g. 'g').")
    info = models.ForeignKey(SensorChannelInfo, on_delete=models.SET_NULL, null=True,
        help_text="The sensor channel type.")
    calibrationId = models.IntegerField(null=True, blank=True,
        help_text="The channel's calibration ID.")
    bwLowerCutoff = models.IntegerField(null=True, blank=True, default=2,
        help_text="Bandwidth lower cutoff frequency in Hz.")
    bwUpperCutoff = models.IntegerField(null=True, blank=True, default=6000,
        help_text="Bandwidth upper cutoff frequency in Hz.")
    notes = models.TextField(blank=True,
        help_text="General notes about this specific component.")

    # noinspection PyTypeChecker
    def __init__(self, *args, **kwargs):
        """ Constructor.
        """
        # Copy missing values from the given `SensorChannelInfo` defaults
        # For future use, when analog channel can be added as needed.
        info = kwargs.get('info', None)
        if info is not None:
            kwargs.setdefault('adcChannel', info.defaultAdcChannel)
            kwargs.setdefault('axisName', info.defaultAxisName)
            kwargs.setdefault('channelId', info.defaultChannelId)
            kwargs.setdefault('label', info.defaultLabel)
            kwargs.setdefault('units', info.defaultUnits)

        super(SensorChannel, self).__init__(*args, **kwargs)


    def __str__(self):
        # Is including a foreign key in __str__ a bad idea (overhead, etc.)?
        try:
            return u"%s Channel %s '%s'" % (self.sensor, self.channelId,
                                            self.axisName)
        except AttributeError:
            return super(SensorChannel, self).__str__()


    # ==========================================================================
    #
    # ==========================================================================


    def copy(self, **kwargs):
        """ Copy this SensorChannel, duplicating the general fields (i.e. those
            not applicable to a single SensorChannel). Keyword arguments are
            passed to the new SensorChannel. Some instance-specific attributes
            will note be copied (e.g. `notes`).

            :returns: The duplicate SensorChannel object.
        """
        copyArgs = getKwargs(self, exclude=("notes",))
        copyArgs.update(kwargs)

        newChannel = SensorChannel(**copyArgs)
        newChannel.save()

        return newChannel


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed)
        if self.info.templateFile:
            return self.info.templateFile
        return "SensorChannel_%s" % self.info.name


    def sameAs(self, other):
        """ Check if this sensor channel is the same type as another: same
            info, same ID, etc. Separated from `__eq__()` to avoid interfering
            with Django.
        """
        if self == other:
            return True
        try:
            return all((self.info == other.info,
                        self.channelId == other.channelId,
                        self.calibrationId == other.calibrationId,
                        self.adcChannel == other.adcChannel,
                        self.axisName == other.axisName,
                        self.label == other.label,
                        self.units == other.units))
        except AttributeError:
            return False


# ==============================================================================
# Misc.
# ==============================================================================

class Battery(models.Model):
    """ Battery model information. Not exclusive to a single Device.
    """
    class Meta:
        verbose_name_plural = "batteries"

    NONE    = -1
    LIPO    = 0
    LITHIUM = 10
    OTHER   = 99

    BATTERY_TYPES = ((LIPO,    "Rechargeable (LiPo)"),
                     (LITHIUM, "Primary (Lithium)"),
                     (OTHER,   "Other"))
    
    name = models.CharField(max_length=60, blank=True,
        help_text="The battery's name in the database. Not exposed.")
    partNumber = models.CharField(max_length=30,
        help_text="The battery's manufacturer's part number.")
    manufacturer = models.CharField(max_length=100, blank=True,
        help_text="The manufacturer of the battery.")
    capacity = models.IntegerField(default=180,
        help_text="The battery capacity, in mAh.")
    type = models.IntegerField(default=0, choices=BATTERY_TYPES,
        help_text="The battery type (e.g. chemistry).")
    templateFile = models.CharField(max_length=100, blank=True,
        help_text="Manifest XML fragment template. Defaults to part number.")

    full = models.IntegerField(default=39,
        help_text="ADC Vdd 'battery full' threshold value. Varies by device.")
    ok = models.IntegerField(default=37,
        help_text="ADC Vdd 'battery charge OK' threshold value. Varies by device.")
    low = models.IntegerField(default=35,
        help_text="ADC Vdd 'battery low' threshold value. Varies by device.")
    dead = models.IntegerField(default=33,
        help_text="ADC Vdd 'battery dead' threshold value. Varies by device.")

    chargeVoltage = models.IntegerField(default=4200,
        help_text="The maximum charge voltage, in mV.")
    chargeCurrent = models.IntegerField(default=200,
        help_text="The maximum charge current, in mA.")

    notes = models.TextField(blank=True,
        help_text="General notes about the model of battery.")


    def __str__(self):
        
        if self.name:
            s = self.name
        elif self.manufacturer:
            s = "%s %s" % (self.manufacturer, self.partNumber)
        else:
            s = self.partNumber
        
        return "%s %smAh" % (s, self.capacity)


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed)
        if self.templateFile:
            return self.templateFile
        return "Battery_%s" % self.partNumber


# ==============================================================================
# Calibration
# ==============================================================================

class CalCertificate(models.Model):
    """ The data required to generate the calibration certificate PDF.
    """
    class Meta:
        verbose_name = "calibration certificate"

    name = models.CharField(max_length=100, db_index=True,
        help_text="The name of the certificate, as displayed to technician.")
    documentNumber = models.CharField(max_length=16, default="LOG-0002-604",
        help_text="The certificate document number.")
    procedureNumber = models.CharField(max_length=20, default="300-601-502",
        help_text="The certificate procedure number.")
    revision = models.CharField(max_length=2, default="C",
        help_text="The calibration procedure version (one letter).")
    templateFile = models.CharField(max_length=100, blank=True,
        help_text="Certificate SVG template. Defaults to one based on name.")

    def __str__(self):
        return "%s (Doc# %s %s)" % (self.name, self.documentNumber, 
                                    self.revision)


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed), including document/part
        # number, revision, etc., instead of just the name.
        return self.templateFile or ("%s-Calibration-template.svg" % self.name
                                     ).replace(' ', '-')


class CalSession(models.Model):
    """ A calibration session.
    """
    class Meta:
        verbose_name = "calibration session"

    sessionId = models.IntegerField(default=0, db_index=True,
        help_text="The calibration session ID (a/k/a calibration serial number or certificate number).")
    certificate = models.ForeignKey(CalCertificate, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="The calibration procedure and certificate.")
    device = models.ForeignKey(Device, on_delete=models.CASCADE,
        help_text="The device being calibrated.")
    date = models.DateTimeField(default=timezone.now, null=True, blank=True,
        help_text="Date the calibration was performed.")
    user = models.CharField(max_length=20, blank=True,
        help_text="Technician who performed the calibration.")  # Maybe a ForeignKey to Django User?
    humidity = models.FloatField(null=True, blank=True,
        help_text="Humidity at the time of calibration.")
    temperature = models.FloatField(null=True, blank=True,
        help_text="Temperature (C) at the time of calibration.")
    pressure = models.FloatField(default=101325.0, null=True, blank=True,
        help_text="Pressure (Pa) at the time of calibration.")

    orderId = models.CharField(max_length=20, blank=True, db_index=True,
        help_text="The recalibration order that included this device (if any).")

    failed = models.BooleanField(default=False,
        help_text="Did this calibration attempt fail?")

    completed = models.BooleanField(default=True,
        help_text="Did the calibration process complete successfully? Note: may not be accurate for old sessions.")

    notes = models.TextField(blank=True,
        help_text="General notes about the calibration.")


    def __str__(self):
        try:
            s = f'C{self.sessionId:05d}'
            if self.device:
                b = self.device.getLastBirth()
                if b and b.serialNumber > 0:
                    s = f'{s}, {b.serialNumberString} '
            if self.date:
                s = f'{s}, {self.date.date()}'
            return s
        except (AttributeError, TypeError, ValueError):
            return super().__str__()


    @property
    def dateString(self):
        """ The calibration date, in US format (MM/DD/YYYY).
        """
        return self.date.strftime('%m/%d/%Y')


class CalReference(models.Model):
    """ A reference sensor, used during calibration. Each calibration of the
        reference sensor should be a new object in the database.
    """
    class Meta:
        verbose_name = "calibration reference"

    name = models.CharField(max_length=200, db_index=True,
        help_text="The name/model of the reference sensor.")
    manufacturer = models.CharField(max_length=200, blank=True,
        help_text="The reference sensor's manufacturer")
    model = models.CharField(max_length=80, blank=True,
        help_text="The reference sensor's model name.")
    serialNumber = models.CharField(max_length=80, blank=True, db_index=True,
        help_text="The reference sensor's serial number.")
    nist = models.CharField(max_length=80, blank=True,
        help_text="The reference sensor's NIST ID.")
    notes = models.TextField(blank=True,
        help_text="General notes about the reference sensor.")

    date = models.DateTimeField(null=True, blank=True,
        help_text="Date the reference sensor was calibrated.")


    def __str__(self):
        if self.serialNumber:
            s = "%s SN:%s" % (self.name, self.serialNumber)
        else:
            s = "%s NIST:%s" % (self.name, self.nist)
        if not self.date:
            return s
        return f"{s} ({self.date.date()})"


class CalTemplate(models.Model):
    """ A reference to the XML fragment corresponding to an entry in the
        device's ``CalibrationList``, e.g. a ``UnivariatePolynomial`` or a
        ``BivariatePolynomial``. Separated from the `CalAxis` to avoid bloat.
    """
    name = models.CharField(max_length=200, db_index=True,
        help_text="The name and/or short description of the calibration "
                  "element, displayed only to the technician.")
    templateFile = models.CharField(max_length=100, blank=True,
        help_text="Calibration XML template fragment filename.")

    notes = models.TextField(blank=True,
        help_text="Description of the template, and/or general notes.")


    def __str__(self):
        return self.name


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed), including device hardware
        # revision, maybe.
        if self.templateFile:
            return self.templateFile
        return self.name


class CalAxis(models.Model):
    """ Calibration data for one axis, i.e. one subchannel.
    """
    class Meta:
        verbose_name = "calibration axis"
        verbose_name_plural = "calibration axes"

    calibrationId = models.IntegerField(null=True, blank=True, default=1,
        help_text="The axis' calibration ID.")
    session = models.ForeignKey(CalSession, on_delete=models.CASCADE,
        help_text="The device being calibrated.")
    sensor = models.ForeignKey(Sensor, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The device's sensor that generated the data.")
    axis = models.CharField(max_length=30, blank=True,
        help_text="The axis name (e.g. 'X'). A sanity check; also makes the "
                  "data easier for humans to read.")
    channelId = models.IntegerField(null=True, blank=True,
        help_text="For bivariate polynomials: the dependent channel ID (e.g. "
                  "the pressure/temperature channel). Ignored for univariates.")
    subchannelId = models.IntegerField(null=True, blank=True,
        help_text="For bivariate polynomials: the dependent subchannel ID "
                  "(e.g. the temperature subchannel). Ignored for univariates.")
    filename = models.CharField(max_length=200, blank=True,
        help_text="The IDE file used for calibration.")
    value = models.FloatField(default=0.0,
        help_text="The calibration gain.")
    offset = models.FloatField(default=0.0,
        help_text="The calibration offset.")
    rms = models.FloatField(null=True, blank=True,
        help_text="Calibration file RMS.")
    reference = models.ForeignKey(CalReference, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The calibration reference sensor.")

    sourceChannelId = models.IntegerField(null=True, blank=True,
        help_text="The Channel ID of the data used to calculate the "
                  "calibration (if known).")
    sourceSubchannelId = models.IntegerField(null=True, blank=True,
        help_text="The Subchannel ID of the data used to calculate the "
                  "calibration (if known).")

    template = models.ForeignKey(CalTemplate, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The XML template fragment used to write the polynomial.")


    def __str__(self):
        # Is including a foreign key in __str__ a bad idea (overhead, etc.)?
        return "%s %s" % (self.session, self.axis)


    def getTemplateName(self):
        """ Get the name of the manifest XML fragment for this object.
        """
        # FUTURE: Smarter name generation (if needed), including device hardware
        # revision, maybe.
        if self.template:
            return self.template.getTemplateName()


class CalTransverse(models.Model):
    """ Transverse measurements between two axes, i.e. two subchannels of the
        same parent channel.
    """
    class Meta:
        verbose_name = "calibration transverse"

    session = models.ForeignKey(CalSession, on_delete=models.CASCADE,
        help_text="The device being calibrated.")
    axis = models.CharField(max_length=16, blank=True,
        help_text="The axis names (e.g. XY). A sanity check.")
    channelId = models.IntegerField(default=0,
        help_text="The parent channel ID.")
    subchannelId1 = models.IntegerField(default=0, null=True, blank=True,
        help_text="The first axis' subchannel ID.")
    subchannelId2 = models.IntegerField(default=0, null=True, blank=True,
        help_text="The second axis' subchannel ID.")
    value = models.FloatField(
        help_text="The transverse value.")


    def __str__(self):
        # Is including a foreign key in __str__ a bad idea (overhead, etc.)?
        return "%s %s" % (self.session, self.axis)


    def getAxis(self, axis=1):
        """ Helper method to get the CalAxis associated with either of the
            CalTransverse subchannels.
        """
        schId = self.subchannelId2 if axis == 2 else self.subchannelId1
        try:
            ch = CalAxis.objects.filter(session=self.session,
                                        sourceChannelId=self.channelId,
                                        sourceSubchannelId=schId).last()
            return ch
        except CalAxis.DoesNotExist:
            # Shouldn't happen with a filter
            raise


    @property
    def reference(self):
        """ The calibration reference sensor.
        """
        ch = self.getAxis()
        if ch:
            return ch.reference


    @property
    def sensor(self):
        """ The calibrated sensor.
        """
        ch = self.getAxis()
        if ch:
            return ch.sensor


#===========================================================================
#
#===========================================================================

class MaintenanceRecord(models.Model):
    """ This is part of a simple system for notifying users that work is
        being performed on the code and/or database. To a lesser degree, it
        can be used to roughly track the work performed. Entries are created
        when work starts; an entry is created when work ends with the
        `closed` field `True`. Ends are not connected to specific starts.
        Only the latest record is checked to see if work is being performed.
    """
    COMPLETE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3

    SEVERITY_LEVELS = (
        (COMPLETE, "Maintenance completed"),
        (LOW, "Low severity (use may continue)"),
        (MEDIUM, "Medium severity (proceed with caution)"),
        (HIGH, "High severity (do not use until work is complete)")
    )

    date = models.DateTimeField(default=timezone.now, null=True, blank=True,
        help_text="Date of maintenance start or end.")
    user = models.CharField(max_length=20, blank=True,
        help_text="Developer performing the maintenance.")
    severity = models.IntegerField(default=LOW, choices=SEVERITY_LEVELS,
        help_text="The severity of the work being done. In low severity, users may continue using "
                  "the system. In high severity, the system should not be used. Zero means work "
                  "is complete.")
    description = models.TextField(blank=True,
        help_text="General notes about the maintenance being done.")
    related = models.ForeignKey('MaintenanceRecord', on_delete=models.SET_NULL, null=True, blank=True,
        help_text="The related (i.e. starting or closing) MaintenanceRecord.")


def startMaintenance(desc, level=MaintenanceRecord.LOW):
    """ Create a new 'open' maintenance notification.

        :param desc: Description of the work being done.
        :param level: The severity level of the work being done.
        :returns: The new `MaintenanceRecord`.
    """
    user = getpass.getuser()
    m = MaintenanceRecord(user=user, severity=level, description=desc)
    m.save()
    return m


def endMaintenance(desc="", related=None):
    """ Close a maintenance notification. All parameters are optional.

        :param desc: Optional description of the notification.
        :param related: The opening `MaintenanceRecord`.
        :returns: The new, closing `MaintenanceRecord`.
    """
    user = getpass.getuser()
    m = MaintenanceRecord(user=user, severity=MaintenanceRecord.COMPLETE, description=desc, related=related)
    m.save()
    return m
