"""
The database-backed calibration GUI!

Not actually a wizard.

Created on Sep 5, 2019

@author: dstokes
"""

from datetime import datetime
import json
import os.path
import subprocess
import tempfile
import time

import wx
import wx.lib.sized_controls as SC

import paths

# ===============================================================================
# --- Logging setup: Done early to set up for other modules

import logging
import shared_logger
from shared_logger import logger

if os.path.isdir(paths.LOG_DIR):
    logfilename = os.path.join(paths.LOG_DIR, shared_logger.LOG_FILENAME)
    logger.info(f"Logging to {logfilename}")
    filehandler = logging.FileHandler(logfilename)
    filehandler.setLevel(logging.DEBUG)
    fileformat = logging.Formatter(shared_logger.LOG_FORMAT)
    filehandler.setFormatter(fileformat)
    logger.addHandler(filehandler)
else:
    logger.warning(f"Could not find LOG_DIR ({paths.LOG_DIR})!")

# ===============================================================================

import django.db
import endaq.device

from busybox import BusyBox
from calibration2 import models  # Note: does the Django setup, etc.
import calibration2 as calibration
import cal_util
from firmware import FirmwareFileUpdater, FirmwareFileUpdaterGG11
import labels

from util import copyContent, makeBackup, restoreBackup, deepCopy  # , ejectDrive
from util import allInRange, inRange

from template_generator import CalCertificateTemplater, CalTemplater
from generate_userpage import generateUserpage


# ===============================================================================
#
# ===============================================================================

class CalInfoDialog(SC.SizedDialog):
    """ A dialog showing calibration values and fields for selecting various
        things for the calibration certificate and post-calibration actions.
    """

    TITLE_FONT = None

    def __init__(self, *args, **kwargs):
        """ Constructor. Standard dialog arguments, plus:

            @keyword info: The info to display in the dialog's top field.
            @keyword humidity: The humidity at recording time.
            @keyword fromFile: Was the humidity taken from the recordings?
            @keyword reference: The selected reference accelerometer.
            @type reference: `products.models.CalReference`
            @keyword references: A list of all valid references.
            @keyword certificate: The selected calibration certificate.
            @type certificate: `products.models.CalCertificate`
            @keyword certificates: A list of all valid certificates.
        """
        self.canPrint = labels.canPrint()

        kwargs.setdefault("title", "Calibration")
        kwargs.setdefault("size", (800, 640))
        kwargs.setdefault("style", wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        self.info = kwargs.pop('info', '')
        self.device = kwargs.pop('device', None)
        self.calNumber = kwargs.pop('calNumber', None)
        self.humidity = kwargs.pop('humidity', 50)
        self.fromFile = kwargs.pop('fromFile', True)
        self.reference = kwargs.pop('reference', None)
        self.references = kwargs.pop('references', [])
        self.certificate = kwargs.pop('certificate', [])
        self.certificates = kwargs.pop('certificates', [])

        self.printLabel = kwargs.pop('printLabel', True) and self.canPrint
        self.cleanDevice = kwargs.pop('cleanDevice', True)
        self.cleanWorkDir = kwargs.pop('cleanWorkDir', True)
        self.copyContent = kwargs.pop('copyContent', True)
        self.makeCertificate = kwargs.pop('makeCertificate', True)
        self.writeUserpage = kwargs.pop('writeUserpage', True)
        self.runChkdsk = kwargs.pop('runChkdsk', True)

        SC.SizedDialog.__init__(self, *args, **kwargs)

        if CalInfoDialog.TITLE_FONT is None:
            CalInfoDialog.TITLE_FONT = wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

        self.buildUI()

        self.SetButtonSizer(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL))
        self.FindWindowById(wx.ID_OK).SetLabelText("Calibrate!")

        self.populate()

        self.SetMinSize((640, 480))

    def buildUI(self):
        """ Add all the widgets.
        """
        outerpane = self.GetContentsPane()
        outerpane.SetSizerType("horizontal")

        # The goofy vertical graphic
        img = wx.Image(os.path.join(paths.RESOURCES_PATH, 'calomatic.png'), wx.BITMAP_TYPE_PNG)
        bg = wx.Colour(img.GetRed(1, 1), img.GetGreen(1, 1), img.GetBlue(1, 1))

        imgpane = SC.SizedPanel(outerpane, -1)
        imgpane.SetSizerType("vertical")
        imgpane.SetSizerProps(valign="bottom", expand=True)
        imgpane.SetBackgroundColour(bg)
        simg = wx.StaticBitmap(imgpane, -1, img.ConvertToBitmap())
        simg.SetSizerProps(valign="bottom", expand=True, proportion=1)

        # The "real" contents
        mainpane = SC.SizedPanel(outerpane, -1)
        mainpane.SetSizerProps(expand=True, proportion=1, border=(["left"], 8))
        mainpane.SetSizerType("vertical")

        # Info
        self.headingText = wx.StaticText(mainpane, -1, "Calibrating Device")
        self.headingText.SetFont(self.TITLE_FONT)

        # Top display: text field
        tpane = SC.SizedPanel(mainpane, -1)
        tpane.SetSizerProps(expand=True, proportion=1)
        tpane.SetSizerType("vertical")

        self.infoField = wx.TextCtrl(tpane, -1, self.info,
                                     style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP)
        self.infoField.SetSizerProps(expand=True, proportion=1)

        font = self.infoField.GetFont()
        font.SetFamily(wx.FONTFAMILY_TELETYPE)
        self.infoField.SetFont(font)

        # Bottom display: selectable things.
        pane = SC.SizedPanel(mainpane, -1)
        pane.SetSizerProps(expand=True, border=(["top"], 16))
        pane.SetSizerType("form")

        # Calibration ID field
        wx.StaticText(pane, -1, "Calibration Number:").SetSizerProps(valign="top")
        snpane = SC.SizedPanel(pane, -1)
        snpane.SetSizerType("form")

        self.newSNButton = wx.RadioButton(snpane, -1, "New Calibration Number")
        wx.StaticText(snpane, -1, '(will be generated at the end)')

        self.customSNButton = wx.RadioButton(snpane, -1, "Set Calibration Number:")
        self.customSNButton.SetSizerProps(valign="center")
        self.snField = wx.SpinCtrl(snpane, -1, "")
        self.snField.SetRange(0, 99999)
        self.snField.SetSizerProps(expand=True)

        self.Bind(wx.EVT_RADIOBUTTON, self.OnRadioButton)

        # Reference and certificate selection
        wx.StaticText(pane, -1, "Calibration Reference:").SetSizerProps(valign="center")
        self.refList = wx.Choice(pane, -1)
        self.refList.SetSizerProps(valign="center", expand=True)

        wx.StaticText(pane, -1, "Calibration Certificate:").SetSizerProps(valign="center")
        self.certList = wx.Choice(pane, -1)
        self.certList.SetSizerProps(valign="center", expand=True)

        # Humidity selection
        wx.StaticText(pane, -1, "Calibration Humidity:").SetSizerProps(valign="center")
        humpane = SC.SizedPanel(pane, -1)
        humpane.SetSizerType('horizontal')
        humpane.SetSizerProps(valign='center', expand=True)

        self.humField = wx.SpinCtrlDouble(humpane, -1, value=str(self.humidity),
                                          min=0.0, max=100.0, inc=0.1)
        self.humField.SetSizerProps(valign="center", expand=True)

        self.humLabel = wx.StaticText(humpane, -1, f"Default: {self.humidity:.2f}")
        self.humLabel.SetSizerProps(valign="center", expand=True)

        def _check(parent, label, tooltip=""):
            check = wx.CheckBox(parent, -1, label)
            if tooltip:
                check.SetToolTip(tooltip)
            check.SetSizerProps(valign="center")
            return check

        bpane = SC.SizedPanel(mainpane, -1)
        bpane.SetSizerProps(expand=True, border=(["top"], 16))
        bpane.SetSizerType("form")

        wx.StaticText(bpane, -1, "Post-Calibration Actions:").SetSizerProps(valign="top")
        actpane = SC.SizedPanel(bpane, -1)
        actpane.SetSizerType("grid", {"cols": 3})
        actpane.SetSizerProps(border=(["left"], 8))
        self.labelCheck = _check(actpane, "Print Label",
                                 "Print the calibration label (serial number and date).")
        self.cleanCheck = _check(actpane, "Clean Device",
                                 "Remove calibration recordings and config data after calibration. "
                                 "If a recalibration, restore old settings.\n"
                                 "Should usually be checked.")
        self.workCheck = _check(actpane, "Clean Work Directory",
                                "Remove temporary copies of calibration files from computer.\n"
                                "Should usually be checked.")
        self.copyCheck = _check(actpane, "Copy Content to Recorder",
                                "Copy software, documentation, calibration certificate, etc., to "
                                "recorder after calibration.")
        self.certCheck = _check(actpane, "Generate Certificate PDF",
                                "Create the certificate PDF file after calibration.\n"
                                "Should usually be checked.")
        self.writeCheck = _check(actpane, "Write Device USERPAGE",
                                 "Write the updated calibration to the device.\n"
                                 "Should almost always be checked.")

        self.chkdskCheck = _check(actpane, "Run chkdsk on drive",
                                  "Run the 'chkdsk' command to fix any disk error notifications.\n"
                                  "Performed at the very end.")

    def populate(self):
        """ Put values in the widgets.
        """
        if self.device:
            name = self.device.productName or self.device.partNumber
            self.headingText.SetLabel(f"Calibrating {name}")

        if self.calNumber is not None:
            self.snField.Enable()
            self.snField.SetValue(self.calNumber)
            self.customSNButton.SetValue(True)
        else:
            self.snField.Enable(False)
            self.newSNButton.SetValue(True)

        self.refList.SetItems([str(x) for x in self.references] + ["None"])
        if self.reference in self.references:
            self.refList.SetSelection(self.references.index(self.reference))

        self.certList.SetItems([str(x) for x in self.certificates] + ['None'])
        if self.certificate in self.certificates:
            self.certList.SetSelection(self.certificates.index(self.certificate))

        self.humField.SetValue(self.humidity)
        if self.fromFile:
            self.humLabel.SetLabelText("From recording: {self.humidity:.2f}")
        else:
            self.humLabel.SetLabelText("Last used: {self.humidity:.2f}")

        self.labelCheck.SetValue(self.printLabel)
        #         self.labelCheck.Enable(self.canPrint)
        self.cleanCheck.SetValue(self.cleanDevice)
        self.workCheck.SetValue(self.cleanWorkDir)
        self.copyCheck.SetValue(self.copyContent)
        self.certCheck.SetValue(self.makeCertificate)
        self.writeCheck.SetValue(self.writeUserpage)
        self.chkdskCheck.SetValue(self.runChkdsk)

    def getValues(self):
        """ Get values selected in dialog.

            @return: A tuple containing the calibration ID, selected reference,
                the selected certificate, and the entered humidity.
        """
        sn = cert = ref = None

        if self.customSNButton.GetValue():
            sn = self.snField.GetValue()

        idx = self.refList.GetSelection()
        if 0 <= idx < len(self.references):
            ref = self.references[idx]

        idx = self.certList.GetSelection()
        if 0 <= idx < len(self.certificates):
            cert = self.certificates[idx]

        hum = self.humField.GetValue()

        actions = {'printLabel': self.labelCheck.GetValue(),
                   'copyContent': self.copyCheck.GetValue(),
                   'cleanDevice': self.cleanCheck.GetValue(),
                   'cleanWorkDir': self.workCheck.GetValue(),
                   'makeCertificate': self.certCheck.GetValue(),
                   'writeUserpage': self.writeCheck.GetValue(),
                   'runChkdsk': self.chkdskCheck.GetValue()}

        return sn, ref, cert, hum, actions

    def OnRadioButton(self, evt):
        """ Event handler for radio buttons (i.e. old/new serial number).
        """
        rb = evt.GetEventObject()
        if rb == self.newSNButton:
            self.snField.Enable(False)
        elif rb == self.customSNButton:
            self.snField.Show()
            self.snField.Enable(True)


# ===============================================================================
#
# ===============================================================================

class CalApp(wx.App):
    """ The Cal-o-Matic 2.0 application!
    """
    PREFS_FILE = "cal_wizard.cfg"

    # Ranges for file validation/sanity checks
    VALID_CAL_RANGE = (0.5, 2.5)
    VALID_PRESS_RANGE = (96235, 106365)
    MAX_TRANSVERSE = 10.0

    # Time to wait for a rebooted device to reappear as a drive (in seconds)
    REBOOT_TIMEOUT = 120

    def OnInit(self):
        """ Post-Constructor initialization event handler.
        """
        self.hasInkscape = os.path.exists(paths.INKSCAPE_PATH)
        if not self.hasInkscape:
            q = wx.MessageBox("Could not find Inkscape application!"
                              "\n\nIt is required to generate calibration certificates. "
                              "\nDo you want to continue anyway?",
                              "Cal-o-Matic Error",
                              wx.YES_NO | wx.NO_DEFAULT)
            if q == wx.NO:
                wx.Exit()

        self.lastCal = None
        self.prefsFile = os.path.join(os.path.dirname(__file__),
                                      self.PREFS_FILE)
        self.loadPrefs()

        try:
            cal_util.purgeWorkDir()
        except Exception as err:
            logger.error(f"Exception when removing working directory: {err!r}")
            raise

        # This app doesn't have a main window, so the calibration loop starts
        # here. This seems kind of wrong, though.
        keepGoing = True
        while keepGoing:
            pd = wx.ProgressDialog("Cal-o-Matic 2.0", "",
                                   style=wx.PD_APP_MODAL | wx.PD_CAN_ABORT)
            try:
                pd.Pulse("Waiting for Device\n\n ")
                keepGoing = self.calibrationLoop(pd)
            finally:
                pd.Close()
                pd.Destroy()

        self.savePrefs()

        # Required: return True/False to indicate whether app started up or not.
        # Since this application has no main window, just return False
        return False

    # ===========================================================================
    #
    # ===========================================================================

    def calibrationLoop(self, pd):
        """ Find and calibrate a recorder.
        """
        self.pd = pd
        calFinished = False
        cancelled = False
        #         clean = False
        name = "Cal-o-Matic"
        self.lastCal = None

        msg = "Calibrate another device?\n\n "
        icon = wx.ICON_INFORMATION

        try:
            dev = self.findRecorder()
        except ValueError:
            dev = None

        if dev is None:
            calFinished = False
            msg = "Failed to find device!\n\nTry again?"
            icon = wx.ICON_ERROR

        else:
            if dev.productName != dev.partNumber:
                name = f"{dev.productName} ({dev.partNumber})"
            else:
                name = f"{dev.partNumber}"

            name = f"{name}, SN: {dev.serial}"

            pd.Pulse(f"Calibrating {name}\nPath: {dev.path}")
            calFinished = self.calibrateWithWizard(dev)

            cancelled = getattr(self.lastCal, 'cancelled', False)
            #             clean = self.prefs['postCalActions'].get('cleanWorkDir', True)

            if calFinished:
                msg = (f"Calibrated {name}"
                       f"\n\nCalibration ID: {self.lastCal.sessionId}"
                       "\n\nCalibrate another?")

            elif cancelled:
                msg = "Calibration cancelled.\n\nTry again?"
                icon = wx.ICON_INFORMATION

            else:
                msg = "Calibration did not complete!\n\nTry again?"
                icon = wx.ICON_WARNING
        #                 clean = False

        # Post-calibration message: keep going?
        q = wx.MessageBox(msg, name, wx.YES_NO | wx.YES_DEFAULT | icon)

        keepGoing = (q == wx.YES)

        #         workDir = getattr(self.lastCal, 'workDir', '')
        #         if not clean and not calFinished and not cancelled:
        #             if workDir and os.path.exists(str(workDir)):
        #                 q = wx.MessageBox("Clean up temporary files?\n\n"
        #                       "Depending on why the calibration failed, "
        #                       "they might help diagnose the problem",
        #                       "Cal-o-Matic", wx.YES_NO|wx.YES_DEFAULT|icon)
        #                 clean = (q == wx.YES)
        #
        #         if clean:
        #             try:
        #                 cal_util.cleanWorkDir(self.lastCal)
        #             except Exception as err:
        #                 logger.error("%s when removing working directory: %s" %
        #                              (type(err).__name__, err))

        return keepGoing

    # ===========================================================================
    #
    # ===========================================================================

    @classmethod
    def reconnect(cls):
        """ Test the database connection; disconnect if timed out, to force a
            new connection. This feels like a hack, though.
        """
        try:
            # Arbitrary simple query to 'ping' the database connection
            models.Product.objects.count()

        except django.db.utils.InterfaceError:
            django.db.connection.close()

            # Try again, just in case there was some other InterfaceError that
            # closing the connection didn't fix.
            models.Product.objects.count()

    # ===========================================================================
    #
    # ===========================================================================

    def copyPrefs(self, p):
        """ Recursively copy a dictionary of preferences. Assumes values are
            dictionaries, lists, or simple types (numbers and strings).

            @param p: A dictionary/list of preferences.
            @return: The deep copy of `p`.
        """
        # Cheesy way to do a deep copy!
        return json.loads(json.dumps(p))

    def loadPrefs(self):
        """ Read the preferences file (i.e. the last options selected, to use
            as defaults).
        """
        self.prefs = {}
        try:
            with open(self.prefsFile, 'rb') as f:
                self.prefs = json.load(f)
        except (json.JSONDecodeError, WindowsError, IOError) as err:
            logger.error(f"Failed to load prefs file! {err!r}")

        self.prefs.setdefault('fwHistory', [])
        self.prefs.setdefault('bootloaderHistory', [])
        self.prefs.setdefault('postCalActions', {})

        self.origPrefs = self.copyPrefs(self.prefs)

    def savePrefs(self):
        """ Save the preferences file. A backup of the previous file will be
            created if the preferences have changed.
        """
        # Don't save post-calibration actions; every run starts w/ defaults
        self.prefs.pop('postCalActions', None)

        try:
            if self.prefs != self.origPrefs:
                makeBackup(self.prefsFile)
        except (WindowsError, IOError):
            logger.error("Failed to make backup of prefs file!")

        try:
            with open(self.prefsFile, 'w') as f:
                json.dump(self.prefs, f)
            return
        except (json.JSONDecodeError, WindowsError, IOError) as err:
            logger.error(f"Failed to save prefs file! {err!r}")

        try:
            restoreBackup(self.prefsFile)
        except (WindowsError, IOError):
            logger.error("Failed to restore backup of prefs file!")

    # ===========================================================================
    #
    # ===========================================================================

    def findRecorder(self):
        """ Find (or wait for) a recorder to calibrate.

            @return: An instance of a `devices.Recorder` subclass.
        """
        # Force cache of known drive letters to clear (recorder may already be
        # present as a USB disk).
        endaq.device._LAST_RECORDERS = None

        # Device-finding callback for BusyBox
        def findDrive(*args):
            if endaq.device.deviceChanged():
                for dev in endaq.device.getDevices():
                    # TODO: Add extra test for recorder in calibration?
                    return dev
            return None

        status, dev = BusyBox.run(findDrive, "Waiting for Device...",
                                  "Attach a recorder via USB now.")

        if not dev:
            if status == wx.ID_CANCEL:
                logger.info('Cancelled scan for device.')
            elif status == BusyBox.ID_TIMEOUT:
                logger.warning('Scan for device timed out!')
            else:
                logger.warning('Scan for device failed, reason unknown!')

        return dev

    @classmethod
    def getUpdater(cls):
        """ Get the appropriate firmware updater for the architecture.
        """
        # No need to try the bootloader version.
        #         x = FirmwareUpdater.findBootloader()
        #         if x:
        #             fw = FirmwareUpdater()
        #             return (x, fw)

        x = FirmwareFileUpdaterGG11.findBootloader()
        if x:
            return FirmwareFileUpdaterGG11()

        x = FirmwareFileUpdater.findBootloader()
        if x:
            return FirmwareFileUpdater()

    @classmethod
    def getRecorder(cls, serialNumber):
        """ Wait for a recorder to reboot and appear as a USB disk.

            @param serialNumber: The serial number of the expected device.
        """
        # Force cache of known drive letters to clear (recorder may already be
        # present as a USB disk).
        # endaq.device._LAST_RECORDERS = None

        deadline = time.time() + cls.REBOOT_TIMEOUT

        while time.time() < deadline:
            if endaq.device.deviceChanged():
                for dev in endaq.device.getDevices():
                    if dev.serialInt == serialNumber:
                        return dev
            wx.Yield()
            time.sleep(.25)

    @classmethod
    def waitForEject(cls, dev):
        """
        """
        logger.info("Waiting for device to unmount...")

        deadline = time.time() + cls.REBOOT_TIMEOUT
        path = dev.path

        while time.time() < deadline:
            if not os.path.exists(path):
                return True
            wx.Yield()
            time.sleep(0.25)

        return False

    # ===========================================================================
    #
    # ===========================================================================

    def printLabel(self, session, printer=None):
        """ Print the calibration label.

            @param session: The current `products.models.CalSession`.
            @param printer: The name of the printer, if not the default.
        """
        try:
            while not labels.canPrint(printer):
                # Note: PLite LED is specific to PT-P700
                q = wx.MessageBox("The label printer could not be found.\n\n"
                                  "Make sure it is attached, turned on, "
                                  'and the "PLite" LED is off.\n\n'
                                  "Try again?", "Label Printing Error",
                                  wx.YES_NO | wx.ICON_ERROR)
                if q == wx.NO:
                    return

            labels.printCalLabel(session.sessionId, session.date)

        except RuntimeError:
            wx.MessageBox("The printer SDK components could not be loaded.\n\n"
                          "Have they been installed?", "Label Printing Error",
                          wx.OK | wx.ICON_ERROR)

    # ===========================================================================
    #
    # ===========================================================================

    def logFailure(self, cal, failure, aborted=True):
        """ Write the failure to the log.
        """
        cal.failure = failure
        failure = f'{failure}: calibration {"aborted" if aborted else "failed"}!'
        logger.error(failure)

        try:
            cal.session.failed = True
            if cal.session.notes:
                cal.session.notes = f"{cal.session.notes}\n\n{failure}"
            else:
                cal.session.notes = failure
            cal.session.save()
        except AttributeError:
            # Database probably not updated yet. Continue.
            pass

        # XXX: TODO: Re-enable calibration log writing?

    #         legacy.writeCalibrationLog(cal, err=failure, writeCalNumber=False)

    def _cancelCalPrompt(self, dev, msgList,
                         title="Possible Calibration Problem"):
        """ Helper function to reduce prompting to to quit to one or two lines.
        """
        # TODO: Use this instead of function in `validateCalibration()`?
        name = f"{dev.productName} SN:{dev.serial}"
        msg = "\n".join(msgList) + (f"\n\nContinue calibrating {name}?")
        q = wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_WARNING)

        if q == wx.YES:
            return False

        return True

    def validateDevice(self, dev, maxDrift=86400):
        """ Perform basic sanity check validation on the device being
            calibrated. Currently just checks clock drift.

            @param dev: The current device.
            @param maxDrift: The maximum allowable clock drift, in seconds.
        """
        # TODO: Check log files (GG11 only?)

        # Validate device clock
        try:
            drift = dev.getClockDrift()
            if drift <= maxDrift:
                return True
        except ValueError:
            return True

        msg = ["Extreme clock drift detected!", "",
               f"The device clock is off by {drift:0.2} seconds.",
               "This could indicate a hardware, firmware or battery problem."]
        if self._cancelCalPrompt(dev, msg, "Possible Device Problem"):
            logger.error(f"Extreme clock drift: {drift:0.2}; calibration aborted!")
            # TODO: Write to database?
            return False

        # Passed!
        return True

    def validateCalibration(self, cal, transMax=MAX_TRANSVERSE,
                            calRange=VALID_CAL_RANGE,
                            pressRange=VALID_PRESS_RANGE,
                            maxDrift=86400, maxDaysDrift=90):
        """ Perform basic sanity check validation on calibration data.

            @param cal: The current `calibration.Calibrator` object
            @param transMax: The maximum allowed transverse value.
            @param calRange: A tuple with the min and max valid cal values.
            @param pressRange: A tuple w/ the min and max pressure values.
            @param maxDrift:
            @param maxDaysDrift:
            @return: `True` if calibration should continue, `False` if not.
        """

        name = f"{cal.dev.productName}, SN:{cal.dev.serial}"

        def _cancelCalPrompt(msgList):
            """ Helper function to reduce prompting to quit to one line. """
            msg = "\n".join(msgList) + (f"\n\nContinue calibrating {name}?")
            q = wx.MessageBox(msg, "Possible Calibration Problem",
                              wx.YES_NO | wx.ICON_WARNING)
            return q == wx.NO

        # Validate recording times
        now = time.time()
        deltas = [(now - c.timestamp) for c in cal.calFiles]
        if any(abs(d / (60 * 60 * 24) > maxDaysDrift) for d in deltas):
            now = datetime.now()
            msg = ["Bad recording date(s) detected!",
                   "",
                   "The following recordings had bad timestamps, which may indicate a bad clock:",
                   ""]
            for c in cal.calFiles:
                d = now - datetime.fromtimestamp(c.timestamp)
                if d.days > maxDaysDrift:
                    n = os.path.basename(c.filename)
                    msg.append(f"    \u2022 {n}: off by {d}")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Bad recording times")
                return False

        # Validate transverse
        if None in cal.trans:
            msg = ["Error in calculating transverse sensitivity!",
                   "",
                   "Only found the following:"]
            for i, trans in enumerate(cal.trans):
                if trans is not None:
                    name = os.path.basename(cal.calFiles[i].filename)
                    axes = ("XY", "YZ", "ZX")[i]
                    msg.append(f"    \u2022 {name}, Transverse Sensitivity in {axes} = {trans:.2f}%")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Bad transverse sensitivity")
                return False

        if any((x > transMax for x in cal.trans)):
            msg = ["Extreme transverse sensitivity detected!", ""]
            for i, trans in enumerate(cal.trans):
                if trans > transMax:
                    name = os.path.basename(cal.calFiles[i].filename)
                    axes = ("XY", "YZ", "ZX")[i]
                    msg.append(f"    \u2022 {name}, Transverse Sensitivity in {axes} = {trans:.2f}%")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Extreme transverse sensitivity")
                return False

        # Validate air pressure
        badPress = [f for f in cal.calFiles if not inRange(f.cal_press, *pressRange)]
        if len(badPress) > 0:
            msg = ["Extreme air pressure detected in recording(s)!", ""]
            for f in badPress:
                msg.append(f"    \u2022 {os.path.basename(f.filename)}: {f.cal_press:.2f} Pa")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Pressure out of range")
                return False

        # Validate actual calibration coefficients
        if cal.hasHiAccel and not allInRange(cal.cal, *calRange, absolute=True):
            msg = ["Out-of-range calibration coefficient(s) detected!", ""]
            for i, axis in enumerate("XYZ"):
                c = cal.cal[i]
                f = cal.calFiles[i]
                ch = f.accelChannel
                filename = os.path.basename(f.filename)
                msg.append(f"    \u2022 {axis} Axis ({filename}, Channel {ch.id}) coefficient: {c:.4f}")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Coefficient(s) out of range")
                return False

        if cal.hasLoAccel and not allInRange(cal.calLo, *calRange, absolute=True):
            msg = ["Out-of-range calibration coefficient(s) detected!", ""]
            for i, axis in enumerate("XYZ"):
                c = cal.calLo[i]
                f = cal.calFiles[i]
                ch = f.accelChannelLo
                filename = os.path.basename(f.filename)
                msg.append(f"    \u2022 {axis} Axis ({filename}, Channel {ch.id}) coefficient: {c:.4f}")

            if _cancelCalPrompt(msg):
                self.logFailure(cal, "Coefficient(s) out of range")
                return False

        # Passed!
        return True

    def handleCalibrationException(self, err):
        """ Show a message box with information about why a calibration failed.

            @param err: The raised `calibration.CalibrationError`
        """
        print(err.args)
        msg = err.message or "An unspecified error occurred!"
        if len(err.args) > 1:
            msg += f"\n\nFile: {err.args[1].filename}"
        if len(err.args) > 2:
            msg += f'\n{str(err.args[2]).rsplit(" at ", 1)[0].strip("<>")}'
        msg += "\n\nCalibration aborted."
        wx.MessageBox(msg, "Calibration Error", wx.OK | wx.ICON_ERROR)

    def generateEbml(self, session, filename):
        """ Create the calibration XML and EBML.

            @param session: The calibration session record
            @type session: `products.models.CalSession`
            @param filename: The name of the file to write. Note: the created
                files will always get the appropriate extensions (``.ebml``
                and ``.xml``), regardless of what's in the given filename.
        """
        base, _ext = os.path.splitext(filename)
        xmlName = base + ".xml"
        ebmlName = base + ".ebml"

        calTempl = CalTemplater(session)
        calTempl.writeXML(xmlName)
        calTempl.writeEBML(ebmlName)

        return calTempl.dumpEBML()

    def getUserInput(self, cal, defaultHumidity=calibration.DEFAULT_HUMIDITY,
                     actions=None):
        """ Prompt the user for the session ID, the reference sensor, the
            calibration certificate, and the humidity.

            @param cal: The current `calibration.Calibrator` object
            @param defaultHumidity: The default humidity value to use if the
                recordings didn't have humidity data.
            @param actions:
            @return: A tuple containing the calibration ID, selected reference,
                the selected certificate, and the entered humidity.
        """
        actions = actions or {}

        calibration.reconnect()

        info = cal_util.dumpCal(cal)

        hum = cal.meanCalHumid or defaultHumidity
        fromFile = cal.meanCalHumid is not None

        certs = list(models.CalCertificate.objects.all().extra(order_by=['name', '-revision']))
        cert = cal.certificate or cal.getCertificateRecord()

        refs = list(models.CalReference.objects.all())
        ref = cal.reference or models.CalReference.objects.latest('date')

        with CalInfoDialog(None, info=info, device=cal.dev,
                           humidity=hum, fromFile=fromFile,
                           reference=ref, references=refs,
                           certificate=cert, certificates=certs,
                           **actions) as dlg:
            dlg.CenterOnScreen()

            q = dlg.ShowModal()
            result = dlg.getValues()

        actions.update(result[-1])

        if q != wx.ID_OK:
            cal.cancelled = True
            return None

        return result

    def copyCertificate(self, dev, pdfName):
        """ Copy the generated PDF file to the device's DOCUMENTATION
            directory.
        """
        try:
            if pdfName and os.path.exists(pdfName):
                destName = os.path.join(dev.path, "DOCUMENTATION",
                                        os.path.basename(pdfName))
                deepCopy(pdfName, destName, clobber=True)
        except (IOError, WindowsError) as err:
            # TODO: message box for failed cert copy?
            logger.error(f"Failed to copy certificate to device: {err!s}")

    # ===========================================================================
    #
    # ===========================================================================

    def updateProgress(self, msg, step=None):
        """ Update the progress dialog, showing current step.
        """
        logger.info(msg)
        dev = self.lastCal.dev

        if dev.productName != dev.partNumber:
            name = f"{dev.productName} ({dev.partNumber})"
        else:
            name = f"{dev.partNumber}"

        name = f"Calibrating {name}, SN:{dev.serial}\n\n{msg}"

        if step:
            self.pd.Update(name, step)
        else:
            self.pd.Pulse(name)

    def calibrateWithWizard(self, dev):
        """ Do the thing.

            @param dev: The device to calibrate. Currently, this is limited to
                "real" devices (as opposed to virtual ones created from
                recording data).
            @type dev: An instance of a `devices.Recorder` subclass.
            @return: `True` if everything worked, `False` if not.
        """
        logger.info(f'*** Starting calibration of {dev}')

        # PROLOGUE: CHECK HW AND GET APPROPRIATE FIRMWARE UPDATER =============
        if not self.validateDevice(dev):
            return False

        fw = self.getUpdater()
        if fw is None:
            logger.error("Failed to find updater!")
            return False

        fw.connect(dev)

        # PROLOGUE: GET UI DEFAULTS FROM PREFERENCES ==========================
        actions = self.prefs.setdefault('postCalActions', {})
        humidity = self.prefs.get('humidity', calibration.DEFAULT_HUMIDITY)

        # 0: CREATE CALIBRATOR ================================================
        logger.info("Step 0: Create Calibrator")
        cal = calibration.Calibrator(dev)
        self.lastCal = cal

        # 1-2: FIND RECORDINGS, COPY TO TEMP. DIRECTORY =======================
        self.updateProgress("Steps 1,2: Find Recordings, copy to temp. directory")
        cal_util.makeWorkDir(cal)
        ideFiles = cal_util.copyToWorkDir(cal)

        if len(ideFiles) == 0:
            wx.MessageBox("No IDEs found!\n\n3 required, 0 found.\n\n"
                          "Calibration aborted.", "Invalid Calibration Files",
                          wx.OK | wx.ICON_ERROR)
            return False

        elif len(ideFiles) != 3:
            # Too few (or too many) recordings!
            files = '\n'.join([f"  * {f}" for f in ideFiles])
            wx.MessageBox(f"Wrong number of IDEs found!"
                          f"\n\n3 required, {len(ideFiles)} found:\n{files}"
                          f"\n\nCalibration aborted.",
                          "Invalid Calibration Files",
                          wx.OK | wx.ICON_ERROR)
            return False

        # 3: ANALYZE ==========================================================
        self.updateProgress("Step 3: Analyze and validate calibration recordings")
        try:
            cal.calculate(ideFiles)
            if not self.validateCalibration(cal):
                return False
        except calibration.CalibrationError as err:
            self.handleCalibrationException(err)
        finally:
            try:
                cal.closeFiles()
            except Exception as err:
                logger.error(f'Could not close files; {err}')
                return False

        # 4: GET USER INPUT ===================================================
        self.updateProgress("Step 4: Get/verify information")
        sessionInfo = self.getUserInput(cal, humidity, actions)
        if sessionInfo is None:
            return False

        sessionId, reference, certificate, humidity, actions = sessionInfo

        # 5: UPDATE DATABASE ==================================================
        self.updateProgress("Step 5: Update database")
        self.reconnect()  # Just in case it's timed out
        session = cal.updateDatabase(sessionId=sessionId, reference=reference,
                                     certificate=certificate, humidity=humidity)

        # 6: GENERATE CALIBRATION EBML ========================================
        self.updateProgress("Step 6: Generate calibration XML/EBML")
        xmlName = os.path.join(cal.workDir, "cal.current.xml")
        calEbml = self.generateEbml(session, xmlName)

        self.updateProgress("Step 6.1: Generate userpage.bin")
        userpageFile = os.path.join(cal.workDir, 'userpage.bin')
        generateUserpage(cal.birth, cal=session, filename=userpageFile)

        # 7: GENERATE CERTIFICATE =============================================
        if self.hasInkscape and actions.get('makeCertificate', True):
            self.updateProgress("Step 7: Generate calibration certificate")
            certTempl = CalCertificateTemplater(session)
            certName = certTempl.templateFile.replace('template', str(session).replace(', ', '_'))
            pdfName = certTempl.writePDF(os.path.join(cal.workDir, certName))
        else:
            logger.debug("Skipping Step 7: Generate calibration certificate")
            pdfName = None

        # 8: COPY FROM TEMP. DIRECTORY TO NETWORK =============================
        self.updateProgress("Step 8: Copy from temp. directory to network folder")
        cal_util.copyFromWorkDir(cal)

        # 8.1: COPY CALIBRATION TO CHIP DIR
        self.updateProgress("Step 8.1: Copy calibration to device chip directory")
        cal_util.copyCal(cal)

        # 9: INSTALL NEW MANIFEST and REBOOT =================================
        if actions.get('writeUserpage', True):
            self.updateProgress("Step 9: Install manifest and new calibration and reboot")
            dev.command.updateDevice(userpage=userpageFile)

            # Delay a little to make sure the device has time to start
            # rebooting.
            wx.MilliSleep(250)

            # TODO: Fail if the recorder doesn't disconnect after a time?
            dev = self.getRecorder(dev.serialInt)
            if dev is None:
                # Timed out!
                logger.error('Timed out waiting for device in disk mode!')
                wx.MessageBox(f"Reboot timed out!\n\nRecorder did not appear "
                              f"as a drive after {self.REBOOT_TIMEOUT} seconds."
                              "\nCalibration may have failed.",
                              "Reboot Timeout",
                              wx.OK | wx.ICON_ERROR)
                return None
        else:
            logger.debug("Skipping Step 9: Install manifest with new calibration")

        # 10: CLEAN DEVICE =====================================================
        if actions.get('cleanDevice', True):
            self.updateProgress("Step 10: Clean device")
            cal_util.cleanRecorder(dev)
        else:
            logger.debug("Skipping Step 10: Clean device")

        self.updateProgress("Setting the clock...")
        try:
            dev.command.setTime()
        except (IOError, WindowsError) as err:
            # TODO: report that clock could not get set?
            logger.error(f"Failed to set clock! {err!r}")

        # 11: PRINT LABEL (optional) ==========================================
        if actions.get('printLabel', True):
            self.updateProgress("Step 11: Print Label")
            self.printLabel(session)
        else:
            logger.debug("Skipping Step 11: Print Label")

        # 12: COPY SOFTWARE/DOCS/ETC. =========================================
        if actions.get('copyContent', True):
            self.updateProgress("Step 12: Copy software/docs/etc. to device")
            copyContent(dev, paths.DB_PATH)
        else:
            logger.debug("Skipping Step 12: Copy software/docs/etc. to device")

        # 12.1: COPY CAL CERTIFICATE
        self.updateProgress("Step 12.1: Copy calibration certificate to device")
        self.copyCertificate(dev, pdfName)

        # X: DISCONNECT THE DRIVE
        # Meant to fix issue that apparently wasn't actually related.
        # try:
        #     ejectDrive(dev.path)
        # except Exception as err:
        #     logger.error(f"Failed to eject drive: {err}")

        # X: FINISHING ========================================================
        self.updateProgress("Finished!")

        # Keep data to use as defaults for next birth
        self.prefs['humidity'] = humidity
        self.prefs['postCalActions'] = actions

        session.completed = True
        session.save()

        # Y: CHECK DISK FOR ERRORS =============================================
        if actions.get('runChkdsk', True):
            cmd = ['chkdsk.exe', dev.path, '/offlinescanandfix']
            logger.info('Executing:', ' '.join(cmd))
            subprocess.call(cmd, shell=True)

        # Z: DONE! =============================================================
        logger.info(f'*** Completed calibration of {dev}')

        return True

app = CalApp()
