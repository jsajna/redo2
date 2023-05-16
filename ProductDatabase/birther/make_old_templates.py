'''
Created on Jan 13, 2020

@author: dstokes
'''
import logging
import os
import shutil
import sys

# Django setup
sys.path.insert(0, os.path.realpath('../ProductDatabase'))
os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

import django
django.setup()

# My Django components
from products import models
import template_generator as TG
import util

#===============================================================================
# 
#===============================================================================

OLD_PATH = r"R:\LOG-Data_Loggers\LOG-0002_Slam_Stick_X\Design_Files\Firmware_and_Software\Manufacturing\LOG-XXXX-SlamStickX_Birther\data_templates"
ROOT_PATH = os.path.join(os.path.dirname(__file__), 'updater_templates')

TG.logger.setLevel(logging.WARNING)


#===============================================================================
# 
#===============================================================================

def makeTemplates(rootPath=ROOT_PATH):
    """
    """
    prods = list(models.Product.objects.all())
    for prod in prods:
        ex = models.Birth.objects.filter(serialNumber=-1, product=prod).last()
        if not ex:
            continue
        
        man = TG.ManifestTemplater(ex)
        cal = TG.DefaultCalTemplater(ex)
        
        oldPath = os.path.join(OLD_PATH, ex.partNumber, str(ex.device.hwRev))
        path = os.path.join(rootPath, ex.partNumber, str(ex.device.hwRev))
        util.safeMakedirs(path)
        
        if os.path.isdir(oldPath):
            print("Copying old templates to %s" % path)
            mt = os.path.join(oldPath, 'manifest.template.xml')
            ct = os.path.join(oldPath, 'cal.template.xml')
            if os.path.isfile(mt):
                shutil.copy2(mt, os.path.join(path, 'manifest.template.xml'))
            if os.path.isfile(ct):
                shutil.copy2(ct, os.path.join(path, 'cal.template.xml'))
            continue
        
        print("Making new templates in %s" % path)
        
        # SerialNumber is a UINT in EBML, but examples are SN -1. Temporarily
        # change it. Does not get saved back to DB.
        ex.serialNumber=0
        man.writeXML(os.path.join(path, 'manifest.template.xml'), backup=False)
        cal.writeXML(os.path.join(path, 'cal.template.xml'), backup=False)
#         man.writeEBML(os.path.join(path, 'manifest.template.ebml'), backup=False)
#         cal.writeEBML(os.path.join(path, 'cal.template.ebml'), backup=False)
        ex.serialNumber=-1
