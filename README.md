# A django-syncdata project

Application, that allows to define import process with data loading, including
attached media files, such as images or documents, data validation via builtin
form validation mechanizm and data generation by method, similar to loaddata
django builtin command's generation method (with help of deserializer).

----

# Requirements

* Python (2.7, 3.3, 3.4, 3.5, 3.6)
* Django (1.8, 1.9, 1.10, 1.11)

# Installation

Install using `pip`:

    pip install django-syncdata

or

    pip install -e hg+https://bitbucket.org/sakkada/django-syncdata/@django-1.11.x#egg=django-syncdata-dev

Add `syncdata` to installed apps and `syncdata` options to `settings.py`:

```python
INSTALLED_APPS = (
    ...  # Default installed apps here
    'syncdata',
)

# Syncdata
SYNCDATA_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, 'syncdata'))
SYNCDATA_IMPORTERS = {
    'importername': 'main.sync.ProjectXMLImporter',
}
```

**ToDo**: describe example with models, Loaders, ModelHandlers and Importers.

Add `SyncDataLogEntry` model to `main/models.py` (`main` just for example):

```python
from syncdata.models import BaseSyncDataLogEntry


class SyncDataLogEntry(BaseSyncDataLogEntry):
    pass
```

Add `SyncDataLogEntry` to Django administration panel (`main/admin.py`):

```python
from syncdata.admin import SyncDataLogEntryAdmin
from main import models

admin.site.register(models.SyncDataLogEntry, SyncDataLogEntryAdmin)
```

Run data synchronization process:

    python manage.py syncdata -i importername -p "main.generate=True main.download=True"

And go to the Admin page `http://127.0.0.1:8000/admin/main/syncdatalog/` to
watch results of import process.

----
Source code at [bitbucket.org][bitbucket] and [github.com][github].

[github]: https://github.com/sakkada/django-syncdata
[bitbucket]: https://bitbucket.org/sakkada/django-syncdata