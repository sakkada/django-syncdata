from django.conf import settings

IMPORTERS = getattr(settings, 'SYNCDATA_IMPORTERS', {})
DATA_DIR = getattr(settings, 'SYNCDATA_DATA_DIR', settings.BASE_DIR)
