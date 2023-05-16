from __future__ import absolute_import, unicode_literals

from django.conf.urls import url
from django.urls import path

from . import views

app_name = 'products'
urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('search', views.search, name='search'),
    path('birth_info', views.birth_info, name='birth_info'),
    path('device_info', views.birth_info, name='device_info'),
    path('fw_info', views.birth_info, name='fw_info'),
]
