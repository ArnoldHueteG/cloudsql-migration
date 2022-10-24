# Pre-GCP Migration Script Details

In order to migrate AWS RDS to Cloudsql with GCP Database Migration Service, AWS RDS need to be configured with certain
parameters and have user with replication permission. The following functions will provide automate processes like:

- scrape AWS RDS information
- configure with required parameters
- configure user info with replication permission

Reference: https://cloud.google.com/database-migration/docs/postgres/configure-source-database

The following functions are located in **rds-prep-scripts/run.sh**

## _collect_audits_for

Collects audits for specific db instances given an input: file with db identifiers Example

```bash
source run.sh
_collect_audits_for instances-<env>.txt
```

instances-env.txt example

```bash
adqquenzy9jli4 # aws account-service dev db identifier 
iam-dev-20190328183009 # aws iam dev db identifier
...
```

Outputs a csv file in **/tmp/audits.csv**

## _modify_with_pglogical

- [x] This is important since it applies required parameter to the parameter group based on input: parameter group name

```bash
source run.sh
_modify_with_pglogical <paramter-group name>
```

This results in adding required params to the corresponding param group:

```bash
 shared_preload_libraries = {
      value        = "pglogical"
      apply_method = "pending-reboot"
    }
 rds.logical_replication = {
      value        = "1"
      apply_method = "pending-reboot"
    }
```

## _reboot_instances_for

Reboot RDS instances given an input file: with db identifiers

- [x] This is important. Reboot needs to happen after running **_modify_with_pglogical** to configure the parameters.

```bash
source run.sh
_reboot_instances_for instances-<env>.txt
```

## _create_replication_user_for

Extends pglogical & Creates new user and grants usage/selects/rds_replication\

- [x] This is important for GCP Migration script since this creates replication user/password

```bash
source run.sh
_create_replication_user_for instances-<env>.txt
```

Results in creating replication username and password\
All the configured RDS will have the same replication username: **gcp_replication**
and the same password: **gcp_password**