"""
Generate manifest and calibration XML and EBML from template fragments,
and create calibration certificate PDFs, using information in the database.

There are two kinds of calibration templates: the default 'birth' calibration
(same for every device of that type), and the actual calibration (calculated
for that specific device).

TEST (ignore me):
```
import sys; sys.path.insert(0, '../birther')
import template_generator as T
from products import models
b = models.Birth.filter(serialNumber=1554).last()
```
"""

__author__ = "dstokes"
__copyright__ = "Copyright 2020 Mide Technology Corporation"

import calendar
import errno
import getpass
import math
import os
import socket
from string import Formatter
from io import BytesIO, StringIO
import subprocess
import sys
import tempfile
from xml.dom.minidom import parseString
import xml.etree.ElementTree as ET
import xml.sax.saxutils

import endaq.device  # @UnusedImport - sets up schema paths when imported
import ebmlite.util
import pytz

import paths
from util import makeBackup

# Django setup
# os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"
# import django
# django.setup()

# NOTE: Django import paths are weird. Get `products.models` from Django itself.
# from ProductDatabase.products import models
from django.apps import apps
models = apps.get_app_config('products').models_module


#===============================================================================
#--- Logger setup
#===============================================================================

from shared_logger import logger

#===============================================================================
#--- Globals and 'constants' (paths, default filenames, etc.) 
#===============================================================================

LOCALTZ = pytz.timezone('US/Eastern')
USER = getpass.getuser()
MACHINE = socket.gethostname()

# XML namespaces. Extend if necessary.
NS = {'svg': 'http://www.w3.org/2000/svg'}

for k, v in NS.items():
    ET.register_namespace(k, v)


#===============================================================================
# 
#===============================================================================

class EvalFormatter(Formatter):
    """ Smarter string formatter, which allows for mathematical expressions
        in keywords, e.g. 
        
        >>> f = EvalFormatter()
        >>> f.format('{m.title()} {x} {x+1} {hex(x)}', m="hello world", x=42)
        'Hello World 42 43 0x2a'
    """
    def __init__(self, evalArgs=None):
        evalArgs = evalArgs or {'math': math}
        self.evalArgs = evalArgs
        super(EvalFormatter, self).__init__()
        

    def get_field(self, field_name, args, kwargs):
        try:
            return Formatter.get_field(self, field_name, args, kwargs)
        except (AttributeError, KeyError):
            evalArgs = self.evalArgs.copy()
            evalArgs.update(kwargs)
            try:
                return eval(field_name, evalArgs), field_name
            except Exception as ex:
                logger.error(f'EvalFormatter failed eval on {field_name!r}: {ex!r}')
                raise
    

#===============================================================================
# 
#===============================================================================

class ManifestTemplater(object):
    """ Class to manufacture Slam Stick manifest data from information in the
        database. It works by assembling multiple XML fragments and inserting
        values.
    """
    SCHEMA = 'mide_manifest.xml'

    def xmlComment(self, el, comment, end=False):
        """ Utility method to create and insert a sanitized XML comment.

            @param el: The parent XML element
            @param comment: The comment (presumably a string).
            @param end: If `True`, append the comment to the end of the
                element's children. If `False`, insert at the beginning.
        """
        # Comment tags seem to be problematic even after escaping.
        if isinstance(str, bytes):
            comment = str(comment, 'utf8')
        else:
            comment = str(comment)
        comment = xml.sax.saxutils.escape(comment)

        index = len(el) if end else 0
        el.insert(index, ET.Comment(" %s " % comment))


    def getNonComment(self, parent):
        """ Find the first child of an XML element that isn't a comment.
        """
        for el in parent:
            if isinstance(el.tag, str):
                return el
        return None


    def getTemplateFile(self, name, path="", prefix="", suffix=""):
        """ Find a template XML fragment. The prefix, suffix, and '.xml' will
            be added if the named file does not exist.
            
            @param name: The base name of the template. Could be a filename,
                a part number, etc.
            @param path: The directory in which to look, a subdirectory of
                the object's `templatePath`.
            @param prefix: A prefix string to be inserted when trying to find
                a template file.
            @param suffix: A suffix string to be appended when trying to find
                a template file.
        """
        path = os.path.realpath(os.path.join(self.templatePath, path))
        filename = os.path.join(path, name)

        # Try 1: a literal filename (e.g., `Cal_DigitalSensorADXL345_Default.xml`)
        if os.path.isfile(filename):
            return filename

        if name.lower().endswith('.xml'):
            name = name[:-4]

        # Try 2: Probably an object name (e.g. `DigitalSensorADXL345`)
        filename = os.path.join(path, f"{prefix}{name}{suffix}.xml")
        if os.path.isfile(filename):
            return filename

        raise IOError(errno.ENOENT, 'No such template', filename)
        
    
    def readTemplate(self, name, path="", prefix="", suffix="",
                     startComment=True, endComment=True, **kwargs):
        """ Read a template (or template fragment), populate it with data
            from the keyword arguments, and return the parsed DOM.

            @param name: The base name of the template. Could be a filename,
                a part number, etc.
            @param path: The directory in which to look, a subdirectory of
                the object's `templatePath`.
            @param prefix: A prefix string to be inserted when trying to find
                a template file.
            @param suffix: A suffix string to be appended when trying to find
                a template file.
            @param startComment: Text to include in a comment before the
                template contents.
            @param endComment: Text to include in a comment after the
                template contents.
        """
        filename = self.getTemplateFile(name, path, prefix, suffix)
        basename = os.path.basename(filename)

        with open(filename, 'r') as f:
            # Read the template and insert data from keyword arguments.
            templateArgs = self.templateArgs.copy()
            templateArgs.update(kwargs)
            templateSrc = self.formatter.format(f.read(), **templateArgs)

        template = ET.fromstring(templateSrc)
        if startComment:
            self.xmlComment(template, 'From template %s' % basename)
        if endComment:
            self.xmlComment(template, 'End of %s' % basename, end=True)
        return template


    #===========================================================================
    # 
    #===========================================================================
    
    def __init__(self, birth, templatePath=paths.TEMPLATE_PATH, template=None):
        """ Constructor.
        
            @param birth: The `products.models.Birth` object of the recorder
                for which to generate the templates.
            @param templatePath: The root directory of the template fragment
                XML files.
        """
        self.templatePath = templatePath
        self.templateFile = template
        self.birth = birth
        self.device = birth.device
        self.formatter = EvalFormatter()
        
        self.templateArgs = {'birth': birth, 'device': self.device,
                             'user': USER, 'machine': MACHINE}
        
        if template is None:
            self.templateFile = birth.getTemplateName()
        
        self.template = None
        

    def __repr__(self):
        return "<%s (for %s) at 0x%X>" % (self.__class__.__name__, self.birth,
                                          id(self))
        

    def generate(self):
        """ Add additional product-specific data to the template. Override this
            when subclassing for future devices.
        """
        self.template = self.readTemplate(self.templateFile, path="", 
                                          endComment=False)
        
        self.xmlComment(self.template, 'Manifest for %s' % self.birth)
        
        if self.birth.fwCustomStr:
            # Add custom firmware name. NOTE: This does direct template
            # manipulation, so don't try it with future (non-SlamStick) devices.
            el = ET.Element('FwCustomStr', {'value': self.birth.fwCustomStr})
            self.template.find('./SystemInfo').append(el)
        
        # The insertion point for sensors
        parent = self.template.find('.')
        
        # Sensors, sorted analog first, then by ID
        sensors = models.Sensor.objects.filter(device=self.device)
        for sensor in sensors.extra(order_by=['-info__analog', 'sensorId']):
            parent.extend(self.makeSensor(sensor))
        
        # Battery
        if self.device.battery:
            parent.extend(self.makeBattery(self.device.battery))
        

    def makeSensor(self, sensor):
        """ Create an XML element for a Sensor from its template fragment,
            including its channels (if it has any).
            
            @param sensor: The `products.models.Sensor` from which to generate
                the XML.
        """
        # Hack to fix ``<AnalogSensorCalIDRef>`` if `None`. Doesn't change DB.
        if sensor.calibrationId is None:
            sensor.calibrationId = 0
            
        # Get the template file. For an analog sensor, the fragment will
        # contain an ``<AnalogSensorInfo>`` element with formatter tags for
        # various values (e.g. `sensor.serialNumber`). Digital sensor fragments
        # typically just have a single device-specific element, no tags.
        template = self.readTemplate(sensor.getTemplateName(), sensor=sensor)
        parent = self.getNonComment(template)

        # Add analog sensor channels. Digital sensors don't have any.
        channels = sensor.getChannels()
        for channel in channels:
            frag = self.readTemplate("AnalogSensorChannel.xml", 
                                     channel=channel)
            parent.extend(frag)

        return template
    
    
    def makeBattery(self, battery):
        """ Create an XML element for a Battery from its template fragment.
        """
        template = self.readTemplate(battery.getTemplateName(), battery=battery)
        return template
    
    
    #===========================================================================
    # 
    #===========================================================================
    
    def writeXML(self, filename, pretty=True, backup=True):
        """ Write the compiled template as pretty XML.

            @param filename: The name of the file to write.
            @param pretty: If `True`, do some extra work to make the XML
                more human-readable.
            @param backup: If `True`, made a backup copy of the XML file
                (if it exists) before starting to write.
        """
        if self.template is None:
            self.generate()
        
        if backup:
            makeBackup(filename)
        
        if not pretty:
            self.template.write(filename, "utf-8")
            return
        
        with open(filename, 'w') as f:
            s = ET.tostring(self.template, encoding="utf-8")
            
#             if not pretty:
#                 f.write(s)
#                 return
            
            # Convert to a `xml.dom.minidom.Document` first. Kind of an ugly
            # hack, but the stock ElementTree doesn't really do pretty-printing
            # (the `lxml` fork introduced it).
            x = parseString(s)
             
            temp = StringIO()
            x.writexml(temp, addindent="    ", newl="\n", encoding="utf-8")
 
            # Hack to remove blank lines from included fragments. There's got
            # to be a better way, but just removing `el.text` and `el.tail`
            # didn't get everything. Not a requirement, but it makes the
            # generated XML easier to read (by humans).
            temp.seek(0)
            for line in temp:
                if line.strip():
                    f.write(line)
    
    
    def writeEBML(self, filename, backup=True):
        """ Write the compiled template as EBML.
            
            @param filename: The name of the file to write, or an open,
                writable stream.
            @param backup: If `True`, made a backup copy of the EBML file
                (if it exists) before starting to write.
        """
        if self.template is None:
            self.generate()
        
        if backup:
            makeBackup(filename)

        schema = ebmlite.loadSchema(self.SCHEMA)
        ebmlite.util.xml2ebml(self.template, filename, schema,
                              headers=False)


    def dumpXML(self, pretty=True):
        """ Render the compiled template to an XML string.
        """
        # Write to a temporary file, then read the contents.
        xmlfile = tempfile.mkstemp()[1]
        self.writeXML(xmlfile, pretty=pretty, backup=False)
        with open(xmlfile, 'r') as f:
            return f.read()


    def dumpEBML(self):
        """ Render the compiled template to an EBML string.
        """
        # Write to a fake file (BytesIO), then read the contents.
        temp = BytesIO()
        self.writeEBML(temp, backup=False)
        temp.seek(0)
        return temp.read()


#===============================================================================
# 
#===============================================================================

class DefaultCalTemplater(ManifestTemplater):
    """ Class to manufacture the default calibration data for a freshly birthed
        recorder, so the calibration recordings can be made. Unlike the 'real'
        `CalTemplater`, this works using a `Birth` instead of a `CalSession`.
    """
    SCHEMA = 'mide_ide.xml'

    def __init__(self, birth,  template=None, templatePath=paths.TEMPLATE_PATH):
        """ Constructor.
        
            @param birth: The `products.models.Birth` object of the recorder
                for which to generate the templates.
            @param template: The name of the 'base' XML fragment.
            @param templatePath: The root directory of the template fragment
                XML files.
        """
        self.templatePath = templatePath
        
        try:
            if template is None:
                template = "Cal_" + birth.getTemplateName()
            _name = self.getTemplateFile(template)
        except IOError as err:
            # Use default if no specific file exists.
            if err.errno == errno.ENOENT:
                template = "Cal_Default.base.xml"
            else:
                raise
        
        self.usedIds = []
        
        super(DefaultCalTemplater, self).__init__(birth, template=template,
                                                  templatePath=templatePath)
        

    def makeSensorCal(self, sensor):
        """ Create the default calibration element(s) for one Sensor, if 
            that Sensor has a corresponding template file. Its template
            may contain multiple ``UnivariatePolynomial`` or 
            ``BivariatePolynomial`` elements (e.g. conversion for pressure
            and temperature).
        """
        if sensor.info:
            # Don't add duplicate sensor calibration (all axes on an S use the
            # same one, so it only needs to be represented once.)
            if sensor.calibrationId in self.usedIds:
                return None
            
            # First, try to use the `birthCalTemplateFile`.
            if sensor.info.birthCalTemplateFile:
                
                try:
                    return self.readTemplate(sensor.info.birthCalTemplateFile,
                                             sensor=sensor)
                except IOError as err:
                    # File-not-found is OK, other IOErrors not so much.
                    if err.errno != errno.ENOENT:
                        raise
            
            # Second, try a generic template based on the sensor info.
            try:
                result = self.readTemplate(sensor.info.name,
                                         prefix="Cal_", suffix="_Default",
                                         sensor=sensor)
                
                # Digital sensors will all have calibrationId==None, so
                # don't add that to the 'used IDs' list.
                if sensor.calibrationId is not None:
                    self.usedIds.append(sensor.calibrationId)
                
                logger.info("Loaded default cal fragment for %s" % sensor)
                return result
            
            except IOError as err:
                if err.errno != errno.ENOENT:
                    raise
                
                if 'Sensor' in str(err) and 'Reset' not in str(err):
                    logger.warning("%s (probably okay)" % err)
                
        return None


    def makeSensorChannelCal(self, sensor, channel):
        """ Create the default calibration element(s) for one SensorChannel, 
            if there is an explicitly-defined one set in the DB.
        """
        # First, try to use `channel.info.birthCalTemplateFile`
        if channel.info:
            if channel.info.birthCalTemplateFile:
                try:
                    return self.readTemplate(channel.info.birthCalTemplateFile,
                                             sensor=sensor, channel=channel)
                except IOError as err:
                    if err.errno != errno.ENOENT:
                        raise
        
        return None


    def generate(self):
        """ Fill out the generic ``CalibrationList`` data.
        """
        self.template = self.readTemplate(self.templateFile, path="",
                                          endComment=False)

        self.xmlComment(self.template, 'Default calibration data for %s' %
                        self.birth)

        for s in self.device.getSensors():
            stemplate = self.makeSensorCal(s)
            if stemplate is not None:
                self.template.extend(stemplate)
            
            for sc in s.getChannels():
                ctemplate = self.makeSensorChannelCal(s, sc)
                if ctemplate is not None:
                    self.template.extend(ctemplate)
            
            
#===============================================================================
# 
#===============================================================================

class CalTemplater(DefaultCalTemplater):
    """ Class to manufacture Slam Stick calibration data from information in
        the database. It works by assembling multiple XML fragments and 
        inserting values.
    """

    def __init__(self, session, templatePath=paths.TEMPLATE_PATH,
                 template="Cal_LOG-000x.base.xml"):
        """ Constructor.
        
            @param session: The `products.models.CalSession` object from which
                to generate the template.
            @param templatePath: The root directory of the template fragment
                XML files.
            @param template: The default 'base' template to use.
        """
        self.session = session
        self.axes = models.CalAxis.objects.filter(session=session)
        self.usedIds = []
        
        birth = session.device.getLastBirth()
        super(CalTemplater, self).__init__(birth, template, templatePath)
        
        # Used by `readTemplate()`
        self.templateArgs['session'] = session
        

    def makeAxisCal(self, axis):
        """ Add the CalibrationList element for one axis.
        """
        name = axis.getTemplateName()
        if not name:
            if axis.channelId is not None and axis.subchannelId is not None:
                name = "CalAxisBivariate"
            else:
                name = "CalAxisUnivariate"

        t = self.readTemplate(name, axis=axis, sensor=axis.sensor,
                              startComment=False, endComment=False)
        if len(t):
            self.xmlComment(t[0], 'Calibration for %s' % axis.axis)
        
        return t


    def addTraceData(self, session, parent):
        """ Append the traceability data to the end of the XML document. Note
            that this actually modifies the the parent element, unlike the
            other 'make' methods.
        """
        # It seems somewhat inconsistent for this not to use a template.
        if session.date:
            # TODO: Make expiration date a field in the DB?
            date = calendar.timegm(session.date.utctimetuple())
            expiration = date + (60 * 60 * 24 * 365)
            ET.SubElement(parent, 'CalibrationDate', {'value': str(date)})
            ET.SubElement(parent, 'CalibrationExpiry', {'value': str(expiration)})
        else:
            logger.error("No calibration date for %r, continuing anyway..." %
                         session)
            
        calSerial = session.sessionId
        ET.SubElement(parent, 'CalibrationSerialNumber', {'value': str(calSerial)})


    def generate(self):
        """ Build the ``CalibrationList`` XML.
        """
        self.template = self.readTemplate(self.templateFile, path="",
                                          endComment=False)

        self.xmlComment(self.template, 'Calibration data for %s' % self.birth)

        parent = self.template.find('.')
        
        # Create the individual calibrated axes.
        for axis in self.axes:
            c = self.makeAxisCal(axis)
            if c is not None:
                parent.extend(c)
                logger.info("Added calibration for %r" % axis)
            else:
                logger.warning("Could not make Calibration for %r, "
                               "might be okay" % axis)

        # Add the base calibration for all sensors, if applicable.
        baseSensors = self.session.device.getSensors()
        
        for sensor in baseSensors:
            frag = self.makeSensorCal(sensor)
            if frag is not None:
                parent.extend(frag)
        
        self.addTraceData(self.session, parent)


    def makeSensorCal(self, sensor):
        """ Create the base calibration element(s) for one Sensor, if 
            that Sensor has a corresponding template file. Its template
            may contain multiple ``UnivariatePolynomial`` or 
            ``BivariatePolynomial`` elements (e.g. conversion for pressure
            and temperature).
        """
        result = None

        if sensor.info:
            # Don't add duplicate sensor calibration (all axes on an S use the
            # same one, so it only needs to be represented once.)
            if sensor.calibrationId in self.usedIds:
                return None
            
            # First, try to use the sensor info's `calTemplateFile`.
            if sensor.info.calTemplateFile:
                try:
                    return self.readTemplate(sensor.info.calTemplateFile,
                                             sensor=sensor)
                except IOError as err:
                    # File-not-found is OK, other IOErrors not so much.
                    if err.errno != errno.ENOENT:
                        raise

            # Second, try a generic base template based on the sensor name.
            try:
                result = self.readTemplate(sensor.info.name, prefix="Cal_",
                                           sensor=sensor)
                logger.info("Loaded base cal fragment for %s" % sensor)

            except IOError as err:
                if err.errno != errno.ENOENT:
                    raise

            # Third, fall back to using the birth default template.
            if result is None:
                try:
                    if sensor.info.birthCalTemplateFile:
                        # Explicitly named birth cal template
                        result = self.readTemplate(sensor.info.birthCalTemplateFile,
                                                   sensor=sensor)
                    else:
                        # Look for a template based on the sensor name
                        result = self.readTemplate(sensor.info.name, prefix="Cal_",
                                                   suffix="_Default", sensor=sensor)

                    logger.info("Loaded default cal fragment for %s" % sensor)

                except IOError as err:
                    if err.errno != errno.ENOENT:
                        raise

            if result is not None:
                # Digital sensors will all have calibrationId==None, so
                # don't add that to the 'used IDs' list.
                if sensor.calibrationId is not None:
                    self.usedIds.append(sensor.calibrationId)
                return result

        logger.info("No base calibration for %s (probably okay)" % sensor)

        return None


#===============================================================================
# 
#===============================================================================

class CalCertificateTemplater(object):
    """ Generate the calibration certificate: populate fields in an SVG and
        convert it to PDF. 
        
        The certificate is built differently than the other templates. It is a
        single file, rather than one assembled from fragments. Also, the
        string specifying the content and format of each field is stored in
        each ``<text>`` element's ``<desc>`` child element. 
    """

    # PDF generation commands.
    if 'bin' in paths.INKSCAPE_PATH:
        # For Inkscape >= 1.0
        CONVERT_COMMAND = '"{exe}" --export-filename "{pdfname}" "{svgname}"'
    else:
        # For Inkscape < 1.0
        CONVERT_COMMAND = '"{exe}" -f "{svgname}" -A "{pdfname}"'


    def __init__(self, session, templatePath=paths.CERTIFICATE_PATH,
                 template=None):
        """ Constructor.
        
            @param session: The `products.models.CalSession` object from which
                to generate the template.
            @param templatePath: The root directory of the template fragment
                XML files.
            @param template: The default 'base' template to use.
        """
        self.session = session
        birth = session.device.getLastBirth()
        self.templatePath = templatePath
        self.templateFile = template
        self.birth = birth
        self.device = birth.device
        self.axes = models.CalAxis.objects.filter(session=session)
        self.cal = {}
        self.reference = None
        self.formatter = EvalFormatter()
        
        for axis in self.axes:
            calId = axis.calibrationId
            if calId in self.cal:
                logger.warning("Calibration ID %s defined more than once!" % calId)
            self.cal[calId] = axis
            
            # NOTE: This will need to change if we ever use multiple references
            if axis.reference:
                self.reference = axis.reference
        
        # Set up 'primary' and 'secondary' accelerometer calibration
#         self.calPrimary = self.calSecondary = None
#         if 80 in self.cal:
#             self.calPrimary = XYZ(self.cal[33], self.cal[34], self.cal[35])
#             self.calSecondary = XYZ(self.cal[81], self.cal[82], self.cal[83])
#         elif 8 in self.cal:
#             self.calPrimary = XYZ(self.cal[1], self.cal[2], self.cal[3])
#             if 32 in self.cal:
#                 self.calSecondary = XYZ(self.cal[33], self.cal[34], self.cal[35])
#         else:
#             self.calPrimary = XYZ(self.cal[33], self.cal[34], self.cal[35])
        
        self.templateArgs = {'birth': self.birth,
                             'cal': self.cal,
#                              'primary': self.calPrimary,
#                              'secondary': self.calSecondary,
                             'session': self.session,
                             'certificate': self.session.certificate,
                             'reference': self.reference}

        if not self.templateFile:
            self.templateFile = session.certificate.getTemplateName()
            
        self.template = None

    
    def getFields(self):
        """
        """
        fields = self.template.findall('.//svg:text', NS)
        return [el for el in fields if el.find('svg:desc', NS) is not None]


    def populateField(self, el):
        """
        """
        desc = el.find('svg:desc', NS)
        if desc is None:
            return
        
        desc = desc.text.strip()
        if not desc:
            return

        # Format the field. Failure *is* an option.
        try:
            val = self.formatter.format(desc, **self.templateArgs)
            
            # Most fields contain a <tspan> with the actual text. In the past,
            # some had the contents in the <text> element itself. Handle both.
            spans = el.find('svg:tspan', NS)
            if spans is not None:
                spans.text = val
            else:
                print("no tspan")
                for ch in el:
                    ch.text = ""
                    ch.tail = ""
                el.text = val
            
        except (AttributeError, IndexError, KeyError, NameError) as err:
            logger.warning("%s: %s" % (desc, err))
        
        except ValueError:
            logger.error("Failed to parse %r" % desc)
            raise


    def generate(self):
        """
        """
        self.template = ET.parse(os.path.join(self.templatePath,
                                              self.templateFile))

        for field in self.getFields():
            self.populateField(field)


    def writePDF(self, filename, removeSvg=True, exe=paths.INKSCAPE_PATH):
        """ Export the PDF certificate. Internally, it writes to a SVG, and
            then uses Inkscape (via its command-line interface) to generate
            a PDF. 
        
            @param filename: The generated PDF name. The resulting file will
                get the extension `.pdf`, even if `filename` doesn't have it.
            @param removeSvg: If `True`, delete the intermediate SVG file.
            @param exe: The path to the Inkscape executable.
            @return: The name of the generated certificate PDF.
        """
        if not os.path.exists(exe):
            raise IOError(errno.ENOENT, 'Inkscape application not found', exe)

        if self.template is None:
            self.generate()
        
        name = os.path.splitext(filename)[0]
        svgname = os.path.realpath(name + ".svg")
        pdfname = os.path.realpath(name + ".pdf")
        errfile = os.path.join(tempfile.gettempdir(), 'svg_err.txt')

        self.template.write(svgname)
        
        with open(errfile, 'w') as f:
            cmd = self.CONVERT_COMMAND.format(exe=exe, svgname=svgname, pdfname=pdfname)
            logger.debug(f'Generating PDF via "{cmd}"')
            result = subprocess.call(cmd, stdout=sys.stdout, stdin=sys.stdin, 
                                     stderr=f, shell=True)

        if result != 0:
            logger.error(f'Call to Inkscape finished with exit code {result}')

            with open(errfile, 'r') as f:
                err = (f.read().replace('\n', ' ').replace('\r', '').strip()
                       or "no information dumped to stderr")

            raise IOError(f"Execution of Inkscape failed (code {result}): {err}")

        if removeSvg and os.path.isfile(pdfname) and os.path.isfile(svgname):
            os.remove(svgname)
            
        return pdfname


#===============================================================================
#
#===============================================================================

def remakeCertificate(sn, filename=None):
    """ Recreate the latest calibration certificate for a given device SN.

        @param sn: A recorder serial number, or a `Birth` instance.
        @param filename: The PDF filename, overriding the default.
        @returns: The name of the generated file.
    """
    if isinstance(sn, models.Birth):
        sn = sn.serialNumber

    b = models.getBirth(sn)
    cal = b.device.calsession_set.latest('date')
    ct = CalCertificateTemplater(cal)

    filename = filename or f"{b.serialNumberString}_Calibration_Certificate_C{cal.sessionId}.pdf"

    return ct.writePDF(filename)
