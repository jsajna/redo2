from django import forms


class DeviceForm(forms.Form):
    chipId = forms.CharField(label='Chip ID', max_length=200, required=False, empty_value='')
