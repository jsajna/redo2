"""
Basic Brother printer control. Done using PT-D600, but should be applicable to
any PT model with USB. Requires the b-PAC SDK:
    * https://www.brother.co.jp/eng/dev/bpac/download/index.aspx).

Other notes:
    * Reboot required after installing the SDK before the script will work.
    * Some of the functions in the SDK present as Properties for some reason
        (the ones with no arguments, maybe). Access them to call them (e.g.,
        `_ = doc.Close`).
    * This works with only one Brother printer attached. It's probably using
        the first one found. Something will need to be done to select a
        specific printer if there's more than one.
"""
import os.path
import subprocess
import tempfile

# Uses pywin32. Could probably be done with ctypes, but it isn't as clean.
from win32com.client import Dispatch, pywintypes

import wx

# A 'template' label, generated with the P-Touch desktop software.
# Template has two text objects, with names "PartNumber" and "SerialNumber".
# In the P-Touch editor, right-click an object to change properties.
# Note: "0.23" is the tape width.
from .paths import TEMPLATE_PATH
TEMPLATE = os.path.join(TEMPLATE_PATH, "ProductLabel_0.23.lbx")
CAL_TEMPLATE = os.path.join(TEMPLATE_PATH, "Calibrated_0.23.lbx")

# A preview file
PREVIEW = "LabelPreview.bmp"

# Option flag bits for `printLabel()`
OPTION_DEFAULT = 0
OPTION_AUTOCUT = 0x0001
OPTION_CHAINPRINT = 0x0400

# Combined options flags (use these)
SINGLE_PRINT = OPTION_DEFAULT
CHAIN_PRINT = OPTION_CHAINPRINT | OPTION_AUTOCUT

#===============================================================================
# Logging setup
#===============================================================================

from .shared_logger import logger


#===============================================================================
#--- Printer utilities: finding, checking, etc. 
#===============================================================================

def _Dispatch(*args, **kwargs):
    """ Wrapper for `win32com.client.Dispatch` that raises a standard Python
        `RuntimeError` rather than a `pywintypes.com_error`, which is slightly
        easier to deal with outside of this module.
    """
    try:
        return Dispatch(*args, **kwargs)
    except pywintypes.com_error as err:  # @UndefinedVariable - not sure why
        raise RuntimeError(f"Brother printer SDK not installed! ({err!r})")


def getDefaultPrinter():
    """ Get the name of the default printer. If the default is offline, the
        first usable printer's name will be returned. The system default
        printer name will be returned if no printers are usable.
    """
    name = _Dispatch("bpac.Document").GetPrinterName
    if canPrint(name):
        return name
    
    for p in getPrinters():
        if canPrint(p):
            return p

    return name
    

def getPrinters(offline=False):
    """ Get the names of all known printers. 
    
        @keyword offline: If `True`, return all installed printers, available
            or not.
        @return: A list of printer names (strings).
    """
    pobj = _Dispatch("bpac.Printer")
    printers = pobj.GetInstalledPrinters
    if offline:
        return printers
    return [p for p in printers if pobj.IsPrinterOnline(p)]


def canPrint(printer=None):
    """ Basic check to see if the printer is connected (and its drivers
        installed).
        
        :param printer: The name of the label printer to use, if there
            is more than one attached.
        :returns: True or False.
    """
    try:
        printer = printer or getDefaultPrinter()
        return printer in getPrinters()
    except pywintypes.com_error:  # @UndefinedVariable - not sure why
        logger.error("canPrint() failed; are Brother drivers installed?")
        return False
    except Exception as err:
        logger.error("canPrint() got error: %r" % err)
        return False


#===============================================================================
#--- Generic printing/previewing functions. Called by type-specific functions.
#===============================================================================

def _populateLabel(template=TEMPLATE, **kwargs):
    """ Populate a generic label. Keyword arguments (other than `template`)
        are the names of the fields to populate (e.g. `PartNumber` and
        `SerialNumber`) and their values.
        
        :param template: The template P-touch Editor label file (.LBX)
    """
    doc = _Dispatch("bpac.Document")
    if doc.Open(template):
        for k, v in kwargs.items():
            doc.GetObject(k).Text = str(v)
        return doc
    else:
        raise IOError("Could not open template %s" % template)


def _printLabel(doc, printer=None, options=CHAIN_PRINT):
    """ Print a label.
    
        :param doc: The label to print (`bpac.Document`)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
        :param options: Bit flags for the `StartPrint` method.
    """
    if printer is None:
        printer = getDefaultPrinter()
    if printer and printer in getPrinters():
        doc.SetPrinter(printer, False)  # name, fitPage (resize to media)
            
    doc.StartPrint("", options)  # doc name, options bit flags
    doc.PrintOut(1, 0)     # No. of copies, "invalidity" (whatever that means)
    _ = doc.Close          # A Property. Accessing it makes label print.
    _ = doc.EndPrint       # Also a Property.
 

def _previewLabel(doc, filename=None, dpi=180):
    """ Generate a preview image.
    
        :param doc: The label to preview (`bpac.Document`)
        :param filename: The output file name. If `None`,
            output will go to a temporary file. Use if you
            want to keep the preview bitmap.
        :param dpi: The resolution of the resulting image.
        :returns: The name of the preview image (.BMP)
    """
    if filename is None:
        filename = os.path.join(tempfile.gettempdir(), PREVIEW)
    doc.Export(4, filename, dpi)    # First argument: type ID (4=bmp)
    return filename


def viewPreview(filename):
    """ Display a preview image. Example usage:
        `viewPreview(previewCalLabel(sn, calId, calDate))`

        :param filename: The name of the file to view.
    """
    # HACK: This is a simple way to get Windows to show an image,
    #  assuming the .BMP extension hasn't been associated with
    #  a specific app (unlikely).
    if os.path.isfile(filename):
        subprocess.call(['explorer', filename], shell=True)


#===============================================================================
#--- Birth label (part number, serial number)
#===============================================================================

def makeBirthLabel(partNumber, serialNumber, template=TEMPLATE):
    """ Create a birth label from a template file.
    
        :param partNumber: The device's full part number (with SD size and
            case style, etc.)
        :param serialNumber: The device's serial number.
        :param template: The template P-touch Editor label file (.LBX)
        :returns: The opened label (`<COMObject bpac.Document>`)
    """
    return _populateLabel(PartNumber=str(partNumber),
                          SerialNumber="S/N: %s" % serialNumber,
                          template=template)

    
def printBirthLabel(partNumber, serialNumber, template=TEMPLATE,
                    printer=None, chain=True):
    """ Print a Birth label, containing the part number and serial number.
    
        :param partNumber: The device's full part number (with SD size and
            case style, etc., if applicable)
        :param serialNumber: The device's serial number.
        :param template: The template P-touch Editor label file (.LBX)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
        :param chain: If `True`, don't automatically cut after the last
            label. Saves tape when printing multiple labels. Note that the
            user needs to manually press the printer's 'cut' button!
    """
    options = CHAIN_PRINT if chain else SINGLE_PRINT
    return _printLabel(makeBirthLabel(partNumber, serialNumber, template),
                      printer=printer, options=options)
 

def previewBirthLabel(partNumber, serialNumber, template=TEMPLATE,
                      view=True):
    """ Generate a preview image.
    
        :param partNumber: The device's full part number (with SD size and
            case style, etc., if applicable)
        :param serialNumber: The device's serial number.
        :param template: The template P-touch Editor label file (.LBX)
        :param view: If `True`, display the image.
        :returns: The name of the preview image (.BMP)
    """
    doc = makeBirthLabel(partNumber, serialNumber, template)
    filename = _previewLabel(doc)
    if view:
        viewPreview(filename)
    return filename


#===============================================================================
#--- Calibration label (calibration serial number, calibration date)
#===============================================================================

def makeCalLabel(serialNumber, calId, calDate, template=CAL_TEMPLATE):
    """ Create a calibration label from a template file.
    
        :param serialNumber: The device's serial number.
        :param calId: The device's calibration serial number (integer)
        :param calDate: The device's calibration date (`datetime`).
        :param template: The template P-touch Editor label file (.LBX)
    """
    # Just use the birth label template.
    return _populateLabel(SerialNumber=f"{serialNumber}",
                          CalInfo=f"C{calId:05d}  {calDate.date()}",
                          template=template)


def printCalLabel(serialNumber, calId, calDate, template=CAL_TEMPLATE,
                  printer=None, chain=True):
    """ Print a Calibration label, containing the calibration SN and date.

        :param serialNumber: The device's serial number.
        :param calId: The device's calibration serial number (integer)
        :param calDate: The device's calibration date (`datetime`).
        :param template: The template P-touch Editor label file (.LBX)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
        :param chain: If `True`, don't automatically cut after the last
            label. Saves tape when printing multiple labels. Note that the
            user needs to manually press the printer's 'cut' button!
    """
    options = CHAIN_PRINT if chain else SINGLE_PRINT
    return _printLabel(makeCalLabel(serialNumber, calId, calDate, template=template),
                      printer=printer, options=options)


def previewCalLabel(serialNumber, calId, calDate, template=CAL_TEMPLATE,
                    view=True):
    """ Generate a preview image.

        :param serialNumber: The device's serial number.
        :param calId: The device's calibration serial number (integer)
        :param calDate: The device's calibration date (`datetime`).
        :param template: The template P-touch Editor label file (.LBX)
        :param view: If `True`, display the image.
        :returns: The name of the preview image (.BMP)
    """
    doc = makeCalLabel(serialNumber, calId, calDate, template=template)
    filename = _previewLabel(doc)
    if view:
        viewPreview(filename)
    return filename


#===============================================================================
#
#===============================================================================

def printLabels(dev, name=None, session=None, printer=None, chain=True,
                parent=None):
    """ Convenience function to print one or both labels, with GUI
        warning/error message boxes. Which labels get printed is
        determined by the presence of `name` and/or `session` keyword
        arguments.

        :param dev: The `endaq.device.Recorder` in need of labels.
        :param name: The name (SKU) printed on the serial number label.
            `None` to skip this label.
        :param session: The CalSession to print. `None` to skip this
            label.
        :param printer: The label printer to use. Defaults to first
            found. Almost always `None`.
        :param chain: If `True`, don't automatically cut after the last
            label. Saves tape when printing multiple labels. Note that
            the user needs to manually press the printer's 'cut' button!
        :param parent: The parent window/dialog, if any. For message
            dialog box placement.
    """
    try:
        while not canPrint(printer):
            # Note: PLite LED is specific to PT-P700
            q = wx.MessageBox("The label printer could not be found.\n\n"
                              "Make sure it is attached, turned on, "
                              'and the "PLite" LED is off.\n\n'
                              "Try again?", "Label Printing Error",
                              wx.YES_NO | wx.ICON_ERROR,
                              parent=parent)
            if q == wx.NO:
                return False

        if name:
            sku = dev.partNumber
            sn = dev.serial
            printBirthLabel(sku, sn, printer=printer, chain=chain)

        if session:
            printCalLabel(dev.serial, session.sessionId, session.date, printer=printer, chain=chain)

        return True

    except RuntimeError:
        wx.MessageBox("The printer SDK components could not be loaded.\n\n"
                      "Have they been installed?", "Label Printing Error",
                      wx.OK | wx.ICON_ERROR, parent=parent)
        return False
