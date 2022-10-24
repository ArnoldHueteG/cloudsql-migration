import json
import os
import os.path as osp
import re
import shutil
import sqlite3
import subprocess as sp
import sys
from googleapiclient import discovery

import fire
import pyjq
import yaml
from jinja2 import Template

AWS_CPU_MEM = {"db.m5.large": [2, 10],
               "db.m4.large": [8, 32],
               "db.m5.2xlarge": [16, 64],
               "db.t2.medium": [2, 8],
               "db.t2.small": [1, 4],
               "db.m5.xlarge": [4, 16],
               "db.m5.12xlarge": [4, 16],
               "db.t3.micro": [8, 32],
               "db.m5.4xlarge": [2, 4],
               "db.m4.xlarge": [2, 8],
               "db.m4.2xlarge": [4, 16],
               "db.t2.large": [48, 192],
               "db.m5.16xlarge": [4, 16],
               "db.m3.medium": [64, 256],
               }


def version(pgver):
    if pgver.startswith("9."):
        return "POSTGRES_9_6"
    elif pgver.startswith("11."):
        return "POSTGRES_11"
    elif pgver.startswith("12."):
        return "POSTGRES_12"
    elif pgver.startswith("13."):
        return "POSTGRES_13"
    return "?"


def project(env):
    return "prj-" + {"dev": "d", "staging": "s", "prod": "p", "sb1": "sb1"}[env] + "-"


def jq(q, j):
    return pyjq.all(q.replace("\n", ""), j)


def app_from_pod(pod):
    return "-".join(pod["pod"].split("-")[:-1 if pod["kind"] == "StatefulSet" else -2])


def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


class Api:

    def get_instances(self):
        """
        :param instance: db instance identifier
        :return: the security group object for given database instance
        """
        instances = json.loads(
            sp.check_output(
                f"aws-okta exec okta -- aws rds describe-db-instances".split()
            ).decode(sys.stdout.encoding))
        instances = jq("""
        .DBInstances[] | 
        {"instance": .DBInstanceIdentifier, 
         "class": .DBInstanceClass, 
          "database": .DBName,
          "host": .Endpoint.Address,
          "port": .Endpoint.Port,
          "storage": .AllocatedStorage,
          "multiaz": .MultiAZ,
          "version": .EngineVersion,
          "team": (.TagList[] | select(.Key == "au:team") | .Value),
          "app": (.TagList[] | select(.Key == "au:app") | .Value),
          "env": ((.TagList[] | select(.Key == "au:environment") | .Value) // (.TagList[] | select(.Key == "Environment") | .Value)),
          }
""", instances)
        return instances

    def _get_services(self):
        pods = json.loads(
            sp.check_output(
                f"kubectl get pods --all-namespaces -o json".split()
            ).decode(sys.stdout.encoding))
        pods = jq(""".items[] | { 
            pod: (.metadata.name // ""),
            kind: (try (.metadata.ownerReferences[0].kind) catch ""),
            namespace: (.metadata.namespace // ""), 
            app: (try (.metadata.labels.app) catch ""),
            team: (try (.metadata.labels["4ut0n0m1c.41/team"]) catch ""),
            secrets: (try (.spec.containers[0].env | 
              reduce .[] as $item ({}; 
                ( try $item.valueFrom.secretKeyRef.name catch "" ) as $secret
                | if $secret != "" then . + { ($secret) : "" } else . end
              ) | keys | reduce .[] as $secret (""; . + ( if . == "" then "" else ";" end )  + $secret)
            ) catch "" )
        }
        """, pods)
        apps = {}
        for pod in pods:
            pod["name"] = app_from_pod(pod)
            apps[pod["name"]] = pod
        apps = list(apps.values())
        # attempt to get the instance for each pod with a secret
        secrets = json.loads(
            sp.check_output(
                f"kubectl -n alfa get secrets -o json".split()
            ).decode(sys.stdout.encoding))
        secrets = jq(""".items[] | select(.data.dbname // false) | {
            "name": .metadata.name,
            "dbname": (.data.dbname | @base64d),
            "host": (.data.host | @base64d)
        }
        """, secrets)
        name_secrets = {}
        for secret in secrets:
            name_secrets[secret["name"]] = secret
        for app in apps:
            secrets = app['secrets'].split(";")
            host = ""
            name = ""
            instance = ""
            for secret in secrets:
                if secret in name_secrets:
                    name = name_secrets[secret]["dbname"]
                    host = name_secrets[secret]["host"]
                    instance = host.split(".")[0]
                    break
                elif secret.replace(".rw", ".ro") in name_secrets:
                    secret = secret.replace(".rw", ".ro")
                    name = name_secrets[secret]["dbname"]
                    host = name_secrets[secret]["host"]
                    instance = host.split(".")[0]
                    break
            app["dbname"] = name
            app["dbhost"] = host
            app["dbinstance"] = instance
            del app["pod"]
        return apps

    def get_services(self):
        rv = []
        for env in ["dev", "staging", "prod", "sb1"]:
            sp.check_output(f"kubectl config use-context {env}.k8s.au-infrastructure.com".split())
            rv.extend(list(map(lambda r: {**r, "env": env}, self._get_services())))
        return rv


class ConfigurationCommands:
    def __init__(self):
        self._api = Api()

    def _create_csv(self, fn, data, columns):
        with open(fn, "w") as f:
            for i, c in enumerate(columns):
                f.write(c + ("" if i == (len(columns) - 1) else ","))
            f.write("\n")
            for d in data:
                for i, c in enumerate(columns):
                    f.write(str(d.get(c, "")) + ("" if i == (len(columns) - 1) else ","))
                f.write("\n")

    def scrape(self):
        services = self._api.get_services()
        self._create_csv("services.csv",
                         services,
                         ["name",
                          "app",
                          "namespace",
                          "team",
                          "kind",
                          "env",
                          "secrets",
                          "dbname",
                          "dbhost",
                          "dbinstance"])

        databases = self._api.get_instances()
        self._create_csv("databases.csv", databases,
                         ["instance",
                          "host",
                          "port",
                          "class",
                          "database",
                          "version",
                          "multiaz",
                          "team",
                          "app",
                          "env",
                          "storage"])

    def _create_yaml(self, con, env="dev"):
        # instance -> service
        #               -> projects
        #          -> database

        # get databases for env
        cur = con.cursor()
        rows = cur.execute("""
                        select m.instance, d.* from migrate m 
                                inner join databases d on m.instance = d.instance
                        where d.env = ?
                        """, (env,))
        instances = list(rows)
        final = {}
        for r in instances:
            # try to match with service
            res = list(cur.execute("select * from services where app = ? and env = ?", (r['app'], env,)))
            if len(res) > 0:
                r.update(res[0])
            else:
                r["error"] = "unknown_app"

            secret = r["app"] + "." + r["database"]
            secrets = r.get("allsecrets", "").split(";")
            for s in secrets:
                if s.endswith(".rw") or s.endswith(".ro"):
                    secret = s[:-3]
                    break
            proj = list(cur.execute("select project from projects where app = ?", (r["app"],)))

            final[r["app"]] = {
                "aws-host": r["host"],
                "aws-instance": r["instance"],
                "aws-port": int(r["port"]),
                "aws-replication-username": "gcp_replication",
                "aws-replication-password": "?",
                "database-name": r["database"],
                "readonly-secret-name": secret + ".ro",
                "readwrite-secret-name": secret + ".rw",

                "gcp-auto-storage-increase": True,
                "gcp-database-version": version(r["version"]),
                "gcp-disk-type": "PD_SSD",
                "gcp-migration-strategy": "local",
                "gcp-instance-cpu": AWS_CPU_MEM[r["class"]][0],
                "gcp-instance-mem": 1024 * AWS_CPU_MEM[r["class"]][1],
                "gcp-instance-region": "us-west1" if env == "dev" else "us-central1",
                "gcp-instance-storage": int(r["storage"]),
                "gcp-project-name": project(env) + ("?" if len(proj) == 0 else proj[0]["project"]),

                "k8s-env": env,
                "k8s-namespace": r.get("namespace", "?"),
                "k8s-service": r.get("app")
            }
        return final

    def create_yaml(self, env):
        if not osp.isfile("./services.csv") or not osp.isfile("./databases.csv"):
            self.scrape()

        # hack since . commands don't work in python client
        try:
            os.remove("x.db")
        except:
            pass
        sp.check_output("sqlite3 x.db".split(),
                        input=bytes("\n".join([
                            ".mode csv",
                            ".import services.csv services",
                            ".import databases.csv databases",
                            ".import migrate.csv migrate",
                            ".import projects.csv projects",
                            ".import secrets.csv secrets"
                        ]), sys.stdout.encoding))
        with open('overrides.sql', 'r') as f:
            sp.check_output("sqlite3 x.db".split(), stdin=f)

        con = sqlite3.connect("x.db")
        con.row_factory = dict_factory
        for e in [env] if env != "all" else ["dev", "staging", "prod", "sb1"]:
            doc = self._create_yaml(con, e)
            with open(f'config-{env}.yaml', 'w') as f:
                f.write(yaml.dump(doc))
        con.close()

    def create_tf(self, env):
        """
        Try to find the created instance in the GCP project. If it doesn't exist,
        then use a guess of the parameters from what we can derive in the yaml.

        Note this should be run AFTER the migration to generate the right TF values
        since we won't know the prefix or the zone until after the migration completes

        :param env:
        :return:
        """
        clusters = {
            "dev": 'gke-d-tmc-01',
            "staging": 'gke-s-tmc-01',
            "prod": 'gke-p-tmc-01',
            "sb1": 'gke-sb-tmc-01',
        }
        env_codes = {
            "dev": 'd',
            "staging": 's',
            "prod": 'p',
            "sb1": 'sb',
        }
        suffix_re = re.compile("^\d{8}t\d{6}$")

        con = sqlite3.connect("x.db")
        con.row_factory = dict_factory
        default_doc = self._create_yaml(con, env)

        tfdir = f"tf-{env}"
        try:
            shutil.rmtree(tfdir)
        except:
            pass
        os.mkdir(tfdir)
        with open('cloudsql.tf.j2', 'r') as f:
            template = Template(source=f.read())

        # get project ids
        resource_manager = discovery.build('cloudresourcemanager', 'v1')
        proj_result = resource_manager.projects().list().execute().get("projects")
        projects = {project.get("name"): project for project in proj_result}
        sqladmin = discovery.build('sqladmin', 'v1beta4')

        for service in default_doc.keys():
            doc = default_doc[service]
            project_id = projects[doc['gcp-project-name']]["projectId"]
            instances = sqladmin.instances().list(project=project_id).execute()
            # some defaults in case we don't find the right instance
            instance = {
                "region":doc['gcp-instance-region'],
                "gceZone": "-?",
                "name": "-?",
            }
            multi_warning = None
            for i in instances.get("items", []):
                if i['name'].startswith(f"sql-{env_codes[env]}-p-{service}"):
                    if not suffix_re.match(i['name'].split("-")[-1]):
                        continue
                    if 'createTime' in instance:
                        multi_warning = "WARNING: the generation script found multiple cloudSQL instances with the same prefix. Validate the correct sql_name_suffix was chosen!!!"
                    else:
                        instance = i
            cur = con.cursor()
            with open(f"{tfdir}/{service}-cloudsql.tf", 'w') as f:
                f.write(template.render(
                    app=service,
                    team=list(cur.execute("select team from databases where host = ?", (doc["aws-host"],)))[0]["team"],
                    db_name=doc['database-name'],
                    cluster_name=clusters[env],
                    k8s_namespace=doc['k8s-namespace'],
                    region=instance.get("region"),
                    zone=instance.get("gceZone").split("-")[-1],
                    pg_disk_gb=doc['gcp-instance-storage'],
                    pg_version=doc['gcp-database-version'],
                    pg_cpu=doc['gcp-instance-cpu'],
                    pg_mem_mb=doc['gcp-instance-mem'],
                    env=env,
                    project=project_id,
                    instance_suffix=instance.get("name").split("-")[-1],
                    instance=None if instance.get("name") == "-?" else instance.get("name"),
                    warning=multi_warning
                ))
            cur.close()
        con.close()


if __name__ == '__main__':
    fire.Fire(ConfigurationCommands)
