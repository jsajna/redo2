# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import datetime

from django.views import generic

from .models import Birth, Device, CalSession
from django.shortcuts import render
from .birth_form import BirthForm
from .device_form import DeviceForm
from .fw_form import FirmwareForm
from .date_form import DateForm

# ===============================================================================
#
# ===============================================================================


class IndexView(generic.ListView):
    """
        This creates a very basic page for when you just go to /products
        Has the ability to be extended if more than a search ability was to be added
    """
    template_name = 'products/index.html'
    context_object_name = 'latest_question_list'

    def get_queryset(self):
        """Return the last five published questions."""
        return Birth.objects.all()


def search(request):
    """
        This creates the forms for searching by Birth Serial Number and Device Chip ID
        BirthForm() is for the Birth Serial Number form
        DeviceForm() is for the Device Chip ID form
    """
    # creates form
    form = BirthForm()
    form2 = DeviceForm()
    form3 = FirmwareForm()
    form4 = DateForm()
    # renders the search page with the form
    return render(request, 'products/search.html', {'form': form,
                                                    'form2': form2,
                                                    'form3': form3,
                                                    'form4': form4})


def birth_info(request):
    """
        This renders either birth_info.html or device_info.html depending on what search is done
        Both pages are done in this one method so that both forms can just use one search button
    """
    form = BirthForm(request.GET)
    form2 = DeviceForm(request.GET)
    form3 = FirmwareForm(request.GET)
    form4 = DateForm(request.GET)
    # checks to make sure form fields were filled
    if form.is_valid():
        # Grabs the inputted serial number with letters and leading zeros taken out
        sn = form.cleaned_data['serialNumber']
        if not sn == '':
            return birth(request, sn)
        else:
            if form2.is_valid():
                # Gets data from the inputted chipId
                ci = form2.cleaned_data['chipId']
                if not ci == '':
                    # Adds leading spaces until fix comes
                    ci = ci.rjust(16)
                    return device(request, ci)
                elif form3.is_valid():
                    fw = form3.cleaned_data['fwRevision']
                    if not fw == '':
                        return fw_revision(request, fw)
                    elif form4.is_valid():
                        dr = form4.cleaned_data['dateRange']
                        if not dr == '':
                            return date(request, dr)
                        else:
                            # creates form
                            form = BirthForm()
                            form2 = DeviceForm()
                            form3 = FirmwareForm()
                            form4 = DateForm()
                            error = True
                            # renders the search page with the form
                            return render(request, 'products/search.html', {'form': form,
                                                                            'form2': form2,
                                                                            'form3': form3,
                                                                            'form4': form4,
                                                                            'error': error})


def birth(request, sn):
    """
        This creates the render statements for the birth_info.html page
        It does error checking on user input and creates the information to be passed to the template
    """
    # Removes leading letters and 0s
    serial = ''.join(filter(str.isdigit, sn)).strip("0")
    if serial.isnumeric() and Birth.objects.filter(serialNumber=serial).exists():
        data = Birth.objects.filter(serialNumber=serial)
        cal = CalSession.objects.filter(device=data.last().device)
        cal_bool = cal.count() > 0
        # Adds leading spaces until fix comes
        chip_id = data.last().device.chipId.strip().rjust(16)
        # Creates manifest path
        url = '\\\MIDE2007\Products\LOG-Data_Loggers\LOG-0002_Slam_Stick_X\Product_Database\\' + chip_id
        zip_info = zip(data, cal)
        # Creates new forms in order to clear search fields (should be way around this)
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Birth information for " + sn
        # Puts information for page in json object
        info = {'title': title,
                'data': data,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'cal': cal,
                'url': url,
                'calBool': cal_bool,
                'zip': zip_info}
    else:
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Birth information for " + sn + " does not exist"
        # Puts information for page in json object
        info = {'title': title,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'error': True}
    # Renders the page with data from the serial number
    return render(request, 'products/birth_info.html', info)


def device(request, ci):
    """
        This creates the render statements for the device_info.html page
        It does error checking on user input and creates the information to be passed to the template
    """
    if Device.objects.filter(chipId=ci).exists():
        data = Device.objects.filter(chipId=ci)
        birth_data = Birth.objects.filter(device_id=data.last().id)
        # Gets if the device has been calibrated
        cal = CalSession.objects.filter(device=data.last()).count() > 0
        # Creates manifest path
        url = '\\\MIDE2007\Products\LOG-Data_Loggers\LOG-0002_Slam_Stick_X\Product_Database\\' + ci
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Device information for " + ci
        # Puts information for page in json object
        info = {'title': title,
                'data': birth_data,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'cal': cal,
                'url': url}
    else:
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Device " + ci + " does not exist"
        # Puts information for page in json object
        info = {'title': title,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'error': True}
    # Renders page with data from the chipId
    return render(request, 'products/device_info.html', info)


def fw_revision(request, fw):
    if fw.isnumeric() and Birth.objects.filter(fwRev=fw).exists():
        data = Birth.objects.filter(fwRev=fw)
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Birth information for Firmware Release " + fw
        # Puts information for page in json object
        info = {'title': title,
                'data': data,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4}
    else:
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Firmware Release " + fw + " is not valid"
        # Puts information for page in json object
        info = {'title': title,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'error': True}
    # Renders page with data from the chipId
    return render(request, 'products/birth_info.html', info)


def date(request, dr):
    """
        This creates the render statement for the birth_info page when a date range is entered
    """
    # Try except to make sure dates are inputted in proper format
    try:
        # Splits date range input into the two dates
        date1 = datetime.datetime.strptime(dr.split(',')[0].strip(), '%Y-%m-%d')
        date2 = datetime.datetime.strptime(dr.split(',')[1].strip(), '%Y-%m-%d')
        data = Birth.objects.filter(date__range=[date1, date2])
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Birth information for " + dr
        # Puts information for page in json object
        info = {'title': title,
                'data': data,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4}
        return render(request, 'products/birth_info.html', info)
    except ValueError:
        # Creates new forms in order to clear search fields
        form = BirthForm()
        form2 = DeviceForm()
        form3 = FirmwareForm()
        form4 = DateForm()
        # Creates title for top of page
        title = "Improper input format for date range " + dr
        # Puts information for page in json object
        info = {'title': title,
                'form': form,
                'form2': form2,
                'form3': form3,
                'form4': form4,
                'error': True}
        # Renders the page with data from the serial number
        return render(request, 'products/birth_info.html', info)
