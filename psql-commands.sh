#!/bin/bash

pod_name=psql-client-${USER//.}

_start_psql() {

  # check if already exists, if already exists, then return
  kubectl get pod "${pod_name}" &>/dev/null
  if [[ $? -eq 0 ]]; then return 0 ; fi

  k8s_user=$USER
  # start psql pod
  kubectl run "$pod_name" --restart=Never --wait --labels="app=kpsql,kpsql=$pod_name,user=$k8s_user,4ut0n0m1c.41/rds-access=true" \
    --image postgres:11.5 --overrides "$(cat <<EOF
  {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": {
      "labels": {
        "sidecar.istio.io/inject": "false",
        "app": "cloudsql-migration"
      }
    },
    "spec": {
      "containers": [
        {
          "name": "$pod_name",
          "image": "postgres:11.5",
          "env": [{"name": "PGPASSFILE", "value": "/.pgpass"}],
          "command": [
            "sh"
          ],
          "args": [],
          "stdin": true,
          "tty": true
        }
      ]
    }
  }
EOF
)" &> /dev/null

  while [[ $(kubectl get pod "$pod_name" -o 'jsonpath={..status.conditions[?(@.type=="Ready")].status}') != "True" ]];
    do echo "awaiting pod $pod_name" && sleep 1;
  done
}

_check_connection() {
  _start_psql
  local host=$1; shift
  local port=$1; shift
  local database=$1; shift

  local user=$1; shift
  local password=$1; shift
  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "$host" -p "$port" -d "$database" -U "$user" -At -c 'SELECT TRUE;'
  return $?
}

_grant_access_to_user() {
  # Grants permission to READWRITE or READONLY
  host=$1
  port=$2
  db=$3
  username=$4
  password=$5
  username_to_grant=$6

  _start_psql

  if [ "$username_to_grant" == "readwrite" ] ; then
    # iterate over possible schemas and give permission READWRITE
    schema_list=$(kubectl exec "$pod_name" -- env PGPASSWORD="${password}" psql -h "${host}" \
    -p "${port}" -d "${db}" -U "${username}" -qAt -c "\dn;")
    for schema in 'public' 'hdb_catalog' 'hdb_views' ; do
      if [[ $( echo "$schema_list" | grep -c "${schema}") == 1 ]] ; then
        kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" \
        -p "${port}" -d "${db}" -U "${username}" \
        -qAt -c "GRANT ALL PRIVILEGES ON ALL TABLES in SCHEMA ${schema} to readwrite;"
      fi
    done
  else
    # READONLY - public schema only
    kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" \
    -p "${port}" -d "${db}" -U "${username}" \
    -qAt -c "GRANT SELECT ON ALL TABLES in SCHEMA public to readonly;"
    return $?
  fi
}

_set_owner_all_tables() {
  # Grants permission to READWRITE or READONLY
  host=$1
  port=$2
  db=$3
  username=$4
  password=$5
  username_to_grant=$6

  _start_psql

  # iterate over possible schemas and give permission READWRITE
  table_list=$(kubectl exec "$pod_name" -- env PGPASSWORD="${password}" psql -h "${host}" \
  -p "${port}" -d "${db}" -U "${username}" -qAt -c "\dt;")
  while IFS= read -r line
  do
      alter=$(echo "$line" | awk -F  "|" '{printf "alter table %s.%s owner to readwrite;\n",$1,$2}')
      kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" \
      -p "${port}" -d "${db}" -U "${username}" \
      -qAt -c "${alter}"
  done <<< "$table_list"
}

_create_replication_user() {
   host=$1
   port=$2
   db=$3
   username=$4
   password=$5
   replication_password=$6

  _echo() {
    echo "${db}::${host} / ${1}"
  }

  retry=0
  maxRetries=10
  retryInterval=5
  until [ ${retry} -ge ${maxRetries} ]
  do
    _check_connection "${host}" "${port}" "${db}" "${username}" "${password}" && break
    retry=$(( ${retry} + 1  ))
    _echo "retrying [${retry}/${maxRetries}] in ${retryInterval}(s) "
    sleep ${retryInterval}
  done

  if [ ${retry} -ge ${maxRetries} ]; then
    _echo "can't connect to ${db} after ${maxRetries} attempts!"
    return 1;
  fi

  _echo "creating replication user: gcp_replication for ${db}..."
   # 1.a Check if gcp_replication is there. If not, create new user "gcp_replication"
  if [[ $(kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "SELECT 1 FROM pg_roles WHERE rolname='gcp_replication';" | grep -c 1)  == 1 ]] ; then
     _echo "already has gcp_replication user in ${db}"
  else
    _echo "creating gcp_replication user in ${db}"
    kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "CREATE USER gcp_replication;" &>/dev/null
    if [ $? -ne 0 ] ; then
      _echo "failed to create gcp_replication user in ${db}"
      return 1
    fi
  fi

  # 1.b Set gcp_replication user password
  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "ALTER USER gcp_replication WITH PASSWORD '${replication_password}';" &>/dev/null
  if [ $? -ne 0 ] ; then
    _echo "failed to set gcp_replication password"
    return 1
  fi
  _echo "replication_password: ${replication_password}"

  # 1.c Make pgadmin user inherit from readwrite (pgadmin is not superuser)
  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT readwrite to pgadmin;" &>/dev/null
  if [ $? -ne 0 ] ; then
      _echo "failed to grant pgadmin readwrite role in ${db}"
      return 1
  fi

  # 2. Extends pglogical to db
  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "CREATE EXTENSION IF NOT EXISTS pglogical;" &>/dev/null
  if [ $? -ne 0 ] ; then
      _echo "failed to extend pglogical in ${db}"
      return 1
  fi

  # 3.
  # a. GRANT USAGE on SCHEMA SCHEMA to USER on all schemas , including pglogical
  # b. GRANT SELECT on ALL TABLES in SCHEMA pglogical to USER on all databases to get replication information from source databases.
  # c. GRANT SELECT on ALL SEQUENCES in SCHEMA SCHEMA to USER
  for schema in 'public' 'pglogical' 'sla_service' 'hdb_catalog' 'hdb_views'; do
    if [[ $(  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "\dn;" | grep -c "${schema}") == 1 ]] ; then
      # a
      kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT USAGE on SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echo "failed to Grant Usage on ${schema}"
        return 1
      fi

       # b
      kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT SELECT on ALL TABLES in SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echo "failed to Grant Select on All Tables on ${schema}"
        return 1
      fi

      # c
      kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT SELECT on ALL SEQUENCES in SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echo "failed to Grant Select on All Tables on ${schema}"
        return 1
      fi
    fi
  done

  # 4. GRANT rds_replication to USER
  kubectl exec "$pod_name" -- env PGPASSWORD="$password" psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT rds_replication to gcp_replication;" &>/dev/null
  if [ $? -ne 0 ] ; then
    _echo "failed to Grant rds_replication to gcp_replication"
    return 1
  fi

  _echo "Finished Creating replication user: gcp_replication for ${db}"
}