from django import forms


class FirmwareForm(forms.Form):
    fwRevision = forms.CharField(label='Firmware Revision', max_length=200, required=False)
