# -- coding: utf-8 --
import sys
import codecs
import locale

from django.core.management.base import BaseCommand
from django.utils import translation, module_loading
from django.conf import settings

from ...utils import params_parser
from ... import settings as syncdata_settings


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-i', '--importer', dest='importer', default=None,
            help='Importer name for processing.'),
        parser.add_argument(
            '-p', '--params', dest='params', default={},
            help='Handler runtime params.'),
        parser.add_argument(
            '-e', '--ttyenc', dest='ttyenc', default='preferred',
            help='Attached tty encoding (preferred, none or encoding).'),

    def handle(self, *args, **options):
        # django.core.management.base forces the locale to en-us.
        translation.activate(settings.LANGUAGE_CODE)

        # set output encoding
        ttyenc = options['ttyenc']
        if ttyenc == 'preferred' and not sys.stdout.encoding:
            sys.stdout = codecs.getwriter(
                locale.getpreferredencoding())(sys.stdout)
        elif ttyenc and ttyenc not in ('none', 'preferred'):
            sys.stdout = codecs.getwriter(ttyenc)(sys.stdout)

        if not options['importer']:
            sys.stdout.write('\nImporter name is required, exit...\n')
            return

        # get data from arguments
        IMPORTERS = syncdata_settings.IMPORTERS
        importers = options['importer'].split()
        statuses = {}
        params = options['params'] and params_parser(options['params'])
        params.update(message=u'SyncData Importer run from shell (syncdata)')

        for iname in importers:
            Importer = IMPORTERS.get(iname, None)
            Importer = (module_loading.import_string(Importer)
                        if Importer else None)
            if not Importer:
                sys.stdout.write('\nImporter "%s" does not exist,'
                                 ' pass...' % iname)
                continue

            statuses[iname] = Importer().run(**params)

        sys.stdout.write('\n')

        if any(statuses.values()):
            sys.stdout.write('\nOne of requested importers finished'
                             ' with non zero status: (%s).' % statuses)
            exit([i for i in statuses.values() if i][0])
