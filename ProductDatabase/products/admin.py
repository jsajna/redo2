# -*- coding: utf-8 -*-
from __future__ import absolute_import, unicode_literals

from django.contrib import admin
from django.db.models import Model

import products.models

# XXX: This is probably a bad way to do it, but handy at the moment.
for name in dir(products.models):
    if not name[0].isupper():
        continue
    try:
        m = getattr(products.models, name)
        if issubclass(m, Model):
            admin.site.register(m)
    except (TypeError, AttributeError):
        # Not a class
        pass