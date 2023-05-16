from django import forms


class DateForm(forms.Form):
    dateRange = forms.CharField(label='Date Range (yyyy-mm-dd, yyyy-mm-dd)', max_length=200, required=False)
