import base64
import json
import logging
import subprocess as sp
import sys
import os
import traceback
import uuid
from datetime import datetime
import abc
from typing import Optional
from typing import Tuple
import psycopg2


from kubernetes import client
from kubernetes import config
from kubernetes.client import ApiException
from kubernetes.client import V1ObjectMeta
from kubernetes.client import V1Pod
from kubernetes.client import V1PodList
from kubernetes.client import V1Secret


def d64(s: str):
    try:
        return str(base64.urlsafe_b64decode(bytes(s, encoding="UTF-8")), encoding="UTF-8")
    except:
        return None


def e64(s: str) -> str:
    return str(base64.standard_b64encode(bytes(s, encoding="UTF-8")), encoding="UTF-8")


class K8sApiBase:
    def __init__(self, logger=None):
        self._gke_cluster = {
            "dev": "gke-d-tmc-01",
            "staging": "gke-s-tmc-01",
            "sb1": "gke-sb1-tmc-01",
            "prod": "gke-p-tmc-01"
        }
        self._logger = logging.getLogger(__name__) if not logger else logger

        if os.path.isfile(config.incluster_config.SERVICE_TOKEN_FILENAME):
            config.load_incluster_config()
        else:
            config.load_config()
        self._v1: client.CoreV1Api = client.CoreV1Api()
        self._v1_apps: client.AppsV1Api = client.AppsV1Api()

    def check_connection(self, host, port, database_name, username, password):
        """
        Checks that script can connect to AWS database's replication user.

        :param host:
        :param port:
        :param database_name:
        :param username:
        :param password:

        :raises: exception if connecting to target database fails
        :return None
        """
        raise Exception("override me")

    def restart_gcp_service(self, app, namespace):
        """
        Tries to restart a gcp deployment or statefulset, logs if there's a problem related to discovering the service
        (see: https://github.com/kubernetes-client/python/issues/1378 for why we restart this way)
        """
        now = str(datetime.utcnow().isoformat("T") + "Z")
        body = {
            'spec': {
                'template': {
                    'metadata': {
                        'annotations': {
                            'kubectl.kubernetes.io/restartedAt': now
                        }
                    }
                }
            }
        }
        try:
            self._v1_apps.patch_namespaced_deployment(app, namespace, body, pretty='true')
            return
        except ApiException as e:
            if e.status != 404:
                raise e

        try:
            self._v1_apps.patch_namespaced_stateful_set(app, namespace, body, pretty='true')
            return
        except ApiException as e:
            if e.status != 404:
                raise e

        self._logger.warning(f"service '{namespace}/{app}' was not found, not restarting")

    def create_secret(self, name, namespace, **kwargs):
        """
        Create a database secret.

        :raises: exception if there's an error creating the secret
        :return:
        """
        self._logger.info(f'creating secret "{namespace}/{name}"')
        exists = False
        old_password = None
        try:
            existing: V1Secret = self._v1.read_namespaced_secret(name, namespace)
            exists = True
            old_password = d64(existing.data["password"])
        except:
            pass

        jdbc_url = f'jdbc:postgresql://{kwargs.get("host", "?")}:{kwargs.get("port", "?")}/{kwargs.get("dbname", "?")}'
        kwargs["jdbc_url"] = jdbc_url
        if old_password:
            kwargs["old-password"] = old_password

        data = {}
        for k, v in kwargs.items():
            data[k] = e64(str(v))
        secret = V1Secret(metadata=V1ObjectMeta(name=name, namespace=namespace), data=data)
        if exists:
            self._v1.patch_namespaced_secret(name, namespace, secret)
        else:
            self._v1.create_namespaced_secret(namespace, secret)

    def grant_access_to_user(self, host, port, database_name, username, password, username_to_grant):
        """
        Grants readonly user access to SELECT on all tables and readwrite user all actions on all tables.
        Logs if there's an error

        :param host:
        :param port:
        :param database_name:
        :param username:
        :param password:
        :param username_to_grant:
        :return:
        """
        raise Exception("override me")

    def set_owner_all_tables(self, host, port, database_name, username, password, username_to_grant):
        raise Exception("override me")

    def get_pods_status(self, pod_name) -> Tuple[int, set, list]:
        """
        :param pod_name:
        :return: restarts, states, raw pod info
        """
        statuses = sp.check_output(
            f"kubectl get pods -lapp={pod_name} -o=jsonpath=\'{{.items[*].status.containerStatuses[0]}}\'".split()).decode(
            sys.stdout.encoding).strip()[1:-1].split()
        pod_infos = []
        for status_str in statuses:
            status = json.loads(status_str)
            info = {"restarts": status['restartCount']}
            info["state"] = "running" if "running" in status['state'].keys() else "error"
            info['raw'] = status
            pod_infos.append(info)
        restarts = sum([int(pod["restarts"]) for pod in pod_infos])
        states = set([pod["state"] for pod in pod_infos])
        return restarts, states, list(map(lambda x: x['raw'], pod_infos))

    def check_app_healthy(self, namespace, app) -> Tuple[bool, Optional[str]]:
        """
        :param namespace: k8s namespace
        :param app: name of app
        :return:
        """
        def statefulset_or_deployment_exists():
            try:
                self._v1_apps.read_namespaced_deployment_status(app, namespace)
                return True, None
            except ApiException as e:
                if e.status != 404:
                    raise
            try:
                self._v1_apps.read_namespaced_stateful_set_status(app, namespace)
                return True, None
            except ApiException as e:
                if e.status != 404:
                    raise
            return False
        try:
            if not statefulset_or_deployment_exists():
                return False, f"statefulset or deployment {namespace}/{app} does not exist"
        except Exception as e:
            return False, f"failed to call k8s api in namespace {namespace}: {str(e)}"

        # TODO: check pods in healthy state: no recent restarts, etc
        return True, ""


    def create_replication_user(self, username, replpw=None, **kwargs):
        """
        :param username: username to create
        :param kwargs: connection parameters
        :return: password for the replication user
        """
        self._logger.warning("create_replication_user not implemented in this version of k8s API - skipping")
        return None


class K8sApiLocal(K8sApiBase):
    """
    For running scripts locally.
    Communicates with db via a proxy pod it spins up on the k8s cluster.
    """

    def __init__(self, **kwargs):
        super(K8sApiLocal, self).__init__(**kwargs)

    def start_psql(self):
        """
        :raises: exception if fails to start psql
        :return: None
        """
        sp.check_output(['bash', '-c', 'source psql-commands.sh; _start_psql'])

    def check_connection(self, host, port, database_name, username, password):
        command = f'source psql-commands.sh; _check_connection {host} {port} {database_name} {username} {password}'
        sp.check_output(['bash', '-c', command])
        self._logger.debug("connection to '{}@{}:{}/{}' was successful".format(username, host, port, database_name))

    def grant_access_to_user(self, host, port, database_name, username, password, username_to_grant):
        self._logger.debug(f"granting access to user '{username_to_grant}' on '{database_name}'")
        try:
            sp.check_output(['bash', '-c', 'source psql-commands.sh; _grant_access_to_user {} {} {} {} {} {}'.format(
                host, port, database_name, username, password, username_to_grant)])
        except Exception as ex:
            self._logger.warning(
                f"failed to GRANT database access permission to '{username}' on database '{database_name}'")
            raise ex

    def set_owner_all_tables(self, host, port, database_name, username, password, username_to_grant):
        self._logger.debug(f"giving owner to all tables to user '{username_to_grant}' on '{database_name}'")
        try:
            sp.check_output(['bash', '-c', 'source psql-commands.sh; _set_owner_all_tables {} {} {} {} {} {}'.format(
                host, port, database_name, username, password, username_to_grant)])
        except Exception as ex:
            self._logger.warning(f"failed to GRANT owner to tables to '{username}' on database '{database_name}'")
            raise ex


class K8sApiNative(K8sApiBase):
    """
    k8s API to be used if running on a pod in k8s.
    """

    def __init__(self, **kwargs):
        super(K8sApiNative, self).__init__(**kwargs)

    def check_connection(self, host, port, database_name, username, password):
        # try to connect using the basic psycopg
        try:
            with psycopg2.connect(dbname=database_name, host=host, port=port,
                                    user=username, password=password) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.fetchall()
        except psycopg2.Error:
            self._logger.warning(f"failed to connect to postgres {host}/{database_name}")
            raise

    def _list_schemas(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
            select distinct schemaname
            from pg_catalog.pg_tables
            where schemaname not in ('pg_catalog', 'information_schema', 'hdb_catalog', 'hdb_views', 'pglogical');
            """)
            return [r[0] for r in cur.fetchall()]

    def grant_access_to_user(self, host, port, database_name, username, password, username_to_grant):
        try:
            with psycopg2.connect(dbname=database_name, host=host, port=port,
                                    user=username, password=password) as conn:
                priv = "ALL PRIVILEGES" if username_to_grant == 'readwrite' else 'SELECT'
                schemas = self._list_schemas(conn) if username_to_grant == 'readwrite' else ['public']
                with conn.cursor() as cur:
                    for schema in schemas:
                        cur.execute(f"GRANT {priv} ON ALL TABLES in SCHEMA {schema} to {username_to_grant};")
        except psycopg2.Error:
            print(f"failed to connect to postgres")
            raise

    def set_owner_all_tables(self, host, port, database_name, username, password, username_to_grant):
        try:
            with psycopg2.connect(dbname=database_name, host=host, port=port,
                                  user=username, password=password) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                    select schemaname, tablename from pg_catalog.pg_tables where schemaname in 
                        (select distinct schemaname from pg_catalog.pg_tables
                         where schemaname not in ('pg_catalog', 'information_schema', 'hdb_catalog', 'hdb_views', 'pglogical'));
                    """)
                    tables = [f"{r[0]}.{r[1]}" for r in cur.fetchall()]
                    for table in tables:
                        cur.execute(f"ALTER TABLE {table} OWNER TO {username_to_grant};")
        except psycopg2.Error:
            print(f"failed to connect to postgres")
            raise

    def _list_target_databases(self, conn):
        with conn.cursor() as cur:
            cur.execute("""
            select rolname, datname from pg_database pgd 
                inner join pg_roles pgr on pgr.oid = pgd.datdba 
            where datistemplate = FALSE and datallowconn = TRUE and rolname <> 'rdsadmin';
            """)
            return [r[1] for r in cur.fetchall()]

    def _list_migrate_schemas(self, conn):
        with conn.cursor() as cur:
            cur.execute("SELECT nspname FROM pg_catalog.pg_namespace where nspowner <> 10;")
            return [r[1] for r in cur.fetchall()]

    def _create_replication_user(self, username, password, conn):
        """
        1/ create user + set password
        2/ GRANT rds_replication to USER
        """
        with conn.cursor() as cur:
            try:
                cur.execute(f"CREATE USER {username};")
            except Exception: # already exists
                conn.rollback()
            cur.execute(f"ALTER USER {username} PASSWORD '{password}'")
            cur.execute(f"GRANT rds_replication TO {username}")

    def _assign_replication_user(self, username, **kwargs):
        self._logger.info(f"granting {username} on db/{kwargs['dbname']}")
        try:
            with psycopg2.connect(**kwargs) as conn:
                with conn.cursor() as cur:
                    self._logger.info(f"create pglogical extension on db/{kwargs['dbname']}")
                    cur.execute("CREATE EXTENSION IF NOT EXISTS pglogical;")
                    cur.execute(f"GRANT SELECT on ALL TABLES in SCHEMA pglogical to {username}")

                schemas = self._list_schemas(conn)
                with conn.cursor() as cur:
                    for schema in schemas:
                        self._logger.info(f"grant {username} with usage & select on schema {kwargs['dbname']}.{schema}")
                        cur.execute(f"GRANT USAGE on SCHEMA {schema} to {username}")
                        cur.execute(f"GRANT SELECT on ALL TABLES in SCHEMA {schema} to {username}")
                        cur.execute(f"GRANT SELECT on ALL SEQUENCES in SCHEMA {schema} to {username}")
        except psycopg2.Error:
            self._logger.warning(f"failed to _assign_replication_user on db/{kwargs['dbname']}")
            self._logger.warning(traceback.format_exc())


    def create_replication_user(self, username, replpw=None, **kwargs):
        """
        see: https://cloud.google.com/database-migration/docs/postgres/configure-source-database#configure-your-source-databases
        :param username: username to create
        :param kwargs: connection parameters: dbname, host, port, username, password
        :return: password for the replication user
        """
        replication_pw = replpw if replpw is not None else str(uuid.uuid4())
        try:
            with psycopg2.connect(**kwargs) as conn:
                self._create_replication_user(username, replication_pw, conn)
                target_dbs = self._list_target_databases(conn)
                conn.commit()
            for db in target_dbs:
                self._assign_replication_user(username, **{**kwargs, "dbname": db})
        except psycopg2.Error:
            self._logger.warning(f"failed to connect to postgres in create_replication_user")
            raise
        return replication_pw