# -- coding: utf-8 --
import sys
import codecs
import locale

from django.core.management.base import BaseCommand
from django.utils import translation
from django.conf import settings
from django.apps import apps


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            '-c', '--confirm', dest='confirm', default=False,
            help='Confirmation preventer (should be set to true).'),
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


        sys.stdout.write('\nDROPDATA\n--------\n')
        sys.stdout.write('\nModels to be deleted:\n%s\n' % ('-'*20,))

        models = apps.get_models()
        app = None
        for m in models:
            if not app == m._meta.app_label:
                app and sys.stdout.write('\n')
                app = m._meta.app_label
            label = '    %s.%s' % (m._meta.app_label, m.__name__,)
            label = '%s%s' % (label, str(m.objects.all().count()).rjust(79-len(label), '.'))
            sys.stdout.write('\n%s' % label)

        sys.stdout.write('\n')

        if not options['confirm']:
            sys.stdout.write('\n%s\nThe data drop should be confirmed...'
                             ' \n\n%s' % ('-'*79, '{:>79}'.format('Breaked'),))
            return

        for model in models:
            for object in model.objects.all():
                object.delete()

        sys.stdout.write('\n%s\nThe data dropping completed successfully, all'
                         ' objects erased from database.\n\n%s' %
                         ('-'*79, '{:>79}'.format('Exit'),))
