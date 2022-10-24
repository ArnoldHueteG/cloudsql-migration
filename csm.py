import base64
import logging
import multiprocessing
import random
import string
import sys
import time
import traceback
from datetime import datetime

import fire

from config import Config
from config import DbConfig
from config import FileBasedConfig
from config import ValidationError
from gcp import GcpApi
from kube import K8sApiBase
from kube import K8sApiLocal

DEFAULT_PORT = 5432
MJ_PREFIX = 'auto-mj-'
CP_SRC_PREFIX = 'src-'
VPC = {
    "dev": {"host": "prj-d-vpc-host", "base": "vpc-d-shared-base"},
    "staging": {"host": "prj-s-vpc-host", "base": "vpc-s-shared-base"},
    "prod": {"host": "prj-p-vpc-host", "base": "vpc-p-shared-base"},
    "sb1": {"host": "prj-sb-vpc-host", "base": "vpc-sb-shared-base"}
}
ENVCODE = {
    "dev": "d",
    "staging": "s",
    "prod": "p",
    "sb1": "sb"
}

# obtained from https://s3.amazonaws.com/rds-downloads/rds-ca-2019-root.pem
RDS_ROOT_PEM64 = "LS0tLS1CRUdJTiBDRVJUSUZJQ0FURS0tLS0tCk1JSUVCakNDQXU2Z0F3SUJBZ0lKQU1jMFp6YVNVSzUxTUEwR0NTcUdTSWIzRFFFQkN3VUFNSUdQTVFzd0NRWUQKVlFRR0V3SlZVekVRTUE0R0ExVUVCd3dIVTJWaGRIUnNaVEVUTUJFR0ExVUVDQXdLVjJGemFHbHVaM1J2YmpFaQpNQ0FHQTFVRUNnd1pRVzFoZW05dUlGZGxZaUJUWlhKMmFXTmxjeXdnU1c1akxqRVRNQkVHQTFVRUN3d0tRVzFoCmVtOXVJRkpFVXpFZ01CNEdBMVVFQXd3WFFXMWhlbTl1SUZKRVV5QlNiMjkwSURJd01Ua2dRMEV3SGhjTk1Ua3cKT0RJeU1UY3dPRFV3V2hjTk1qUXdPREl5TVRjd09EVXdXakNCanpFTE1Ba0dBMVVFQmhNQ1ZWTXhFREFPQmdOVgpCQWNNQjFObFlYUjBiR1V4RXpBUkJnTlZCQWdNQ2xkaGMyaHBibWQwYjI0eElqQWdCZ05WQkFvTUdVRnRZWHB2CmJpQlhaV0lnVTJWeWRtbGpaWE1zSUVsdVl5NHhFekFSQmdOVkJBc01Da0Z0WVhwdmJpQlNSRk14SURBZUJnTlYKQkFNTUYwRnRZWHB2YmlCU1JGTWdVbTl2ZENBeU1ERTVJRU5CTUlJQklqQU5CZ2txaGtpRzl3MEJBUUVGQUFPQwpBUThBTUlJQkNnS0NBUUVBclhuRi9FNi9RaCtrdTNoUVRTS1BNaFFRbENwb1d2bkl0aHpYNk1LM3A1YTBlWEtaCm9XSWpZY05ORzZVd0pqcDRmVVhsNmdscDUzSm9ibit0V05YODhkTkgybjhEVmJwcFN3U2NWRTJMcHVMKzk0dlkKMEVZRS9YeE43c3ZLZWE4WXZscnFrVUJLeXhMeFRqaCtVL0tyR09hSHh6OXYwbDZaTmxEYnVhWnczcUlXZEQvSQo2YU5iR2VSVVZ0cE02UCtiV0lveFZsL2NhUXlsUVM2Q0VZVWsrQ3BWeUpTa29wd0pselhUMDd0TW9ETDVXZ1g5Ck8wOEtWZ0ROejlxUC9JR3RBY1JkdVJjTmlvSDNFOXY5ODFRTzF6dC9HcGIyZjhOcUFqVVVDVVp6T25pajZteDkKTWNaKzljV1g4OENSelIwdlFPRFd1WnNjZ0kwOE52TTY5Rm4yU1FJREFRQUJvMk13WVRBT0JnTlZIUThCQWY4RQpCQU1DQVFZd0R3WURWUjBUQVFIL0JBVXdBd0VCL3pBZEJnTlZIUTRFRmdRVWMxOWcyTHpMQTVqMEt4YzBMalphCnBtRC92Qjh3SHdZRFZSMGpCQmd3Rm9BVWMxOWcyTHpMQTVqMEt4YzBMalphcG1EL3ZCOHdEUVlKS29aSWh2Y04KQVFFTEJRQURnZ0VCQUhBRzdXVG15anpQUklNODVyVmorZldIc0xJdnFwdzZET2JJak1Xb2twbGlDZU1JTlpGVgp5bmZnQktzZjFFeHdidkpOellGWFc2ZGlobmd1REc5Vk1QcGkydXAvY3RRVE44dG05bkRLT3kwOHVOWm9vZk1jCk5VWnhLQ0VrVktaditJTDRvSG9lYXl0OGVndHYzdWpKTTZWMTRBc3RNUTZTd3Z3dkE5M0VQL1VnMmU0V0FYSHUKY2JJMU5BYlVnVkRxcCtEUmRmdlprZ1lLcnlqVFdkLzArMWZTOFgxYkJaVld6bDdlaXJOVm5IYlNIMlpEcE51WQowU0JkOGRqNUY2bGQzdDU4eWRaYnJUSHplN0pKT2Q4aWp5U0FwNC9raXU5VWZaV3VUUEFCekRhL0RTZHo5RGsvCnpQVzRDWFh2aExtRTAyVEE5L0hlQ3czS0VISXdpY051RWZ3PQotLS0tLUVORCBDRVJUSUZJQ0FURS0tLS0tCg=="


class MigrationCommands:

    def __init__(self, config: Config, k8s: K8sApiBase, logger=logging.getLogger("x")):
        self._logger = logger
        self._config = config
        self._now_str = datetime.now().strftime("%Y%m%dt%H%M%S")
        self._rds_cert = str(base64.b64decode(bytes(RDS_ROOT_PEM64, encoding="UTF-8")), encoding='UTF-8')

        self._k8s = k8s
        self._gcp = GcpApi(logger=self._logger)

    def preflight(self, service) -> dict:
        """
        does pre-flight preparation of DB and check for app health
        do:
        1/ idempotent create/update replication user, assign permissions
        check:
        1/ target pod exists in target namespace
        2/ target database can be connected to
        3/ job is not already running
        TODO:
        1/ service account can access these namespaces
        :param service:
        :return: dict of statuses for various preflight checks. key "pass" will be True/False if there were no/any errors
        """
        def is_ok(statuses):
            return not any(filter(lambda k,v: v != 'ok', statuses.items()))

        status = {}
        cfg = self._config[service]
        app_healthy, error = self._k8s.check_app_healthy(cfg['k8s-namespace'], cfg['k8s-service'])
        status['app'] = "ok" if app_healthy else error


        try:
            self._k8s.check_connection(cfg['aws-host'], cfg['aws-port'], cfg['database-name'], 'pgadmin', cfg['aws-master-password'])
        except Exception as e:
            status['rdsMaster'] = f"failed to connect to db {cfg['aws-host']}/{cfg['database-name']} as pgadmin: {str(e)}"
            status['pass'] = False
            return status  # short-circuit

        # prepare rds instance, if running on k8s
        try:
            repl_pw = self._k8s.create_replication_user(
                cfg['aws-replication-username'],
                cfg['aws-replication-password'],
                dbname=cfg['database-name'],
                host=cfg['aws-host'],
                port=cfg['aws-port'],
                user=cfg['aws-master-username'],
                password=cfg['aws-master-password']
            )
            if repl_pw is not None:
                self._config.save({"aws-replication-password": repl_pw}, service)
        except Exception as e:
            status['rdsReplication'] = f"failed to create replication user {cfg['aws-host']}/{cfg['database-name']}: {str(e)}"

        status['pass'] = is_ok(status)
        return status


    def sync(self, service):
        """
        Starts db migration process and creates rw and ro secrets for
        respective services in gcp cluster based on which migration
        scenario the service is part of (local vs remote)
        1. Creates and starts migration job
        2. Create gcp or aws secret in gcp env cluster
        3. Restart gcp service
        :param service: name of service in the config yaml
        """
        cfg = self._config[service]

        # Prepare migration job and Start
        self._create_connection_profile(service)
        self._create_dms_job(service)

        # Create cloudsql users and Retrieve cloudsql information
        self._logger.debug(f'migrating {service} using strategy "{cfg["gcp-migration-strategy"]}"')
        self._create_db_users(service)
        self._create_sync_secrets(service)
        self._k8s.restart_gcp_service(cfg['k8s-service'], cfg['k8s-namespace'])

        self._await_state(service, "RUNNING")
        self._logger.info(f"job running, await database CDC phase")
        self._await_phase(service, target_phase="CDC")
        self._logger.info(f"CDC phase reached, sync complete, ready to cutover")

    def _create_sync_secrets(self, service, force_local=False):
        """
        Create secrets for service to use while gcp migration job is at or before CDC.
        """
        cfg = self._config[service]
        namespace = cfg['k8s-namespace']
        rw_secret_name = cfg['readwrite-secret-name']
        ro_secret_name = cfg['readonly-secret-name']
        rw_username = 'readwrite'

        dbname = cfg['database-name']
        if force_local or cfg["gcp-migration-strategy"] == 'local':
            host = cfg['gcp-host']
            port = cfg['gcp-port']
            # incorrect username is on purpose: don't allow writes to GCP DB until promoted
            rw_username = 'readonly'
            rw_password = cfg['gcp-readonly-password']
            ro_password = cfg['gcp-readonly-password']
        else:
            host = cfg['aws-host']
            port = cfg['aws-port']
            rw_password = cfg['aws-readwrite-password']
            ro_password = cfg['aws-readonly-password']

        self._k8s.create_secret(rw_secret_name, namespace,
                                username=rw_username,
                                password=rw_password,
                                dbname=dbname,
                                host=host,
                                port=port)
        self._k8s.create_secret(ro_secret_name, namespace,
                                username='readonly',
                                password=ro_password,
                                dbname=dbname,
                                host=host,
                                port=port)

    def validate_service(self, service="all"):
        """
        Shows a report on status of services
        """
        if service == 'all':
            errors = []
            for key in self._config.keys():
                try:
                    self.validate_service(key)
                except ValidationError as v:
                    errors.extend(v._errors)
            if errors:
                raise ValidationError(errors)
        else:
            cfg = self._config[service]
            restarts, states, raw = self._k8s.get_pods_status(cfg['k8s-service'])
            self._logger.info(f"{service} states: {states}, restarts: {restarts}")

            for pod in raw:
                self._logger.debug(f"pod: {pod['name']}, state: {pod['state']}, restarts: {pod['restartCount']}")

            if states != {"running"}:
                raise ValidationError([f"service {service} is not running"])

    def _sql_instance_name(self, service):
        # conform the pattern that terraform expects (sql-{env-code}-p-{service-name}-{hash})
        env = self._config[service]['k8s-env']
        return f"sql-{ENVCODE[env]}-p-{service}-{self._now_str}"

    def _grant_access_to_user(self, service, username_to_grant):
        """
        :param service: name of service in the config yaml
        """
        cfg = self._config[service]

        # Retrieve db name from readwrite-secret-name
        # Cloudsql db and AWS rds db names are same
        self._k8s.grant_access_to_user(cfg['gcp-host'],
                                       DEFAULT_PORT,
                                       cfg['readwrite-secret-name'].split(".")[1],
                                       "postgres",
                                       cfg['gcp-root-password'],
                                       username_to_grant)

    def _describe_dms_job(self, service):
        """
        Describes current phase of Database Migration Job for a particular service.

        :param service: name of service in the config yaml
        :return {state:, status:, error:} or None if the job was not found
        """
        cfg = self._config[service]
        project_id = self._gcp.list_projects().get(cfg["gcp-project-name"]).get("projectId")
        return self._gcp.get_dms_status(project_id, cfg["gcp-instance-region"], f"{MJ_PREFIX}{service}")

    def _promote_dms_job(self, service):
        """
        Promotes Database Migration Job for a particular service or "all" to
        specify all services.Defaults to "all".
        Promoting dms job the following steps:
        1. Promotes target cloudsql to primary ONLY IF dms job phase == 'CDC'
        :param service: name of service in the config yaml
        :return True if job was promoted or had already been promoted
        """
        cfg = self._config[service]
        project_id = self._gcp.list_projects().get(cfg["gcp-project-name"]).get("projectId")

        job_desc = self._gcp.get_dms_status(project_id, cfg["gcp-instance-region"], f"{MJ_PREFIX}{service}")
        if job_desc is None or job_desc['state'] == "COMPLETED":
            self._logger.warning(f"promotion already done for {service}")
            return True
        elif job_desc['phase'] == 'CDC':
            self._gcp.promote_dms_job(project_id, cfg["gcp-instance-region"], f"{MJ_PREFIX}{service}")
            return True

        self._logger.warning(f"not ready to promote job {service}. Job: {job_desc}")
        return False

    def _await_state(self, service, target_state):
        """
        Await a state of job
        https://cloud.google.com/database-migration/docs/reference/rest/v1alpha2/projects.locations.migrationJobs#phase
        """
        job_desc = self._describe_dms_job(service)
        if job_desc["state"] is None:
            raise Exception(f"job was not found")

        current_state = job_desc['state']
        sleep_time = 1
        self._logger.info(f"state of job/{service}: {current_state}, target: {target_state}")
        while current_state != target_state:
            time.sleep(sleep_time)
            sleep_time = min(10, sleep_time * 2)
            job_desc = self._describe_dms_job(service)
            if job_desc['state'] == 'FAILED':
                raise Exception(f"job failed: {job_desc}")
            else:
                current_state = job_desc['state']
        self._logger.info(f"state of job/{service}: {job_desc}")

    def _await_phase(self, service, target_phase="CDC"):
        """
        Await a phase of data transfer. Note that the STATE of the job must be RUNNING!!!
        https://cloud.google.com/database-migration/docs/reference/rest/v1alpha2/projects.locations.migrationJobs#phase
        :param service:
        :param target_phase:
        :return:
        """
        phases = {'PHASE_UNSPECIFIED': 1000, 'FULL_DUMP': 2, 'CDC': 3, 'PROMOTE_IN_PROGRESS': 4}
        job_desc = self._describe_dms_job(service)
        if job_desc["state"] != "RUNNING":
            raise Exception(f"job was not in RUNNING state: {job_desc}")

        start_time = time.time()
        current_phase = job_desc['phase']
        sleep_time = 1
        self._logger.info(f"phase {service}: {current_phase}, target: {target_phase}")
        while phases.get(current_phase, -1) < phases.get(target_phase, -2):
            time.sleep(sleep_time)
            sleep_time = min(10, sleep_time * 2)
            job_desc = self._describe_dms_job(service)
            if job_desc['state'] == 'COMPLETED':
                break
            elif job_desc['state'] != 'RUNNING':
                raise Exception(f"job was not in RUNNING state: {job_desc}")
            else:
                current_phase = job_desc['phase']
        self._logger.info(f"phase {service}: {job_desc}, target: {target_phase} after {time.time() - start_time}s")

    def cutover(self, service):
        """
        Promote the DMS job and attach the GCP service to the newly promoted database
        :param service:
        :return: True if promotion was successful
        """

        # if remote, update the secrets to point to cloudSQL such that no
        # new writes go to RDS from this point forward
        cfg = self._config[service]
        app = cfg['k8s-service']
        namespace = cfg['k8s-namespace']
        strategy = cfg['gcp-migration-strategy']

        # precondition: check for CDC phase
        state = self._describe_dms_job(service)
        if state['state'] == 'COMPLETED':
            self._logger.info("job already completed, exiting")
            return
        elif state['state'] != 'RUNNING' and state['phase'] != 'CDC':
            raise Exception(f"{service} dms state: {state}, but expecting 'CDC' mode")

        if strategy == 'remote':
            self._create_sync_secrets(service, force_local=True)
            self._k8s.restart_gcp_service(app, namespace)
            # TODO: improve restart: wait until service finishes restarting
            self._logger.info("waiting 2m for service to restart")
            time.sleep(120)

        self._create_cutover_secrets(service)
        promote_success = self._promote_dms_job(service)
        if not promote_success:
            raise Exception(f"dms job for service {service} was not promoted")

        self._logger.info(f"await job completion for {service}")
        self._await_state(service, 'COMPLETED')

        self._logger.info(f"job/{service} complete, doing final setup")
        self._k8s.set_owner_all_tables(
            cfg['gcp-host'], DEFAULT_PORT,
            cfg['readwrite-secret-name'].split(".")[1], "postgres",
            cfg['gcp-root-password'], 'readwrite')
        self._k8s.restart_gcp_service(app, namespace)
        self._logger.info(f"cutover for {service} complete. {cfg['k8s-service']} is restarting")

    def _create_cutover_secrets(self, service):
        cfg = self._config[service]
        self._k8s.create_secret(cfg['readwrite-secret-name'], cfg['k8s-namespace'],
                                username='readwrite',
                                password=cfg['gcp-readwrite-password'],
                                dbname=cfg['database-name'],
                                host=cfg['gcp-host'],
                                port=cfg['gcp-port'])
        self._k8s.create_secret(cfg['readonly-secret-name'], cfg['k8s-namespace'],
                                username='readonly',
                                password=cfg['gcp-readonly-password'],
                                dbname=cfg['database-name'],
                                host=cfg['gcp-host'],
                                port=cfg['gcp-port'])

    def _create_db_users(self, service):
        """
        Creates readonly & readwrite usernames and passwords for a particular
        service or "all" to specify all services in cloudsql. Defaults to "all".
        Creating db users does the following steps:
        0. Randomly generates passwords
        1. Creates usernames & passwords in cloudsql
        2. Retrieves cloudsql instance private address
        2. Updates information in .yaml
        3. Grant permission to READWRITE user
        :param service: name of service in the config yaml
        """
        cfg = self._config[service]
        project_id = self._gcp.list_projects().get(cfg["gcp-project-name"]).get("projectId")
        region_id = cfg["gcp-instance-region"]
        migration_job_id = "{}{}".format(MJ_PREFIX, service)

        cloudsql_instance = self._gcp.get_cloudsql_instance_name(project_id, region_id, migration_job_id)
        if not cloudsql_instance:
            cloudsql_instance = self._sql_instance_name(service)

        ro_password = self._gcp.create_cloudsql_user(project_id,
                                                     cloudsql_instance,
                                                     "readonly",
                                                     cfg.get('gcp-readonly-password'))
        rw_password = self._gcp.create_cloudsql_user(project_id,
                                                     cloudsql_instance,
                                                     "readwrite",
                                                     cfg.get('gcp-readwrite-password'))

        gcp_config = {
            'gcp-readonly-password': ro_password,
            'gcp-readwrite-password': rw_password,
            'gcp-host': self._gcp.get_cloudsql_host(project_id, cloudsql_instance),
            'gcp-port': DEFAULT_PORT}
        self._config.save(gcp_config, service)

        # Give select permissions to READWRITE & READONLY (but not table ownership - DMS still needs this).
        self._grant_access_to_user(service, 'readwrite')
        self._grant_access_to_user(service, 'readonly')

    def _create_connection_profile(self, service=None):
        """
        Creates required connection profiles for enabling migration job for a
        particular service.Defaults to None.
        Creating conection profiles does the following steps:
        0. Checks if connection profile exists. If there is, then updates the connection profile with new info.
        1. Creates source "postgresql" connection profile (AWS)
        2. Creates destination "cloudsql" connection profile
        :param service: name of service in the config yaml
        """

        self._logger.info(f"creating connection profiles for {service}")
        config :DbConfig = self._config[service]
        project_id = self._gcp.list_projects().get(config["gcp-project-name"]).get("projectId")
        region_id = config["gcp-instance-region"]
        migration_job_id = f"{MJ_PREFIX}{service}"

        # create source connection profile
        connection_profile_id_aws = f"{CP_SRC_PREFIX}{service}"
        request_body_aws = {
            "displayName": connection_profile_id_aws,
            "postgresql": {
                "host": config["aws-host"],
                "port": config["aws-port"],
                "username": config["aws-replication-username"],
                "password": config["aws-replication-password"],
                "ssl": {
                    "type": "SERVER_ONLY",
                    "caCertificate": self._rds_cert
                }
            }
        }
        self._gcp.upsert_connection_profile(project_id, region_id, connection_profile_id_aws, request_body_aws)

        # create dest, if the cloudsql instance name exists
        connection_profile_id_gcp = self._gcp.get_cloudsql_instance_name(project_id, region_id, migration_job_id)
        if connection_profile_id_gcp is not None:
            self._logger.info(f"cloud SQL destination instance for {service} already created: {connection_profile_id_gcp}")
            return None

        # must create dest cloudsql instance, and save its root password
        connection_profile_id_gcp = self._sql_instance_name(service)
        cloudsql_root_password = ''.join(
            random.SystemRandom().choice(string.ascii_uppercase + string.digits) for _ in range(12))
        gcp_cpu = config["gcp-instance-cpu"]
        gcp_mem = config["gcp-instance-mem"]
        self._logger.debug(f"{connection_profile_id_gcp} cpu: {gcp_cpu}, mem: {gcp_mem}")
        vpc_names = VPC[config['k8s-env']]
        vpc_host_id = self._gcp.list_projects().get(vpc_names['host']).get("projectId")
        vpc_shared_base = vpc_names['base']
        request_body_cloudsql = {
            "displayName": connection_profile_id_gcp,
            "cloudsql": {
                "settings": {
                    "autoStorageIncrease": config["gcp-auto-storage-increase"],
                    "dataDiskType": config["gcp-disk-type"],
                    "rootPassword": cloudsql_root_password,
                    "databaseVersion": config["gcp-database-version"],
                    "tier": f"db-custom-{gcp_cpu}-{gcp_mem}",
                    "dataDiskSizeGb": config["gcp-instance-storage"],
                    "sourceId": f"projects/{project_id}/locations/{region_id}/connectionProfiles/{connection_profile_id_aws}",
                    "ipConfig": {
                        "enableIpv4": False,
                        "privateNetwork": f"https://www.googleapis.com/compute/v1/projects/{vpc_host_id}/global/networks/{vpc_shared_base}",
                    }
                }
            }
        }
        self._gcp.upsert_connection_profile(project_id, region_id, connection_profile_id_gcp, request_body_cloudsql)
        self._config.save({"gcp-root-password": cloudsql_root_password}, service)
        self._logger.debug(f"root_password for {service}/{connection_profile_id_gcp}: {cloudsql_root_password}")

        cloudsql_host = self._gcp.get_cloudsql_host(project_id, connection_profile_id_gcp)

        # save the root user just in case
        self._k8s.create_secret(config['gcp-rootuser-secret-name'], config['k8s-namespace'],
                                username='postgres',
                                password=cloudsql_root_password,
                                dbname='postgres',
                                host=cloudsql_host,
                                port=DEFAULT_PORT)

    def _create_dms_job(self, service=None):
        """
        Creates Database Migration Service Job for a particular service
        Defaults to None.

        Creating dms job does the following steps:
        0. Verify if source connection profile and destination connection profile can connect
        1. Create dms job
        2. Start dms job
        :param service: name of service in the config yaml
        """
        cfg = self._config[service]
        self._logger.info(f"creating dms job for {service}")
        connection_profile_id_source = f"{CP_SRC_PREFIX}{service}"
        connection_profile_id_destination = self._sql_instance_name(service)
        migration_job_id = "{}{}".format(MJ_PREFIX, service)
        proj_name = cfg["gcp-project-name"]
        project_id = self._gcp.list_projects().get(proj_name).get("projectId")

        vpc_names = VPC[cfg['k8s-env']]
        vpc_host_id = self._gcp.list_projects().get(vpc_names['host']).get("projectId")
        vpc_shared_base = vpc_names['base']
        region_id = cfg["gcp-instance-region"]

        request_body = {
            "type": "CONTINUOUS",
            "source": f"projects/{project_id}/locations/{region_id}/connectionProfiles/{connection_profile_id_source}",
            "destination": f"projects/{project_id}/locations/{region_id}/connectionProfiles/{connection_profile_id_destination}",
            "destinationDatabase": {
                "provider": "CLOUDSQL",
                "engine": "POSTGRESQL"
            },
            "vpcPeeringConnectivity": {
                "vpc": f'https://www.googleapis.com/compute/v1/projects/{vpc_host_id}/global/networks/{vpc_shared_base}'
            }
        }
        self._gcp.create_migration_job(project_id, region_id, migration_job_id, request_body)
        self._gcp.start_migration_job(project_id, region_id, migration_job_id, )

    def cleanup(self, service):
        """
        Delete the completed job associated with a service. Also deletes any content associated with it
        such as connection profiles
        :param service:
        :return:
        """
        cfg = self._config[service]
        project_id = self._gcp.list_projects().get(cfg["gcp-project-name"]).get("projectId")
        region = cfg["gcp-instance-region"]
        job_id = f"{MJ_PREFIX}{service}"
        job_state = self._gcp.get_dms_status(project_id, region, job_id)
        if not job_state:
            self._logger.warning(f"job for service {service} was not found, exiting")
            return
        if job_state['state'] != 'COMPLETED':
            self._logger.warning(f"job for service {service} was not COMPLETED, exiting")
            return

        job_state = job_state['body']
        aws_ref_instance = job_state['destination'].split("/")[-1] + "-master"
        try:
            self._logger.info(f"deleting db ref {aws_ref_instance}")
            self._gcp.delete_cloudsql_instance(project_id, aws_ref_instance)
        except Exception as e:
            self._logger.debug(traceback.format_exc())
            self._logger.warning(f"unable to delete sql instance '{aws_ref_instance}'. {str(e)}")

        try:
            self._logger.info(f"deleting profile {job_state['source']}")
            self._gcp.delete_dms_connection_profile(job_state['source'])
        except Exception as e:
            self._logger.debug(traceback.format_exc())
            self._logger.warning(f"unable to delete source connection profile '{job_state['source']}'. {str(e)}")

        try:
            self._logger.info(f"deleting job {job_id}")
            self._gcp.delete_dms_job(project_id, region, job_id)
        except Exception as e:
            self._logger.debug(traceback.format_exc())
            self._logger.warning(f"unable to delete dms job {job_id}. {str(e)}")


class FireCli(MigrationCommands):
    def __init__(self, config="config.yaml", verbose=False):
        def setup_logger(verbose):
            logger = logging.getLogger(__name__)
            formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s:%(message)s', datefmt='%Y/%m/%d %H:%M:%S')
            streamHandler = logging.StreamHandler()
            streamHandler.setFormatter(formatter)
            logger.addHandler(streamHandler)
            logger.setLevel(logging.DEBUG if verbose else logging.INFO)
            return logger

        def exception_handler(exception_type, exception, traceback):
            print("%s: %s" % (exception_type.__name__, exception))

        sys.excepthook = exception_handler

        logger = setup_logger(verbose=verbose)
        super(FireCli, self).__init__(
            config=FileBasedConfig(config),
            k8s=K8sApiLocal(logger=logger),
            logger=logger)


if __name__ == '__main__':
    fire.Fire(FireCli)
