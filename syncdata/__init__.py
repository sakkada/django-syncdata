"""
The example of data transformation on each step of syncdata processing.
See the details of syncdata process in "base.py" file in __doc__ strings and
comments.


1.  Loader classes phase
===============================================================================
    Loader classes should generate following data:
----
{
  # M2M model, which have m2m relation with Child model
  'app.m2m': [
    {
      'fields': {
        'naturalkeyone': '12345',   # natural key values which identifies
        'naturalkeytwo': '67890',   # object by both values simultaneously
        'name': 'M2M model object with natural key values',
      },
    },
    {
      # any in memory unique value to identify object while sync process
      '__hash__': 'e44c1c31a0bd673cc7f3c06077b795f1',
      'fields': {
        'name': 'M2M model object without natural key value',
      },
    },
  ],
  # Parent model, which Child model belongs to
  'app.parent': [
    {
      # any in memory unique value to identify object while sync process
      '__hash__': '382b7a535232de74e0ff6f8a813940d1',
      'fields': {
        'weight': 500,
        'name': 'Parent model without natural key value',
      },
    },
    {
      'fields': {
        'naturalkeyunique': '12345',  # natural key unique value of object
        'weight': 500,
        'name': 'Parent model with natural key value',
      },
    },
  ],
  # Child model, which have m2m and m2o relations with M2M and Parent model
  # respectively (it shows how to use syncdata application)
 'grohe.child': [
    {
      # defines, which fields values should be retreived by __hash__ index
      # not by selection by natural keys (hashed models already resolved ids)
      # note: models in hash_related should be imported before current model
      'hash_related': {
          'm2m': 'app.m2m',
      },
      'fields': {
        'name': 'Child model with m2m values and parent with natural key',
        # Parent model relation field, filtered by natural key value (really
        # while sync process parent object will be retreived by selection from
        # database by Parent.object.filter(naturalkeyunique=54321).first()
        # query)
        'parent': {'naturalkeyunique': '54321'},
        # M2M model m2m relation field filtered one by natural key (two values
        # simultaneously) and one by __hash__ value
        'm2m': [
          {'naturalkeyone': '12345', 'naturalkeytwo': '67890'},
          {'__hash__': 'e44c1c31a0bd673cc7f3c06077b795f1'},
        ],
      },
    },
    {
      'hash_related': {
          'parent': 'app.parent',
      },
      'fields': {
        'name': 'Child model with parent model with __hash__ value',
        # Parent model relation fields filtered by __hash__ value
        'parent': {'__hash__': '382b7a535232de74e0ff6f8a813940d1'},
        'm2m': [
          {'naturalkeyone': '12345', 'naturalkeytwo': '67890'},
          456,  # direct id value (if remote field is id) of object, which is
                # already exists in database (this is seldom usable method,
                # cause it is required to know real remote field values
                # before generation, which usually is not known)
        ],
      },
    },
  ],
}.
----


2.  Models Handlers (three models in the following order - M2M, Parent, Child)
===============================================================================
2.1 M2M
-------------------------------------------------------------------------------
2.1.1 M2M synchronize (in importer before handler run).
      Have no effects, because M2M have no any __hash__ relations.
2.1.2 M2M prepare action.
      Have no effects, because M2M have no any relations.
2.1.3 M2M validate action.
      After validation M2M values will be the following:
------
{
  'app.m2m': [
    {
      'fields': {
        'naturalkeyone': '12345',
        'naturalkeytwo': '67890',
        'name': 'M2M model object with natural key values',
      },
      'cleaned': {  # note: object will be updated, cause there is pk value
        'naturalkeyone': '12345',
        'naturalkeytwo': '67890',
        'name': 'M2M model object with natural key values',
        'pk': 123,  # in this example current object was in database before
                    # sync process and pk value=123 retreived by filter
                    # by (naturalkeyone=12345, naturalkeytwo=67890) if
                    # in ModelHandler in Meta class defined property
                    # class Meta:
                    #     natural_keys = ('naturalkeyone', 'naturalkeytwo',)
      },
      'valid': True,  # if it is invalid, there will be errors
    },
    {
      '__hash__': 'e44c1c31a0bd673cc7f3c06077b795f1',
      'fields': {
        'name': 'M2M model object without natural key value',
      },
      'cleaned': {  # note: object will be created, cause there is no pk value
        'name': 'M2M model object without natural key value',
      },
      'valid': True,
    },
  ],
  ...
}.
------
2.1.4 M2M generate action.
      Generation based on copied and modifiled data processing, format similar
      to loaddata format - dict with 'model', 'pk' and 'fields' keys,
      where 'pk' may be None or value. After generation, pk values will be
      inserted into original object dict. Data will be the following:
------
{
  'app.m2m': [
    {
      'fields': {
        'naturalkeyone': '12345',
        'naturalkeytwo': '67890',
        'name': 'M2M model object with natural key values',
      },
      'cleaned': {
        'naturalkeyone': '12345',
        'naturalkeytwo': '67890',
        'name': 'M2M model object with natural key values',
        'pk': 123,
      },
      'pk': 123,  # id is similar, because object was updated
      'valid': True,
    },
    {
      '__hash__': 'e44c1c31a0bd673cc7f3c06077b795f1',
      'fields': {
        'name': 'M2M model object without natural key value',
      },
      'cleaned': {
        'name': 'M2M model object without natural key value',
      },
      'pk': 987,  # new generated object pk value
      'valid': True,
    },
  ],
  ...
}.
------

2.2 Parent
-------------------------------------------------------------------------------
2.2.1 Parent synchronize (in importer before handler run).
      Have no effects, also because Parent have no any __hash__ relations.
2.2.2 Parent prepare action.
      Have no effects, also because Parent have no any relations.
2.2.3 Parent validate action.
      After validation Parent values will be the following:
------
{
  ...
  'app.parent': [
    {
      '__hash__': '382b7a535232de74e0ff6f8a813940d1',
      'fields': {
        'weight': 500,
        'name': 'Parent model without natural key value',
      },
      'cleaned': {
        'weight': 500,
        'name': 'Parent model without natural key value',
      },
      'valid': True,
    },
    {
      'fields': {
        'naturalkeyunique': '12345',
        'weight': 500,
        'name': 'Parent model with natural key value',
      },
      'cleaned': {
        'naturalkeyunique': '12345',
        'weight': 500,
        'name': 'Parent model with natural key value',
        'pk': 1234,  # pk retreived by natural keys (see 2.1.1)
      },
      'valid': True,
    },
  ],
  ...
}.
------
2.2.4 Parent generate action.
      After generation, data will be the following:
------
{
  ...
  'app.parent': [
    {
      '__hash__': '382b7a535232de74e0ff6f8a813940d1',
      'fields': {
        'weight': 500,
        'name': 'Parent model without natural key value',
      },
      'cleaned': {
        'weight': 500,
        'name': 'Parent model without natural key value',
      },
      'pk': 9876,   # new generated object pk value
      'valid': True,
    },
    {
      'fields': {
        'naturalkeyunique': '12345',
        'weight': 500,
        'name': 'Parent model with natural key value',
      },
      'cleaned': {
        'naturalkeyunique': '12345',
        'weight': 500,
        'name': 'Parent model with natural key value',
        'pk': 1234,
      },
      'pk': 1234,   # id is similar, because object was updated
      'valid': True,
    },
  ],
  ...
}.
------

2.3 Child
-------------------------------------------------------------------------------
2.3.1 Parent synchronize (in importer before handler run).
      All __hash__ relations will be resolved here.
------
{
  ...
  'grohe.child': [
    {
      'hash_related': {
          'm2m': 'app.m2m',
      },
      'fields': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': {'naturalkeyunique': '54321'},
        'm2m': [
          {'naturalkeyone': '12345', 'naturalkeytwo': '67890'},
          987,  # real value taken from __hash__ index (m2m is hash_related)
        ],
      },
    },
    {
      'hash_related': {
          'parent': 'app.parent',
      },
      'fields': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,  # real value taken from __hash__ index
        'm2m': [
          {'naturalkeyone': '12345', 'naturalkeytwo': '67890'},
          456,
        ],
      },
    },
  ],
}.
------
2.3.2 Parent prepare action.
      All relation fields will be resolved here if value is dict.
------
{
  ...
  'grohe.child': [
    {
      'hash_related': {
          'm2m': 'app.m2m',
      },
      'fields': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': 987,  # real value taken from database by natural key
        'm2m': [
          123,  # real value taken from database by natural keys
          987,
        ],
      },
    },
    {
      'hash_related': {
          'parent': 'app.parent',
      },
      'fields': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,
        'm2m': [
          123,  # real value taken from database by natural keys
          456,
        ],
      },
    },
  ],
}.
------
2.3.3 Parent validate action.
      After validation Parent values will be the following:
------
{
  'app.child': [
    {
      'hash_related': {
          'm2m': 'app.m2m',
      },
      'fields': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': 987,
        'm2m': [
          123,
          987,
        ],
      },
      'cleaned': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': 987,
        'm2m': [
          123,
          987,
        ],
      },
      'valid': True,
    },
    {
      'hash_related': {
          'parent': 'app.parent',
      },
      'fields': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,
        'm2m': [
          123,
          456,
        ],
      },
      'cleaned': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,
        'm2m': [
          123,
          456,
        ],
      },
      'valid': True,
    },
  ],
  ...
}.
------
2.3.4 Parent generate action.
      After generation, data will be the following:
------
{
  'app.child': [
    {
      'hash_related': {
          'm2m': 'app.m2m',
      },
      'fields': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': 987,
        'm2m': [
          123,
          987,
        ],
      },
      'cleaned': {
        'name': 'Child model with m2m values and parent with natural key',
        'parent': 987,
        'm2m': [
          123,
          987,
        ],
      },
      'pk': 741,  # new generated object pk value
      'valid': True,
    },
    {
      'hash_related': {
          'parent': 'app.parent',
      },
      'fields': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,
        'm2m': [
          123,
          456,
        ],
      },
      'cleaned': {
        'name': 'Child model with parent model with __hash__ value',
        'parent': 9876,
        'm2m': [
          123,
          456,
        ],
      },
      'pk': 852,  # new generated object pk value
      'valid': True,
    },
  ],
  ...
}.
------

After all ModelHandlers will be processed, all logger will be called with
post run method, file locker will be realeazed and process will be finished.

-------------------------------------------------------------------------------

Usage example:
-------------

Define database log entry model in main/models.py:

    from syncdata.models import BaseSyncDataLogEntry


    class SyncDataLogEntry(BaseSyncDataLogEntry):
        pass

Define admin for log entries in main/admin.py:

    from syncdata.admin import SyncDataLogEntryAdmin
    from main import models

    admin.site.register(models.SyncDataLogEntry, SyncDataLogEntryAdmin)

Define Importer in main/sync.py and after register it in setting.py:

    # Syncdata
    SYNCDATA_DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, 'syncdata'))
    SYNCDATA_IMPORTERS = {
        'importername': 'main.sync.ProjectXMLImporter',
    }

After just run:

    python manage.py syncdata -i importername -p "main.generate=True main.download=True"

And go to the Admin page `http://127.0.0.1:8000/admin/main/syncdatalogentry/`
to watch results of import process.
"""

VERSION = (2, 0, 0,)

default_app_config = 'syncdata.config.SyncDataConfig'
