"""
Basic Brother printer control. Done using PT-D600, but should be applicable to
any PT model with USB. Requires the b-PAC SDK:
    * https://www.brother.co.jp/eng/dev/bpac/download/index.aspx).

Other notes:
    * Reboot required after installing the SDK before the script will work.
    * Some of the functions in the SDK present as Properties for some reason
        (the ones with no arguments, maybe). Access them (in any way) to call
        them.
    * This works with only one Brother printer attached. It's probably using
        the first one found. Something will need to be done to select a
        specific printer if there's more than one.
"""
import os.path
import tempfile

# Uses pywin32. Could probably be done with ctypes, but it isn't as clean.
from win32com.client import Dispatch, pywintypes

# A 'template' label, generated with the P-Touch desktop software.
# Template has two text objects, with names "PartNumber" and "SerialNumber".
# In the P-Touch editor, right-click an object to change properties.
# Note: "0.23" is the tape width.
from paths import TEMPLATE_PATH
TEMPLATE = os.path.join(TEMPLATE_PATH, "ProductLabel_0.23.lbx")

# A preview file
PREVIEW = "LabelPreview.bmp"

#===============================================================================
# Logging setup
#===============================================================================

from shared_logger import logger


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
    except pywintypes.com_error:  # @UndefinedVariable - not sure why
        raise RuntimeError("Brother printer SDK not installed!")


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
#--- Generic printing/previewing functions
#===============================================================================

def populateLabel(template=TEMPLATE, **kwargs):
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


def printLabel(doc, printer=None):
    """ Print a label.
    
        :param doc: The label to print (`bpac.Document`)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
    """
    if printer is None:
        printer = getDefaultPrinter()
    if printer and printer in getPrinters():
        doc.SetPrinter(printer, False)  # name, fitPage (resize to media)
            
    doc.StartPrint("", 0)  # doc name, options bit flags (0 = defaults)
    doc.PrintOut(1, 0)     # No. of copies, "invalidity" (whatever that means)
    _ = doc.Close          # A Property. Accessing it makes label print.
    _ = doc.EndPrint       # Also a Property.
 

def previewLabel(doc, dpi=180):
    """ Generate a preview image.
    
        :param doc: The label to preview (`bpac.Document`)
        :param dpi: The resolution of the resulting image.
        :returns: The name of the preview image (.BMP)
    """
    filename = os.path.join(tempfile.gettempdir(), PREVIEW)
    doc.Export(4, filename, dpi)    # First argument: type ID (4=bmp)
    return filename


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
    return populateLabel(PartNumber=str(partNumber),
                         SerialNumber="S/N: %s" % serialNumber,
                         template=template)

    
def printBirthLabel(partNumber, serialNumber, template=TEMPLATE, printer=None):
    """ Print a Birth label, containing the part number and serial number.
    
        :param partNumber: The device's full part number (with SD size and
            case style, etc., if applicable)
        :param serialNumber: The device's serial number.
        :param template: The template P-touch Editor label file (.LBX)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
    """
    return printLabel(makeBirthLabel(partNumber, serialNumber, template),
                      printer=printer)
 

def previewBirthLabel(partNumber, serialNumber, template=TEMPLATE):
    """ Generate a preview image.
    
        :param partNumber: The device's full part number (with SD size and
            case style, etc., if applicable)
        :param serialNumber: The device's serial number.
        :param template: The template P-touch Editor label file (.LBX)
        :returns: The name of the preview image (.BMP)
    """
    return previewLabel(makeBirthLabel(partNumber, serialNumber, template))


#===============================================================================
#--- Calibration label (calibration serial number, calibration date)
#===============================================================================

def makeCalLabel(calId, calDate, template=TEMPLATE):
    """ Create a calibration label from a template file.
    
        :param calId: The device's calibration serial number (integer)
        :param calDate: The device's calibration date (`datetime`).
        :param template: The template P-touch Editor label file (.LBX)
    """
    # Just use the birth label template.
    return populateLabel(SerialNumber="Calibration SN: C%05d" % calId,
                         PartNumber=calDate.strftime("Calibration Date: %Y-%m-%d"),
                         template=template)


def printCalLabel(calId, calDate, template=TEMPLATE, printer=None):
    """ Print a Calibration label, containing the calibration SN and date.
    
        :param calId: The device's calibration serial number (integer)
        :param calDate: The device's calibration date (`datetime`).
        :param template: The template P-touch Editor label file (.LBX)
        :param printer: The name of the label printer to use, if there is
            more than one attached.
    """
    return printLabel(makeCalLabel(calId, calDate, template=template),
                      printer=printer)
