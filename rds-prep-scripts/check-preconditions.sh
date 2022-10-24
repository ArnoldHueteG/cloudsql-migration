# Script to check various preconditions about RDS instances
# uses the secrets harvested by `collect-secrets.sh` as input
_echoerr() { echo "$@" 1>&2; }

pod_name=psql-client-$USER

query_pk=$(cat <<EOF
select count(*) > 0 from information_schema.tables tab
  left join information_schema.table_constraints tco on tab.table_schema = tco.table_schema
    and tab.table_name = tco.table_name and tco.constraint_type = 'PRIMARY KEY'
  where tab.table_type = 'BASE TABLE'
    and tab.table_schema not in ('pg_catalog', 'information_schema')
    and tco.constraint_name is null;
EOF
)

query_specialschemas=$(cat <<EOF
  SELECT nspname FROM pg_catalog.pg_namespace
  WHERE nspname NOT LIKE 'pg_%' AND nspname <> 'information_schema';
EOF
)

_start_psql() {
  # check if already exists
  if [[ $(kubectl get pods --no-headers=true | grep "${pod_name}" | wc -l | xargs) == "1" ]] ; then return 0 ; fi

  k8s_user=$USER
  # start psql pod
  kubectl run "$pod_name" --restart=Never --wait --labels="app=kpsql,kpsql=$pod_name,user=$k8s_user,4ut0n0m1c.41/rds-access=true" \
    --image postgres:11.5 --overrides "$(cat <<EOF
  {
    "apiVersion": "v1",
    "kind": "Pod",
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
}

_stop_psql() {
  kubectl delete pod "psql-client-${USER}" &> /dev/null
}

_check_connection() {
  timeout 5 kubectl exec "$pod_name" -- psql -h "$1" -p "$2" -d "$3" -U "$4" -qAt -c 'SELECT TRUE;' &> /dev/null
  return $?
}

_check_precondition() {
  ## Runs several inspection queries against the given database
  ## Input: secret line: "service,host,db,username"
  ## Output: dbname,SizeDB,HasTableWithNoPrimaryKey,HasLargeObjects,HasMaterializedView
  host=$(echo $1 | cut -d ',' -f 7)
  db=$(echo $1 | cut -d ',' -f 1)
  username=$(echo $1 | cut -d ',' -f 9)
  port=$(echo $1 | cut -d ',' -f 8)

  _echoerr "Check precondition for ${db}"
  dbsize=-1
  # check connection with retry
  retry=0
  maxRetries=5
  retryInterval=2
  until [ ${retry} -ge ${maxRetries} ]
  do
    _check_connection && break
    retry=$[${retry}+1]
    _echoerr "Retrying [${retry}/${maxRetries}] in ${retryInterval}(s) "
    sleep ${retryInterval}
  done

  if [ ${retry} -ge ${maxRetries} ]; then
    _echoerr "Can't connect to ${db} after ${maxRetries} attempts!"
    return 1;
  fi

  dbsize=$(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c 'SELECT pg_database_size(current_database());')
  hasTableWithNoPrimaryKey=$(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "$query_pk")
  hasMaterializedViews=$(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c 'SELECT count(*) > 0 from pg_matviews;')
  hasLargeObjects=$(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c 'SELECT count(*) > 0 from pg_largeobject_metadata;')
  specialSchemas=$(kubectl exec "$pod_name" -- psql -h "${host}" -p "${port}" -d "${db}" -U "${username}" -qAt -c "$query_specialschemas")
  specialSchemasArray=($(for i in $specialSchemas ; do echo "$i" ; done))
  echo "${dbsize},${hasTableWithNoPrimaryKey},${hasLargeObjects},${hasMaterializedViews},(${specialSchemasArray[*]})"
}

_check_preconditions() {
  ## iterates through each database described by the passed in csv file
  ## outputs a csv of HasNonPrimaryKeyTable,DatabaseSizeBytes,HasMaterializedView,HasLargeObjects

  _start_psql
  sleep 8
  unset csvFile
  # create pgpass file, upload to pod
  # see: https://www.postgresql.org/docs/11/libpq-pgpass.html
  rm .pgpass-tmp &>/dev/null
  touch .pgpass-tmp
  while read line; do
    host=$(echo "$line" | cut -d ',' -f 7)
    port=$(echo "$line" | cut -d ',' -f 8)
    db=$(echo "$line" | cut -d ',' -f 1)
    username=$(echo "$line" | cut -d ',' -f 9)
    password=$(echo "$line" | cut -d ',' -f 10)
    echo "${host}:*:${db}:${username}:${password}" >> .pgpass-tmp
  done < "$1"
  kubectl cp .pgpass-tmp "${pod_name}":.pgpass
  kubectl exec "$pod_name" -- chmod 0600 .pgpass
  # need some time bewteen
  rm .pgpass-tmp
  _echoerr "Created pgpass!"

  # psql pod is now prepared to send queries to
  # combine collect-connection and preconditions
  _echoerr "Finding preconditions..."
  while read -r line; do
    sleep 1
    precondition=$(_check_precondition "${line}")
    echo "${line}, ${precondition}"
  done < $1

  # write to csv=
  _echoerr "Finished fetching preconditions and Created '/tmp/...csv'"
  # cleanup
  _stop_psql
}

