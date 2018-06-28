# sample of observer written with watchdog
import os
import re
import sys
import time
import subprocess
import datetime
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler


SYNCDATA_IMPORTERS = {
    'xmlsource': {
        'match': re.compile('^xmlsource\.\d+\.\d+.xml$'),
        'params': (u'xmlsource.path="{path}" '
                   u'main.generate=True main.download=True')
    },
}


def subprocess_syncdata_importer(managepy, srcfile):
    basename = os.path.basename(srcfile.path)
    params = SYNCDATA_IMPORTERS.get(srcfile.importer).get('params', '')
    params = params.format(**srcfile.get_context()) if params else params

    p = subprocess.Popen(
        ['python', managepy, 'syncdata',
         '-i', srcfile.importer, '-p', params,])

    p.communicate()
    if p.returncode == 0:
        srcfile.on_success()
        sys.stdout.write('\nSuccess: importing file "%s" (%s).'
                         % (basename, p.returncode,))
    else:
        srcfile.on_failure()
        sys.stdout.write('\nFailure: importing file "%s" (%s).'
                         % (basename, p.returncode,))


class SourceFileHandler(object):
    regex = re.compile('^(?P<importer>[\w_-]+)\.(?P<datetime>\d{14}\.\d{1,8})'
                       '(?P<extension>\.[\w_-]+)$')

    def __init__(self, path):
        self.path = path

    def is_valid(self):
        # check filename by main regex
        filename = os.path.basename(self.path)
        basename, extension = os.path.splitext(filename)
        match = self.regex.match(filename)
        if not match:
            return False

        # check filename by importer regext
        data = match.groupdict()
        importer = SYNCDATA_IMPORTERS.get(data['importer'], None)
        if not importer or not importer['match'].match(filename):
            return False

        # try to get date from filename
        try:
            date = datetime.datetime.strptime(
                data['datetime'], '%Y%m%d%H%M%S.%f')
        except:
            return False

        self.filename = filename
        self.basename = basename
        self.extension = extension
        self.importer = data['importer']
        self.datetime = date

        return True

    def __unicode__(self):
        return self.path

    def get_context(self):
        return {
            'path': self.path,
            'filename': self.filename,
            'basename': self.basename,
            'extension': self.extension,
            'importer': self.importer,
            'datetime': self.datetime,
        }

    def on_success(self):
        os.unlink(self.path)

    def on_failure(self):
        failpath = '%s.failure' % self.path
        if os.path.exists(failpath):
            os.unlink(failpath)
        os.rename(self.path, failpath)


class SyncDataMatchingEventHandler(PatternMatchingEventHandler):
    def __init__(self, managepy=None, *args, **kwargs):
        super(SyncDataMatchingEventHandler, self).__init__(*args, **kwargs)
        self.managepy = managepy

    def on_moved(self, event):
        super(SyncDataMatchingEventHandler, self).on_moved(event)

    def on_created(self, event):
        super(SyncDataMatchingEventHandler, self).on_created(event)
        if event.is_directory:
            return

        srcfile = SourceFileHandler(os.path.abspath(event.src_path))
        if not srcfile.is_valid():
            return

        time.sleep(0.1)
        sys.stdout.write("\nCreated: %s at %s" % (srcfile.basename,
                                                  datetime.datetime.now(),))

        # call managepy with new file
        subprocess_syncdata_importer(managepy, srcfile)

    def on_deleted(self, event):
        super(SyncDataMatchingEventHandler, self).on_deleted(event)

    def on_modified(self, event):
        super(SyncDataMatchingEventHandler, self).on_modified(event)

if __name__ == "__main__":
    sys.stdout.write(
        'Django SyncData importer observer.'
        '\nStarting datetime: %s.\n%s' % (datetime.datetime.now(), '-' * 18))
    if len(sys.argv) != 3:
        sys.stdout.write(
            '\nTwo args required:'
            '\n- django project "manage.py" path and'
            '\n- importing source directory path, exit...')
        exit(1)

    # get arguments and run observer
    managepy, srcdir = sys.argv[1], sys.argv[2]
    event_handler = SyncDataMatchingEventHandler(patterns=('*.xml',),
                                                 managepy=managepy)

    # get all zip files
    files = [SourceFileHandler(os.path.abspath(os.path.join(srcdir, i)))
             for i in os.walk(srcdir).next()[2]]
    files = [i for i in files if i.is_valid()]

    observer = Observer()
    observer.schedule(event_handler, srcdir, recursive=False)
    observer.start()
    try:
        # manual processing of existing at startup files
        if files:
            sys.stdout.write(
                '\nStartup files: \n  %s.\nProcessing...'
                % ',\n  '.join(map(unicode, files)))
            for i in files:
                subprocess_syncdata_importer(managepy, i)
        # start main loop
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
