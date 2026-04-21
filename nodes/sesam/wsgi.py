import os
import sys

sys.path.append('/app')

# Add the app's directory to the PYTHONPATH
os.environ['DJANGO_SETTINGS_MODULE'] = 'nodes.sesam.settings'

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()

