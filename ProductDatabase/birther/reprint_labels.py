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
        self.skuField = wx.TextCtrl(pane, -1, str(self.dev.partNumber))
        self.skuField.SetSizerProps(expand=True, proportion=2)

        self.calLabelCheck = wx.CheckBox(pane, -1, "Print Calibration label")
        self.calLabelCheck.SetSizerProps(expand=True, proportion=1)
        self.calList = wx.Choice(pane, -1, choices=calNames)
        self.calList.SetSizerProps(expand=True, proportion=2)

        self.nameLabelCheck.SetValue(True)

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


    @classmethod
    def printLabels(cls, dev=None, name=None, session=None, printer=None):
        """ Print one or both labels.

            :param dev: The device in need of labels.
            :param name: The name (SKU) printed on the serial number label.
                `None` to skip this label.
            :param session: The CalSession to print. `None` to skip this
                label.
            :param printer: The label printer to use. Defaults to first
                found. Almost always `None`.
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
                    return False

            if name:
                sku = dev.partNumber
                sn = dev.serial
                labels.printBirthLabel(sku, sn, printer=printer)

            if session:
                labels.printCalLabel(session.sessionId, session.date, printer=printer)

            return True

        except RuntimeError:
            wx.MessageBox("The printer SDK components could not be loaded.\n\n"
                          "Have they been installed?", "Label Printing Error",
                          wx.OK | wx.ICON_ERROR)
            return False


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
                dlg.printLabels(dev=dev, **kwargs)


if __name__ == "__main__":
    app = wx.App()
    main()
