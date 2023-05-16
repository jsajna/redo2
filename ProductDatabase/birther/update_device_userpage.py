"""
GUI for selecting a connected device and regenerating its USERPAGE.
"""
from __future__ import print_function
import argparse
import logging

import wx

import generate_userpage  # Python paths will be set up after importing generate_userpage
from widgets.device_dialog import selectDevice

# Set `True` to prevent update command and show more debugging messages
__DEBUG__ = False

if __name__ == "__main__":
    argparser = argparse.ArgumentParser(description=__doc__)
    argparser.add_argument('--debug', '-d',
                           action="store_true",
                           help="Show additional debugging information")
    argparser.add_argument('--noapply', '-n',
                           action="store_true",
                           help="Don't send the 'Update Userpage' command ('up') after building userpage.bin "
                                "(intended for testing)")
    args = argparser.parse_args()

    if __DEBUG__ or args.debug:
        generate_userpage.template_generator.logger.setLevel(logging.DEBUG)
    else:
        generate_userpage.template_generator.logger.setLevel(logging.ERROR)

    app = wx.App()

    while True:
        dev = selectDevice(hideClock=True, hideRecord=True, showWarnings=False, showAdvanced=True,
                           title="USERPAGE (Manifest/Calibration) Updater",
                           okText="Reapply Selected Device's USERPAGE", cancelText="Cancel")
        if not dev:
            break

        print("Selected: %s" % dev)

        try:
            generate_userpage.updateDevice(dev.path, apply=not args.noapply)
            msg = "Update of %s completed\n\nReapply another device's USERPAGE?" % dev.serial
        except Exception as err:
            msg = "Failed to update %s\n\n%r\n\nTry updating another device's USERPAGE?" % (dev.serial, err)

        if wx.MessageBox(msg, "Update Complete", wx.YES_NO | wx.YES_DEFAULT) == wx.NO:
            break

    exit(0)
