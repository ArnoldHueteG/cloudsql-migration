import abc
import logging
import os
import typing

import yaml
from kubernetes import client
from kubernetes import config
from kubernetes.client import ApiException

Logger = logging.getLogger(__name__)


class ValidationError(BaseException):
    def __init__(self, errors):
        self._errors = errors

    def __str__(self):
        return "validation errors: {}".format("\n".join(self._errors))


class DbConfig:
    _required_fields = [
        'aws-host',
        'aws-instance',
        'aws-port',
        'readonly-secret-name',
        'readwrite-secret-name',
        'aws-replication-password',
        'aws-replication-username',
        'gcp-auto-storage-increase',
        'gcp-database-version',
        'gcp-disk-type',
        'gcp-instance-cpu',
        'gcp-instance-mem',
        'gcp-instance-region',
        'gcp-instance-storage',
        'gcp-migration-strategy',
        'gcp-project-name',
        'k8s-env',
        'k8s-namespace',
        'k8s-service',
    ]

    _remote_fields = [
        'aws-readonly-password',
        'aws-readwrite-password',
    ]

    def __init__(self, name, props):
        self.name = name
        self.props = props

    def to_yaml(self):
        return yaml.safe_dump(repr(self))

    def __str__(self):
        return self.name

    def __repr__(self):
        return {self.name: self.props}

    def get(self, item, default=None):
        try:
            return self.__getitem__(item)
        except:
            return default

    def __getitem__(self, item):
        if item == 'database-name':
            if 'database-name' in self.props:
                return self.props['database-name']
            elif 'readwrite-secret-name' in self.props:
                # infer DB name from secret naming convention
                return self.props['readwrite-secret-name'].split(".")[1]

        if item == 'gcp-rootuser-secret-name':
            if 'gcp-rootuser-secret-name' in self.props:
                return self.props['gcp-rootuser-secret-name']
            return self.props['readwrite-secret-name'].replace('.rw', '.root')

        if item == 'aws-master-username':
            if 'aws-master-username' in self.props:
                return self.props['aws-master-username']
            return 'pgadmin'

        if item == 'aws-replication-password':
            # invalid pw => None
            if 'aws-replication-password' in self.props:
                pw = self.props['aws-replication-password']
                if pw == "?" or pw == "" or not pw:
                    return None
                return pw
            return None

        return self.props[item]

    def validate(self):
        """
        :return: list of errors. An empty list indicates no errors
        """
        errors = []
        for field in DbConfig._required_fields:
            if field not in self.props or self.props[field] is None:
                errors.append('missing configuration field "{}" in config "{}"'.format(field, self.name))

        if self.props.get('gcp-migration-strategy', '') == 'remote':
            for field in DbConfig._remote_fields:
                if field not in self.props or self.props[field] is None:
                    errors.append('missing configuration field "{}" in config "{}"'.format(field, self.name))

        if 'database-name' not in self.props and len(self.props.get('readwrite-secret-name', "").split(".")) != 3:
            errors.append('missing configuration field "database-name" in config "{}"'.format(self.name))

        gcp_cpu = int(self.props.get('gcp-instance-cpu'))
        gcp_mem = int(self.props.get('gcp-instance-mem'))
        min_mem_by_cpu = 0.9 * 1024 * gcp_cpu
        max_mem_by_cpu = 6.5 * 1024 * gcp_cpu
        if gcp_cpu < 1 or gcp_cpu > 96:
            errors.append(f'{self.name}: gcp-cpu is not a valid value: {gcp_cpu} must be between 1 and 96')
        elif gcp_cpu % 2 == 1 and gcp_cpu > 1:
            errors.append(f'{self.name}: gcp-cpu is not a valid value: {gcp_cpu} must be either 1 or an even number')
        if gcp_mem % 256 > 0:
            errors.append(f'{self.name}: gcp-mem is not a valid value: {gcp_mem} must be a multiple of 256 MB')
        elif gcp_mem < 3840:
            errors.append(f'{self.name}: gcp-mem is not a valid value: {gcp_mem} must be at least 3.75 GB (3840 MB)')
        elif gcp_mem < min_mem_by_cpu or gcp_mem > max_mem_by_cpu:
            errors.append(f'{self.name}: gcp-mem is not a valid value: {gcp_mem} must be 0.9 to 6.5 GB per vCPU')
        return errors


class Config(abc.ABC):
    def keys(self) -> []:
        pass

    def save(self, doc: dict, service: str):
        pass

    def __getitem__(self, item: str) -> DbConfig:
        pass


class FileBasedConfig(Config):
    def __init__(self, fn):
        self._config_location = fn
        self._config = {}  # serviceName -> DbConfig
        self._load()

    def _load(self):
        with open(self._config_location) as f:
            doc = yaml.safe_load(f)
            for service_name, service_doc in doc.items():
                self._config[service_name] = DbConfig(service_name, service_doc)

    def keys(self):
        return self._config.keys()

    def __getitem__(self, item):
        return self._config[item]

    def save(self, doc, service):
        try:
            with open(self._config_location, 'r') as f:
                current = yaml.safe_load(f)
                for k, v in doc.items():
                    current[service][k] = v
        except Exception as error:
            Logger.warning("Could NOT LOAD {}: {}".format(self._config_location, error))

        try:
            with open(self._config_location, 'w') as f:
                yaml.safe_dump(current, f)
        except Exception as error:
            raise Exception(f"Failed to update {self._config_location} with error: {error}")

        self._load()


class K8sConfig(Config):
    def __init__(self,
                 name="cloudsql-migration",
                 namespace="tmc-iam",
                 logger=None,
                 v1: typing.Optional[client.CoreV1Api] = None):
        if v1 is None:
            if os.path.isfile(config.incluster_config.SERVICE_TOKEN_FILENAME):
                config.load_incluster_config()
            else:
                config.load_config()
            self._v1: client.CoreV1Api = client.CoreV1Api()
        else:
            self._v1 = v1
        self._namespace = namespace
        self._name = name
        self._config: typing.Mapping[str, DbConfig] = {}  # serviceName -> DbConfig
        self._load()
        self._logger = logger if logger is not None else Logger

    def _load(self):
        self._cm_obj = self._v1.read_namespaced_config_map(self._name, self._namespace)
        # service -> yaml map
        c = {}
        for k, v in self._cm_obj.data.items():
            c[k] = DbConfig(k, yaml.safe_load(v))
        self._config = c

    def keys(self):
        return self._config.keys()

    def __getitem__(self, item):
        return self._config[item]

    def save(self, updated_props, service):
        self._logger.info(f"updating config properties: {service}::{list(updated_props.keys())}")
        limit = 10
        attempt = 0
        while attempt < limit:
            try:
                self._load()  # ensure we have the latest data... not a perfect guarantee though so wrap in try/catch
                props = self._config[service].props
                for k, v in updated_props.items():
                    props[k] = v
                cm_data = self._cm_obj.data
                cm_data[service] = yaml.safe_dump(props)
                self._cm_obj.data = cm_data
                self._v1.patch_namespaced_config_map(self._name, self._namespace, self._cm_obj)
                return  # success
            except ApiException as e:
                if e.status == 409:
                    attempt += 1
                else:
                    raise e
        raise Exception(f"max retries ({limit}) for apply configmap change exceeded")

