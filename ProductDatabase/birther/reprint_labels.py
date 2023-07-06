"""
Reprint the labels (serial number and/or calibration) for an attached
device.
"""
import os.path

from endaq.device import getDevices

import wx
import wx.lib.sized_controls as sc

# Django setup
os.environ['DJANGO_SETTINGS_MODULE'] = "ProductDatabase.settings"

import django.db
django.setup()

# My Django components
# NOTE: Django import paths are weird. Get `products.models` from Django itself instead of importing.
from django.apps import apps
models = apps.get_app_config('products').models_module

from . import labels


#===============================================================================
#
#===============================================================================

class ReprintDialog(sc.SizedDialog):
    """
    Main UI for the label re-printer.
    """

    def __init__(self, *args, **kwargs):
        """ The main dialog. Standard `wx.Dialog` arguments, plus:

            :param device: The device (`endaq.device.Recorder`) in need of
                labels.
            :param cals: A list of `CalSession` objects for the device.
        """
        self.dev = kwargs.pop('device')
        self.cals = kwargs.pop('cals', [])
        kwargs.setdefault('title', f"Reprint for {str(self.dev).strip('<>')}")
        kwargs.setdefault('style', wx.DEFAULT_DIALOG_STYLE|wx.RESIZE_BORDER)

        sc.SizedDialog.__init__(self, *args, **kwargs)

        if self.cals:
            calNames = [f"{s} ({s.date.date()})" for s in self.cals]
        else:
            calNames = []

        pane = self.GetContentsPane()
        pane.SetSizerType("form")

        self.nameLabelCheck = wx.CheckBox(pane, -1, "Print name/SN label")
        self.nameLabelCheck.SetSizerProps(expand=True)
        self.nameLabelCheck.SetValue(True)
        self.skuField = wx.TextCtrl(pane, -1, str(self.dev.partNumber))
        self.skuField.SetSizerProps(expand=True, proportion=2)

        self.calLabelCheck = wx.CheckBox(pane, -1, "Print Calibration label")
        self.calLabelCheck.SetSizerProps(expand=True, proportion=1)
        self.calList = wx.Choice(pane, -1, choices=calNames)
        self.calList.SetSizerProps(expand=True, proportion=2)

        wx.Panel(pane, -1, size=(8,8))  # Padding hack
        wx.Panel(pane, -1, size=(8,8))
        self.chainPrintCheck = wx.CheckBox(pane, -1, "Chain Print")
        self.chainPrintCheck.SetSizerProps(expand=True)
        self.chainPrintCheck.SetValue(True)
        self.chainPrintCheck.SetToolTip("Don't automatically cut the last label. "
                                        "Saves tape when calibrating multiple devices.")

        if not self.cals:
            self.calLabelCheck.SetValue(False)
            self.calLabelCheck.Enable(False)
            self.calLabelCheck.SetToolTip("Device has not been calibrated")
        else:
            self.calList.SetSelection(len(calNames) - 1)
            self.calLabelCheck.SetValue(True)

        self.calList.Enable(self.calLabelCheck.GetValue())
        self.skuField.Enable(self.nameLabelCheck.GetValue())

        self.SetButtonSizer(self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL))
        self.okBtn = self.FindWindowById(wx.ID_OK)
        self.okBtn.SetLabel("Print")

        self.calLabelCheck.Bind(wx.EVT_CHECKBOX, self.OnCalCheck)
        self.nameLabelCheck.Bind(wx.EVT_CHECKBOX, self.OnNameCheck)

        self.Fit()
        minsize = self.GetMinSize()
        self.SetSize((400, minsize[1]))
        self.SetMinSize((400, minsize[1]))

        self.Centre()



    def OnCalCheck(self, evt):
        """ Handle 'print calibration' checkbox changes. """
        self.calList.Enable(evt.IsChecked())


    def OnNameCheck(self, evt):
        """ Handle 'print name' checkbox changes. """
        self.skuField.Enable(evt.IsChecked())


    def OnPrintButton(self, evt):
        """ Handle the Print (OK) button press."""
        evt.Skip()

#===============================================================================
#
#===============================================================================

def main():
    devs = getDevices()
    if len(devs) != 1:
        wx.MessageBox(f"1 device required, {len(devs)} found.\n\n"
                "Make sure there is only one recorder attached and try again.",
                "Reprint Labels", wx.ICON_ERROR)
        return

    dev = devs[0]

    birth = models.getBirth(dev.serialInt)
    cals = list(models.CalSession.objects.filter(device=birth.device).order_by('date'))

    with ReprintDialog(None, -1, device=dev, cals=cals) as dlg:
        q = dlg.ShowModal()
        if q == wx.ID_OK:
            kwargs = {}
            if dlg.nameLabelCheck.GetValue():
                kwargs['name'] = dlg.skuField.GetValue()
            if dlg.calLabelCheck.GetValue():
                idx = dlg.calList.GetSelection()
                if idx >= 0:
                    kwargs['session'] = cals[idx]

            if kwargs:
                labels.printLabels(dev,
                                   chain=dlg.chainPrintCheck.GetValue(),
                                   parent=dlg,
                                   **kwargs)

#===============================================================================
#
#===============================================================================

if __name__ == "__main__":
    app = wx.App()
    main()
