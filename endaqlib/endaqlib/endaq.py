"""
Classes for representing specific models of enDAQ data recoreder.
"""

__author__ = "dstokes"
__copyright__ = "Copyright 2022 Mide Technology Corporation"

import os
from pathlib import Path
import re
from time import time, sleep
from typing import AnyStr, Callable, Optional, Union
import warnings

from ebmlite import loadSchema, MasterElement

from .base import Recorder, DeviceTimeout, os_specific


# ==============================================================================
# 
# ==============================================================================

class EndaqS(Recorder):
    """ An enDAQ S-series data recorder from Mide Technology Corporation. 
    """

    SN_FORMAT = "S%07d"
        
    manufacturer = "Midé Technology Corporation"
    homepage = "https://endaq.com/collections/endaq-shock-recorders-vibration-data-logger-sensors"

    _NAME_PATTERN = re.compile(r'^S(\d|\d\d)-.*')

    def __init__(self, path: Union[AnyStr, Path, None], **kwargs):
        """ Constructor.

            :param path: The filesystem path to the recorder, or `None` if
                it is a 'virtual' device (e.g., constructed from data
                in a recording).
            :param strict: If `True`, only allow real device paths. If
                `False`, allow any path that contains a recorder's
                ``SYSTEM`` directory. Primarily for testing.
        """
        super(EndaqS, self).__init__(path, **kwargs)

        self.commandSchema = loadSchema('command-response.xml')
        if self.path:
            self.responseFile = os.path.join(self.path, self._RESPONSE_FILE)
        else:
            self.responseFile = None


    # ==========================================================================
    # 
    # ==========================================================================

    def _readResponseFile(self) -> Optional[MasterElement]:
        """ Helper to retrieve an EBML response from the device's `RESPONSE`
            file. Checks that the data is EBML and that the first child
            element is a `ResponseIdx` (which all responses should contain).
        """
        if self.path is None:
            return

        raw = os_specific.readUncachedFile(self.responseFile)

        try:
            data = self.commandSchema.loads(raw)
            if data[0].name == "EBMLResponse" and data[0][0].name == "ResponseIdx":
                return data[0]

        except (AttributeError, IndexError, TypeError) as E:
            warnings.warn("%s in EndaqS._readResponseFile" % str(E))

        return None


    def sendCommand(self, cmd: AnyStr,
                    response: bool = True,
                    timeout: int = 10,
                    interval: float = .25,
                    wait: bool = True,
                    callback: Optional[Callable] = None) -> Optional[MasterElement]:
        """ Send a raw command to the device and (optionally) retrieve the
            response.

            :param cmd: The raw EBML representing the command.
            :param response: If `True`, wait for and return a response.
            :param timeout: Time (in seconds) to wait for a response before
                raising a `DeviceTimeout` exception.
            :param interval: Time (in seconds) between checks for a
                response.
            :param wait: If `True`, wait until the device has no additional
                commands queued before sending the new command.
            :param callback: A function to call each response-checking
                cycle. If the callback returns `True`, the wait for a response
                will be cancelled. The callback function should take no
                arguments.

            @raise DeviceTimeout
        """
        if self.path is None:
            return

        now = time()
        deadline = now + timeout
        idx = None
        queueDepth = None

        # Wait until the command queue is empty
        with self._busy:
            while True:
                data = self._readResponseFile()
                if data is not None:  # If this is true, won't it just loop forever while sleeping?
                    idx = data[0].value
                    if not wait or data[1].name != "CMDQueueDepth":
                        break
                    else:
                        queueDepth = data[1].value
                        if queueDepth > 0:
                            break
                if time() > deadline:
                    raise DeviceTimeout("Timed out waiting for device to complete "
                                        "queued commands (%s remaining)" % queueDepth)
                else:
                    sleep(interval)

            # Write to command file
            # NOTES:  This is one of the things that needs to be dealt with if the scanWiFi test is to be used
            with open(self.commandFile, 'wb') as f:
                f.write(cmd)

            if not response:
                return

            while time() <= deadline:
                if callback is not None and callback() is True:
                    return

                sleep(interval)
                data = self._readResponseFile()

                if data and data[0].value != idx:
                    return data

            raise DeviceTimeout("Timed out waiting for command response (%s seconds)" % timeout)


# ==============================================================================
# 
# ==============================================================================

class EndaqW(EndaqS):
    """ An enDAQ W-series wireless-enabled data recorder from Mide Technology Corporation.
    """
    SN_FORMAT = "W%07d"

    # Part number starts with "W", a 1-2 digit number, and "-"
    _NAME_PATTERN = re.compile(r'^W(\d|\d\d)-.*')


    def setWifi(self, wifi_data: dict,
                timeout: int = 10,
                interval: float = .25,
                wait: bool = True,
                callback: Optional[Callable] = None) -> Optional[MasterElement]:
        """ Gives the commands to set the devices WiFi.

            :param wifi_data: The information about the WiFi networks to be
                set on the device.  Specifically, it's a list of dictionaries,
                where each element in the list corresponds to one of the WiFi
                networks to be set.  The following are two examples of this:
                [{'SSID': 'office_wifi', 'Selected': 1, 'Password': 'pass123'}]
                or
                [{'SSID': 'ssid_1', 'Selected': 1, 'Password': 'pass_1'},
                 {'SSID': 'ssid_2', 'Selected': 0},
                 {'SSID': 'ssid_1', 'Selected': 0, 'Password': 'pass_3'}]
            :param timeout: Time (in seconds) to wait for a response before
                raising a `DeviceTimeout` exception.
            :param interval: Time (in seconds) between checks for a response.
            :param wait: If `True`, wait until the device has no additional
                commands queued before sending the new command.
            :param callback: A function to call each response-checking cycle.
                If the callback returns `True`, the wait for a response will be
                cancelled. The callback function should take no arguments.
            :return: None if no information was recieved, else it will return
                the information from the ``QueryWiFiResponse`` command (this
                return statement is not used anywhere)

            :raise DeviceTimeout: Raised if 'timeout' seconds have gone by
                without getting a response
        """
        # TODO: Ensure that the setting of multiple networks at once behaves
        #  as expected (haven't been able to test this)

        if self.path is None:
            return

        command_str = 'QueryWiFi' if wifi_data is None else 'SetWiFi'
        cmd = self.commandSchema.encodes({'EBMLCommand': {command_str: {"AP": wifi_data}}})

        response = self.sendCommand(
            cmd,
            True,
            timeout,
            5*interval if wifi_data is None else interval,
            wait,
            callback)

        if response is None:
            return None

        response_dump = response.dump()

        if 'QueryWiFiResponse' in response_dump:
            return response_dump['QueryWiFiResponse']

        return None


    def scanWifi(self, timeout: int = 10,
                 interval: float = .25,
                 wait: bool = True,
                 callback: Optional[Callable] = None) -> Optional[list]:
        """ Initiate a scan for Wi-Fi access points (APs).

            :param timeout: Time (in seconds) to wait for a response before
                raising a `DeviceTimeout` exception.
            :param interval: Time (in seconds) between checks for a response.
            :param wait: If `True`, wait until the device has no additional
                commands queued before sending the new command.
            :param callback: A function to call each response-checking cycle.
                If the callback returns `True`, the wait for a response will
                be cancelled. The callback function should take no arguments.

            :return: A list of dictionaries, one for each access point,
                with keys:
                - ``SSID`` (str): The access point name.
                - ``RSSI`` (int): The AP's signal strength.
                - ``AuthType`` (int): The authentication (security) type.
                    Currently, this is either 0 (no authentication) or 1
                    (any authentication).
                - ``Known`` (bool): Is this access point known (i.e. has
                    a stored password on the device)?
                - ``Selected`` (bool): Is this the currently selected AP?

            :raise DeviceTimeout: Raised if 'timeout' seconds have gone by
                without getting a response
        """
        if self.path is None:
            return None

        with self._busy:
            cmd = self.commandSchema.encodes({'EBMLCommand': {'WiFiScan': None}})

            response = self.sendCommand(cmd, True, timeout, interval, wait, callback)

            if response is None:
                return None

            data = response.dump()

            aps = []
            if 'WiFiScanResult' in data:  # If at least 1 WiFi was found during the scan
                for ap in data['WiFiScanResult'].get('AP', []):
                    defaults = {'SSID': '', 'RSSI': -1, 'AuthType': 0, 'Known': 0, 'Selected': 0}

                    defaults.update(ap)
                    defaults['Known'] = bool(defaults['Known'])
                    defaults['Selected'] = bool(defaults['Selected'])

                    # defaults['RSSI'] = - defaults['RSSI']
                    aps.append(defaults)

            return aps
