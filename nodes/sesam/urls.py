#~ from django.conf.urls.defaults import *
from django.urls import re_path, include

# Uncomment the next two lines to enable the admin:
#from django.contrib import admin
#admin.autodiscover()

urlpatterns =  [
    re_path(r'^tap/', include('vamdctap.urls')),
    re_path(r'^slap/', include('vamdctap.slapurls')),
]

handler500 = 'vamdctap.views.tapServerError'
handler404 = 'vamdctap.views.tapNotFoundError'
