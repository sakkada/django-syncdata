from django.db import models
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _


class BaseSyncDataLogEntry(models.Model):
    name = models.CharField(_("name"), max_length=2000)
    text = models.TextField(_("log entry text"), blank=True, default=u'')

    status = models.BooleanField(_("status"), default=True)

    date_launch = models.DateTimeField(_("launch time"), default=timezone.now)
    date_finish = models.DateTimeField(_("finish time"), default=timezone.now)

    # stat info
    date_create = models.DateTimeField(editable=False, auto_now_add=True)
    date_update = models.DateTimeField(editable=False, auto_now=True)

    class Meta:
        verbose_name = _('SyncData log entry')
        verbose_name_plural = _('SyncData log entries')
        ordering = ('-date_finish',)
        abstract = True

    def __unicode__(self):
        return self.name

    def log(self, value):
        self.text = u'{}{}'.format(self.text, value)
