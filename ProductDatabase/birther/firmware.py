"""
This implements a subclass of the standard firmware updaters that include
some additional and revised methods. Separated only to prevent contamination.
New/revised methods will eventually be moved into the main SlamStickLab.

Created on Aug 14, 2019

@author: dstokes
"""

import endaq.device

from shared_logger import logger
from util import readFile

# Remove later, once everything has been updated
import efm32_firmware


#===============================================================================
# 
#===============================================================================

class FirmwareUpdater(efm32_firmware.FirmwareUpdater):
    """ Subclass of the standard `FirmwareUpdater` that implements the
        `uploadAppFile()` method. This should get moved into the main
        SlamStickLab repo after the next release of Slam Stick Lab (1.9.1).
    """
    
    def uploadAppFile(self, filename):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`). Overrides data in the object's `fwBin`
            attribute.
        
            @param filename: The name of the binary file to upload.
        """
        payload = readFile(filename)
        return super(FirmwareUpdater, self).uploadApp(payload)
        

#===============================================================================
# 
#===============================================================================

class FirmwareFileUpdater(efm32_firmware.FirmwareFileUpdater):
    """ Subclass of the standard `FileFirmwareUpdater` that implements the
        `findBootloader()` and `connect()` methods. This should get moved into
        the main SlamStickLab repo after the next release of Slam Stick Lab.
    """
    
    @classmethod
    def findBootloader(cls, first=False):
        """ Check attached recorders for a device capable of file-based update.
            EFMGG11 devices are excluded.
        
            @param first: If `True` and multiple recorders are found,
                return the first one. If `False` and multiple recorders are
                found, return None. To help prevent the wrong recorder being
                updated.
            @return: The recorder found (a `devices.Recorder` subclass
                instance), or `None` if no device was found. Also returns
                `None` if more than one device was discovered and `first` is
                `False`.
        """
        # NOTE: Rebirthing needs the DEVINFO to contain the UniqueChipID.
        # When this makes it into the SlamStickLab firmware updater, this
        # restriction should be removed.
        devs = [d for d in endaq.device.getDevices() if (d.canCopyFirmware and
#                             "UniqueChipID" in d.getInfo() and
                            "EFM32GG11" not in d.getInfo().get('McuType', ''))]
        if devs and (len(devs) == 1 or first):
            return devs[0]


    def connect(self, dev=None, **kwargs):
        """ Do preparation for the firmware update. 
        """
        
        if dev is not None:
            self.device = dev

        info = self.device.getInfo()
        bootRev = info.get('BootRev', None)  # Not currently in info!
        chipId = info.get('UniqueChipID', None)
        
        if chipId is not None:
            chipId = "%16X" % chipId
        
        self.clean()
        
        return bootRev, chipId


    def uploadAppFile(self, filename):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`). Overrides data in the object's `fwBin`
            attribute.
        
            @param filename: The name of the binary file to upload.
        """
        payload = readFile(filename)
        return super(FirmwareFileUpdater, self).uploadApp(payload)


#===============================================================================
# 
#===============================================================================


class FirmwareFileUpdaterGG11(FirmwareFileUpdater):
    """ Subclass of `FirmwareFileUpdater` with special provisions for the new,
        GG11-based devices (e.g. S1/S2/S3/S4 series).
    """
    def validateFirmware(self, fwBin, **kwargs):
        return True

    
    def __init__(self, *args, **kwargs):
        super(FirmwareFileUpdaterGG11, self).__init__(*args, **kwargs)
        self._uploadedUserpage = False
        self._uploadedApp = False


    @classmethod
    def findBootloader(cls, first=False):
        """ Check attached recorders for a GG11-based device capable of
            file-based update.
        
            @param first: If `True` and multiple recorders are found,
                return the first one. If `False` and multiple recorders are
                found, return None. To help prevent the wrong recorder being
                updated.
            @return: The recorder found (a `devices.Recorder` subclass
                instance), or `None` if no device was found. Also returns
                `None` if more than one device was discovered and `first` is
                `False`.
        """
        devs = [d for d in endaq.device.getDevices() if (d.canCopyFirmware and
                            "EFM32GG11" in d.getInfo().get('McuType', ''))]
        if devs and (len(devs) == 1 or first):
            return devs[0]


    def uploadBootloader(self, payload=None):
        logger.warning("%s does not support uploadBootloader(), ignoring." %
                       type(self).__name__)
        return False


    def uploadApp(self, payload=None):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`).
        
            @param payload: An alternative payload, to be used instead of the
                object's `fwBin` attribute.
        """
        # Set a flag if the firmware was updated; changes what finalize() does
        uploaded = super(FirmwareFileUpdaterGG11, self).uploadApp(payload)
        self._uploadedApp = uploaded
        return uploaded


    def uploadUserpage(self, payload=None):
        """ Install new userpage data via an update file (specified in the 
            device's `USERPAGE_UPDATE_FILE`).
        
            @param payload: An alternative payload, to be used instead of the
                object's `userpage` attribute.
        """
        # Set a flag if the userpage was updated; changes what finalize() does
        uploaded = super(FirmwareFileUpdaterGG11, self).uploadUserpage(payload)
        self._uploadedUserpage = uploaded
        return uploaded


    def uploadAppFile(self, filename, signature=None):
        """ Install new firmware via an update file (specified in the device's
            `FW_UPDATE_FILE`). Overrides data in the object's `fwBin`
            attribute. Also uploads the "signature" file, which is expected to
            be the same name plus ".sig". 
        
            @param filename: The name of the binary file to upload.
            @param signature: The name of the 'signature' file. Defaults to
                the same as `filename`, plus `".sig"`.
        """
        signature = signature or (filename + ".sig")
        
        payload = readFile(filename)
        sig = readFile(signature)

        uploaded = (self.uploadApp(payload) and 
                    self._writeFile(self.device._FW_UPDATE_FILE+".sig", sig))
        self._uploadedApp = uploaded
        return uploaded


    def finalize(self):
        """ Apply the finishing touches to the firmware/userpage
            update.
        """
        logger.info("Sending 'secure update all' command ('sa')...")
        with open(self.device.commandFile, 'wb') as f:
            f.write(b'sa')
                
#         if self._uploadedUserpage:
#             # GG11 version of this command does not reset the device
#             logger.info("Sending 'update USERPAGE' command...")
#             with open(self.device.commandFile, 'wb') as f:
#                 f.write('up')
# 
#         if self._uploadedApp:
#             # This will reset the device
#             logger.info("Sending 'update firmware package' command...")
#             with open(self.device.commandFile, 'wb') as f:
#                 f.write('pk')
#                 
#         elif self._uploadedUserpage:
#             # Do 'manual' reset if required (userpage change, same firmware)
#             logger.info("Sending 'device reset' command...")
#             with open(self.device.commandFile, 'wb') as f:
#                 f.write('rr')


#===============================================================================
# 
#===============================================================================

# class AnyRecorder(devices.SlamStickX):
#     """
#     """
#     
#     @classmethod
#     def isRecorder(cls, dev, **kwargs):
#         try:
#             return os.path.exists(os.path.join(dev, 'SYSTEM','DEV','DEVINFO'))
#         except Exception as err:
#             print("Error in isRecorder for {}".format(dev, err))
#             return False
#             
# 
# 
# def findOldFirmware():
#     devs = set(devices.getDeviceList(types=[AnyRecorder]))
#     return devs.difference(devices.getDeviceList())
    

#===============================================================================
# 
#===============================================================================

if __name__ == "__main__":
    print("This is just a library, not a stand-alone script!")
