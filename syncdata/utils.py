import io
import os
import re
import sys
import time
import queue
import threading
import traceback
import urllib.error
import urllib.request
from collections import defaultdict
from xml.etree import cElementTree


PARAM_REGEX = re.compile(r"""([a-z0-9_\-\.\:]+) \s*=\s* ("|')? (?(2)"""
                         r""" (?:(.+?)(?<!\\)\2) | ([^\s'"]+))""", re.I | re.X)


def params_parser(params):
    """
    Parse html-like params into dict, example: "attr=10 attr2='v 2' attr3=True"
    Note that None, True, False and digist with no quotes will be converted
    into real python types, so "aa=None bb='None' cc=123 dd='123'" ->
                               {'aa': None, 'bb':'None', 'cc':123, 'dd':'123'}
    """
    varval = lambda x: (eval(x)
                        if x in ('None', 'False', 'True') or x.isdigit() else
                        x)
    params = (re.findall(PARAM_REGEX, params)
              if isinstance(params, str) else [])
    params = [(str(i[0]), i[2] or varval(i[3])) for i in params]
    return dict(params)


def exception_to_text(e, limit=None):
    if isinstance(getattr(e, '_exception_lines', None), (list, tuple)):
        return e._exception_lines

    sfile = io.StringIO()
    etype, value, tb = sys.exc_info()

    sfile.write('\nStack logging (traceback.print_stack):')
    sfile.write('\n%s\n' % ('-'*79,))
    traceback.print_stack(limit=limit, file=sfile)

    sfile.write('\nException logging (traceback.print_exception):')
    sfile.write('\n%s\n' % ('-'*79,))
    traceback.print_exception(etype, e, tb, limit, sfile)

    return sfile.seek(0) or sfile.read()


class FileLock(object):
    locktime = 60*60*4
    lockname = '.lock'

    def __init__(self, basedir, locktime=None, lockname=None):
        self.basedir = basedir

        if locktime:
            self.locktime = locktime
        if lockname:
            self.lockname = lockname

    def lock(self, force=False):
        if self.check() and not force:
            return False

        lockname = self.get_name()
        if os.path.exists(lockname):
            os.utime(lockname, None)
        else:
            open(lockname, 'a').close()
        return True

    def unlock(self):
        lockname = self.get_name()
        os.path.exists(lockname) and os.unlink(lockname)

    def check(self, astime=False, remained=True):
        lockname = self.get_name()
        elapsed = (time.time() - os.path.getmtime(lockname)
                   if os.path.exists(lockname) else None)

        if not (not elapsed is None and elapsed < self.locktime):
            return False

        return ((self.locktime - elapsed if remained else elapsed)
                if astime else True)

    def update(self):
        lockname = self.get_name()
        if self.check() and os.path.exists(lockname):
            os.utime(lockname, None)
            return True
        return False

    def get_name(self):
        return os.path.abspath(os.path.join(self.basedir, self.lockname))


# Loaders helpers
# ---------------
def xml_to_dict(value):
    t = (value if not isinstance(value, str)
         else cElementTree.XML(value))
    d = {t.tag: {} if t.attrib else None}

    children = list(t)
    if children:
        dd = defaultdict(list)
        for dc in map(xml_to_dict, children):
            for k, v in dc.items():
                dd[k].append(v)
        d = {t.tag: {k:v[0] if len(v) == 1 else v for k, v in dd.items()}}

    if t.attrib:
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.items())

    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
              d[t.tag]['#text'] = text
        else:
            d[t.tag] = text

    t.clear()
    return d


# Asynchronous threaded file downloader,
#   original source taken from https://gist.github.com/chandlerprall/1017266
class URLLoader(object):
    def __init__(self, url, destination, tries=5, timeout=60*5):
        self.url = url
        self.destination = destination
        self.timeout = timeout
        self.tries = tries
        self.tried = 0
        self.success = False
        self.error = None

    def is_exists(self):
        return os.path.exists(self.destination)

    def download(self):
        self.tried += 1

        try:
            if self.is_exists():
                self.success = 'exists'
                return self.success

            if not os.path.exists(os.path.dirname(self.destination)):
                os.makedirs(os.path.dirname(self.destination))

            file = urllib.request.urlopen(self.url, timeout=self.timeout)
            data = file.read()
            file.close()

            with open(self.destination, 'wb') as file:
                file.write(data)

            self.success = True

        except urllib.error.HTTPError as e:
            # stop if not (short) time related errors
            if e.code in (403, 404, 405,):
                self.tried = self.tries
            elif e.code in (503,):
                time.sleep(1)
            self.error = e
        except Exception as e:
            self.error = e

        return self.success

    def __str__(self):
        return 'URLLoader (%(url)s, %(success)s, %(error)s)' % {
            'url': self.url, 'success': self.success, 'error': self.error
        }


class DownloaderThread(threading.Thread):
    def __init__(self, queue, report, loggers=None):
        super(DownloaderThread, self).__init__()
        self.queue = queue
        self.report = report
        self.loggers = loggers or []
        # self.daemon = True

    def log(self, value):
        for i in self.loggers:
            i.log(value)

    def run(self):
        while not self.queue.empty():
            url = self.queue.get()
            success = url.download()

            if not success and url.tried < url.tries:
                self.queue.put(url)
            elif not success and url.tried == url.tries:
                self.report['failure'].append(url)
                self.loggers.log('x')
            elif success:
                self.report['success'].append(url)
                self.loggers.log('.' if success == 'exists' else '+')

            self.queue.task_done()


class ThreadedDownloader(object):
    """
    Threaded Asynchronous Downloader.

    urls = [
        ('http://some.domain/path/to/file.ext', '/path/to/file.ext'),
        ...
    ]               # list of url tuples ('source url', 'destination path',)
    threads = 4     # simultanious threads count
    tries = 5       # count of tries before failure
    timeout = 60*5  # urllib.request.urlopen timeout in seconds

    downloader = ThreadedDownloader(urls, threads, tries, timeout)

    print 'Downloading %s files (%s threads)' % (len(urls), threads,)
    downloader.run()
    print 'Downloaded %(success)s of %(total)s' % {
        'success': len(downloader.report['success']), 'total': len(urls)
    }

    if len(downloader.report['failure']) > 0:
        print 'Failed urls:'
        for url in downloader.report['failure']:
            print url
    """
    url_loader_class = URLLoader
    downloader_thread_class = DownloaderThread

    def log(self, value):
        for i in self.loggers:
            i.log(value)

    def __init__(self, urls=None, threads=5, tries=10, timeout=10,
                 loggers=None):
        self.queue = queue.Queue(0)  # infinite sized queue
        self.report = {'success': [], 'failure': [],}
        self.threads = threads
        self.pool = []
        self.loggers = loggers or []

        for url in (urls or []):
            self.queue.put(
                self.url_loader_class(url[0], url[1], tries, timeout))

    def run(self):
        for i in range(min(self.threads, self.queue.qsize())):
            thread = self.downloader_thread_class(self.queue, self.report,
                                                  loggers=self)
            thread.start()
            self.pool.append(thread)
        self.queue.join()

        # stop each alive process (other method: set daemonic to true, see
        #   DownloaderThread.__init__ method - commented line)
        # (if sys.stdout.write used, some threads become a zombie)
        for i in self.pool:
            i.is_alive() and i._Thread__stop()
