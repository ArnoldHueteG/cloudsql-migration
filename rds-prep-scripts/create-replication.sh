source check-preconditions.sh

_echoerr() { echo "$@" 1>&2; }
pod_name=psql-client-$USER

_create_replication_user() {
   host=$1
   port=$2
   db=$3
   username=$4
   replication_password=$5
  _echoerr "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}"

  retry=0
  maxRetries=10
  retryInterval=5
  until [ ${retry} -ge ${maxRetries} ]
  do
    _check_connection "${host}" "${port}" "${db}" "${username}" && break
    retry=$[${retry}+1]
    _echoerr "Retrying [${retry}/${maxRetries}] in ${retryInterval}(s) "
    sleep ${retryInterval}
  done

  if [ ${retry} -ge ${maxRetries} ]; then
    _echoerr "Can't connect to ${db} after ${maxRetries} attempts!"
    return 1;
  fi

  _echoerr "Creating replication user: gcp_replication for ${db}..."
   # 1.a Check if gcp_replication is there. If not, create new user "gcp_replication"
  if [[ $(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "SELECT 1 FROM pg_roles WHERE rolname='gcp_replication';" | grep -c 1)  == 1 ]] ; then
     _echoerr "Already has gcp_replication user in ${db}"
  else
    _echoerr "Creating gcp_replication user in ${db}"
    kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "CREATE USER gcp_replication;" &>/dev/null
    if [ $? -ne 0 ] ; then
      _echoerr "failed to create gcp_replication user in ${db}"
      return 1
    fi
  fi

  # 1.b Set gcp_replication user password
  kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "ALTER USER gcp_replication WITH PASSWORD '${replication_password}';" &>/dev/null
  if [ $? -ne 0 ] ; then
    _echoerr "failed to set gcp_replication password"
    return 1
  fi
  echo "${db}, ${replication_password}"

  # 1.c Make pgadmin user inherit from readwrite (pgadmin is not superuser)
  kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT readwrite to pgadmin;" &>/dev/null
  if [ $? -ne 0 ] ; then
      _echoerr "failed to grant pgadmin readwrite role in ${db}"
      return 1
  fi

  # 2. Extends pglogical to db
  kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "CREATE EXTENSION IF NOT EXISTS pglogical;" &>/dev/null
  if [ $? -ne 0 ] ; then
      _echoerr "failed to extend pglogical in ${db}"
      return 1
  fi

  # 3.
  # a. GRANT USAGE on SCHEMA SCHEMA to USER on all schemas , including pglogical
  # b. GRANT SELECT on ALL TABLES in SCHEMA pglogical to USER on all databases to get replication information from source databases.
  # c. GRANT SELECT on ALL SEQUENCES in SCHEMA SCHEMA to USER
  for schema in 'public' 'pglogical' 'sla_service' 'hdb_catalog' 'hdb_views'; do
    if [[ $(  kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "\dn;" | grep -c "${schema}") == 1 ]] ; then
      # a
      kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT USAGE on SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echoerr "failed to Grant Usage on ${schema}"
        return 1
      fi

       # b
      kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT SELECT on ALL TABLES in SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echoerr "failed to Grant Select on All Tables on ${schema}"
        return 1
      fi

      # c
      kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT SELECT on ALL SEQUENCES in SCHEMA ${schema} to gcp_replication;" &>/dev/null
      if [ $? -ne 0 ] ; then
        _echoerr "failed to Grant Select on All Tables on ${schema}"
        return 1
      fi
    fi
  done

  # 4. GRANT rds_replication to USER
  kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "GRANT rds_replication to gcp_replication;" &>/dev/null
  if [ $? -ne 0 ] ; then
    echoerr "failed to Grant rds_replication to gcp_replication"
    return 1
  fi

  _echoerr "Finished Creating replication user: gcp_replication for ${db}"
}