"""
Module birther.birth_wizard

Created on Jan 17, 2019

FUTURE: Completely remove the `FirmwareUpdater` stuff, which was originally
    written for handling the GG0 serial bootloader and is overly complex for
    newer devices. This has been partially refactored to remove most of the
    `FirmwareUpdater` method calls.
FUTURE: Device channel configuration.
"""

__author__ = "dstokes"
__copyright__ = "Copyright 2023 Mide Technology Corporation"

import errno
import getpass
from glob import glob
import json
import os
import pprint
import shutil
import string
import tempfile

from serial.serialutil import SerialTimeoutException

import wx
from wx.lib.embeddedimage import PyEmbeddedImage
import wx.lib.filebrowsebutton as FB
import wx.lib.mixins.listctrl as listmix
import wx.lib.sized_controls as SC
import wx.adv

# Set up paths. Import even if it isn't used directly. Important! Do early!
from . import paths

#===============================================================================
#--- Logging setup: Done early to set up for other modules

import logging
from . import shared_logger
from .shared_logger import logger

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

#===============================================================================

# Django setup
os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

import pytz
import django.db
from django.db.models import Q
from django.utils import timezone
django.setup()

# My Django components
# NOTE: Django import paths are weird. Get `products.models` from Django itself instead of importing.
from django.apps import apps
models = apps.get_app_config('products').models_module

import ebmlite
import endaq.device

from .busybox import BusyBox
from .generate_userpage import makeUserpage
from . import labels
from . import legacy
from .template_generator import ManifestTemplater, DefaultCalTemplater
from . import util
from .util import makeBackup, restoreBackup, renameVolume, readFile
from .util import safeCopy, safeRemove, safeRmtree, getCardSize

# To be removed after `firmware` merged with SlamStickLab
from firmware import FirmwareUpdater, FirmwareFileUpdater, FirmwareFileUpdaterGG11
from efm32_firmware import FirmwareFileUpdaterSTM32


#===============================================================================
#--- Paths on network shares for content, binaries, etc. 
#===============================================================================

CONFIG_PATH = os.path.join(paths.BIRTHER_PATH, 'configfiles')

# For updating devices with the wrong manufacturing firmware
# This can probably be removed now (1/2023)
GG11_MAN_FW = os.path.join(paths.FW_LOCATION, 'EFM32GG11B820', 'Mfg_Test',
                           '20191015_rev4', 'firmware_mfg-4.bin')

#===============================================================================
#--- Globals and 'constants' 
#===============================================================================

LOCALTZ = pytz.timezone('US/Eastern')
USER = getpass.getuser()

DEFAULT_CAPACITY = 2

uiSchema = ebmlite.loadSchema('mide_config_ui.xml')

# Make this a test birth if the test product path is being used
TEST_BIRTH = paths.PRODUCT_ROOT_PATH != paths.REAL_PRODUCT_ROOT_PATH

#===============================================================================
#
#===============================================================================


def cmp(a, b):
    """ Workaround for removal of `cmp()` from Python 3. """
    if a == b:
        return 0
    elif a and not b:
        return -1
    elif b and not a:
        return 1
    if a > b:
        return 1
    else:
        return -1


#===============================================================================
# 
#===============================================================================


class GenericValidator(wx.Validator):
    """ Generic Validator for text entry widgets, with validation of pasted
        values. Uses whatever validation function is provided when constructed.
    
        The validation function should accept a string of any length and
        return `True` if the string is valid (e.g. all its characters are 
        permitted).
    """

    # Keys that are always valid and not processed by the validator
    VALID_KEYS = (wx.WXK_LEFT, wx.WXK_UP, wx.WXK_RIGHT, wx.WXK_DOWN,
                  wx.WXK_HOME, wx.WXK_END, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN,
                  wx.WXK_INSERT, wx.WXK_DELETE)
    
    @classmethod
    def getClipboardText(cls):
        """ Retrieve text from the clipboard.
        """
        if not wx.TheClipboard.IsOpened(): 
            wx.TheClipboard.Open()
        
        obj = wx.TextDataObject()
        if (wx.TheClipboard.GetData(obj)):
            return obj.GetText()
        
        return ""    

    
    def __init__(self, validator, maxLen=None):
        """ Instantiate a text field validator.
        
            @keyword validator: A function that validates the string. 
            @keyword maxLen: The maximum length of the string entered or `None`
                if there is no limit.
        """
        self.maxLen = maxLen
        self.isValid = validator
        wx.Validator.__init__(self)
        self.Bind(wx.EVT_CHAR, self.OnChar)
        self.Bind(wx.EVT_TEXT_PASTE, self.OnPaste)


    def Clone(self):
        """ Required in wx.PyValidator subclasses. """
        return GenericValidator(self.isValid, self.maxLen)
    
    
    def TransferToWindow(self):
        """ Required in wx.PyValidator subclasses. """
        return True
    
    
    def TransferFromWindow(self):
        """ Required in wx.PyValidator subclasses. """
        return True
    
    
    def Validate(self, _win):
        txt = self.GetWindow().GetValue()
        if self.maxLen is None or len(txt) <= self.maxLen:
            return self.isValid(txt)
        return False


    def OnChar(self, evt):
        """ Validate a character that has been typed.
        """
        key = evt.GetKeyCode()

        if key < wx.WXK_SPACE or key in self.VALID_KEYS:
            evt.Skip()
            return
        
        val = self.GetWindow().GetValue()

        if self.isValid(chr(key)):
            if self.maxLen is None or len(val) < self.maxLen:
                evt.Skip()
                return

        if not wx.Validator.IsSilent():
            wx.Bell()

        return
    
    
    def OnPaste(self, evt):
        """ Validate text pasted into the field.
        """
        txt = self.GetWindow().GetValue() + self.getClipboardText()
        if self.maxLen is not None:
            txt = txt[:self.maxLen]
        if self.isValid(txt):
            evt.Skip()
        elif not wx.Validator.IsSilent():
            wx.Bell()


#===============================================================================
# 
#===============================================================================

class TitledPage(wx.adv.WizardPage):
    """ Base class for a page with title text displayed.
    """
    DEFAULT_TITLE = "Page"
 
    # These get filled in (as class variables) by __init__()
    TITLE_FONT = None
    SECTION_FONT = None
 
    def __init__(self, parent, title=None):
        """ Constructor.
        """
        wx.adv.WizardPage.__init__(self, parent)
        self.app = wx.GetApp()

        self.data = self.GetParent().data

        if TitledPage.TITLE_FONT is None:
            TitledPage.TITLE_FONT = wx.Font(18, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)

        if TitledPage.SECTION_FONT is None:
            TitledPage.SECTION_FONT = wx.Font(12, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
 
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.sizer = sizer
        self.SetSizer(sizer)
 
        if self.data.rebirth:
            self.title = "Rebirth: %s" % (title or self.DEFAULT_TITLE)
        else:
            self.title = "Birth: %s" % (title or self.DEFAULT_TITLE)

        self.titleText = wx.StaticText(self, -1, self.title)
        self.titleText.SetFont(TitledPage.TITLE_FONT)
        sizer.Add(self.titleText, 0, wx.ALIGN_CENTRE | wx.ALL, 5)

        self.prev = self.next = None

        self.getData()
        self.buildUI()
        self.Bind(wx.adv.EVT_WIZARD_PAGE_SHOWN, self.OnPageShown)
        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGING, self.OnPageChanging)


    def addSection(self, name):
        """ Create a section label (static text with the section font).
        """
        line = wx.StaticLine(self, -1)
        section = wx.StaticText(self, -1, name)
        section.SetFont(self.SECTION_FONT)
        self.sizer.Add(line, 0, wx.EXPAND | wx.NORTH | wx.SOUTH, 5)
        self.sizer.Add(section, 0, wx.SOUTH, 5)
        
        return section


    def addBoldLabel(self, *text):
        """ Helper method to add a line of static text, created from one or
            more strings. The second item will be in bold.
        """
        labels = []
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add((0, 0), 1, wx.EXPAND)

        for i, t in enumerate(text):
            label = wx.StaticText(self, -1, t)
            sizer.Add(label, 0, wx.EXPAND)
            labels.append(label)
            if i == 1:
                label.SetFont(label.GetFont().Bold())
                
        sizer.Add((0, 0), 1, wx.EXPAND)
        self.sizer.Add(sizer, 0, wx.WEST, 8)
        
        return labels
    
    
    #===========================================================================
    # 
    #===========================================================================

    def SetPrev(self, page):
        """ Set the previous page. Required by `WizardPage`.
        """
        self.prev = page


    def SetNext(self, page):
        """ Set the next page. Required by `WizardPage`.
        """
        self.next = page
        if page:
            page.SetPrev(self)


    def GetPrev(self):
        """ Get the previous page. Required by `WizardPage`.
        """
        # Override this in subclasses with options that change page order
        # (e.g. have advanced options that appear if a widget is checked)
        return self.prev
    
    
    def GetNext(self):
        """ Get the next page. Required by `WizardPage`.
        """
        # Override this in subclasses with options that change page order
        # (e.g. have advanced options that appear if a widget is checked)
        return self.next


    #===========================================================================
    # Methods that subclasses should/must implement
    #===========================================================================
    
    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        # Implement this in subclasses. Set attributes used by the widgets.
        pass


    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        # Implement this in subclasses. Update what the widgets referenced.
        logger.info("Page '%s': TitledPage.updateData()" % self.title)
        return True
    

    def buildUI(self):
        """ Construct the GUI.
        """
        # Implement this in subclasses.
        pass


    def populate(self):
        """ Fill out the UI with (current) data from the parent.
        """
        # Implement this in subclasses.
        pass


    def OnPageShown(self, evt):
        """ Event handler called when a page is shown. Updates the widgets.
        """
        # Implement this in subclasses (if required).
        # Fetch new data only if entering from previous page.
        if evt.GetDirection():
            self.getData()
            self.populate()


    def OnPageChanging(self, evt):
        """ Event handler called when leaving the page (but not by canceling).
        """
        # If moving to the next page, update parent data based on UI input.
        if evt.GetDirection():
            if not self.updateData():
                logger.info('%s updateData() failed; page change vetoed' %
                            self.__class__.__name__)
                evt.Veto()
                return
        evt.Skip()


#===============================================================================
# 
#===============================================================================

class BatchAndSNPage(TitledPage):
    """ Wizard page for getting basic Device/Birth/Batch information.
    """
    DEFAULT_TITLE = "Basic Information"

    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        self.chipId = self.data.chipId
        self.resetDate = self.data.resetCreationDate
        self.serialNumber = str(self.data.serialNumber or "")
        self.newSerialNumber = not self.serialNumber or self.data.newSerialNumber
        self.batchId = self.data.batchId or ""
        self.batches = self.app.batches
        self.orderId = self.data.orderId or ""
        self.orders = self.app.orders
        self.notes = self.data.birthNotes

        self.caseTypes = [x[1] for x in models.Device.ENCLOSURE_TYPES]
        self.caseMap = {y[0]: x for x, y in enumerate(models.Device.ENCLOSURE_TYPES)}
        self.enclosure = self.data.enclosure
        
        self.capacity = self.data.capacity
        self.capacities = [str(c) for c in self.app.prefs.get('capacities', [])]
    
        if self.data.mcu != self.data.fullMcu:
            self.mcu = "%s (%s)" % (self.data.fullMcu, self.data.mcu)
        else:
            self.mcu = self.data.mcu
            
#         self.showRebirthButton = (self.data.rebirth \
#                                   and self.data.lastBirth is not None)
        self.showRebirthButton = False

    
    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        self.data.batchId = self.batchField.GetValue()
        self.data.birthNotes = self.birthNotesField.GetValue()
        self.data.resetCreationDate = self.resetDateCheck.GetValue()
        
        newSn = self.newSNButton.GetValue()
        self.data.newSerialNumber = newSn
        if not newSn:
            self.data.serialNumber = int(self.snField.GetValue().strip())

        enc = max(self.caseField.GetSelection(), 0)
        self.data.enclosure = models.Device.ENCLOSURE_TYPES[enc][0]
        
        try:
            cap = self.capacityField.GetValue()
            cap = int(cap.strip(string.ascii_letters+string.whitespace))
        except ValueError:
            cap = DEFAULT_CAPACITY
            self.capacityField.SetValue(str(cap))

        self.data.capacity = self.capacity = cap
            
        return True


    def buildUI(self):
        """ Construct the GUI.
        """
        # 'Rebirth using existing data' button - skips the rest of the wizard
        # FUTURE: Hook this up if it seems useful.
        #=======================================================================
        if self.showRebirthButton:
            line = wx.StaticLine(self, -1)
            self.sizer.Add(line, 0, wx.EXPAND | wx.NORTH | wx.SOUTH, 5)

            self.rebirthButton = wx.Button(self, -1, "Rebirth Using Existing Data (%s)" % 
                                           self.data.lastBirth.product)
            self.rebirthButton.SetFont(self.rebirthButton.GetFont().Bold())
            self.sizer.Add(self.rebirthButton, 0, wx.ALIGN_CENTER | wx.EXPAND)
            
            self.rebirthButton.Bind(wx.EVT_BUTTON, self.OnUseExistingDataButton)
        
        # UUID (i.e. the MCU's chip ID)
        #=======================================================================
        self.addSection("Device Unique ID")
         
        idpane = SC.SizedPanel(self, -1)
        idpane.SetSizerType("form")
        
        wx.StaticText(idpane, -1, 'Device UUID:').SetSizerProps(valign="center")
        self.uuidField = wx.TextCtrl(idpane, -1, self.chipId, style=wx.TE_READONLY)
        self.uuidField.SetSizerProps(valign="center", expand=True)

        wx.StaticText(idpane, -1, 'Device MCU:').SetSizerProps(valign="center")
        self.mcuField = wx.TextCtrl(idpane, -1, self.chipId, style=wx.TE_READONLY)
        self.mcuField.SetSizerProps(valign="center", expand=True)

        self.resetDateCheck = wx.CheckBox(idpane, -1, "Reset manufacturing date")
        self.resetDateCheck.SetSizerProps(valign="center", expand=True)

        self.sizer.Add(idpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        # FUTURE: Make editable for things without MCU when we've got them
        # (i.e. the modules for the ENDAQ 'hub').
        
        # Serial Number
        #=======================================================================
        self.addSection("Serial Number")
         
        snpane = SC.SizedPanel(self, -1)
        snpane.SetSizerType("form")
        
        self.oldSNButton = wx.RadioButton(snpane, -1, "Keep Previous Serial Number")
        self.oldSNButton.SetSizerProps(valign="center")
        self.oldSNText = wx.StaticText(snpane, -1, self.serialNumber)
        self.oldSNText.SetSizerProps(valign="center")
        
        self.newSNButton = wx.RadioButton(snpane, -1, "New Serial Number")
        wx.StaticText(snpane, -1, '(will be generated at the end)')
          
        self.customSNButton = wx.RadioButton(snpane, -1, "Set Serial Number:")
        self.customSNButton.SetSizerProps(valign="center")
        self.snField = wx.TextCtrl(snpane, -1, self.serialNumber)
        self.snField.SetSizerProps(expand=True)
        self.snField.SetValidator(GenericValidator(lambda x: not x or x.isdigit()))
  
        self.sizer.Add(snpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        self.Bind(wx.EVT_RADIOBUTTON, self.OnRadioButton)
        
        self.snField.Enable(False)
        self.newSNButton.SetValue(True)
        
        if self.data.rebirth:
            if self.data.serialNumber:
                self.oldSNButton.SetValue(True)
            else:
                self.newSNButton.SetValue(True)
        else:
            self.oldSNButton.Hide()
            self.oldSNText.Hide()
        
        # FUTURE: Also add LastSerialNumber 'group' selector. Currently,
        # all device serial numbers are in the same series.
         
        #=======================================================================
        self.addSection("Case and Capacity")

        bpane = SC.SizedPanel(self, -1)
        bpane.SetSizerType("form")

        wx.StaticText(bpane, -1, 'Enclosure Type:').SetSizerProps(valign="center")
        self.caseField = wx.Choice(bpane, -1, choices=self.caseTypes)
        self.caseField.SetSizerProps(valign="center", expand=True)

        wx.StaticText(bpane, -1, 'SD/eMMC Capacity:').SetSizerProps(valign="center")
        self.capacityField = wx.ComboBox(bpane, -1)
        self.capacityField.SetSizerProps(valign="center", expand=True)
        self.capacityField.SetValidator(GenericValidator(lambda x: not x or x.isdigit()))
        
        self.sizer.Add(bpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)

        # Batch ID
        #=======================================================================
        self.addSection("Batch")
        
        batchpane = SC.SizedPanel(self, -1)
        batchpane.SetSizerType("form")
         
        wx.StaticText(batchpane, -1, "Batch ID:").SetSizerProps(valign="center")
        self.batchField = wx.ComboBox(batchpane, -1)
        self.batchField.SetSizerProps(valign="center", expand=True)

        wx.Panel(batchpane, -1)
        self.batchNote = wx.StaticText(batchpane, -1, "Unknown ID: A new Batch will be generated.")
         
        self.sizer.Add(batchpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)

        self.Bind(wx.EVT_TEXT, self.OnBatchInput, self.batchField)
        
        # Order
        #=======================================================================
        self.addSection("Order")
         
        orderpane = SC.SizedPanel(self, -1)
        orderpane.SetSizerType("form")

        wx.StaticText(orderpane, -1, "Order ID:").SetSizerProps(valign="center")
        self.orderField = wx.ComboBox(orderpane, -1)
        self.orderField.SetSizerProps(valign="center", expand=True)
        
        wx.Panel(orderpane, -1)
        wx.StaticText(orderpane, -1, "Leave blank if this was not created for a specific order.")
        
        self.sizer.Add(orderpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)

        # Notes
        #=======================================================================
        self.addSection("Birth Notes")
        lbl = wx.StaticText(self, -1, "Notes about this birth, not necessarily the hardware itself.")
        self.sizer.Add(lbl, 0, wx.EAST | wx.WEST, 16)
        self.birthNotesField = wx.TextCtrl(self, -1,  style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.sizer.Add(self.birthNotesField, 1, wx.EXPAND | wx.EAST | wx.WEST, 16)

    
    def populate(self):
        """ Fill out the UI with (current) data from the parent.
        """
        self.uuidField.SetValue(self.chipId)
        self.mcuField.SetValue(self.mcu)

        self.resetDateCheck.SetValue(self.resetDate)
        self.resetDateCheck.Enable(self.data.rebirth)

        self.batchField.SetItems(self.batches)
        self.batchField.SetValue(self.batchId)
        
        self.newSNButton.SetValue(self.newSerialNumber)

        self.caseField.SetSelection(self.caseMap.get(self.enclosure, 0))
        self.capacityField.SetItems(self.capacities)
        self.capacityField.SetValue(str(self.capacity))

        self.orderField.SetItems(self.orders)
        self.orderField.SetValue(self.orderId)

        self.birthNotesField.SetValue(self.notes)
        
        self.batchNote.Show(bool(self.batchId) and self.batchId not in self.batches)


    def OnRadioButton(self, evt):
        """ Event handler for radio buttons (i.e. old/new serial number).
        """
        rb = evt.GetEventObject()
        if rb == self.newSNButton:
            self.snField.Enable(False)
        elif rb == self.customSNButton:
            self.snField.Enable(True)
    
    
    def OnBatchInput(self, evt):
        """ Handler for batch field input (selected or typed).
        """
        val = evt.GetString().upper()
        self.batchNote.Show(val != "" and val not in self.batches)
        evt.Skip()

    
    def OnUseExistingDataButton(self, _evt):
        """
        """
        logger.info("FUTURE: Implement 'use existing data' button functionality")


#===============================================================================
# 
#===============================================================================

class PickExamplePage(TitledPage, listmix.ColumnSorterMixin):
    """ Wizard page for selecting an 'example' product (a dummy Birth to be
        used as a template).
    """
    DEFAULT_TITLE = "Select Product Type"
    
    COL_PARTNUM = 0
    COL_NAME = 1
    COL_MCU = 2
    COL_HWREV = 3
    COL_NOTES = 4

    DEFAULT_SORT_COL = COL_PARTNUM
    DEFAULT_SORT_DIR = 1

    # Column header sorting indicators
    SmallUpArrow = PyEmbeddedImage(
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAA"
        "DxJREFUOI1jZGRiZqAEMFGke2gY8P/f3/9kGwDTjM8QnAaga8JlCG3CAJdt2MQxDCAUaO"
        "jyjKMpcRAYAABS2CPsss3BWQAAAABJRU5ErkJggg==")
    
    SmallDnArrow = PyEmbeddedImage(
        "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAAABHNCSVQICAgIfAhkiAAAA"
        "EhJREFUOI1jZGRiZqAEMFGke9QABgYGBgYWdIH///7+J6SJkYmZEacLkCUJacZqAD5DsI"
        "nTLhDRbcPlKrwugGnCFy6Mo3mBAQChDgRlP4RC7wAAAABJRU5ErkJggg==")


    #===========================================================================
    # 
    #===========================================================================
    
    class ProductListCtrl(wx.ListCtrl, listmix.ListCtrlAutoWidthMixin):
        """ Required to create a sortable list with column auto-width.
        """
        def __init__(self, parent, ID, pos=wx.DefaultPosition,
                     size=wx.DefaultSize, style=0):
            wx.ListCtrl.__init__(self, parent, ID, pos, size, style)
            listmix.ListCtrlAutoWidthMixin.__init__(self)  # @UndefinedVariable
            
            
    #===========================================================================
    # 
    #===========================================================================
    
    def __init__(self, parent, title=None):
        """
        """
        self.sortedCol = self.DEFAULT_SORT_COL
        self.sortDir = self.DEFAULT_SORT_DIR
        
        if not hasattr(self, 'upArrowBmp'):
            self.upArrowBmp = self.SmallUpArrow.GetBitmap()
            self.dnArrowBmp = self.SmallDnArrow.GetBitmap()
        
        self.il = wx.ImageList(16, 16)
        self.sortUp = self.il.Add(self.upArrowBmp)
        self.sortDn = self.il.Add(self.dnArrowBmp)
        
        super(PickExamplePage, self).__init__(parent, title)

    
    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        self.itemDataMap = {}
        for itemId, (partNumber, name, hwRev, _hasSn, obj) in self.app.examples.items():
            self.itemDataMap[itemId] = (
                partNumber,
                name,
                str(obj.device.hwType.mcu),
                str(hwRev),
                str(obj.notes))

        self.rebirth = self.data.rebirth
        self.selected = self.data.example
        self.lastBirth = self.data.lastBirth
        self.showAdvanced = self.data.customized
        self.mcu = self.data.mcu

    
    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        if not self.changeExampleCheck.GetValue():
            self.data.example = self.data.lastExample
            self.data.birth = self.data.lastBirth
            self.data.device = self.data.lastDevice
        else:
            selected = self.getSelected()
            self.data.example = selected
            self.data.setBirth(selected)
            if self.data.lastExample != selected or self.data.lastDevice is None:
                self.data.setDevice(selected.device)
        
        self.data.customized = self.customCheck.GetValue()
        
        return True


    @classmethod
    def birthStr(cls, example):
        """ Little helper to create a nice string from a Birth.
            Removes text made redundant by other UI components.
        """
        s = str(example)
        for r in (' (EXAMPLE)', ' (RETIRED)', ' (PREVIEW)'):
            s = s.replace(r, '')
        return s


    def buildUI(self):
        """ Construct the GUI.
        """
        # Contents change slightly if this is a rebirth versus a first-time.
        # Options respectively inapplicable to a birth/rebirth get hidden, plus
        # some cosmetic tweaking.
        if self.rebirth:
            self.addSection("Product Type to Rebirth")
            if self.lastBirth:
                # Show the previous birth product type
                prev = "%s HwRev %s" % (self.data.lastBirth.product, 
                                        self.data.lastDevice.hwRev)
                self.addBoldLabel("(Previous type: ", prev, ")")

        else:
            self.addSection("Product Type to Birth")
        
        self.changeExampleCheck = wx.CheckBox(self, -1, "Change the product type")
        self.changeExampleCheck.SetFont(self.changeExampleCheck.GetFont().Bold())
        self.sizer.Add(self.changeExampleCheck, 0, wx.ALL, 8)
        
        self.list = self.ProductListCtrl(self, -1, size=(600, 400),
             style=(wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SORT_ASCENDING
                    | wx.LC_VRULES | wx.LC_HRULES | wx.LC_SINGLE_SEL))
        self.sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)

        self.list.SetImageList(self.il, wx.IMAGE_LIST_SMALL)
        listmix.ColumnSorterMixin.__init__(self, 5)
        
        self.Bind(wx.EVT_LIST_COL_CLICK, self.OnColClick, self.list)

        _t1, self.selectedText = self.addBoldLabel("Selected: ", " "*30)

        filtersizer = wx.BoxSizer(wx.HORIZONTAL)

        self.showRetiredCheck = wx.CheckBox(self, -1,
            "Show retired product types")
        filtersizer.Add(self.showRetiredCheck, 0)

        self.showPreviewCheck = wx.CheckBox(self, -1,
            "Show prototype product types")
        filtersizer.Add(self.showPreviewCheck, 0, wx.WEST, 8)

        self.sizer.Add(filtersizer, 0, wx.EXPAND | wx.ALL, 8)

        # Filter radio buttons for limiting board revs and type. Rebirth only.
        rbsizer = wx.BoxSizer(wx.VERTICAL)
        self.showSameRB = wx.RadioButton(self, -1,
            "Show examples with the same board type and revision as this unit")
        rbsizer.Add(self.showSameRB, 0, wx.EXPAND | wx.NORTH, 4)

        self.showRevsRB = wx.RadioButton(self, -1,
            "Show all examples with the same board type as this unit")
        rbsizer.Add(self.showRevsRB, 0, wx.EXPAND | wx.NORTH, 4)

        self.showTypesRB = wx.RadioButton(self, -1,
           "Show all board types and revisions")
        rbsizer.Add(self.showTypesRB, 0, wx.EXPAND | wx.NORTH, 4)

        self.sizer.Add(rbsizer, 0, wx.EXPAND | wx.ALL, 8)

        # MCU/CPU type filter. Shown only during birth.
        self.showMcuCheck = wx.CheckBox(self, -1,
            "Show only examples with the same MCU type as this unit")
        self.sizer.Add(self.showMcuCheck, 0, wx.EXPAND | wx.NORTH | wx.WEST, 8)
        self.showMcuText = self.showMcuCheck.GetLabelText()  # for updating text
        
        self.customCheck = wx.CheckBox(self, -1,
           "Show Advanced Options (special/custom hardware, etc.)")
        self.customCheck.SetFont(self.customCheck.GetFont().Bold())
        self.customMsg = wx.StaticText(self, -1, "The next page will show additional options.")
        self.sizer.Add(self.customCheck, 0, wx.ALL, 8)
        self.sizer.Add(self.customMsg, 0, wx.WEST, 24)

        # FUTURE: Remove Hides after fixing advanced options
        self.customCheck.Hide()
        self.customMsg.Hide()

        self.customCheck.SetValue(self.showAdvanced)

        if not self.rebirth:
            # Birth: type/rev filters set to show all, but widgets hidden.
            self.changeExampleCheck.SetValue(True)
            self.changeExampleCheck.Hide()
            self.showMcuCheck.SetValue(True)
            self.showTypesRB.SetValue(True)
            self.showSameRB.Hide()
            self.showTypesRB.Hide()
            self.showRevsRB.Hide()
        else:
            self.list.Enable(False)
            self.showSameRB.SetValue(True)
            self.showSameRB.Enable(False)
            self.showRevsRB.Enable(False)
            self.showRetiredCheck.Enable(False)
            self.showPreviewCheck.Enable(False)
            self.showTypesRB.Enable(False)
            self.showMcuCheck.SetValue(True)
            self.showMcuCheck.Hide()

        self.list.Bind(wx.EVT_LIST_ITEM_SELECTED, self.OnItemSelected)
        self.showSameRB.Bind(wx.EVT_RADIOBUTTON, self.OnFilterCheckChanged)
        self.showRevsRB.Bind(wx.EVT_RADIOBUTTON, self.OnFilterCheckChanged)
        self.showMcuCheck.Bind(wx.EVT_CHECKBOX, self.OnFilterCheckChanged)
        self.showRetiredCheck.Bind(wx.EVT_CHECKBOX, self.OnFilterCheckChanged)
        self.showPreviewCheck.Bind(wx.EVT_CHECKBOX, self.OnFilterCheckChanged)
        self.showTypesRB.Bind(wx.EVT_RADIOBUTTON, self.OnFilterCheckChanged)
        self.customCheck.Bind(wx.EVT_CHECKBOX, self.OnCustomCheck)
        self.changeExampleCheck.Bind(wx.EVT_CHECKBOX, self.OnChangeExampleCheck)


    def _makeListInfo(self, text, image=-1, align=wx.LIST_FORMAT_LEFT):
        info = wx.ListItem()
        info.SetMask(wx.LIST_MASK_TEXT | wx.LIST_MASK_IMAGE | wx.LIST_MASK_FORMAT)
        info.SetImage(image)
        info.SetAlign(align)
        info.SetText(text)
        return info


    def populate(self, sort=True):
        """ Build out the list of "example" Births.
        """
        self.list.ClearAll()
        
        self.list.InsertColumn(0, self._makeListInfo("Part Number"))
        self.list.InsertColumn(1, self._makeListInfo("Name"))
        self.list.InsertColumn(2, self._makeListInfo("MCU"))
        self.list.InsertColumn(3, self._makeListInfo("HwRev"))
        self.list.InsertColumn(4, self._makeListInfo("Notes"))
        showRev = False
        showType = False

        if self.showRevsRB.GetValue():
            showRev = True
        if self.showTypesRB.GetValue():
            showRev = True
            showType = True

        # Force preview/retired if device's exemplar is preview/retired
        if self.data.example:
            if self.data.example.serialNumber == self.data.example.PREVIEW:
                self.showPreviewCheck.SetValue(True)
            elif self.data.example.serialNumber == self.data.example.RETIRED:
                self.showRetiredCheck.SetValue(True)

        showMcu = self.showMcuCheck.GetValue()
        showRetired = self.showRetiredCheck.GetValue()
        showPreview = self.showPreviewCheck.GetValue()

        for itemId, (partNumber, name, mcu, hwRev, notes) in self.itemDataMap.items():
            obj = self.app.examples[itemId][-1]

            mcu = obj.device.hwType.mcu 
            if showMcu and mcu != self.mcu:
                continue
            
            if self.data.device:
                if not showRev:
                    if obj.device.hwType.hwRev != self.data.device.hwType.hwRev:
                        continue
                if not showType:
                    if obj.device.hwType.name != self.data.device.hwType.name:
                        continue

            if obj.serialNumber == obj.RETIRED:
                if not showRetired:
                    continue
                else:
                    name = f"{name} (RETIRED)"
            elif obj.serialNumber == obj.PREVIEW:
                if not showPreview:
                    continue
                else:
                    name = f"{name} (PREVIEW)"

            index = self.list.InsertItem(2**32, partNumber)
            self.list.SetItem(index, self.COL_NAME, name)
            self.list.SetItem(index, self.COL_MCU, mcu)
            self.list.SetItem(index, self.COL_HWREV, hwRev)
            self.list.SetItem(index, self.COL_NOTES, str(obj.notes))
            self.list.SetItemData(index, itemId)

            if obj == self.selected:
                self.list.Select(index)
                self.list.Focus(index)

        self.list.SetColumnWidth(self.COL_PARTNUM, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.COL_NAME, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.COL_MCU, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.COL_HWREV, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.COL_NOTES, 300)

        listmix.ColumnSorterMixin.SortListItems(self, self.sortedCol, self.sortDir)
        
        self.customMsg.Show(self.customCheck.GetValue())
        self.showRevsRB.Show(self.rebirth)
        
        self.showMcuCheck.SetLabelText("%s (%s)" % (self.showMcuText,
                                                    self.mcu))

    
    def sorter(self, key1, key2):
        """ Custom sorter that sorts by part number if sorted column values
            are equal. If sorting by part number, the hardware revision is 
            used as the secondary sort criteria.
        """
        col = self._col
        ascending = self._colSortFlag[col]
        item1 = self.itemDataMap[key1][col]
        item2 = self.itemDataMap[key2][col]

        cmpVal = cmp(item1, item2)

        if cmpVal == 0:
            if col != self.COL_HWREV:
                # If not explicitly sorted by HwRev, HwRev is always shown
                # in descending order
                item1 = self.itemDataMap[key1][self.COL_HWREV]
                item2 = self.itemDataMap[key2][self.COL_HWREV]
                return -cmp(item1, item2)
            else:
                item1 = self.itemDataMap[key1][self.COL_PARTNUM]
                item2 = self.itemDataMap[key2][self.COL_PARTNUM]
                
            cmpVal = cmp(item1, item2)
        
        if ascending:
            return cmpVal
        else:
            return -cmpVal
        
    
    def GetColumnSorter(self):
        """ Used by `ColumnSorterMixin` to get the column sorting function.
        """
        return self.sorter
    
    
    def GetNext(self):
        """ Get the next page. If 'show advanced options' is checked, this
            works as usual; the next page is assumed to be the advanced options
            one. If not checked, it skips to the page after the next.
        """
        if self.customCheck.GetValue():
            return self.next
        if self.next:
            return self.next.GetNext()

        return self.next

    
    def OnFilterCheckChanged(self, _evt):
        """ Event handler called when one of the 'filter' checkboxes is checked
            (show retired, show preview, show same HW, etc.)
        """ 
        self.populate()

    
    def OnChangeExampleCheck(self, evt):
        """ Event handler called when the 'change type' checkbox changes.
        """
        self.populate()
        enable = evt.IsChecked()
        self.list.Enable(enable)
        self.showRevsRB.Enable(enable)
        self.showTypesRB.Enable(enable)
        self.showRetiredCheck.Enable(enable)
        self.showPreviewCheck.Enable(enable)
        self.showSameRB.Enable(enable)


    def getSelected(self):
        """ Get the selected object.
        """
        idx = self.list.GetFirstSelected()
        if idx == -1:
            return None
        
        data = self.app.examples.get(self.list.GetItemData(idx), None)
        if data:
            return data[-1]
    
    
    def GetListCtrl(self):
        """ Required by `ColumnSorterMixin.`
        """
        return self.list


    def GetSortImages(self):
        """ Required by `ColumnSorterMixin` for sort up/down icons.
        """
        return (self.sortDn, self.sortUp)
    
    
    def OnColClick(self, evt):
        """ Required by `ColumnSorterMixin.`
        """
        self.sortedCol = evt.GetColumn()
        self.sortDir = self._colSortFlag[self.sortedCol]
        evt.Skip()


    def OnCustomCheck(self, evt):
        """ Event handler for the 'custom unit' checkbox.
        """
        checked = evt.IsChecked()
        self.showAdvanced = self.data.customized = checked
        self.customMsg.Show(checked)


    def OnItemSelected(self, evt):
        """
        """
        data = self.app.examples[evt.GetData()]
        self.GetParent().showSerialsPage = data[-2]
        if self.selectedText is not None:
            txt = self.birthStr(data[-1])
            self.selectedText.SetLabel(txt)


    def OnPageChanging(self, evt):
        """ Event handler called when leaving the page (but not by canceling).
        """
        # Ensure that an Example has been selected before going to next page
        if evt.GetDirection():
            if self.changeExampleCheck.GetValue() and self.getSelected() is None:
                wx.MessageBox("You must select a device type!", 
                      "Pick Device Type", wx.OK | wx.ICON_ERROR,
                      self.GetParent())
                evt.Veto()
                return
        
        return super(PickExamplePage, self).OnPageChanging(evt)
        

#===============================================================================
# 
#===============================================================================

class SensorSerialNumPage(PickExamplePage):
    """ Wizard page that has fields for entering serial numbers for all Sensors
        that require them.
    """
    DEFAULT_TITLE = "Sensor Serial Numbers"

    NAME_COLUMN = 0
    ID_COLUMN = 1
    SN_COLUMN = 2

    DEFAULT_SORT_COL = ID_COLUMN
    DEFAULT_SORT_DIR = 1
    
    #===========================================================================
    # 
    #===========================================================================
    
    class SNListCtrl(wx.ListCtrl,
                     listmix.ListCtrlAutoWidthMixin,
                     listmix.TextEditMixin):
        """ Required to create a sortable list.
        """
        def __init__(self, *args, **kwargs):
            """
            """
            wx.ListCtrl.__init__(self, *args, **kwargs)
            listmix.ListCtrlAutoWidthMixin.__init__(self) 
            listmix.TextEditMixin.__init__(self) 

        #     self.Bind(wx.EVT_LIST_ITEM_FOCUSED, self.OnItemSelected)
        #
        #
        # def OnItemSelected(self, evt):
        #     """ Handle item selection events. Automatically starts editing.
        #     """
        #     idx = evt.GetIndex()
        #     if idx >= 0:
        #         self.OpenEditor(2, idx)
        #

        # def OpenEditor(self, col, row):
        #     """ Start editing a cell.
        #     """
        #     self.curRow = row
        #     self.curCol = col
        #
        #     # I shouldn't have to do this, but there's a bug in TextEditMixin,
        #     # in which it doesn't do this initialization until after a click.
        #     self.col_locs = [0]
        #     loc = 0
        #     for n in range(self.GetColumnCount()):
        #         loc = loc + self.GetColumnWidth(n)
        #         self.col_locs.append(loc)
        #
        #     super(SensorSerialNumPage.SNListCtrl, self).OpenEditor(col, row)
        #
        #
        # def OnChar(self, evt):
        #     """ Handle key press event when editing. Does field changing with
        #         tab and enter.
        #     """
        #     key = evt.GetKeyCode()
        #     if key == wx.WXK_TAB or key == wx.WXK_RETURN:
        #         if wx.GetKeyState(wx.WXK_SHIFT):
        #             if self.curRow > 0:
        #                 self.CloseEditor()
        #                 self.OpenEditor(self.curCol, self.curRow-1)
        #                 return
        #         elif self.curRow < self.GetItemCount()-1:
        #             self.CloseEditor()
        #             self.OpenEditor(self.curCol, self.curRow+1)
        #             return
        #
        #     super(SensorSerialNumPage.SNListCtrl, self).OnChar(evt)

    def SetStringItem(self, index, col, data):
        if col != 2:
            return
        wx.ListCtrl.SetItem(self, index, col, data)

    #===========================================================================
    # 
    #===========================================================================

    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        self.showAdvanced = self.data.customized
        
        if self.data.device is not None:
            self.itemDataMap = self.data.analogSensors
        else:
            self.itemDataMap = {}
    
        
    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        serials = {}
        for i in range(self.list.GetItemCount()):
            col = self.list.GetItem(i, self.SN_COLUMN)
            itemId = col.GetData()
            sn = col.GetText().strip()
            if not sn:
                return False
            # FUTURE: serial number validation (regex?)
            serials[itemId] = sn

        self.data.sensorSerials.update(serials)
        return True


    def buildUI(self):
        """ Construct the GUI.
        """
        self.list = self.SNListCtrl(self, -1, size=(600, 400),
             style=(wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SORT_ASCENDING
                    | wx.LC_VRULES | wx.LC_HRULES | wx.LC_SINGLE_SEL 
                    | wx.LC_EDIT_LABELS))
        self.sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)

        self.list.SetImageList(self.il, wx.IMAGE_LIST_SMALL)
        listmix.ColumnSorterMixin.__init__(self, 3)
        
        self.Bind(wx.EVT_LIST_BEGIN_LABEL_EDIT, self.OnBeginEdit)
        self.Bind(wx.EVT_LIST_END_LABEL_EDIT, self.OnEndEdit)
 
    
    def populate(self, sort=True):
        """ Build out the list of Sensors requiring serial numbers.
        """
        self.list.ClearAll()
        
        self.list.InsertColumn(self.NAME_COLUMN, self._makeListInfo("Name"))
        self.list.InsertColumn(self.ID_COLUMN, self._makeListInfo("ID", align=wx.LIST_FORMAT_RIGHT))
        self.list.InsertColumn(self.SN_COLUMN, self._makeListInfo("Serial Number"))

        for itemId, (name, sensorId, sn, _sensor) in self.itemDataMap.items():
            if "CommunicationWiFi" in name:
                continue

            index = self.list.InsertItem(2**32, name)
            self.list.SetItem(index, self.ID_COLUMN, str(sensorId or ""))
            self.list.SetItem(index, self.SN_COLUMN, str(sn or ""))
            self.list.SetItemData(index, itemId)
            
        self.list.SetColumnWidth(self.NAME_COLUMN, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.ID_COLUMN, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(self.SN_COLUMN, wx.LIST_AUTOSIZE)

        listmix.ColumnSorterMixin.SortListItems(self, self.sortedCol, self.sortDir)

        # XXX: Fails in new system
        # if len(self.itemDataMap) > 0:
        #     self.list.Select(0)
        #     self.list.OpenEditor(self.SN_COLUMN, 0)


    def OnBeginEdit(self, evt):
        """ Event handler called when editing a list item starts. Makes only
            the serial number column editable.
        """
        # XXX: This worked in old system (Py2.7, wxPython 3.x), but doesn't work in
        #  Py3.9, wxPython 4.x; column is always 0! Only applicable to 'col events' now?
        # item = evt.GetItem()
        # col = item.GetColumn()
        # if col != self.SN_COLUMN:
        #     evt.Veto()
        #     return
        
        evt.Skip()


    def OnEndEdit(self, evt):
        """ Event handler called when editing a list item finishes.
        """
        # Prevent editing of anything but SN column. Hack; didn't work in `OnBeginEdit()`.
        if evt.Column != self.SN_COLUMN:
            evt.Veto()
            return

        # FUTURE: Validate serial number, veto event if format is bad
        evt.Skip()
    

    def sorter(self, key1, key2):
        """ Custom sorter that sorts by Sensor ID if sorted column values
            are equal.
        """
        col = self._col
        ascending = self._colSortFlag[col]
        item1 = self.itemDataMap[key1][col]
        item2 = self.itemDataMap[key2][col]
        
        cmpVal = cmp(item1, item2)

        if cmpVal == 0:
            if col != self.ID_COLUMN:
                # If not explicitly sorted by HwRev, HwRev is always shown
                # in descending order
                item1 = self.itemDataMap[key1][1]
                item2 = self.itemDataMap[key2][1]
                return cmp(item1, item2)
            else:
                item1 = self.itemDataMap[key1][0]
                item2 = self.itemDataMap[key2][0]
                
            cmpVal = cmp(item1, item2)
        
        if ascending:
            return cmpVal
        else:
            return -cmpVal
        
    
    def GetColumnSorter(self):
        """ Used by `ColumnSorterMixin` to get the column sorting function.
        """
        return self.sorter
    
    
    def GetNext(self):
        return self.next


    def GetPrev(self):
        """ Get the previous page. Skips the 'advanced options' page if the
            corresponding checkbox isn't checked.
        """
        # If advanced options weren't shown, skip to immediately previous page.
        if not self.data.customized and self.prev is not None:
            return self.prev.GetPrev()

        return self.prev

    
    def OnPageChanging(self, evt):
        """ Event handler called when leaving the page (but not by canceling).
        """
        # If moving to the next page, update parent data based on UI input.
        if not evt.GetDirection():
            evt.Skip()
            return
        
        if self.updateData():
            evt.Skip()
            return
        
        wx.MessageBox("All sensors require serial numbers", 
                      "Invalid Serial Number", wx.OK | wx.ICON_ERROR,
                      self.GetParent())
        evt.Veto()


#===============================================================================
# 
#===============================================================================

class DeviceOptionsPage(PickExamplePage):
    """ Wizard page for editing `Device` parameters (shown optionally).
    """
    DEFAULT_TITLE = "Advanced Options (Hardware and FW)"

    #===========================================================================
    # 
    #===========================================================================
    
    class CheckListCtrl(wx.ListCtrl, listmix.CheckListCtrlMixin,
                        listmix.ListCtrlAutoWidthMixin):
        """ Required to create a sortable list with checkboxes.
        """
        
        def __init__(self, *args, **kwargs):
            wx.ListCtrl.__init__(self, *args, **kwargs)
            listmix.CheckListCtrlMixin.__init__(self)
            listmix.ListCtrlAutoWidthMixin.__init__(self)

            self.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.OnItemActivated)
    
    
        def OnItemActivated(self, evt):
            self.ToggleItem(evt.m_itemIndex)


    #===========================================================================
    # 
    #===========================================================================

    def __init__(self, parent, title=None):
        """ Constructor.
        """
        self.sortedCol = self.DEFAULT_SORT_COL
        self.sortDir = self.DEFAULT_SORT_DIR
        
        if not hasattr(self, 'upArrowBmp'):
            self.upArrowBmp = self.SmallUpArrow.GetBitmap()
            self.dnArrowBmp = self.SmallDnArrow.GetBitmap()
        
        super(DeviceOptionsPage, self).__init__(parent, title)


    def sorter(self, key1, key2):
        """ Custom sorter that sorts by part number if sorted column values
            are equal. If sorting by part number, the hardware revision is
            used as the secondary sort criteria.
        """
        col = self._col
        ascending = self._colSortFlag[col]
        item1 = self.itemDataMap[key1][col]
        item2 = self.itemDataMap[key2][col]

        cmpVal = cmp(item1, item2)

        if ascending:
            return cmpVal
        else:
            return -cmpVal



    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        self.hwTypeMap = self.app.hwTypes
        self.hwTypes = list(self.hwTypeMap.keys())
        self.selectedType = self.data.hwType

        self.batTypeMap = self.app.batteries
        self.batTypes = list(self.batTypeMap.keys())
        self.selectedBat = self.data.battery

        self.itemDataMap = self.app.digitalSensors
        self.presentSensors = self.data.getDigitalPeripherals()


    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        hwTypeName = self.hwTypeField.GetStringSelection()
        self.data.hwType = self.hwTypeMap.get(hwTypeName)

        batTypeName = self.batteryField.GetStringSelection()
        self.data.battery = self.batTypeMap.get(batTypeName)

        del self.data.digitalSensors[:]
        for i in range(self.list.GetItemCount()):
            if self.list.IsChecked(i):
                d = self.itemDataMap[self.list.GetItemData(i)]
                self.data.digitalSensors.append(d[-1])
        
        self.data.deviceNotes = self.notesField.GetValue()
        
        return True


    def buildUI(self):
        """ Construct the GUI.
        """
        #=======================================================================
        self.addSection("Device Type")
        
        tpane = SC.SizedPanel(self, -1)
        tpane.SetSizerType("form")
        
        wx.StaticText(tpane, -1, 'Board Type:').SetSizerProps(valign="center")
        self.hwTypeField = wx.Choice(tpane, -1)
        self.hwTypeField.SetSizerProps(valign="center", expand=True)
        
        wx.StaticText(tpane, -1, 'Custom HW ID:').SetSizerProps(valign="center")
        self.customHwField = wx.ComboBox(tpane, -1)
        self.customHwField.SetSizerProps(valign="center", expand=True)

        self.sizer.Add(tpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        #=======================================================================
        self.addSection("Battery")

        bpane = SC.SizedPanel(self, -1)
        bpane.SetSizerType("form")

        wx.StaticText(bpane, -1, 'Battery Type:').SetSizerProps(valign="center")
        self.batteryField = wx.Choice(bpane, -1)
        self.batteryField.SetSizerProps(valign="center", expand=True)

        self.sizer.Add(bpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)

        #=======================================================================
        self.addSection("Digital Sensors/Peripherals")
        self.buildSensorList()
        
        #=======================================================================
        self.addSection("Device Notes")
        lbl = wx.StaticText(self, -1, "Notes about the hardware itself, not this specific birthing.")
        self.sizer.Add(lbl, 0, wx.EAST | wx.WEST, 16)
        self.notesField = wx.TextCtrl(self, -1, size=(-1, 64),
                                      style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
        self.sizer.Add(self.notesField, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        

    def buildSensorList(self):
        """ Construct the GUI.
        """
        self.itemDataMap = {}  # required by ColumnSorterMixin

        self.list = self.CheckListCtrl(self, -1, size=(600, 400),
             style=(wx.LC_REPORT | wx.BORDER_SUNKEN | wx.LC_SORT_ASCENDING
                    | wx.LC_VRULES | wx.LC_HRULES | wx.LC_SINGLE_SEL))
        self.sizer.Add(self.list, 1, wx.EXPAND | wx.ALL, 5)

        # Checkboxes are actually in the ImageList, added by the mixin
        self.il = self.list.GetImageList(wx.IMAGE_LIST_SMALL)
        self.sortUp = self.il.Add(self.upArrowBmp)
        self.sortDn = self.il.Add(self.dnArrowBmp)

        self.list.SetImageList(self.il, wx.IMAGE_LIST_SMALL)
        listmix.ColumnSorterMixin.__init__(self, 3)
        
        self.Bind(wx.EVT_LIST_COL_CLICK, self.OnColClick, self.list)


    def populateList(self):
        """ Build out the list of digital sensors/peripherals.
        """
        self.list.ClearAll()
        
        self.list.InsertColumn(0, self._makeListInfo("Part Number"))
        self.list.InsertColumn(1, self._makeListInfo("Description"))
        self.list.InsertColumn(2, self._makeListInfo("Manufacturer"))

        for itemId, data in self.itemDataMap.items():
            name, desc, manufacturer, _sensor = data
            
            index = self.list.InsertItem(2**32, name)
            self.list.SetItem(index, 1, desc)
            self.list.SetItem(index, 2, manufacturer)
            self.list.SetItemData(index, itemId)

            if itemId in self.presentSensors:
                self.list.CheckItem(index)

        self.list.SetColumnWidth(0, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(1, wx.LIST_AUTOSIZE)
        self.list.SetColumnWidth(2, wx.LIST_AUTOSIZE)

        listmix.ColumnSorterMixin.SortListItems(self, self.sortedCol, self.sortDir)
    
    
    def populate(self, sort=True):
        """ Fill out the UI with (current) data from the parent.
        """
        self.hwTypeField.SetItems(self.hwTypes)
        t = str(self.selectedType)
        if t in self.hwTypes:
            self.hwTypeField.SetSelection(self.hwTypes.index(t))
        
        self.batteryField.SetItems(self.batTypes)
        b = str(self.selectedBat)
        if b in self.batTypes:
            self.batteryField.SetSelection(self.batTypes.index(b))

        self.populateList()

    
    def GetNext(self):
        """ Get the next page. If there are no analog sensors (the next page),
            skip to the final page.
        """
        if self.next and not self.GetParent().showSerialsPage:
            return self.next.GetNext()
        return self.next


    def OnPageShown(self, evt):
        """ Event handler called when a page is shown. Updates the widgets.
        """
        TitledPage.OnPageShown(self, evt)


    def OnPageChanging(self, evt):
        """ Event handler called when leaving the page (but not by canceling).
        """
        return super(PickExamplePage, self).OnPageChanging(evt)
    
    
#===============================================================================
# 
#===============================================================================

class FirmwareWidget(SC.SizedPanel):
    """ Single composite widget for selecting bootloader or firmware, with
        options for no change, a known version, or a specific binary file.
    """
    def __init__(self, *args, **kwargs):
        """ Constructor. Takes standard `SizedPanel` arguments, plus:
        
            @keyword startDirectory: The initial path for browsing binaries.
            @keyword type: A string, with the type of binary (firmware, etc.)
        """
        self.type = kwargs.pop('type', 'firmware')
        self.new = kwargs.pop('new', False)
        self.choices = kwargs.pop('choices', {})
        self.history = kwargs.pop('history', [])
        self.rev = kwargs.pop('rev', 0)
        self.lastRev = kwargs.pop('lastRev', None)
        self.actualRev = kwargs.pop('actualRev', None)
        self.filename = kwargs.pop('filename', "")
        
        startDirectory = kwargs.pop('startDirectory', '')
        buttonText = kwargs.pop('buttonText', "Browse")
        
        super(FirmwareWidget, self).__init__(*args, **kwargs)
        self.SetSizerType("form")
        
        self.noChangeBtn = wx.RadioButton(self, -1, "Keep Current",
                                          style=wx.RB_GROUP)
        self.noChangeBtn.SetSizerProps(valign="center")
        self.previousText = wx.StaticText(self, -1, " "*30)
        self.previousText.SetSizerProps(valign="center", expand=True, 
                                        border=(['left'], 8))
        
        self.newBtn = wx.RadioButton(self, -1, "Replace With:")
        self.newBtn.SetSizerProps(valign="center")
        self.newField = wx.Choice(self, -1)
        self.newField.SetSizerProps(valign="center", expand=True, 
                                    border=(['left'], 8))
        
        self.fileBtn = wx.RadioButton(self, -1, "Upload File:")
        self.fileBtn.SetSizerProps(valign="center")
        self.fileField = FB.FileBrowseButtonWithHistory(self, -1,
            labelText="", buttonText=buttonText, fileMask="*.bin", 
            startDirectory=startDirectory, changeCallback=self.OnFilePicked,
            dialogTitle="Choose a %s file" % self.type)
        self.fileField.SetSizerProps(valign="center", expand=True)
        
        self.Bind(wx.EVT_RADIOBUTTON, self.OnRadioButton)

    
    def populate(self, new=None, rev=None, choices=None, filename=None,
                 history=None, lastRev=None, actualRev=None):
        """
            @param new: Has a new version been selected?
            @param rev: Selected revision number/ID
            @param choices: A dictionary of versions, keyed by DB value.
            @param filename: The firmware/bootloader binary file (if
                non-standard).
            @param history: A list of previously-used binary filenames.
            @param lastRev: The previous revision from the DB (if any).
            @param actualRev:  The device-reported revision (if any).
        """
        self.new = new if new is not None else self.new
        self.history = history or self.history
        self.filename = filename or self.filename
        self.rev = rev or self.rev
        self.choices = choices or self.choices
        self.lastRev = lastRev or self.lastRev
        self.actualRev = actualRev or self.actualRev
        
        if self.actualRev:
            msg = "%s (reported by device)" % self.actualRev
        elif self.lastRev:
            msg = "%s (according to database)" % self.lastRev
        else:
            msg = ""
        
        self.previousText.SetLabel(msg)
        
        self.fileField.SetHistory(self.history)
        self.fileField.SetValue(self.filename)
        
        self.newField.SetItems(list(self.choices.values()))
        if self.choices:
            self.newField.SetSelection(0)

        if not self.choices:
            self.newBtn.Enable(False)

        elif self.rev in self.choices:
            # Known version 
            idx = list(self.choices.keys()).index(self.rev)
            self.newField.SetSelection(idx)
            self.newBtn.SetValue(True)
        
        if self.new:
            if self.filename:
                # A specific alternate file to upload
                self.fileBtn.SetValue(True)
            else:
                self.newBtn.SetValue(True)
        else:
            self.noChangeBtn.SetValue(True)
        
        self.fileField.Enable(self.fileBtn.GetValue())
        self.newField.Enable(self.newBtn.GetValue())
        


    def validate(self):
        """
        """
        if self.fileBtn.GetValue() and not os.path.isfile(self.filename):
            msg = ("The specified %s file could not be found!\n\nFilename: '%s'"
                   % (self.type, self.filename))
            wx.MessageBox(msg, "%s File Not Found" % self.type.capitalize(), 
                          wx.OK | wx.ICON_ERROR, self.GetParent())
            return False
        
        # FUTURE: Additional validation (correct MCU type, maybe)
        return True
        

    def GetValue(self):
        """ Get the selected bootloader/firmware version or filename.
            @return: A tuple containing:
                * New FW/BL selected (bool)
                * Selected revision (a key from `choices`)
                * Selected filename (string)
        """
        self.new = False
        self.filename = self.fileField.GetValue().strip()

        if self.newBtn.GetValue():
            idx = self.newField.GetSelection()
            if idx > -1:
                self.new = True
                self.rev = list(self.choices.keys())[idx]
        elif self.fileBtn.GetValue():
            f = self.fileField.GetValue().strip()
            if f:
                if f in self.history:
                    self.history.remove(f)
                self.history.insert(0, f)
                self.new = True
                self.filename = f

        return self.new, self.rev, self.filename


    def OnFilePicked(self, evt):
        """
        """
        self.filename = evt.GetString()


    def OnRadioButton(self, evt):
        """ Handle any radio button selection.
        """
        rb = evt.GetEventObject()
        self.fileField.Enable(rb == self.fileBtn)
        self.newField.Enable(rb == self.newBtn)

        
#===============================================================================

class FirmwarePage(TitledPage):
    """ Wizard page for selecting firmware and/or bootloader. Selection can be
        by revision number/ID or a specific file to upload.
    """
    DEFAULT_TITLE = "Firmware and Bootloader"
    
    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        self.newFirmware = self.data.newFirmware or not self.data.rebirth
        self.fwRev = self.data.fwRev
        self.firmware = self.data.firmware or ""
        self.fwVersions = self.app.getFirmware(self.data)
        self.fwHistory = self.app.prefs.get('fwHistory')
        
        self.actualFwRev = self.data.actualFwRev
        self.lastFwRev = self.data.lastFwRev
        
        self.newBootloader = self.data.newBootloader
        self.bootRev = self.data.bootRev
        self.bootloader = self.data.bootloader or ""
        self.bootVersions = self.app.getBootloaders(self.data)
        self.bootHistory = self.app.prefs.get('bootloaderHistory')

        self.actualBootRev = self.data.actualBootRev
        self.lastBootRev = self.data.lastBootRev 
        
    
    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        #=======================================================================
        fwValue = self.fwWidget.GetValue()
        self.newFirmware, self.fwRev, self.firmware = fwValue
        self.data.newFirmware, self.data.fwRev, self.data.firmware = fwValue

        logger.info('fwWidget: {}'.format(fwValue))

        #=======================================================================
        blValue = self.bootWidget.GetValue()
        self.newBootloader, self.bootRev, self.bootloader = blValue
        self.data.newBootloader, self.data.bootRev, self.data.bootloader = blValue

        return True
    

    def buildUI(self):
        """ Construct the GUI.
        """
        #=======================================================================
        self.addSection("Firmware")

        self.fwWidget = FirmwareWidget(self, -1, type="firmware",
                                       startDirectory=paths.FW_LOCATION)
        self.sizer.Add(self.fwWidget, 0, wx.EXPAND | wx.EAST, 16)
        
        #=======================================================================
        self.addSection("Bootloader")

        self.bootWidget = FirmwareWidget(self, -1, type="bootloader",
                                         startDirectory=paths.BL_LOCATION)
        self.sizer.Add(self.bootWidget, 0, wx.EXPAND | wx.EAST, 16)

    
    def populate(self):
        """ Fill out the UI with (current) data from the parent.
        """
        self.fwWidget.populate(new=self.newFirmware, rev=self.fwRev, 
                               choices=self.fwVersions, filename=self.firmware,
                               history=self.fwHistory, lastRev=self.lastFwRev,
                               actualRev=self.actualFwRev)

        self.bootWidget.populate(new=self.newBootloader, rev=self.bootRev,
                                 choices=self.bootVersions, 
                                 filename=self.bootloader,
                                 history=self.bootHistory, 
                                 lastRev=self.lastBootRev,
                                 actualRev=self.actualBootRev)

    
    def OnPageChanging(self, evt):
        """ Event handler called when leaving the page (but not by canceling).
        """
        # If moving to the next page, update parent data based on UI input.
        if evt.GetDirection():
            if not self.bootWidget.validate():
                evt.Veto()
                return
            if not self.fwWidget.validate():
                evt.Veto()
                return
                
            self.updateData()

        evt.Skip()


#===============================================================================
# 
#===============================================================================

class FinalPage(TitledPage):
    """ The final Birth Wizard page. Summarizes what's going to happen if the
        user clicks "Finish."
        
        TODO: Finish final page display!
    """
    DEFAULT_TITLE = "Final Page"

    
    def __init__(self, parent, title=None):
        self.editedName = False
        self.volumeName = ""
        self.editedSku = False
        self.sku = ""
        TitledPage.__init__(self, parent, title=title)


    def print(self, *args):
        """ Convenience hack for populating the summary page.
            Will probably get removed.
        """
        msg = ' '.join(map(str, args))
        self.summary.write(msg + '\n')


    def getData(self):
        """ Retrieve data from the parent. Called before `buildUI()` and every
            time the page is advanced to.
        """
        # Printing label is default for new devices or devices with recycled MCU
        self.printLabel = self.data.resetCreationDate or not self.data.rebirth
        if not self.editedSku and self.data.birth is not None:
            if self.data.resetCreationDate:
                # Recycled MCU, ignore SKU from original device birth.
                self.sku = self.data.birth.partNumber
            else:
                self.sku = self.data.birth.getSKU()
            
        if not self.editedName:
            self.volumeName = self.data.volumeName
            if not self.volumeName:
                self.volumeName = self.data.getVolumeName()

        self.configFiles = self.app.configs[:]
        self.configNames = [os.path.basename(f) for f in self.configFiles]
        

    def updateData(self):
        """ Update the parent's info based on the page contents.
        
            @return: `True` if the data was valid and updated.
        """
        parent = self.GetParent()
        self.volumeName = self.volNameField.GetValue().strip()
        self.data.volumeName = self.volumeName
        self.data.sku = self.skuField.GetValue()
        parent.makeDirs = self.dirsCheck.GetValue()
        parent.copyContent = self.copyCheck.GetValue()
        parent.doDatabaseUpdate = self.updateDbCheck.GetValue()
        parent.doBirth = self.doBirthCheck.GetValue()
        parent.keepOldCal = self.keepCalCheck.GetValue()
        parent.configDevice = self.configCheck.GetValue()
        parent.printLabel = self.printCheck.GetValue()
 
        return True
        
 
    def buildUI(self):
        """ Construct the GUI.
        """
        parent = self.GetParent()
        
        self.addSection('Summary')
        self.summary = wx.TextCtrl(self, -1, "", 
                                   style=wx.TE_READONLY | wx.TE_MULTILINE)
        self.sizer.Add(self.summary, 1, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        self.addSection('Final Birth Options')
        
        namepane = SC.SizedPanel(self, -1)
        namepane.SetSizerType("form")
        
        tts = "Leave blank to leave the device's volume name unchanged."
        label = wx.StaticText(namepane, -1, 'Disk Volume Name:')
        label.SetSizerProps(valign="center")
        label.SetToolTip(tts)
        self.volNameField = wx.TextCtrl(namepane, -1, self.data.getVolumeName())
        self.volNameField.SetSizerProps(valign="center", expand=True)
        self.volNameField.SetToolTip(tts)
        self.volNameField.Bind(wx.EVT_CHAR, self.OnNameCharacter)
        self.sizer.Add(namepane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        checkPanel = wx.Panel(self, -1)
        checkSizer = wx.BoxSizer(wx.VERTICAL)
        checkPanel.SetSizer(checkSizer)
        
        # Convenience function for adding checkboxes. Saves several lines.
        def _cb(label, val, tooltip):
            check = wx.CheckBox(checkPanel, -1, label)
            check.SetValue(val)
            check.SetToolTip(tooltip)
            checkSizer.Add(check, 1, wx.EXPAND | wx.ALL, 2)
            return check
        
        self.dirsCheck = _cb("Create content directories", parent.makeDirs,
                     "Create empty directories for SYSTEM, DOCUMENTATION, etc.")
        self.copyCheck = _cb("Copy content to recorder", parent.copyContent,
                     "Copy content (Slam Stick Lab, documentation, "
                     "etc.) to device after birth.")
        self.configCheck = _cb("Configure recorder for calibration", 
                     parent.configDevice,
                     "Set up the device to record on the shaker.")
        self.configCheck.Bind(wx.EVT_CHECKBOX, self.OnSetConfigCheck)
        self.keepCalCheck = _cb("Keep Existing Calibration", parent.keepOldCal,
                    "If checked, keep previously-generated calibration data. "
                    "If unchecked, upload default values.")
        self.updateDbCheck = _cb("Update the Database", parent.doDatabaseUpdate,
                     "Write the birth to the database. "
                     "Should almost always be checked!")
        self.doBirthCheck = _cb("Write device Manifest", parent.doBirth,
                     "Write birth data to the device. "
                     "Should almost always be checked!")

        checkSizer.Add(wx.StaticText(self, -1, ""), 0)        
        self.sizer.Add(checkPanel, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)
        
        configpane = SC.SizedPanel(self, -1)
        configpane.SetSizerType("form")
        self.printCheck = wx.CheckBox(configpane, -1, "Print SKU label:")
        self.skuField = wx.TextCtrl(configpane, -1, self.sku)
        self.printCheck.SetToolTip("Print a label with the SKU and serial number.")
        self.printCheck.SetSizerProps(valign="center")
        self.skuField.SetSizerProps(valign="center", expand=True)
        self.printCheck.Bind(wx.EVT_CHECKBOX, self.OnPrintCheck)
        self.skuField.Bind(wx.EVT_CHAR, self.OnSkuCharacter)

        self.copyConfigCheck = wx.CheckBox(configpane, -1, "Install config file:")
        self.copyConfigCheck.SetSizerProps(valign="center")
        self.copyConfigField = wx.Choice(configpane, choices=self.configNames)
        self.copyConfigField.SetSizerProps(valign="center", expand=True)
        self.copyConfigCheck.Bind(wx.EVT_CHECKBOX, self.OnCopyConfigCheck)
        if self.configNames:
            self.copyConfigField.SetSelection(0)
        self.sizer.Add(configpane, 0, wx.EXPAND | wx.EAST | wx.WEST, 16)

        hasOldCal =  legacy.findOldCal(self.data.chipId) is not None
        self.keepCalCheck.Show(hasOldCal)
        self.keepCalCheck.SetValue(hasOldCal)
        self.copyConfigField.Enable(False)
        
 
 
    def populate(self):
        """ Fill out the UI with (current) data from the parent.
        """
        encName = dict(models.Device.ENCLOSURE_TYPES).get(self.data.enclosure)
        self.summary.SetValue('')
        self.print("Final page")
        self.print("This text is temporary. Contents will change.")
        self.print("-"*40)
        self.print("self.data.example: %r" % self.data.example)
        self.print("self.data.birth: %r" % self.data.birth)
        self.print("self.data.device: %r" % self.data.device)
        self.print("self.data.getSensors: {}".format(self.data.getSensors()))
        self.print("self.data.sensorSerials: {}".format(self.data.sensorSerials))
        if self.data.lastDevice is not None:
            sensUnchanged, sens = self.data.lastDevice.compareSensors(self.data.device)
            if not sensUnchanged:
                self.print(" Changed sensors:\n%s" % pprint.pformat(sens, 4))
            else:
                self.print(" Sensor loadout unchanged")
        self.print("-"*40)
        self.print("self.data.newFirmware: %r" % (self.data.newFirmware))
        self.print("self.data.fwRev: %r" % (self.data.fwRev))
        self.print("self.data.firmware: %r" % (self.data.firmware))
        self.print("self.data.actualFwRev: %r" % (self.data.actualFwRev))
        self.print("self.data.newBootloader: %r" % (self.data.newBootloader))
        self.print("self.data.bootRev: %r" % (self.data.bootRev))
        self.print("self.data.bootloader: %r" % (self.data.bootloader))
        self.print("self.data.actualBootRev: %r" % (self.data.actualBootRev))
        self.print("self.data.enclosure: %r (%r)" % (encName, self.data.enclosure))
        self.print("self.data.capacity: %r" % (self.data.capacity))

        self.volNameField.SetValue(self.volumeName)

        parent = self.GetParent()
        self.updateDbCheck.SetValue(parent.doDatabaseUpdate)
        self.doBirthCheck.SetValue(parent.doBirth)
        self.keepCalCheck.SetValue(parent.keepOldCal)
        self.configCheck.SetValue(parent.configDevice)
        self.copyCheck.SetValue(parent.copyContent)
        
        self.printCheck.SetValue(self.printLabel)
#         self.skuLabel.Enable(self.printLabel)
        self.skuField.Enable(self.printLabel)


    def OnSetConfigCheck(self, _evt):
        checked = self.configCheck.GetValue()
        if checked:
            self.copyConfigCheck.SetValue(False)

    
    def OnCopyConfigCheck(self, _evt):
        checked = self.copyConfigCheck.GetValue()
        if checked:
            self.configCheck.SetValue(False)
            idx = self.copyConfigField.GetSelection()
            if idx >= 0:
                self.GetParent().config = self.configFiles[idx]
            else:
                self.GetParent().config = None
        else:
            self.GetParent().config = None
        self.copyConfigField.Enable(checked)


    def OnPrintCheck(self, evt):
        checked = evt.IsChecked()
#         self.skuLabel.Enable(checked)
        self.skuField.Enable(checked)


    def OnNameCharacter(self, evt):
        kc = evt.GetKeyCode()
        if 31 < kc < 127:
            self.editedName = True
        evt.Skip()


    def OnSkuCharacter(self, evt):
        kc = evt.GetKeyCode()
        if 31 < kc < 127:
            self.editedSku = True
        evt.Skip()


    def GetPrev(self):
        """ Get the previous page. Returns whatever page was seen last.
        """
        return self.GetParent().lastSeenPage


    def OnPageChanging(self, evt):
        """
        """
        if self.editedName:
            self.volumeName = self.volNameField.GetValue().strip()
        
        if not evt.GetDirection():
            # Going backwards
            evt.Skip()
            return

        # Make sure user meant to use weird options.
        checks = ((self.doBirthCheck.GetValue()) |
                  (self.updateDbCheck.GetValue() << 1))
                
        if checks != 3:
            msg = (('"Update the Database" and "Write to Manifest" are both '
                    'unselected!\n\n'
                    "Neither the device's manifest nor the database will be "
                    "updated. Only the firmware and/or bootloader will be "
                    "uploaded (if selected on the previous page)."),
                   ('"Update the Database" not selected!\n\n'
                    "The device will get birthed, but no record kept."),
                   ('"Write to Manifest" not selected!\n\n'
                    'The database will be updated, but the device will keep '
                    'its existing Manifest, unmodified.'))
            
            m = msg[checks] + "\n\nAre you sure you want to continue?"
            q = wx.MessageBox(m, "Confirmation", 
                              wx.YES_NO | wx.NO_DEFAULT | wx.ICON_WARNING,
                              self.GetParent())
            if q == wx.NO:
                evt.Veto()
                return

        if not self.updateData():
            logger.info('%s updateData() failed; page change vetoed' %
                        self.__class__.__name__)
            evt.Veto()
            return

        evt.Skip()


#===============================================================================
# 
#===============================================================================

class BirthWizard(wx.adv.Wizard):
    """ Birthing Wizard! Container for the individual Wizard pages; those do
        the real work.
    """

    def __init__(self, data, title="Birther Wizard"):
        """ Constructor.
        
            @param data: A `BirthData` instance, which is either mostly blank
                or contains data from the device's previous birth.
            @param title: Dialog title.
        """
        self.data = data
        
        # Variables to indicate what to do after the successful completion of
        # the Wizard: update the database with Wizard info, and/or do the
        # actual birth (writing manifest, etc.). There are cases in which the
        # user might want to do one and not the other.
        self.makeDirs = True
        self.copyContent = False
        self.doDatabaseUpdate = True
        self.doBirth = True
        self.keepOldCal = False
        self.configDevice = True
        self.printLabel = True
        self.config = None
        
        self.showSerialsPage = True
        
        img = wx.Image(os.path.join(paths.RESOURCES_PATH, 'birthomatic.png'), wx.BITMAP_TYPE_PNG)
        bg = wx.Colour(img.GetRed(1, 1), img.GetGreen(1, 1), img.GetBlue(1, 1))
        super(BirthWizard, self).__init__(None, -1, title, img.ConvertToBitmap())
        self.SetBitmapPlacement(wx.adv.WIZARD_VALIGN_BOTTOM)
        self.SetBitmapBackgroundColour(bg)

        oldCursor = self.GetCursor()
        wx.SetCursor(wx.Cursor(wx.CURSOR_WAIT))

        self.addPages(BatchAndSNPage(self),
                      PickExamplePage(self),
                      DeviceOptionsPage(self),
                      SensorSerialNumPage(self),
                      FirmwarePage(self),
                      FinalPage(self))
        
        self.Bind(wx.adv.EVT_WIZARD_PAGE_CHANGING, self.OnPageChanging)
        self.Bind(wx.adv.EVT_WIZARD_CANCEL, self.OnCancel)

        wx.SetCursor(oldCursor)
    
    
    def addPages(self, *pages):
        """ Convenience function to do the busy work of adding multiple pages.
        """
        self.pages = pages
        self.lastSeenPage = None
        self.firstPage = pages[0]
        self.lastPage = pages[-1]
        
        prev = None
        for p in pages:
            if prev is not None:
                prev.SetNext(p)
                p.SetPrev(prev)
            prev = p

        self.GetPageAreaSizer().Add(self.pages[0])


    def OnPageChanging(self, evt):
        """ Handle a page changing; keep track of last seen. For final page.
        """
        self.lastSeenPage = evt.GetPage()


    def OnCancel(self, evt):
        """ Handle the "Cancel" button and window close events.
        """
        q = wx.MessageBox("Cancel birthing?\n\nThe database has not "
                          "been updated yet; any changes will be lost.", 
                          "Confirmation", 
                          wx.YES_NO | wx.YES_DEFAULT | wx.ICON_WARNING,
                          self.GetParent())
        if q == wx.NO:
            evt.Veto()
            return

        evt.Skip()
    

#===============================================================================
# 
#===============================================================================

# noinspection PyUnusedLocal
class BirthData(object):
    """ Class for keeping all of the information collected for a device birth.
    """
    
    def __init__(self, chipId=None, bootRev=None, fwRev=None, mcu="EFM32GG330",
                 exampleId=None, batchId="", orderId="", customized=False,
                 capacity=8, **kwargs):
        """ Constructor.
        
            @param chipId: The unique hardware ID of the device being birthed.
            @param bootRev: The current bootloader version, as reported by
                the device itself.
            @param fwRev: The current firmware version, as reported by the
                device itself.
            @param mcu: The name of the device's MCU type; currently
                either "GG" (or starting with "EFM32GG330") or "GG11" (or
                starting with "EFM32GG11").
            @param exampleId: The DB ID (primary key) of the default Example
                for new births.
            @param batchId: The default batch ID (string) for new births.
            @param orderId: The default order ID (string) for new births.
        """
        if isinstance(chipId, bytes):
            chipId = str(chipId, 'utf8')
        if isinstance(mcu, bytes):
            mcu = str(mcu, 'utf8')

        self.chipId = chipId
        self.customized = customized
        
        self.mcu = self.fullMcu = mcu = (mcu or "EFM32GG330").upper()
        
        # TODO: Modify DB to use the whole MCU name, instead of GG/GG11
        #  Converting back and forth is kind of messy.
        if "GG" in mcu:
            if mcu.startswith("EFM32GG330") or mcu == "GG":
                self.mcu = "GG"
                self.fullMcu = "EFM32GG330"
            elif mcu.startswith("EFM32GG11") or mcu == "GG11":
                self.mcu = "GG11"
                self.fullMcu = "EFM32GG11"
        elif "STM" in mcu:
            if mcu.startswith("STM32U585AII6") or mcu == "STM32":
                self.mcu = "STM32"
                self.fullMcu = "STM32U585AII6"
        
        self.rebirth = False
        self.sku = None

        self.resetCreationDate = False

        # Bootloader and firmware revision numbers, as read from the device.
        self.actualBootRev = bootRev
        self.actualFwRev = fwRev
        
        # `device` (a `Device` reference) will get changed according to
        # selections in the UI. `lastDevice` (if any) is the `Device` read from
        # the database. `device` starts same as `lastDevice`.
        self.device = None      # Current Device. Could be an Example.
        self.lastDevice = None  # Last birth. A 'real' Device (or None).
        self.batchId = batchId
        self.orderId = orderId
        self.battery = None
        self.hwType = None
        self.hwCustomStr = ""
        self.enclosure = models.Device.ENCLOSURE_NONE
        self.capacity = capacity
        self.deviceNotes = ""
        
        # `birth` (a `Birth` reference) will get changed according to
        # selections in the UI. `lastBirth` (if any) is the `Birth` read from
        # the database. 
        self.birth = None            # Current Birth. Could be an Example.
        self.lastBirth = None        # Last birth from the DB. A 'real' Birth.
        self.serialNumber = None     # Serial # to use (prev. or manually set)
        self.newSerialNumber = True  # Should a new SN be generated?
        self.birthNotes = ""

        # Firmware and bootloader
        self.newFirmware = False     # Upload new FW?
        self.firmware = ""           # Name of alternate '.bin' or ""
        self.lastFirmware = ""       # Previous alternate '.bin' (if any)
        self.fwRev = 0  
        self.lastFwRev = 0           # Previous FW revision # (integer)
        self.newBootloader = False   # Upload new Bootloader?
        self.bootloader = ""         # Name of alternate '.bin' or ""
        self.lastBootloader = ""     # Previous alternate '.bin' (if any)
        self.bootRev = ""
        self.lastBootRev = self.actualBootRev or ""
        
        # `example` (a `Birth` reference with SN=-1) will get changed according
        # to selections in the UI. `lastExample` (if any) is the example
        # `Birth` closest to `lastBirth`. Not really used in the case of a 
        # rebirth that doesn't change type.
        self.example = None
        self.lastExample = None
        
        # Maps `Sensor` DB IDs (a/k/a PKs) to `Sensor` objects. 
        self.digitalSensors = {}
        self.analogSensors = {}
        
        # Maps `Sensor` DB IDs to serial numbers. Note that the ID may belong
        # to an Example's sensor!
        self.sensorSerials = {} 

        self.volumeName = ""

        self.setDevice(models.Device.objects.filter(chipId=self.chipId).last())
        self.lastDevice = self.device
        
        if self.device is not None:
            self.setBirth(self.device.getLastBirth())
            self.lastBirth = self.birth
            self.lastFwRev = self.fwRev
            
            if self.birth is not None:
                self.newSerialNumber = False
                self.rebirth = True
                self.example = self.lastExample = self.birth.getExample()
                self.lastFirmware = self.firmware
                self.lastBootloader = self.bootloader
                self.lastBootRev = self.bootRev
                
        if self.example is None:
            try:
                self.example = models.Birth.objects.get(id=exampleId)
            except models.Birth.DoesNotExist:
                pass


    def __repr__(self):
        return "<%s chipId=%s at 0x%X>" % (self.__class__.__name__,
                                           self.chipId, id(self))
        

    def setBirth(self, birth):
        """ Set the current `Birth` referenced by the data. Could be a previous
            `Birth` or an Example. Only affects 'local' data; does not modify
            database (that's done later).
        """
        
        if birth:
            self.serialNumber = (self.serialNumber or birth.serialNumber)
            if self.serialNumber < 0:
                self.serialNumber = None
            self.firmware = birth.firmware
            self.fwRev = birth.fwRev
            self.bootloader = birth.bootloader
            self.bootRev = birth.bootRev
            self.birthNotes = birth.notes
            
            if birth != self.birth:
                self.volumeName = self.getVolumeName()

        self.birth = birth


    def setDevice(self, dev):
        """ Set the current `Device` referenced by the data. Could be a
            previous `Device` or the one from an Example birth. Only affects
            'local' data; does not modify database (that's done later).
        """
        self.device = dev
        
        if dev:
            self.batchId = dev.batchId or self.batchId
            self.battery = dev.battery or self.battery
            self.enclosure = dev.enclosure or self.enclosure
            self.capacity = dev.capacity or self.capacity
            self.deviceNotes = dev.notes or self.deviceNotes
            self.hwCustomStr = dev.hwCustomStr or self.hwCustomStr
            self.hwType = dev.hwType or self.hwType
            self.orderId = dev.orderId
            
            if dev.hwType:
                self.mcu = dev.hwType.mcu or self.mcu
            
            if dev != self.device:
                self.sensorSerials.clear()
                
            self.analogSensors = self.getSensors()
            self.digitalSensors = self.getDigitalPeripherals()
    
    
    def getDigitalPeripherals(self, dev=None):
        """ Get all of the device's digital sensors and peripherals (i.e. the
            things represented by 'marker' elements in the manifest).
        """
        dev = dev or self.device
        if dev is None:
            return []
        return [s.info.id for s in dev.getSensors(analog=False)]


    def getSensors(self):
        """ Get the sensors/peripherals that require serial numbers (i.e. the
            analog ones). Note: modifies `sensorSerial` in place!
        """
        if self.lastDevice is not None:
            _diff, sensors = self.lastDevice.compareSensors(self.device, info__hasSerialNumber=True)
        elif self.device is not None:
            sensors = [(None, s) for s in self.device.getSensors(info__hasSerialNumber=True)]
        else:
            # Happens only when beginning to birth a new device. It's okay.
            sensors = []

        result = {}
        
        for lastSens, newSens in sensors:
            if newSens is None:
                # Not in selected Example; may get deleted, so don't show
                continue
            
            s = lastSens or newSens  # the first non-None one
            # NOTE: Should this use dict.setdefault, or just dict[x] = y?
            sn = self.sensorSerials.setdefault(s.id, s.serialNumber)
            result[s.id] = [s.info.name, s.sensorId, sn, s]
        
        return result


    def getVolumeName(self):
        """ Get the default drive volume name for the device type.
        """
        if not self.birth:
            return ""
        
        # Hack for Slam Stick devices. New devices just use the part number.
        pn = self.birth.partNumber
        if pn.startswith('LOG-0002'):
            return "SlamStick X"
        elif pn.startswith('LOG-0003'):
            return "SlamStick C"
        elif pn.startswith('LOG-0004'):
            return "SlamStick S"
        else:
            return pn
        

    #===========================================================================
    # 
    #===========================================================================

    def updateDatabase(self):
        """ Do the actual work of creating a new `Birth` record from the
            current data, creating/modifying the `Device` if needed.
        """
        now = timezone.now()
        
        if self.batchId:
            try:
                batch, created = models.Batch.objects.get_or_create(batchId=self.batchId)
                if created:
                    logger.info('Created Batch, ID %r' % self.batchId)
            except models.Batch.MultipleObjectsReturned:
                logger.error('More than one Batch with ID %r exists; using last!')
                batch = models.Batch.objects.filter(batchId=self.batchId).last()
        else:
            batch = None
            
        if not self.rebirth:
            # SCENARIO 1: New device (first time birth). Duplicate the selected
            # device (i.e. the one referenced by the selected example birth).
            # Sensors are *not* duplicated here (note recurse=False); this is
            # done in `updateSensors()`, called later.
            logger.info('Creating new Device record')
            newDevice = self.device.copy(recurse=False, chipId=self.chipId,
                                         batch=batch, orderId=self.orderId,
                                         created=now, notes=self.deviceNotes)
        elif self.device == self.lastDevice:
            # SCENARIO 2: Rebirth, with no changes to the device type.
            logger.info('Rebirth: unmodified device')
            newDevice = self.device
            if batch != newDevice.batch:
                newDevice.batch = batch
                newDevice.save()
        else:
            # SCENARIO 3: Rebirth, as different product. Update the device.
            # The device's sensors are not modified here; that is done in
            # `updateSensors()`, called later.
            logger.info('Rebirth: Changing device type')
            newDevice = self.lastDevice
            newDevice.copyFrom(self.device, recurse=False, batch=batch,
                               orderId=self.orderId, modified=now,
                               notes=self.deviceNotes)

        if self.customized:
            # Update 'advanced options'
            logger.info('Updating "advanced" options...')
            newDevice.battery = self.battery
            newDevice.hwType = self.hwType
            newDevice.hwCustomStr = self.hwCustomStr

        newDevice.capacity = self.capacity
        newDevice.enclosure = self.enclosure
        newDevice.save()
        
        if not self.newBootloader:
            self.bootRev = self.actualBootRev or self.bootRev
        
        if self.newSerialNumber:
            self.serialNumber = models.newSerialNumber("SlamStick")
            logger.info('Generated new serial number: %s' % self.serialNumber)

        success = False
        try:
            logger.info('Copying birth: %s' % self.birth)

            newBirth = self.birth.copy(user=USER,
                                       device=newDevice, 
                                       serialNumber=self.serialNumber,
                                       rebirth=self.rebirth,
                                       date=now,
                                       firmware=self.firmware,
                                       fwRev=self.fwRev,
                                       bootloader=self.bootloader,
                                       bootRev=self.bootRev,
                                       sku=self.sku or self.birth.partNumber,
                                       notes=self.birthNotes,
                                       test=TEST_BIRTH,
                                       completed=False)
            
            self.updateSensors(newDevice)
    
            # Set all the local data for the new birth. Necessary?
            self.setBirth(newBirth)
            self.setDevice(newDevice)
            self.rebirth = True

            if self.resetCreationDate:
                logger.info(f'Resetting device creation date to {newBirth.date.date()}')
                newDevice.created = newBirth.date
                newDevice.save()

            success = True
            return newBirth
        
        finally:
            if not success and self.newSerialNumber:
                logger.error('Something bad happened, resetting SN %s' %
                             self.serialNumber)
                if models.revertSerialNumber(self.serialNumber):
                    logger.info('Successfully reverted serial number.')
                else:
                    logger.info('Failed to revert serial number.')
                
    
    def updateSensors(self, device):
        """ Update the device's sensors. New `Sensor` records will be
            generated (if needed). For a new `Birth`, this should be called
            after the birthed `Device` record have been created. Better yet,
            don't call it directly; this method is called by `updateDatabase()`. 
            
            @param device: The device to modify. For a new birth, it is a new
                `Device` instance (i.e. copied from `self.device`). 
        """
        if not self.rebirth:
            # SCENARIO 1: New device with new sensors. `self.device` is the
            # device from the selected example.
            for s in self.device.getSensors():
                sn = self.sensorSerials.get(s.id, '')
                s.copy(device=device, serialNumber=sn)
            return
        
        elif device == self.device:
            # SCENARIO 2: Rebirth, with no change to the device type. Just
            # update the serial numbers (as necessary). `self.device` is the
            # same as `self.lastDevice`.
            for s in device.getSensors(info__hasSerialNumber=True):
                sn = self.sensorSerials.get(s.id, '')
                if sn != s.serialNumber:
                    s.serialNumber = sn
                    s.save()
            return
        
        # SCENARIO 3: Rebirth, with sensors that differ from what exists in 
        # the database for the `Device`. `self.device` is the device from the
        # selected example.
        _diff, sensors = device.compareSensors(self.device)
        
        deletedSensors = []
        
        for lastSens, newSens in sensors:
            if newSens is None:
                # Updated device does not have sensor; add to deletion list.
                deletedSensors.append(lastSens)
                continue

            elif lastSens is None:
                # Old device does not have sensor; make new one.
                sn = self.sensorSerials.get(newSens.id, '')
                newSens.copy(device=device, serialNumber=sn)

            else:
                # Old and new both have sensor; update serial numbers.
                sn = self.sensorSerials.get(lastSens.id, '')
                if sn != lastSens.serialNumber:
                    lastSens.serialNumber = sn
                    lastSens.save()

        self.deleteSensors(*deletedSensors)
    
    
    def deleteSensors(self, *sensors, **kwargs):
        """ Delete one or more Sensors, e.g. the ones no longer associated
            with a `Device` after it was rebirthed as a different product.
            
            @keyword safe: If `True`, the Sensors won't actually get deleted
                from the database. Instead, they will get their `device` set
                to `None`, which has the same effect (but is more-or-less
                reversible). 
        """
        if not sensors:
            return

        safe = kwargs.pop('safe', False)

        if safe:
            # "Fake" (safe) delete: just sets the referenced `Device` to 
            # `None`, and adds a note about which Device it was originally
            # attached to. Sensors with `device==None` can be gathered and
            # deleted later. 
            logger.debug("deleteSensors(): Doing safe 'delete'")
            for s in sensors:
                if s.device:
                    s.notes += "(deleted from device %s)" % s.device.pk
                    s.device = None
                    s.save()
        else:        
            # "Real" delete. Actually does the deletion, which is reversible
            # and not necessarily safe during development.
            logger.debug("deleteSensors(): Doing real delete")
            
            # For deleting multiple sensors: build out a 'Q' object that will 
            # "OR" together all the record primary keys (a/k/a/ `id`), to be 
            # used to create a QuerySet for deletion.
            q = Q(pk=sensors[0].pk)
            for s in sensors[1:]:
                q |= Q(pk=s.pk)
            models.Sensor.objects.filter(q).delete()
    
                
#===============================================================================
# 
#===============================================================================

class ProgressDialog(wx.ProgressDialog):
    def Update(self, *args, **kwargs):
        if len(args) > 1:
            logger.info(args[1])
        super(ProgressDialog, self).Update(*args, **kwargs)


class BirtherApp(wx.App):
    """ The database-driven birthing utility! Wraps the process, and keeps
        some information not specific to a single birth (e.g. master lists of
        all Products, etc.).
    """
    PREFS_FILE = "birth_wizard.cfg"

    # Platform-specific subdirectories and filenames.
    GG_PATH = "EFM32GG330"
    GG_FW = "firmware.bin"
    
    GG11_FW = "update.pkg"
    GG11_PATH = "EFM32GG11B820"

    STM32_FW = "update.pkg"
    STM32_PATH = "STM32U585AII6"

    FIRMWARE = {
        "GG11": ("GG11", GG11_PATH, GG11_FW),
        "STM32": ("STM32", STM32_PATH, STM32_FW),
        "GG": ("GG", GG_PATH, GG_FW),

        # Duplicates for eventual move to using full MCU name in DB
        "EFM32GG11B820": ("GG11", GG11_PATH, GG11_FW),
        "STM32U585AII6": ("STM32", STM32_PATH, STM32_FW),
        "EFM32GG330": ("GG", GG_PATH, GG_FW)
    }

    def OnInit(self):
        """ Post-Constructor initialization event handler.
        """
        self.prefsFile = os.path.join(os.path.dirname(__file__),
                                      self.PREFS_FILE)
        self.loadPrefs()
        
        self.reconnect()
        
        self.examples = self.getExampleListData()
        self.digitalSensors = self.getDigitalSensorListData()
        self.hwTypes = self.getHwTypeListData()
        self.batteries = self.getBatteryListData()
        
        self.products = self.getProductListData()
        self.batches = self.getBatchIds()
        self.orders = self.getOrderIds()
        
        self.firmware = self.getFirmwareDirs()
        self.bootloaders = self.getBootloaderDirs()
        
        self.configs = self.getConfigFiles()
        
        keepGoing = True
        while keepGoing:
            # These get set according to failure or success
            msg = "Birth another device?\n\n "
            icon = wx.ICON_INFORMATION
            fw = chipId = bootloader = device = None
            
            try:
                fw, chipId, bootloader = self.getFirmwareUpdater()
                device = fw.device if fw else None
            except ValueError:
                msg = "Failed to find device!\n\nTry again?"
                icon = wx.ICON_ERROR
            
            if fw is not None:
                if device:
                    info = device.getInfo()
                    mcu = info.get('McuType', None)
                else:
                    mcu = None
                    info = None
                
                if info:
                    logger.info("Found device: Chip ID {:X}, "
                                "FwRevStr {}".format(info.get('UniqueChipID', 0),
                                                     info.get('FwRevStr', None)))
                
                # Check if device has old manufacturing firmware. If so, it
                # gets updated and the loop starts again.
                # This will eventually get removed.
                if (info and info.get('FwRevStr', 'TST-0.2.1') == 'TST-0.2.1'
                        and info.get('McuType', '').startswith('EFM32GG11')):
                    self.replaceOldFirmware(device)
                    continue
                
                dev = self.birthWithWizard(fw, chipId, bootloader, mcu)
                if dev is None:
                    msg = "Birthing did not complete!\n\nTry again?"
                    icon = wx.ICON_WARNING
                else:
                    # Some silliness for a nicer 'done' message box.
                    if dev.productName != dev.partNumber:
                        name = "%s (%s)" % (dev.productName, dev.partNumber)
                    else:
                        name = "%s" % dev.partNumber
                    msg = "Birthed %s, SN:%s\n\nBirth another?" % \
                        (name, dev.serial)
                
            q = wx.MessageBox(msg, "Birth-o-Matic",
                              wx.YES_NO | wx.YES_DEFAULT | icon)
            
            keepGoing = (q == wx.YES)
        
        # Required: indicates app started up.
        return True


    def replaceOldFirmware(self, dev):
        """ Upload new manufacturing firmware for GG11. This will eventually
            get removed.
        """
        logger.info("Replacing old GG11 manufacturing firmware...")
        fwfile = os.path.join(dev.path, 'SYSTEM', 'firmware.bin')
        safeRemove(fwfile)
        safeCopy(GG11_MAN_FW, fwfile)
        with open(dev.commandFile, 'wb') as f:
            f.write('ua')
        self.waitForEject(dev)
        

    def copyPrefs(self, p):
        """ Recursively copy a dictionary of preferences. Assumes values are
            dictionaries, lists, or simple types (numbers and strings).
        """
        copy = {}
        for k, v in p.items():
            if isinstance(v, dict):
                v = self.copyPrefs(v)
            elif isinstance(v, (tuple, list)):
                v = v[:]
            copy[k] = v
        return copy
            

    def loadPrefs(self):
        """ Read the preferences file (i.e. the last options selected, to use
            as defaults).
        """
        self.prefs = {}
        try:
            with open(self.prefsFile, 'rb') as f:
                self.prefs = json.load(f)
        except (WindowsError, IOError, json.JSONDecodeError) as err:
            logger.error(f"Failed to load prefs file ({type(err).__name__}), probably okay.")
        
        self.prefs.setdefault('fwHistory', [])
        self.prefs.setdefault('bootloaderHistory', [])
        
        self.origPrefs = self.copyPrefs(self.prefs)
        
    
    def savePrefs(self):
        """ Save the preferences file. A backup of the previous file will be
            created if the preferences have changed.
        """
        try:
            if self.prefs != self.origPrefs:
                makeBackup(self.prefsFile)
        except (WindowsError, IOError):
            logger.error("Failed to make backup of prefs file!")
            
        try:
            with open(self.prefsFile, 'w') as f:
                json.dump(self.prefs, f)
            return
        except (WindowsError, IOError):
            logger.error("Failed to save prefs file!")

        try:
            restoreBackup(self.prefsFile)
        except (WindowsError, IOError):
            logger.error("Failed to restore backup of prefs file!")


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


    def getProductListData(self, **filterArgs):
        """ Gather the 'Examples' in a form that the wizard can use to quickly
            build lists. Keyword arguments are used in the query.
            
            @return: A dictionary mapping the example `Birth` database IDs
                (assigned by Django on creation) to a tuple containing the
                part number, name, hardware revision, and the example `Birth`.
        """
        q = models.Product.objects.filter(**filterArgs)
        
        products = {}
        for product in q:
            partNumber = str(product.partNumber or "")
            name = str(product.name or "")
            products[product.id] = (partNumber, name, product)
    
        return products


    def getExampleListData(self, **filterArgs):
        """ Gather the 'Examples' in a form that the wizard can use to quickly
            build lists. Keyword arguments are used in the query.
            
            @return: A dictionary mapping the example `Birth` database IDs
                (assigned by Django on creation) to a tuple containing the
                part number, name, hardware revision, and the example `Birth`.
        """
        q = models.Birth.objects.filter(serialNumber__lt=0, **filterArgs)
        
        examples = {}
        for example in q:
            partNumber = str(example.product.partNumber or "")
            name = str(example.product.name or "")
            hwRev = "{} rev {}".format(str(example.device.hwType.name).partition(':')[0],
                                       example.device.hwType.hwRev)
            hasSerials = example.device.getSensors(info__hasSerialNumber=True)
            examples[example.id] = (partNumber, name, hwRev, hasSerials, example)
    
        return examples


    def getDigitalSensorListData(self, **filterArgs):
        """ Gather the 'SensorInfo' in a form that the wizard can use to
            quickly build lists. Keyword arguments are used in the query.

            @return: A dictionary mapping `Sensor` database IDs (assigned by
                Django on creation) to a tuple containing the part number, 
                notes, manufacturer name, and the `Sensor` object.
        """
        q = models.SensorInfo.objects.filter(analog=False, **filterArgs)
        sensors = {}
        
        for sensor in q:
            partNumber = str(sensor.partNumber or "")
            notes = sensor.notes
            manufacturer = sensor.manufacturer or ""
            sensors[sensor.id] = (partNumber, notes, manufacturer, sensor)
            
        return sensors


    def getHwTypeListData(self, **filterArgs):
        """ Gather the `DeviceType` data in a form that the wizard can use to
            quickly build lists. Keyword arguments are used in the query.
            
            @return: A dictionary mapping `DeviceType` strings to objects.
        """
        q = models.DeviceType.objects.filter(**filterArgs)
        types = {}
        
        for t in q.extra(order_by=['name', 'hwRev']):
            types[str(t)] = t
            
        return types

    
    def getBatteryListData(self, **filterArgs):
        """ Gather the `Battery` data in a form that the wizard can use to
            quickly build lists. Keyword arguments are used in the query.
            
            @return: A dictionary mapping `Battery` strings to objects.
        """
        q = models.Battery.objects.filter(**filterArgs)
        types = {'None': None}

        for t in q.extra(order_by=['capacity', 'manufacturer', 'partNumber']):
            types[str(t)] = t
            
        return types

    
    def getBatchIds(self, **filterArgs):
        """ Gather the IDs/names of all `Batch` objects in a form that the
            wizard can use to quickly build lists (a flat list of strings).
            Keyword arguments are used in the query.
        """
        # Note: `.filter()` with no args works like `.all()`
        return [str(i) for i in models.Batch.objects.filter(**filterArgs)]


    def getOrderIds(self, **filterArgs):
        """ Gather all `Device` objects' `orderId` field values in a form that
            the wizard can use to quickly build lists (a flat list of strings).
        """
        q = models.Device.objects.filter(**filterArgs).exclude(orderId="")
        orders = []
        
        for d in q:
            if d.orderId not in orders:
                orders.append(d.orderId)
        return orders
        
        
    #===========================================================================
    # 
    #===========================================================================
    
    def _getFirmwareDirs(self, path, filename=GG_FW):
        """ Get the paths of all firmware files within a directory. 
            
            @param path: The root directory, containing firmware subdirectories.
            @param filename: The name of the binary file to look for.
            @return: A dictionary of firmware names keyed by revision number
                (integer).
        """
        result = []
        for f in os.listdir(path):
            if '_rev' not in f or f.startswith('.'):
                continue

            fullname = os.path.join(path, f)
            if not os.path.isdir(fullname):
                # Ignore non-directories, hidden directories
                continue

            if os.path.isfile(os.path.join(fullname, filename)):
                # DB stores fwRev as a number; extract it from directory name
                try:
                    sp = f.strip().split('_')
                    if len(sp) > 1:
                        rev = int(sp[-1].strip(string.ascii_letters+string.punctuation))
                        result.insert(0, (rev, f))
                        continue
                except ValueError:
                    pass
                logger.error('Could not get FwRev # from %r' % f)

        return dict(result)


    def getFirmwareDirs(self, root=paths.FW_LOCATION):
        """ Get the paths of all firmware files. 
            
            @return: A dictionary, keyed by MCU type. Values are dictionaries
                of firmware names keyed by revision number (integer).
        """
        # TODO: This should get changed (along with DB schema) to use the full
        #  MCU type names, as used in the directories.
        return {k: self._getFirmwareDirs(os.path.join(root, v[1], "Main_App"), v[2])
                for k, v in self.FIRMWARE.items()}


    def getFirmware(self, data=None):
        """ Get the names of firmware compatible with the given device data.
            Called when the firmware/bootloader page updates.
        """
        try:
            return self.firmware[data.mcu]
        except KeyError:
            logger.error("No firmware for unknown MCU type %r" % data.mcu)
        except AttributeError:
            logger.info("getFirmware(): No MCU?")
            
        return {}

    
    def _getBootloaderDirs(self, path, filename='boot.bin'):
        """ Get the paths of all bootloader files from one directory. 
            
            @param filename: The name of the binary file to look for.
            @return: A dictionary of bootloader names keyed by revision number
                (both strings). Names and revision numbers are currently the
                same.
        """
        result = []
        
        if os.path.isdir(path):
            for f in os.listdir(path):
                fullname = os.path.join(path, f)
                if not os.path.isdir(fullname) or f.startswith('.'):
                    continue
                elif os.path.isfile(os.path.join(fullname, filename)):
                    # DB stores bootRev as string, same as directory name
                    result.insert(0, (f, f))
        elif 'GG11' not in path and 'STM' not in path:
            logger.info("No such directory: %s" % path)
                
        return dict(result)


    def getBootloaderDirs(self, root=paths.BL_LOCATION):
        """ Get the paths of all bootloader files. Called once. 
            
            @return: A dictionary, keyed by MCU type. Values are dictionaries
                of bootloader names keyed by revision number (both strings).
                Names and revision numbers are currently the same.
        """
        # TODO: This should get changed (along with DB schema) to use the full
        #  MCU type names, as used in the directories.
        return {k: self._getBootloaderDirs(os.path.join(root, v[1], "Bootloader"))
                for k, v in self.FIRMWARE.items()}


    def getBootloaders(self, data=None):
        """ Get the names of bootloaders compatible with the given device data.
            Called when the firmware/bootloader page updates.
        """
        try:
            return self.bootloaders[data.mcu]
        except KeyError:
            logger.error("No bootloaders for unknown MCU type %r" % data.mcu)
        except AttributeError:
            logger.info("getBootloaders(): No MCU?")
            
        return {}


    def getFirmwareFile(self, data, root=paths.FW_LOCATION):
        """ Get the firmware ``.bin`` or ``.pkg`` file corresponding to device
            data. Will return `None` if the firmware is not to be updated.

            @param data: `BirthData` information for the device.
            @param root: The firmware root directory.
        """
        if not data.newFirmware:
            # Not updating firmware; abort.
            return None  
        elif data.firmware:
            # A specific file was specified, rather than a revision.
            fw = data.firmware
            if not os.path.isfile(fw):
                fw = os.path.join(root, fw)
        else:
            # Get the firmware filename for the device type.
            mcu = data.device.hwType.mcu
            _shortname, fwpath, fwfile = self.FIRMWARE[mcu]
            fw = os.path.join(root, fwpath, 'Main_App',
                              self.firmware[mcu][data.fwRev], fwfile)

        if not os.path.isfile(fw):
            logger.error('Could not find firmware file: %s' % fw)

        return os.path.realpath(fw)
        
        
    def getBootloaderFile(self, data, root=paths.BL_LOCATION):
        """ Get the bootloader ``.bin`` file corresponding to device data.
            Will return `None` if the bootloader is not to be updated.
        """
        mcu = data.device.hwType.mcu
        mcuPath = self.FIRMWARE.get(mcu, None)

        if not mcuPath:
            logger.error(f'Unrecognized MCU type ({mcu!r}), defaulting to {self.GG_PATH}')

        mcuPath = mcuPath[1]

        if not data.newBootloader:
            # Don't update bootloader.
            return None
        if data.bootloader:
            # A specific bootloader .bin was selected
            bl = data.bootloader
        else:
            # Get the .bin for the specified MCU and revision
            bl = os.path.join(mcuPath, "Bootloader", data.bootRev, 'boot.bin')
        
        if not os.path.isfile(bl):
            bl = os.path.join(root, bl)
        if not os.path.isfile(bl):
            logger.error('Could not find bootloader .bin: %s' % bl)
        
        return os.path.realpath(bl)
        

    def getConfigFiles(self, root=CONFIG_PATH):
        """ Get a list of pre-made config files that can be installed after
            birth.
        """
        return glob(os.path.join(root, '*.cfg'))
        
    
    #===========================================================================
    # 
    #===========================================================================

    @staticmethod
    def _findBootloader(*_args):
        """
        """
        x = FirmwareFileUpdaterSTM32.findBootloader()
        if x:
            fw = FirmwareFileUpdaterSTM32()
            return (x, fw)

        # Try to get the GG11 file-based firmware updater.
        x = FirmwareFileUpdaterGG11.findBootloader()
        if x:
            fw = FirmwareFileUpdaterGG11()
            return (x, fw)

        # Lastly, try to get the GG file-based firmware updater.
        x = FirmwareFileUpdater.findBootloader()
        if x:
            fw = FirmwareFileUpdater()
            return (x, fw)

        # Try to get the bootloader-based firmware updater.
        x = FirmwareUpdater.findBootloader()
        if x:
            fw = FirmwareUpdater()
            return (x, fw)


    @classmethod
    def getFirmwareUpdater(cls):
        """
        """
        status, result = BusyBox.run(cls._findBootloader, 
           "Waiting for Device",
           "Attach a device now, or put a device in bootloader mode.")
        
        if not result:
            if status == wx.ID_CANCEL:
                logger.info('Cancelled scan for bootloader')
            elif status == BusyBox.ID_TIMEOUT:
                logger.info('Scan for bootloader timed out')
            else:
                logger.info('Scan for bootloader failed, reason unknown')
            return None, None, None
        
        dev, fw = result
        
        try:
            bootloader, chipId = fw.connect(dev)
            
        except (TypeError, WindowsError, SerialTimeoutException) as err:
            # connect probably returned `None`
            logger.error('Failed to connect to bootloader: %s' % err)
            return None, None

        logger.info('Firmware updater: {}'.format(fw))
        return fw, chipId, bootloader


    @classmethod
    def waitForEject(cls, dev, timeout=BusyBox.DEFAULT_TIMEOUT_MS):
        """
        """
        logger.info("Waiting for device to unmount...")
        path = dev.path
        
        def findDrive(*_args):
            wx.Yield()  # Not sure if this actually helps in this case
            if os.path.exists(path):
                return None
            return True

        status, ok = BusyBox.run(findDrive, "Waiting for device to reboot")

        if not ok:
            if status == wx.ID_CANCEL:
                logger.info('Cancelled scan for device.')
                msg = "Scan for device cancelled\n\nAborted by user."
            elif status == BusyBox.ID_TIMEOUT:
                logger.warning('Scan for device timed out!')
                msg = ("Device scan failed (timed out)\n\n"
                       "Device did not reboot after %d seconds."
                       % (timeout/1000))
            else:
                logger.warning('Scan for device failed, reason unknown! '
                               '(BusyBox.run() status: %r)' % status)
                msg = ("Device scan failed!\n\nReason unknown.\n"
                       "(Scan returned status %d)" % status)

            wx.MessageBox(msg, "Could not reboot device", wx.OK | wx.ICON_WARNING)

        return ok
        

    @classmethod
    def getRecorder(cls, serialNumber, timeout=BusyBox.DEFAULT_TIMEOUT_MS):
        """ Wait for a recorder to reboot and appear as a USB disk.

            @param serialNumber: The serial number of the expected device.
            @param timeout: Time (in ms) to wait before timing out.
        """
        logger.info("Waiting for device in disk mode...")
        # Force cache of known drive letters to clear (recorder may already be
        # present as a USB disk).
        endaq.device._LAST_RECORDERS = None
        
        def findDrive(*_args):
            wx.Yield()  # Not sure if this helps
            if endaq.device.deviceChanged():
                for dev in endaq.device.getDevices():
                    if dev.serialInt == serialNumber:
                        return dev
            return None
        
        status, dev = BusyBox.run(findDrive, "Waiting for device in disk mode")

        if not dev:
            if status == wx.ID_CANCEL:
                logger.info('Cancelled scan for device.')
                msg = "Scan for device cancelled\n\nAborted by user."
            elif status == BusyBox.ID_TIMEOUT:
                logger.warning('Scan for device timed out!')
                msg = ("Device scan failed (timed out)\n\n"
                       "Could not find device after trying for %d seconds."
                       % (timeout/1000))
            else:
                logger.warning('Scan for device failed, reason unknown! '
                               '(BusyBox.run() status: %r)' % status)
                msg = ("Device scan failed!\n\nReason unknown.\n"
                       "(Scan returned status %d)" % status)

            wx.MessageBox(msg, "Could not get device", wx.OK | wx.ICON_WARNING)

        return dev
    
    
    #===========================================================================
    # 
    #===========================================================================

    def initData(self, chipId, bootloader="", fwRev=None, capacity=16,
                 **kwargs):
        """ Create a `BirthData` object for a device based on its unique ID
            (e.g. its EFM32 chip ID).
            
            @param chipId: The device's unique ID.
            @param bootloader: The device's self-reported bootloader version
                (if known).
            @param fwRev: The device's reported firmware version (if known)
            @param capacity: The size of the device's flash memory/SD card.
        """
        self.reconnect()
        defaults = self.prefs.setdefault('defaults', {}).copy()
        defaults.update(kwargs)
        showAdvanced = self.prefs.get('showAdvancedOptions', False)
        return BirthData(chipId=chipId, bootRev=bootloader, fwRev=fwRev,
                         customized=showAdvanced, capacity=capacity, 
                         **defaults)

        
    def updatePrefs(self, data, **kwargs):
        """ Update defaults and such in the preferences using current data.
        
            @param data: The device birth data (a `BirthData` instance).
        """
        defaults = self.prefs.setdefault('defaults', {})
        if data.example:
            defaults['exampleId'] = data.example.id
        defaults['batchId'] = data.batchId
        defaults['orderId'] = data.orderId
        
        capacities = defaults.get('capacities', [])
        capacities.append(data.capacity)
        defaults['capacities'] = sorted(set(capacities))
        
        self.prefs['showAdvancedOptions'] = data.customized
        self.prefs.update(kwargs)
        self.savePrefs()


#===============================================================================
# 
#===============================================================================

    def getContent(self, dev):
        """ Get the names of the default content items that will be copied to
            the root directory of the recorder.
            
            @param dev: The device to copy to. An instance of a 
                `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
            @return: A list of two-item tuples: the source filename and the
                destination filename.
        """
        contentPath = os.path.join(paths.DB_PATH,
                                   '_%s_Contents' % dev.partNumber[:8])
        if not os.path.isdir(contentPath):
            contentPath = os.path.join(paths.DB_PATH, '_Copy_Folder')
            
        ignore = shutil.ignore_patterns('.*', '*.lnk', 'Thumbs.db')
        
        files = os.listdir(contentPath)
        files = set(files).difference(ignore(contentPath, files))
        
        return [(os.path.realpath(os.path.join(contentPath, c)),
                 os.path.realpath(os.path.join(dev.path, c)))
                 for c in files]


    
    # @classmethod  # <-- for testing, remove later
    def setDeviceConfig(self, dev, validate=True):
        """ Set up the device for a run on the shaker. Configures the channels
            and removes files that could cause problems (user calibration,
            etc.). Existing configuration and other items are duplicated for
            later restoration.
            
            @param dev: The device to configure. An instance of a 
                `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
            @param validate: If `True`, perform basic tests on the EBML data.
        """
        # Keep copy of old config (for rebirth). Calibration will restore.
        makeBackup(dev.configFile)
        
        # TODO: Refactor to do configuration via `endaq.device`
        conf = dict()
        confList = conf.setdefault('RecorderConfigurationList', {})

        confItems = [
            {'ConfigID': 0x08ff7f, 'TextValue': 'Configured for Calibration'},
            {'ConfigID': 0x16ff7f, 'UIntValue': 1},
            {'ConfigID': 0x14ff7f, 'ASCIIValue': 'RECORD'},
            {'ConfigID': 0x10ff7f, 'UIntValue': 0},
            {'ConfigID': 0x0bff7f, 'FloatValue': 0.0},
            {'ConfigID': 0x12ff7f, 'UIntValue': 0},
            {'ConfigID': 0x13ff7f, 'BooleanValue': 0},
        ]
        confList.setdefault('RecorderConfigurationItem', confItems)

        channels = dev.getChannels()
        
        # Digital accelerometer 1 (ch32, 0x20): enable and sample rate
        if 32 in channels:
            confItems.append({'ConfigID': 0x01ff20, 'UIntValue': 1})
            confItems.append({'ConfigID': 0x02ff20, 'UIntValue': 3200})

        # Digital accelerometer 1 (ch80, 0x50): enable and sample rate
        if 80 in channels:
            confItems.append({'ConfigID': 0x01ff50, 'UIntValue': 1})
            confItems.append({'ConfigID': 0x02ff50, 'UIntValue': 4000})

        # IMU (ch 43, 0x2b): enable and sample rate
        if 43 in channels:
            confItems.append({'ConfigID': 0x01ff2b, 'UIntValue': 16})
            confItems.append({'ConfigID': 0x02082b, 'UIntValue': 100})

        # Pad pressure/temperature/humidity (ch59, 0x3b): enable
        if 59 in channels:
            confItems.append({'ConfigID': 0x01ff3b, 'UIntValue': 7})

        # Light sensor (ch76, 0x4c): enable
        if 76 in channels:
            confItems.append({'ConfigID': 0x01ff4c, 'UIntValue': 1})

        with open(dev.configFile, 'wb') as f:
            uiSchema.encode(f, conf)
        
        msg = None
        if validate:
            try:
                doc = uiSchema.load(dev.configFile)
                if doc[0].name != "RecorderConfigurationList":
                    errStr = "First element: %s" % doc[0]
                    msg = "The file was corrupted."
                    logger.error("Config validation failure (%s)" % errStr)
            except (IOError, WindowsError) as err:
                if err.errno == errno.ENOENT:
                    msg = "The file could not be found."
                else:
                    msg = "An unexpected error occurred."
                errStr = "%s: %s" % (err.__class__.__name__, err)
                logger.error("Config validation failure (%s)" % errStr)
                msg = "%s\n\n%s" % (msg, errStr)
        if msg is not None:
            msg = "Config file validation failed!\n\n%s" % msg
            wx.MessageBox(msg, "Config Validation Error", wx.ICON_ERROR)
            return False
        
        # Keep a copy of any user calibration and remove it (for rebirth).
        # Calibration will restore.
        try:
            makeBackup(dev.userCalFile)
            os.remove(dev.userCalFile)
        except (IOError, WindowsError) as err:
            if err.errno != errno.ENOENT:
                raise
        
        # Keep a copy of any existing recordings (for rebirth).
        # Calibration will restore.
        dataDir = os.path.join(dev.path, 'DATA')
        backupDir = dataDir + "~"
        try:
            if os.path.exists(dataDir) and not os.path.exists(backupDir):
                logger.debug("Renaming existing data directory '%s'" % dataDir)
                os.rename(dataDir, backupDir)
        except (IOError, WindowsError) as err:
            if err.errno != errno.ENOENT and err.errno != 183:
                raise

        return True

    
    # @classmethod # <-- for testing, remove later
    def copyDeviceConfig(self, dev, configFile):
        """ Copy a pre-built config file to the device.
        
            @param dev: The device to configure. An instance of a 
                `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
            @param configFile: The full path and name of a ``.cfg`` file to
                copy.
        """
        try:
            shutil.copy2(configFile, dev.configFile)
        except (IOError, WindowsError):
            logger.error('Failed to copy config file %s!' % configFile)
            wx.MessageBox("Could not copy config file!.\n\n"
                          'The file %s\ncould not be copied to the device.\n\n'
                          'Birthing will continue without it.',
                          "Config Copying Error", wx.ICON_ERROR)
            
    
    def backupUserData(self, dev):
        """ Back up (rename) the existing `DATA` directory. For use with
            rebirths. The data will be restored after calibration.
            
            @param dev: The device to configure. An instance of a 
                `devices.Recorder` subclass (e.g. `devices.SlamStickX`).
        """
        data = os.path.join(dev.path, 'DATA')
        backup = data + "~"
        
        if os.path.exists(data) and os.listdir(data):
            if os.path.exists(backup):
                shutil.rmtree(backup)
            os.rename(data, backup)
            return True
        
        return False


    def cleanupDevice(self, dev):
        """
        """
        data = os.path.join(dev.path, 'DATA')
        
        for dirname in (data, data+"~"):
            if safeRmtree(dirname):
                logger.info("Removed old %s" % dirname)
            elif not os.path.exists(dirname):
                logger.warning("Could not remove old %s" % dirname)
        
        for config in (dev.configFile, dev.configFile+"~"):
            if safeRemove(config):
                logger.info("Removed old %s" % config)
            elif os.path.exists(config):
                logger.warning("Could not remove old %s" % config)

    
    def printLabel(self, data, printer=None):
        """ Print the birth label.
        
            @param data: The device's `BirthData`.
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
                
            labels.printBirthLabel(data.sku, data.birth.serialNumberString)
            
        except RuntimeError:
            wx.MessageBox("The printer SDK components could not be loaded.\n\n"
                          "Have they been installed?", "Label Printing Error",
                          wx.OK | wx.ICON_ERROR)
        
         
    def birthWithWizard(self, fw, chipId=None, bootloader=None, mcu=None,
                        doLegacy=True):
        """ Perform the birthing, using the wizard.
        
            @param fw: A firmware updater object, either a `FirmwareUpdater`
                or `FirmwareFileUpdater`.
            @param chipId: The device's unique ID (e.g. the MCU chip ID).
            @param bootloader: The device's reported bootloader version
                (if known).
            @param mcu: The microcontroller type.
            @param doLegacy: If `True`, write legacy birth log data.
        """
        # TODO: Consider breaking this up. 200 lines in 1 method is a bit much. 
        #  Make each step its own function/method (w/ identical arguments) and build
        #  a list, then iterate over that list, executing each function/method. Raise
        #  `StopIteration` or return False if cancelled or errored.

        usingBootloader = not isinstance(fw, FirmwareFileUpdater)
        dev = fw.device

        if chipId is None and not usingBootloader:
            # File-based birth, no chip ID; get from serial number.
            b = models.Birth.objects.filter(serialNumber=dev.serialInt
                                            ).latest('date')
            try:
                chipId = b.device.chipId
            except AttributeError:
                pass
                    
        if chipId is None:
            logger.error('chipId is None: Could not get bootloader?')
            return None
        
        
        try:
            capacity = getCardSize(dev.path)
        except (AttributeError, IOError, WindowsError):
            capacity = DEFAULT_CAPACITY
    
        data = self.initData(chipId, bootloader, mcu=mcu, capacity=capacity)
        
        if usingBootloader:
            title = "Birther Wizard (bootloader mode)"
        else:
            title = "Birther Wizard (file mode)"

        if TEST_BIRTH:
            title = f"TEST * {title} * TEST"

        wizard = BirthWizard(data=data, title=title)
        if not wizard.RunWizard(wizard.firstPage):
            wizard.Destroy()
            return None
        
        # Get all the wizard data before deleting it
        copyContent = wizard.copyContent
        configFile = wizard.config
        makeDirs = wizard.makeDirs and not copyContent
        doDatabaseUpdate = wizard.doDatabaseUpdate
        doBirth = wizard.doBirth
        keepCal = wizard.keepOldCal
        configDevice = wizard.configDevice
        printLabel = wizard.printLabel
        wizard.Destroy()

        data.sku = data.sku or data.birth.partNumber

        self.updatePrefs(data)

        NUM_STEPS = 17
        step = 0

        if printLabel:
            NUM_STEPS += 1

        # Initial sanity checks, prevents cluttering database with bad births
        if data.newFirmware:
            fwFile = self.getFirmwareFile(data)
            if not os.path.exists(fwFile):
                wx.MessageBox("Could not find firmware!\n\n"
                    f"The file {fwFile}\ncould not be found. This shouldn't happen, "
                    "and is probably a Birth-o-Matic bug.\n\n"
                    'Birthing cancelled.', "Firmware Not Found!",
                    wx.ICON_ERROR)
                return None
        # TODO: More sanity checks (maybe update database later?)

        pd = ProgressDialog("Birthing Device", "Starting birth...",
                               maximum=NUM_STEPS)

        try:
            step += 1
            if doDatabaseUpdate:
                pd.Update(step, "Updating database...")
                # Will also update `data.birth`, used below
                data.updateDatabase()
            
            mt = ManifestTemplater(data.birth)
            ct = DefaultCalTemplater(data.birth)

            step += 1
            pd.Update(step, "Creating chip ID and calibration directories...")
            chipDir, calDir = legacy.makeDirectories(data.birth)

            if doBirth:
                # NOTE: In the SlamStickLab master branch, only the file-based
                # FW updater has clean(). This 'if' can be removed after merge.
                step += 1
                if hasattr(fw, 'clean'):
                    pd.Update(step, 'Cleaning old files from device...')
                    util.cleanOldUpdates(dev)

                step += 1
                pd.Update(step, "Creating legacy XML and EBML files...")
                legacy.writeTemplates(mt, ct)
                
                step += 1
                if keepCal:
                    # NOTE: existing data *should* exist if the keepCal is True!
                    pd.Update(step, "Reading existing calibration data...")
                    caldata = readFile(legacy.findOldCal(chipId))
                else:
                    pd.Update(step, "Generating default calibration data...")
                    caldata = ct.dumpEBML()
                
                step += 1
                pd.Update(step, "Generating Manifest...")
                mandata = mt.dumpEBML()
                
                step += 1
                pd.Update(step, "Building USERPAGE data...")
                userpageFile = os.path.join(tempfile.gettempdir(), 'userpage.bin')
                with open(userpageFile, 'wb') as f:
                    f.write(makeUserpage(mandata, caldata))
                
            else:
                userpageFile = None
                step += 5  # Jump the progress bar

            step += 1
            # FUTURE: Remove this whole thing
            if data.newBootloader:
                bootFile = self.getBootloaderFile(data)
                pd.Update(step, "Uploading new bootloader: %s" % bootFile)
                bootBin = readFile(bootFile)
                fw.uploadBootloader(bootBin)

            step += 1
            if data.newFirmware:
                fwFile = self.getFirmwareFile(data)
                pd.Update(step, "Getting new firmware file: %s" % fwFile)
            else:
                fwFile = None

            step += 1
            if doLegacy and doDatabaseUpdate:
                pd.Update(step, "Updating legacy log files...")
                legacy.updateLogs(data.birth, chipDir, calDir, 
                                  newSerialNumber=data.newSerialNumber)
            
            step += 1
            # Reboot the device to get new DEVPROPS and get out of bootloader
            # (if applicable).
            pd.Update(step, "Applying FW and/or userpage and rebooting device...")
            dev.command.updateDevice(firmware=fwFile, userpage=userpageFile)

            if not usingBootloader:
                self.waitForEject(dev)

            dev = self.getRecorder(data.birth.serialNumber)
            # Cancel/timeout/failure returns None
            if dev is None:
                return None

            # TODO: Check GG11 log files to confirm things installed?

            step += 1
            if printLabel:
                pd.Update(step, "Printing Label...")
                self.printLabel(data)

            step += 1
            if data.volumeName:
                pd.Update(step, 'Renaming device volume: %s' % data.volumeName)
                if renameVolume(dev.path, data.volumeName):
                    logger.info('Renamed device volume: %s' % data.volumeName)
                else:
                    # TODO: Show volume name failure error dialog (maybe)
                    logger.error('Failed to rename volume!')
    
            step += 1
            pd.Update(step, "Setting device clock...")
            dev.setTime()
    
            step += 1
            if configDevice:
                pd.Update(step, 'Configuring device for calibration run...')
                c = self.setDeviceConfig(dev)
                if not c:
                    logger.error("setDeviceConfig() returned %r" % c)
                    return None
            elif configFile:
                pd.Update(step, 'Copying calibration file "%s"...' %
                          os.path.basename(configFile))
                self.copyDeviceConfig(dev, configFile)
                
            if copyContent:
                pd.Pulse("Copying content to device...")
                util.copyContent(dev)
            elif makeDirs:
                pd.Pulse("Making empty content directories...")
                util.makeContentDirs(dev)
            
#             # Attempt to eject the drive.
#             pd.Pulse("Preparing %s for removal..." % dev.path)
#             try:
#                 ejectDrive(dev.path)
#             except Exception as err:
#                 logger.error("Failed to eject drive: %s" % err)
            
            # Force Recorder to have new serial number (for display)
            # Can be wrong after a previous bad birth
            dev._snInt = data.birth.serialNumber
            dev._sn = dev.SN_FORMAT % dev._snInt

            if doDatabaseUpdate:
                data.birth.completed = True
                data.birth.save()

            return dev
            
        finally:
            pd.Close()
            pd.Destroy()


#===============================================================================
# 
#===============================================================================

if __name__ == "__main__":
    try:
        from git.repo import Repo

        repo = Repo('..')
        commit = next(repo.iter_commits())
        logger.info("%s: branch %s, commit %s" % (os.path.basename(__file__),
                                                  repo.active_branch.name,
                                                  commit.hexsha[:7]))
        logger.info("Commit date: %s" % commit.authored_datetime)
    except Exception as err:
        logger.error("Could not get git information! Exception: %s" % err)

    app = BirtherApp(False)
    app.MainLoop()
