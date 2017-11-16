# -- coding: utf-8 --
"""
Общее описание процесса синхронизации.

Фаза загрузки (BaseLoader):
1.  Получаем список массивов данных (коллекции) с помощью лоадеров.
    Запуск лоадеров производится последовательно, каждый последующий лоадер
    получает на вход данные предыдущего и возвращает обновленные данные.

Фаза обработки (BaseModelHandler):
По умолчанию, запуск обработчика происходит в три этапа:
2.  Подготовка данных (prepare).
    Запускаем синхронизатор hash связей объектов:
    - получаем все поля внешних связей из указанных в качестве hash связанных,
      (указанных в поле hash_related (словарь {поле: коллекция})),
    - если значение поля не словарь с ключем __hash__, оставляем как есть,
      т.к. это скалярное значение, являющееся значением related_field или
      словарь с натуральными ключами,
    - если словарь с ключем __hash__ (динамически связанное по hash значению
      поле), то ищем объект в hash индексе и получаем искомое значение поля
      (обычно primary key связанной модели).
3.  Запускаем валидацию всех данных коллекции и, в случае ошибки, либо
    завершаем аварийно процесс, если для коллекции указан флаг strict (по
    умолчанию), либо игонорируем ошибочные данные и сейчас, и на этапе записи
    в базу данных.
4.  Запускаем непосредственно генератор объектов:
    - обрабатываем данные - преобразовываем значения внешних связей в реальные
      значения (remote field value -> related_field value)
    - если объект существует, обновляем, иначе добавляем
    - получаем обратно значения primary_key для каждого обработанного объекта
      для разрешения внешних связей и идентификации в последующих итерациях.

Общее описание процесса запуска:

1.  Запуск всех лоадеров.
2.  Вызов метода pre_run всех лоадеров и обработчиков моделей перед запуском
    основного цикла генерации.
3.  Запуск цикла генерации.
4.  Вызов метода post_run всех лоадеров и обработчиков моделей после запуска
    основного цикла генерации. Обычно на этом этапе удаляются файлы, и
    выполняется прочая «уборка мусора».

Обработка внешних ключей (подробнее смотреть метод process_relation):
- если значение скаляр:
    - выбираем объекты из базы, фильтруя по полю rfield (related_field,
      поле внешней связи, обычно primary key):
      {id: 1, fk_object: 7} ->
        fk_object = fk_model.objects.filter(rfield=7).first()
- если значение словарь:
    - выбираем объекты из базы на основании данных из словаря (фактически это
      готовый фильтр для запроса):
      {id: 1, fk_object: {code: some, eid=7}} ->
        fk_object = fk_model.objects.filter(code='some', eid=7).first()

Сущности системы:

    Лоадер - класс отвечающий за загрузку первоначальных данных из различных
    источников и преобразование к необходимому формату: {
        '__hash__': any hash value,
        'hash_related': {'model_nane': value},
        'fields': {
            'name': value
        },
    }

    Хендлер Модели - класс отвечающий за преобразование внешних данных
    к необходимому виду, валидацию, и процесс сохранения.
    Класс в целом расширяем, если есть необходимость добавления функционала,
    либо изменения существующего.

    Импортер/Синхронизатор данных коллекций (по сути списка dict-ов) - класс,
    включающий в себя все импортеры моделей и отвечающий за их запуск
    по очереди и за преобразование сырых данных (xml, csv и т.п.)
    при помощи лоадеров в список коллекций. Координатор работы лоадеров,
    хендлеров и логгеров.

Примерная цель системы:

    Преобразование внешних данных в формат, схожий с тем, что получается
    на выходе команды dumpdata, валидация полученных данных, динамическое
    связывание значений внешних ключей в процессе работы (синхронизация)
    при запуске очередной коллекции, сохранение/обновление данных в базе
    с возможностью указать как внешние ключи, так и "натуральные" ключи.

Конфигурация.

Хендлеры:
    actions_queue - список функций обработчиков (действий), которые будут
                    выполнены при запуске хендлера
    Meta:
        natural_keys - список полей, по значениям которых производится поиск
        form_class - класс формы для валидации
        fields - список полей формы
        exclude - список полей, исключаемых из формы

Пример данных: {
    'appname.firstmodelname': [{
        '__hash__': 'first-uniq-str',
        'fields': {
            'name': 'some first name',
        },
    },]
    'appname.secondmodelname': [{
        '__hash__': 'second-uniq-str',
        'hash_related': {
            # key of firstmodelname entries list
            'firstmodelname': 'appname.firstmodelname',
        },
        'fields': {
            # hash of firstmodelname related instance
            'firstmodelname': {'__hash__': first-uniq-str,},
            'thirdmodelname': 7,
            'fourthmodelname': {'code': 'uniqcode'},
            'name': 'some second name',
        },
    },]
}
"""

import os
import sys
import copy
import mimetypes
import urllib
import json
import traceback

from itertools import izip
from django import forms
from django import db
from django.db import models
from django.core.serializers.python import Deserializer
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from .utils import exception_to_text, FileLock
from . import settings, signals


# Exceptions
# ----------
class LockedModelHandlerException(Exception):
    pass


# Loggers
# -------
class BaseLogger(object):
    def log(self, value):
        raise NotImplementedError

    def finallog(self, name=None, status=True):
        pass


class BaseModelLogger(object):
    model = None
    def __init__(self):
        self.object = self.model()

    def log(self, value):
        self.object.log(value)

    def finallog(self, name=None, status=True):
        self.object.name = name or u'SyncData'
        self.object.status = not bool(status)
        self.object.save()


class ConsoleLogger(BaseLogger):
    def log(self, value):
        sys.stdout.write(value)
        sys.stdout.flush()


# Loaders
# -------
class BaseLoader(object):
    loggers = None

    def __init__(self, loggers=None):
        self.loggers = loggers or []

    def log(self, value):
        for i in self.loggers:
            i.log(value)

    def run(self, data=None, **options):
        raise NotImplementedError

    def pre_run(self, **kwargs):
        pass

    def post_run(self, **kwargs):
        pass

    def get_key(self, model):
        # get key for model: User -> auth.user
        return '.'.join([model._meta.app_label, model._meta.model_name,])


# Model Handlers
# --------------
class BaseModelHandler(object):
    strict_mode = True
    strict_mode_synchronize = False
    actions_queue = ['prepare', 'validate', 'generate',]
    save_unchanged_objects = False
    loggers = None

    def __init__(self, **kwargs):
        self.meta = self.Meta()
        self.options = kwargs.get('options')
        self.loggers = kwargs.get('loggers') or []

    def log(self, value):
        for i in self.loggers:
            i.log(value)

    def get_key(self):
        # get key for model: User -> auth.user
        return '.'.join([self.meta.model._meta.app_label,
                         self.meta.model._meta.model_name,])

    def get_uploaded_file_from_path(self, path, quiet=True):
        # get SimpleUploadedFile instances from path string
        try:
            with open(path, 'rb') as image:
                file = SimpleUploadedFile(image.name, image.read())
                file.content_type = mimetypes.guess_type(path)[0]
        except IOError as e:
            if not quiet:
                raise
            file = None
        return file

    def get_related_key(self, value):
        # get key by value, converts dict value to scalar, sorted by keys:
        #   1 -> 1, {'z': 1, 'a': 'value'} -> 'a__value__z__1'
        if not isinstance(value, dict):
            return value
        return u'__'.join([unicode(i) for i in reduce(tuple.__add__,
                                                      sorted(value.items()))])

    # prepare action: initial data processing
    # ---------------------------------------
    def get_related_values(self, field, values):
        """
        Получение значения remote_field (см. описание process_relation).
        Возможные два варианта:
        1.  User - (m2m) - Group
            User.id -> User_groups (through: user_id, group_id) -> Group.id
                field - это поле groups объекта User (user.groups, rel-manager)
                rfield - это поле Group.id (remote_field)
        2.  User - (m2o) - City
            User.city_id -> City.id
                field - это поле city объекта User (user.city)
                rfield - это поле City.id (remote_field)
        """

        # get separatelly filtered scalars and dicts (which is not None)
        # (1,{1:1},2,None,{2:2},0,False) -> [(1,2,0,False), ({1:1,},{2:2,},),]
        sc_di = [(None, i,) if isinstance(i, dict) else (i, None,)
                 for i in values]
        sc_di = map(lambda x: filter(lambda y: y is not None, x), zip(*sc_di))
        if not sc_di:
            return {}

        # get remote_field name (differently for m2o and m2m)
        if isinstance(field.remote_field, models.ManyToManyRel):
            rfield = field.m2m_reverse_target_field_name()
        elif isinstance(field.remote_field, models.ManyToOneRel):
            rfield = field.remote_field.field_name

        # direct (scalar) remote values
        objects = dict([
            (i[rfield], i[rfield],)
            for i in field.remote_field.model.objects.filter(
                **{'%s__in' % rfield: set(sc_di[0])}).values(rfield)
        ]) if sc_di[0] else {}

        # complex (dict) remote values
        for query in sc_di[1]:
            value = field.remote_field.model.objects.filter(
                **query).values(rfield).first()
            if not value:
                continue
            objects.update({self.get_related_key(query): value[rfield],})

        return objects

    def process_relation(self, field, data):
        """
        Преобразовывие данных связей.
        Значения, полученные в лоадере преобразовываем в значения
        related_field (далее rfield) связанного объекта
        (это поле связанного объекта, через которое осуществляется связь,
        указывается с помощью параметра "ForeignKey.to_field", по умолчанию
        primary key).
        Значение из лоадера может быть двух видов.
        1. Cкаляром, тогда считается, что это непосредственное значение rfield.
        Процесс:
          обрабатываемый объект {some_uniq: 1, fk_object: 7}
          rfield - fk_object-field.remote_field.field_name (для m2o; для m2m
                   немного сложнее, но в целом аналогично)
          получаем:
          {some_uniq: 1,
           fk_object: 7 --> fk_object - filter(rfield=7) - getattr(rfield)}
        Так же следует учитывать, что запрос в базу данных для всех
        объектов со скалярныхми значениями будет всего один, что
        в некоторой степени ускоряет процесс обработки.

        2. Словарем. Тогда вместо значения rfield используется весь полученный
        словарь в качестве фильтра для queryset, как есть. И при этом,
        на каждый такой объект, запрос в базу данных будет производится
        отдельно, что может приводить к большим временным затратам.
        Процесс:
          обрабатываемый объект {some_uniq: 1, fk_object: {name: SOMENAME}}
          rfield - fk_object-field.remote_field.field_name
          получаем:
          {some_uniq: 1,
           fk_object: {name: SOMENAME} --> fk_object
                                           - filter(**{name: SOMENAME})
                                           - getattr(rfield)}
        """

        fname = field.name
        if field.remote_field and isinstance(field.remote_field,
                                             models.ManyToManyRel):
            values = reduce(list.__add__, [i['fields'][fname] for i in data
                                           if i['fields'].has_key(fname)], [])
            objs = values and self.get_related_values(field, values)
            if not objs:
                return

            for i in data:
                for k, j in enumerate(i['fields'].get(fname, [])):
                    i['fields'][fname][k] = objs.get(self.get_related_key(j),
                                                     j or None)

        elif field.remote_field and isinstance(field.remote_field,
                                               models.ManyToOneRel):
            values = [i['fields'][fname] for i in data
                      if i['fields'].has_key(fname)]
            objs = values and self.get_related_values(field, values)
            if not objs:
                return

            for i in data:
                value = i['fields'][fname]
                i['fields'][fname] = objs.get(self.get_related_key(value),
                                              value or None)

    def action_prepare(self, data):
        """
        Метод обработчик действия prepare.
        Данное действие отвечает за преобразование данных внешних полей или
        related_field, указанных в лоадере в реальные данные внешних объектов,
        полученных из базы данных. Данный этап необходим для работы как
        действия валидации, так и действия генерации, фактически на этапе
        подготовки, данные преобразовываются к виду, которые получают формы
        при обработке запросов от клиента.
        """
        meta = self.meta.model._meta
        fields = dict([(i.name, i,) for i in meta.fields + meta.many_to_many])
        fnames = ([i.name for i in meta.fields + meta.many_to_many]
                  if not hasattr(self.meta, 'fields') else self.meta.fields)

        self.log("\nprepare (fields)         %s " %
                 (str(len(fnames)).ljust(5),))
        for fname in fnames:
            # field not in model (only in form)
            if not fname in fields:
                continue
            if fields[fname].remote_field:
                self.process_relation(fields[fname], data)
            self.log('.')

    # validation action: forms validation like in admin's create/update view
    # ----------------------------------------------------------------------
    def get_form_class(self, **kwargs):
        """
        Получение класса формы валидации.
        Класс формы может быть указан следующими способами:
        - в Meta классе хендрела с помощью атрибута form_class,
        - сгенерирован вручную в переоределенном методе get_form_class
        - сгенерирован автоматически (по умолчанию)
        """
        if hasattr(self.meta, 'form_class'):
            FormClass = self.meta.form_class
        else:
            if not hasattr(self, '_form_class'):
                # generate simple configured form
                class FormClass(forms.ModelForm):
                    class Meta:
                        model = self.meta.model
                        fields = getattr(self.meta, 'fields', None)
                        exclude = getattr(self.meta, 'exclude', None)
                self._form_class = FormClass
            FormClass = self._form_class
        return FormClass

    def get_form_instance(self, form_class, data=None, files=None,
                          instance=None, **kwargs):
        # get form instances, method can be extened, if required
        return form_class(data=data, files=files, instance=instance)

    def get_instance_from_data(self, item):
        # get model instance by pk or by narural keys from data
        filter = None
        if item.has_key('pk'):
            filter = {self.meta.model._meta.pk.attname: item['pk'],}
        elif hasattr(self.meta, 'natural_keys'):
            filter = dict([(i, item['fields'][i],)
                           for i in self.meta.natural_keys
                           if item['fields'].get(i, None)])
        return (self.meta.model.objects.filter(**filter).first()
                if filter else None)

    def prepare_uncleaned_data(self, data, item):
        # update uncleaned_data values:
        #   set FileFields values as SimpleUploadedFile instances instead paths
        #   return data and files

        meta = self.meta.model._meta
        fields = dict([(i.name, i,) for i in meta.fields + meta.many_to_many])
        files = {}

        for k, v in data.items():
            field = fields.get(k, None)
            if not field or not v:
                continue
            elif isinstance(field, models.FileField):
                files[k] = self.get_uploaded_file_from_path(v)

        return data, files

    def prepare_cleaned_data(self, form, item):
        # update cleaned_data values:
        #   set rfield scalar values for m2o and m2m fields instead instances
        #   set path values for FileFields instead File descriptors
        # extend it if require to modify cleaned_data dict
        meta = self.meta.model._meta
        fields = dict([(i.name, i,) for i in meta.fields + meta.many_to_many])
        cdata = form.cleaned_data

        for k, v in cdata.items():
            field = fields.get(k, None)
            if not field or not v:
                continue
            elif field.remote_field and isinstance(field.remote_field,
                                                   models.ManyToManyRel):
                rfield = field.m2m_reverse_target_field_name()
                cdata[k] = [getattr(i, rfield) for i in v]
            elif field.remote_field and isinstance(field.remote_field,
                                                   models.ManyToOneRel):
                rfield = field.remote_field.field_name
                cdata[k] = getattr(v, rfield)
            elif isinstance(field, models.FileField):
                cdata[k].closed or cdata[k].close()
                cdata[k] = form.data.get(k, None)

        return cdata

    def validate_item(self, item):
        # validate one element of data:
        #   get instance from uncleaned_data,
        #   validate instance by form and return cleaned_data or errors
        data = copy.deepcopy(item['fields'])
        data, files = self.prepare_uncleaned_data(data, item)

        instance = self.get_instance_from_data(item)
        kwargs = {'item': item, 'data': data,
                  'files': files, 'instance': instance,}

        form = self.get_form_class(**kwargs)
        form = self.get_form_instance(form, **kwargs)

        if form.is_valid():
            data = dict(self.prepare_cleaned_data(form, item),
                        pk=form.instance.pk or item.get('pk', None))
            elem = {'valid': True, 'cleaned': data,
                    'changed': form.has_changed(),}
        else:
            elem = {'valid': False, 'errors': dict(form.errors),}

        return elem

    def action_validate(self, data):
        """
        Метод обработчик действия validate.
        Данное действие отвечает за проверку всех полученных от лоадера и
        подготовленных действием prepare данных.
        В случае, если режим работы хендлера указан как строгий (strict) и
        при наличии хотя бы одного ошибочного элемента данных действием будет
        выброшено исключение, завершающее работу всего хендлера.
        """
        self.log("\nvalidate                 %s " % str(len(data)).ljust(5))
        for item in data:
            item.update(self.validate_item(item))
            self.log("%s" % ('.' if item['valid'] else 'x'))

        # show errors and halt if required
        verbose = self.options.get('main.verbose', True)
        isvalid = all([i['valid'] for i in data])

        if verbose and not isvalid:
            self.log('\n%s\nvalidate - invalid items raw visualization:\n%s\n'
                     % ('*'*25, '*'*25,))
            self.log(json.dumps([i for i in data if not i['valid']],
                                indent=2, ensure_ascii=False))
            self.log('\n%s' % ('*'*25,))

        if self.strict_mode and not isvalid:
            self.log('\n%s\nERROR' % ('-'*25))
            raise ValueError('Validation errors.')

    # generation action: sync all valid data with database
    # ----------------------------------------------------
    def get_serialized_data(self, data):
        # get serialized data in required format (like builtin loaddata)
        serialized = []
        for i in data:
            if not i.get('valid', False):
                continue
            item = copy.deepcopy(i['cleaned'])
            item = {'model': self.get_key(),
                    'pk': item.pop('pk', None),
                    'fields': item,
                    'source': i,}
            serialized.append(item)
        return serialized

    def prepare_serialized_data(self, data):
        """
        get serialized data prepared to save:
            SimpleUploadedFile instances instead path in FileFields
        note: this should be a generater to prevent huge memory usage
        """
        meta = self.meta.model._meta
        fields = dict([(i.name, i,) for i in meta.fields + meta.many_to_many])

        for i in data:
            item = copy.deepcopy(i)
            for k, v in item['fields'].items():
                field = fields.get(k, None)
                if not field or not v:
                    continue
                elif isinstance(field, models.FileField):
                    item['fields'][k] = self.get_uploaded_file_from_path(v)

            yield item

    def merge_model_instances(self, src, dst, fields):
        # merge values of saving object (deserialized) with existing one
        for name in fields:
            value = getattr(src, name)

            # save only File (to create new instance of FieldFile)
            if isinstance(value, models.fields.files.FieldFile):
                value = value and value.file or None

            setattr(dst, name, value)

        return dst

    def get_deserialized_object(self, desobj, serobj):
        # get object from deserializer:
        #   original django deserializer can't update objects, just save new
        #   ones, that's why we should merge existing object with deserialized
        #   from data, if it exists in database, otherwise just get new object
        #   from deserializer
        o = (desobj.object.__class__.objects.filter(pk=desobj.object.pk).first()
             if desobj.object.pk else None)

        if desobj.object.pk and o:
            m2m = [i.name for i in desobj.object.__class__._meta.many_to_many]
            fields = [i for i in serobj['fields'].keys() if i not in m2m]
            object = self.merge_model_instances(desobj.object, o, fields)
        else:
            object = desobj.object
            object.__is_new__ = True

        return object

    def save_deserialized_object(self, object, desobj, serobj):
        # save deserialized object explicitelly, because original deserializer
        # save method work like in raw mode, but we need real model.save call
        object.save()
        for accessor_name, object_list in desobj.m2m_data.items():
            getattr(object, accessor_name).set(object_list)

        return object

    def require_to_save_object(self, deserialized, serialized):
        """
        Method tells is there requirement to save current object or not.
        By default unchanged objects does not saving, because there is no need
        to do it. To force update unchanged objects anyway, set
        save_unchanged_objects property to True or just extend this method.
        """
        return serialized['source']['changed'] or self.save_unchanged_objects

    def action_generate(self, data):
        """
        Метод обработчик действия generate.
        Данное действие отвечает за сохранение всех корретных данных,
        полученных и проверенных на этопе валидации.
        Для получения объектов моделей используется встроенный десериализатор,
        используемый в команде loaddata (так как он умеет только создавать
        объекты, а не обновлять их, используется несколько более сложный
        механизм вызова метода save у модели, нежели в десериализаторе).

        После добавления объектов в базу данных, pk новых объектов сохранаются
        в массиве и используются в дальнейшем при обработке нижестоящих
        в иерархии коллекций.
        """
        serialized = self.get_serialized_data(data)
        prepared = self.prepare_serialized_data(serialized)  # lazy
        deserialized = Deserializer(prepared)  # lazy

        self.log("\ngenerate                 %s "
                 % str(len(serialized)).ljust(5))
        for dobj, sobj in izip(deserialized, serialized):  # lazy
            if not self.require_to_save_object(dobj, sobj):
                sobj['source']['pk'] = dobj.object.pk
                char = '-'
            else:
                obj = self.get_deserialized_object(dobj, sobj)
                obj = self.save_deserialized_object(obj, dobj, sobj)
                sobj['source']['pk'] = obj.pk
                char = '+' if getattr(obj, '__is_new__', False) else '.'
            self.log(char)

        # clear query log
        db.reset_queries()

    # execution: main cycle
    # ---------------------
    def get_actions_queue(self, **kwargs):
        for action in self.actions_queue:
            if hasattr(self, 'action_%s' % action):
                yield getattr(self, 'action_%s' % action)

    def pre_run(self, **kwargs):
        # pre run event handler
        pass

    def post_run(self, **kwargs):
        # post run event handler
        pass

    def run(self, data, **kwargs):
        # main run cycle, note - data is a pointer variable
        for action in self.get_actions_queue(**kwargs):
            action(data)


# Importers
# ---------
class BaseImporter(object):
    options = None
    lockable = True  # allow only one instance at the same time
    lockname = None  # lock file name, default "classname.lock"
    locktime = 60*60  # max lock time period
    loggers = None

    def __init__(self, **kwargs):
        self.meta = self.Meta()
        self.loggers = [i() for i in getattr(self.meta, 'loggers',
                                             [ConsoleLogger])]

    def log(self, value):
        for i in self.loggers:
            i.log(value)

    def finallog(self, name=None, status=True):
        for i in self.loggers:
            i.finallog(name, status)

    def download_media(self, urls):
        def reporter(blocknr, blocksize, size):
            current = blocknr * blocksize if size > blocksize else size
            error = '  -- ERROR, NOT FOUND!' if current < 0 else ''
            self.log("\r{0} - {1:.2f}%{2}".format(
                current, 100.0 * current/size, error
            ))

        def downloader(source, destination, retries=5):
            self.log("\nsource: %s" % source)
            self.log("\ntarget: %s\n" % destination)

            dest_dirname = os.path.dirname(destination)
            os.path.exists(dest_dirname) or os.makedirs(dest_dirname)

            while True:
                try:
                    urllib.urlretrieve(source, destination, reporter)
                    break
                except IOError as e:
                    if not retries:
                        raise
                    retries -= 1
                    self.log("\ndownload error (%s), %s retries left,"
                             " retry..." % (e.errno, retries,))
                    continue

        count = urls.__len__()
        for i, (s, d) in enumerate(urls.items(), 1):
            self.log("\n------")
            self.log("\nloading #%s of #%s" % (i, count,))
            downloader(s, d)

    def get_handlers_queue(self, **kwargs):
        """
        На данный момент возможно только вручную указать и
        список и приоритет загрузки обработчиков моделей
        """
        queue = []
        for handler in self.meta.handlers:
            handler = handler(options=kwargs, loggers=self.loggers)
            queue.append((handler.get_key(), handler,))

        return queue

    def get_loaders_queue(self, **kwargs):
        queue = []
        for loader in self.meta.loaders:
            queue.append(loader(self.loggers))

        return queue

    def get_synchronized_value(self, rfield, elem, hashed_value,
                               strict_mode, message):
        if not elem or not elem.get('pk', None):
            if strict_mode:
                raise ValueError(message)
            return hashed_value

        return (getattr(rfield.model.objects.get(pk=elem['pk']), rfield.name)
                if rfield and not rfield.primary_key else elem['pk'])

    def synchronize(self, handler, data, **kwargs):
        """
        Синхронизация связанных объектов.
        Hash ключ пребразовывается в значение rfield поля связанного
        объекта (см. описание метода BaseModelHandler.process_relation),
        Например:
            Обработанные ранее объекты fk_objects: (
                {__hash__: SOME,  id: 1,},
                {__hash__: VALUE, id: 2,},
            )
            Текущий объект object: {id: 1, fk_object: {__hash__: SOME,},}

            Преобразовываем значение {__hash__: SOME,} в 1, получив его из
            массива данных fk_objects по hash ключу SOME, и выбрав в
            найденнном объекте значение id, при условии что rfield
            в связи object->fk_object это поле id (может быть иное поле).

            Обработанный объект object: {id: 1, fk_object: 1,}
        """

        collection = data[handler.get_key()]
        strict_mode = handler.strict_mode_synchronize

        hrel = [i.get('hash_related').items()
                for i in collection if i.has_key('hash_related')]
        hrel = dict(set(reduce(list.__add__, hrel, [])))
        if not hrel:
            return

        # get hashed index for required collections
        hashed = dict([(r, dict([(i['__hash__'], i,) for i in data[r]
                                 if i.has_key('__hash__')]),)
                       for r in hrel.values()])

        # get field objects for required collections
        fields = dict([(i, handler.meta.model._meta.get_field(i),)
                       for i in hrel.keys()])

        self.log("\nsynchronization          %s " %
                 str(len(collection)).ljust(5))
        for item in collection:
            for fname, cname in item.get('hash_related', {}).items():
                field, value = fields[fname], item['fields'][fname]
                msg = ('Hash relation corrupted in "%s:%s->%s" [%s:%s].'
                       % (handler.get_key(), fname, cname, field, value))

                rvalue = hashed[cname]

                # process m2m, fk (m2o) and direct value differently
                if isinstance(field.remote_field, models.ManyToManyRel):
                    rfield = field.remote_field.get_related_field()
                    for key, val in enumerate(value):
                        if isinstance(val, dict) and '__hash__' in val:
                            value[key] = self.get_synchronized_value(
                                rfield, rvalue.get(val['__hash__'], None),
                                val, strict_mode, msg)

                elif isinstance(field.remote_field, models.ManyToOneRel):
                    rfield = field.remote_field.get_related_field()
                    if isinstance(value, dict) and '__hash__' in value:
                        item['fields'][fname] = self.get_synchronized_value(
                            rfield, rvalue.get(value['__hash__'], None),
                            value, strict_mode, msg)

                elif isinstance(value, dict) and '__hash__' in value:
                    item['fields'][fname] = self.get_synchronized_value(
                        None, rvalue.get(value['__hash__'], None),
                        value, strict_mode, msg)
            self.log('.')

    def pre_run(self, lqueue=None, hqueue=None, data=None, files=None):
        for loader in lqueue:
            loader.pre_run(data=data, files=files)
        for name, handler in hqueue:
            handler.pre_run(data=data, files=files)

    def post_run(self, lqueue=None, hqueue=None, data=None, files=None):
        for loader in lqueue:
            loader.post_run(data=data, files=files)
        for name, handler in hqueue:
            handler.post_run(data=data, files=files)

    def visualize_struct(self, loaders, handlers):
        return (u'Importer "%s"\n- loaders:\n    %s\n- handlers:\n    %s'
                % (self.__class__.__name__,
                   '\n    '.join(i.__class__.__name__ for i in loaders),
                   '\n    '.join('%s (%s)%s' %  (
                                     i[1].__class__.__name__, i[0],
                                     ' [strict]' if i[1].strict_mode else ''
                                 ) for i in handlers),))

    def run(self, data=None, files=None, **kwargs):
        """
        Внимание: прием переменных data и fiels добавлен для случая,
                  когда нет необходимости использования лоадеров.
                  По умолчанию необходимо использовать лоадеры.
        Каждый лоадер принимает параметр data и **kwargs и должен обновлять
        переменную data, добавляя загруженные им значения к уже существующим.
        """

        options = dict(self.options or {}, **kwargs)
        clsname = type(self).__name__
        download = options.get('main.download', False)
        generate = options.get('main.generate', False)

        lqueue = self.get_loaders_queue(**options)
        hqueue = self.get_handlers_queue(**options)
        status = 0

        self.log(u'%s\n%s S Y N C D A T A %s\n%s\n'
                 u'\nStarting Importer "%s".'
                 u'\n- message       %s'
                 u'\n- datetime      %s'
                 u'\n- class         %s'
                 u'\n- datadir       %s'
                 u'\n- options       %s'
                 u'\n- struct\n  %s'
                 % ('-'*79, '-'*31, '-'*31, '-'*79,
                    clsname, options.get('message', u'—'),
                    timezone.localtime(timezone.now()), self.__class__,
                    settings.DATA_DIR,
                    json.dumps(options, indent=2, ensure_ascii=False),
                    '\n  '.join(self.visualize_struct(lqueue,
                                                      hqueue).splitlines()),))

        try:
            locker = self.lockname or '%s.lock' % clsname.lower()
            locker = (FileLock(settings.DATA_DIR,
                               locktime=self.locktime, lockname=locker)
                      if self.lockable else None)
            if locker and not locker.lock():
                raise LockedModelHandlerException
            elif locker:
                self.log('\n\n%s\n-- L O C K E D %s seconds --\n%s' % (
                    '-'*79, '{:>53}'.format(locker.check(astime=True)), '-'*79))

            # data loading
            self.log('\n\n%s LOADERS Queue %s' % ('-'*32, '-'*32))
            data, files = data or {}, files or {}
            if not data and lqueue:
                for loader in lqueue:
                    self.log('\n\n%s ...' % clsname)

                    data, urls = loader.run(data, **options)
                    urls and files.update(urls)

                    self.log(' OK')

            if download and files:
                self.log('\n\nDownload files ...\n%s\n'
                         'Downloading              %s ' %
                         ('-'*25, str(len(files)).ljust(5)))

                (loader.download_media_handler(files)
                 if hasattr(loader, 'download_media_handler')
                 else self.download_media(files))

                self.log('\n%s\nOK' % ('-'*25,))

            if generate:
                signals.importer_pre_launch.send(
                    sender=type(self), importer=self,
                    lqueue=lqueue, hqueue=hqueue, data=data, files=files)
                self.pre_run(lqueue=lqueue, hqueue=hqueue,
                             data=data, files=files)

                # data importing
                self.log('\n\n%s HANDLERS Queue %s' % ('-'*32, '-'*31))
                for name, handler in hqueue:
                    collection = data.get(name, None)
                    if collection is not None:
                        self.log('\n\n%s (%s) ...\n%s' % (
                                 handler.__class__.__name__, name, '-'*25))

                        self.synchronize(handler, data, **options)
                        handler.run(collection, **options)

                        self.log('\n%s\nOK' % ('-'*25))

                self.post_run(lqueue=lqueue, hqueue=hqueue,
                              data=data, files=files)
                signals.importer_post_launch.send(
                    sender=type(self), importer=self,
                    lqueue=lqueue, hqueue=hqueue, data=data, files=files)

        except LockedModelHandlerException as e:
            self.log('\n\n%s\n%s I M P O R T E R   I S   L O C K E D %s\n%s\n'
                     '// Seconds to unlock%s //\n%s' %
                     ('/'*79, '/'*21, '/'*21, '/'*79,
                      '{:.>56}'.format(locker.check(astime=True)), '/'*79,))
            status = 1
            locker = None

        except Exception as e:
            self.log('\n\n%s\n%s R A I Z E D   E X C E P T I O N %s\n%s'
                     '\n\nImporter "%s" stopped with the following exception'
                     ' and traceback:\n%s\n%s%s' %
                     ('*'*79, '*'*23, '*'*23, '*'*79, clsname,
                      '-'*79, exception_to_text(e), '-'*79,))
            status = 1

        finally:
            if locker:
                self.log('\n\n%s\n-- U N L O C K E D %s seconds --\n%s' % (
                    '-'*79,
                    '{:>49}'.format(locker.check(astime=True, remained=False)),
                    '-'*79))
                locker.unlock()

        self.log('\n\n%s\nFINISHED at "%s" with status "%s" (%s)' % (
            '-'*8, timezone.localtime(timezone.now()),
            status, 'FAIL' if status else 'SUCCESS'))
        self.finallog(name=clsname, status=status)
        return status
