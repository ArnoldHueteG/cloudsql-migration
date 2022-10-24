import logging
import sys
import time

import fire
import yaml
from kubernetes import client
from kubernetes import config
from kubernetes.client import V1ConfigMap
from kubernetes.client import V1ObjectMeta

from aws import AwsApi
from config import FileBasedConfig
from config import K8sConfig
from config import ValidationError
from kube import K8sApiLocal
from kube import K8sApiNative


class PrepCommands:

    def __init__(self, config="config.yaml", logger=None):
        """
        Run locally only on aws/k8s!
        :param config: set as "k8s" to use the configmap in tmc-iam namespace to store config 
        """
        self._logger = logger if logger is not None else logging.getLogger(__name__)
        self._config = FileBasedConfig(config) if not config == 'k8s' else K8sConfig(logger=logger)
        self._k8s = K8sApiLocal(logger=logger)
        self._aws = AwsApi()

    def validate_config(self, service="all"):
        """
        Validate a config object for a particular service or "all" to specify
        all services. Defaults to "all". Validation does the following steps:
        1. ensure that each required field is present
        2. ensure gcp-cpu and gcp-mem are valid.
        3. ensure that the AWS-DB can be reached and logged into

        Requires that the current k8s context is the AWS env, not GCP!!!

        :param service: name of service in the config yaml
        """

        # start up k8s psql node
        self._k8s.start_psql()

        if service == 'all':
            for key in self._config.keys():
                self.validate_config(key)
        else:
            errors = self._config[service].validate()
            if errors:
                raise ValidationError(errors)

            cfg = self._config[service]
            self._k8s.check_connection(cfg['aws-host'],
                                       cfg['aws-port'],
                                       cfg['database-name'],
                                       cfg['aws-replication-username'],
                                       cfg['aws-replication-password'])

    def prepare_rds_network(self, service="all"):
        """
        Ensure the RDS instance has the correct inbound cidr rules to connect to
        GCP
        :return:
        """
        if service == "all":
            for s in self._config.keys():
                self.prepare_rds_network(s)
            return

        # all private ranges
        env_cidr = {
            "dev": ["10.0.0.0/8", "172.0.0.0/8", "192.0.0.0/8"],
            "staging": ["10.0.0.0/8", "172.0.0.0/8", "192.0.0.0/8"],
            "prod": ["10.0.0.0/8", "172.0.0.0/8", "192.0.0.0/8"],
            "sb1": ["10.0.0.0/8", "172.0.0.0/8", "192.0.0.0/8"]
        }
        props = self._config[service].props
        ip_added = self._aws.allow_sec_group_ip_ingress(props['aws-instance'], env_cidr[props['k8s-env']])
        if ip_added:
            self._logger.info(f"updating allowed cidr blocks for {service}/{props['aws-instance']} :: {ip_added}")
        else:
            self._logger.info(f"no action taken for {service}/{props['aws-instance']}")

    def prepare_rds_users(self, service, create_replication_user=False, recurse=False):
        """
        Prior to running:
        1. ensure logged into gcp-scripts
        2. ensure k8s access
        3. ensure logged into aws-okta
        :param service:
        :return:
        """
        if not recurse:
            self._logger.warning("ENSURE YOU ARE ON AWS K8S")
            self._logger.warning("ENSURE YOU HAVE RECENTLY RUN: 'aws-okta exec okta -- aws rds'")
            self._logger.warning("you have 2 seconds to press ctl+c to exit...")
            time.sleep(2)
            self._logger.warning("continuing..")
        if service == "all":
            for s in self._config.keys():
                self.prepare_rds_users(s, create_replication_user=create_replication_user, recurse=True)
            return

        props = self._config[service]

        master_password = props.get("aws-master-password", False)
        if not master_password:
            self._logger.info(f"resetting master password for {service}")
            master_password = self._aws.reset_rds_master_password(props['aws-instance'])
            self._config.save({"aws-master-password": master_password}, service)

        if create_replication_user:
            self._logger.info("creating replication user")
            replication_username, replication_password = \
                self._aws.create_replication_user(props['aws-host'], props['database-name'], 'pgadmin', master_password)

            self._config.save({"aws-replication-username": replication_username,
                               "aws-replication-password": replication_password},
                              service)
        else:
            self._logger.info("skipping creating replication user, this will happen automatically on sync")

    def update_config_map(self, location: str, name="cloudsql-migration", namespace="tmc-iam", service=None):
        """
        Updates existing config map with new config map. Completely replaces
        :param location:
        :param name:
        :param namespace:
        :param service Only update a specified service. If not specified, replaces everything
        :return:
        """
        with open(location, 'r') as f:
            doc = yaml.safe_load(f)
        body = {}
        for k, v in doc.items():
            if service is None or service == k:
                body[k] = yaml.safe_dump(v)
        if len(body) == 0:
            self._logger.error(f"0 services for update, select one of: {list(doc.keys())}")
            return

        config.load_kube_config()
        v1 = client.CoreV1Api = client.CoreV1Api()
        exists = True
        try:
            v1.read_namespaced_config_map(name, namespace)
        except:
            exists = False

        meta = V1ObjectMeta(name=name, namespace=namespace, labels={"au/team": "accounts-identity"})
        cfgmap = V1ConfigMap(metadata=meta, data=body)
        if exists:
            self._logger.info(f"patching {list(body.keys())}")
            v1.patch_namespaced_config_map(name, "tmc-iam", cfgmap)
        else:
            self._logger.info(f"creating {list(body.keys())}")
            v1.create_namespaced_config_map("tmc-iam", cfgmap)


class PrepCli(PrepCommands):
    def __init__(self, config="config.yaml"):
        def setup_logger():
            logger = logging.getLogger(__name__)
            formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s', datefmt='%Y/%m/%d %H:%M:%S')
            streamHandler = logging.StreamHandler()
            streamHandler.setFormatter(formatter)
            logger.addHandler(streamHandler)
            logger.setLevel(logging.DEBUG)
            return logger

        def exception_handler(exception_type, exception, traceback):
            print("%s: %s" % (exception_type.__name__, exception))
        sys.excepthook = exception_handler

        logger = setup_logger()
        super(PrepCli, self).__init__(config=config, logger=logger)


if __name__ == '__main__':
    fire.Fire(PrepCli)
