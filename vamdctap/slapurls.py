from django.urls import re_path
from django.conf import settings
import django.views.static
from vamdctap.slapviews import lines, species, availability, capabilities

#import vamdctap
urlpatterns = [re_path(r'^lines[/]?$', lines),
               re_path(r'^species[/]?$', species),
               re_path(r'^availability[/]?$', availability),
               re_path(r'^capabilities[/]?$', capabilities),
               ]



if settings.SERVE_STATIC:
    import django.views.static
    urlpatterns += [re_path(r'^static/(?P<path>.*)$',
                    django.views.static.serve,
                    {'document_root': settings.BASE_PATH+'/static'}),
                    ]

