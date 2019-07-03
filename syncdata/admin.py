from django.contrib import admin
from django import forms


# Admin forms
# -----------
class SyncDataLogEntryForm(forms.ModelForm):
    class Meta:
        fields = '__all__'
        widgets = {
            'text': forms.Textarea(attrs={
                'style': 'font-family: monospace; overflow-x: hidden;',
                'rows': 35, 'cols': 81,
            }),
        }


# Admin models
# ------------
class SyncDataLogEntryAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'id', 'status', 'finished', 'date_launch', 'date_finish',
    )
    list_filter = ('status',)
    form = SyncDataLogEntryForm
    fields = (
        ('name', 'status', 'finished',),
        'text',
        ('date_launch', 'date_finish',),
    )
