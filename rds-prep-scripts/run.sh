source check-preconditions.sh
source collect-connection-info.sh
source create-replication.sh

# Collects audits for all db instances for specified environment
_collect_all_audits() {
  ALLOWED_ENVS="dev|staging|prod|sb1|tools|all"
  if [ -z "$1" ] || [[ ! ${1} =~ ${ALLOWED_ENVS} ]] ; then
    echo "usage: ./_collect_audits ${ALLOWED_ENVS}"
    return 1
  fi
  echo "running collect_connection_info for $1"
  _collect_connection_info_all "$1" > /tmp/"$1"-temp.csv
  sleep 1
  _reset_passwords /tmp/"$1"-temp.csv
  echo "running check_preconditions"
  _check_preconditions /tmp/"$1"-temp.csv > /tmp/"$1"-rds-info.csv
}

# Collects audits for specific db instances given an input: file with db identifiers
_collect_audits_for() {
  if [ -z "$1" ] ; then
    echo "usage: ./_collect_audits_for instances.txt"
    echo "Look at instances.txt for input file guidance"
    return 1
  fi
  _echoerr "running collection_connection_info"
  _collect_connection_info_for "$1" > /tmp/audits-temp.csv
  sleep 1
  _reset_passwords /tmp/audits-temp.csv
  echo "running check_preconditions"
  _check_preconditions /tmp/audits-temp.csv > /tmp/audits.csv
}

# Applies pglogical parameter to db paramter group based on input: parameter group name
_modify_with_pglogical() {
  if [ -z "$1" ] ; then
    echo "usage: ./_modify_with_pglogical <parameter group name>"
    return 1
  fi
  _modify_param() {
    aws-okta exec okta -- aws rds modify-db-parameter-group --db-parameter-group-name "$1" \
    --parameters "ParameterName='shared_preload_libraries', ParameterValue='$2', ApplyMethod='pending-reboot'"
  }
  _collect_db_parameters_data "$1"
  PARAM_JSON=$(jq '.Parameters[] | select(.ParameterName == "shared_preload_libraries") |{ParameterValue: (if .ParameterValue != null then .ParameterValue else "none" end)}' < /tmp/rds-instances-parameters.json)
  value=$(jq -r 'to_entries|map(.value)|@csv' <<< "${PARAM_JSON}"| sed 's/\"//g')
  if [[ ${value} == "none" ]] ; then
      _modify_param "$1" "pglogical"
  else
    param=${value},"pglogical"
    _modify_param "$1" "${param}"
  fi
}

# Reboot db instances given an input file: with db identifiers
_reboot_instances_for() {
  if [ -z "$1" ] ; then
    echo "usage: ./_reboot_instances_for <instances>.txt"
    echo "Look at instances.txt for input file guidance"
    return 1
  fi
  _reboot_aws() {
    aws-okta exec okta -- aws rds reboot-db-instance --db-instance-identifier "$1"
    return $?
  }
  while IFS= read -r instance; do
    _echoerr "Rebooting: ${instance}"
    retry=0
    maxRetries=5
    retryInterval=2
    until [ ${retry} -ge ${maxRetries} ]
    do
      _reboot_aws "${instance}" && break
      retry=$[${retry}+1]
      _echoerr "Retrying [${retry}/${maxRetries}] in ${retryInterval}(s) "
      sleep ${retryInterval}
    done
    if [ ${retry} -ge ${maxRetries} ]; then
      _echoerr "Can't reboot ${dbID} after ${maxRetries} attempts!"
    fi
    sleep 0.5
  done < "$1"
}

# Extends pglogical, Creates new user, grants usage/selects/rds_replication
_create_replication_user_for() {
  if [ -z "$1" ] ; then
    _echoerr "usage: ./_create_replication_user_for <instances>.txt"
    _echoerr "Look at instances.txt for input file guidance"
    return 1
  fi
  _collect_connection_info_for "$1" > /tmp/audits-temp.csv
  sleep 1
  _reset_passwords /tmp/audits-temp.csv
  _start_psql
  rm .pgpass-tmp &>/dev/null
  while read -r line; do
    host=$(echo "${line}" | cut -d ',' -f 7)
    db=$(echo "${line}" | cut -d ',' -f 1)
    username=$(echo "${line}" | cut -d ',' -f 9)
    port=$(echo "${line}" | cut -d ',' -f 8)
    echo "${host}:*:${db}:${username}:${password}" >> .pgpass-tmp
    echo "${host}:*:postgres:${username}:${password}" >> .pgpass-tmp
  done < /tmp/audits-temp.csv
  pod_name=psql-client-$USER
  kubectl cp .pgpass-tmp "${pod_name}":.pgpass
  kubectl exec "${pod_name}" -- chmod 0600 .pgpass
  rm .pgpass-tmp
  while read -r line; do
    #replication_password=$(cat /dev/urandom | LC_CTYPE=C tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
    replication_password="gcp_password"
    host=$(echo "${line}" | cut -d ',' -f 7)
    db=$(echo "${line}" | cut -d ',' -f 1)
    username=$(echo "${line}" | cut -d ',' -f 9)
    port=$(echo "${line}" | cut -d ',' -f 8)
    sleep 5;
    _create_replication_user "${host}" "${port}" "${db}" "${username}" "${replication_password}"
    _create_replication_user "${host}" "${port}" postgres "${username}" "${replication_password}"
  done < /tmp/audits-temp.csv
  _stop_psql
}

