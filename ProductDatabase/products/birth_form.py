from django import forms


class BirthForm(forms.Form):
    serialNumber = forms.CharField(label='Serial Number', max_length=200, required=False)
