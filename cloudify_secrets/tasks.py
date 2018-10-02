########
# Copyright (c) 2018 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#    * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    * See the License for the specific language governing permissions and
#    * limitations under the License.

import json

from cloudify.exceptions import NonRecoverableError
from cloudify.decorators import operation
from cloudify.manager import get_rest_client
from cloudify_rest_client.exceptions import CloudifyClientError

DATA_RUNTIME_PROPERTY = 'data'

DO_NOT_DELETE_PROPERTY = 'do_not_delete'

KEYS_PROPERTY = 'keys'


class SecretsSDK(object):
    DEFAULT_SEPARATOR = '__'

    @staticmethod
    def _handle_variant(key,
                        variant=None,
                        separator=DEFAULT_SEPARATOR,
                        **_):
        if variant:
            return '{0}{1}{2}'.format(key, separator, variant)

        return key

    @staticmethod
    def _try_to_serialize(value):
        if isinstance(value, dict):
            return json.dumps(value)

        return value

    @staticmethod
    def _try_to_parse(value):
        try:
            return json.loads(value)
        except ValueError:
            return value

    def __init__(self, logger, rest_client):
        self._logger = logger
        self._rest_client = rest_client

    def _write(self, parameters, rest_client_method):
        entries = parameters.get('entries', {})

        result = {}

        for key, value in entries.iteritems():
            self._logger.debug(
                'Creating secret "{0}" with value: {1}'
                    .format(key, value)
            )

            result[key] = rest_client_method(
                key=self._handle_variant(key, **parameters),
                value=self._try_to_serialize(value)
            )

        return result

    def create(self, parameters):
        return self._write(parameters, self._rest_client.secrets.create)

    def update(self, parameters):
        return self._write(parameters, self._rest_client.secrets.patch)

    def delete(self, parameters, secrets):
        for key in secrets.keys():
            self._logger.debug(
                'Deleting secret "{0}" ...'.format(key)
            )

            self._rest_client.secrets.delete(
                key=self._handle_variant(key, **parameters)
            )

    def read(self, parameters, keys):
        result = {}

        for key in keys:
            self._logger.debug('Reading secret "{0}" ...'.format(key))

            result[key] = self._rest_client.secrets.get(
                key=self._handle_variant(key, **parameters)
            )

        return result


def _get_parameters(properties, kwargs):
    for k, v in properties.iteritems():
        if k not in kwargs:
            kwargs[k] = v

    return kwargs


@operation
def create(ctx, **kwargs):
    parameters = _get_parameters(ctx.node.properties, kwargs)

    result = SecretsSDK(ctx.logger, get_rest_client()).create(parameters)

    ctx.instance.runtime_properties[DO_NOT_DELETE_PROPERTY] = parameters.get(
        DO_NOT_DELETE_PROPERTY,
        False
    )
    ctx.instance.runtime_properties[DATA_RUNTIME_PROPERTY] = result


@operation
def update(ctx, **kwargs):
    parameters = _get_parameters(ctx.node.properties, kwargs)

    result = SecretsSDK(ctx.logger, get_rest_client()).update(parameters)

    ctx.instance.runtime_properties[DO_NOT_DELETE_PROPERTY] = parameters.get(
        DO_NOT_DELETE_PROPERTY,
        False
    )
    ctx.instance.runtime_properties[DATA_RUNTIME_PROPERTY] = result


@operation
def delete(ctx, **kwargs):
    if ctx.instance.runtime_properties.get(DO_NOT_DELETE_PROPERTY, False):
        ctx.logger.info(
            '"do_not_delete" property set to <true> - skipping deletion ...'
        )

        return

    parameters = _get_parameters(ctx.node.properties, kwargs)
    secrets = ctx.instance.runtime_properties[DATA_RUNTIME_PROPERTY]

    SecretsSDK(ctx.logger, get_rest_client()).delete(parameters, secrets)

    ctx.instance.runtime_properties.pop(DATA_RUNTIME_PROPERTY, None)
    ctx.instance.runtime_properties.pop(DO_NOT_DELETE_PROPERTY, None)


@operation
def read(ctx, **kwargs):
    parameters = _get_parameters(ctx.node.properties, kwargs)
    keys = parameters.get(KEYS_PROPERTY, [])

    result = SecretsSDK(ctx.logger, get_rest_client()).read(parameters, keys)

    ctx.instance.runtime_properties[DATA_RUNTIME_PROPERTY] = result
