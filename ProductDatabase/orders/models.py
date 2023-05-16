# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

import datetime

from django.db import models
import django.utils.timezone


class Order(models.Model):
    """
    """
    orderId = models.CharField(max_length=80,
        help_text="The order number or ID")
    customer = models.CharField(max_length=80, blank=True,
        help_text="The customer placing the order")
    date = models.DateField(default=datetime.date.today,
        help_text="The date the order was received")
    notes = models.TextField(blank=True,
        help_text="General notes about the order")
