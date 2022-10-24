_echoerr() { echo "$@" 1>&2; }

_reset_password() {
  aws-okta exec okta -- aws rds modify-db-instance --db-instance-identifier "$1" --master-user-password="$2" &>/dev/null
  return $?
}

_reset_passwords() {
  # reset passwords
  while IFS=, read -r line; do
    dbID=$(echo "$line" | cut -d ',' -f 3)
    password=$(echo "$line" | cut -d ',' -f 10)
    _echoerr "Resetting password for ${dbID}"
    retry=0
    maxRetries=5
    retryInterval=2
    until [ ${retry} -ge ${maxRetries} ]
    do
      _reset_password "${dbID}" "${password}" && break
      retry=$[${retry}+1]
      _echoerr "Retrying [${retry}/${maxRetries}] in ${retryInterval}(s) "
      sleep ${retryInterval}
    done
    if [ ${retry} -ge ${maxRetries} ]; then
      _echoerr "Can't reset password for ${dbID} after ${maxRetries} attempts!"
    fi
  done < $1

}

_collect_db_instances_data() {
  aws-okta exec okta -- aws rds describe-db-instances > /tmp/rds-instances.json &>/dev/null
  if [ $? -ne 0 ] ; then
    _echoerr "failed to collect db instances data"
  fi
}

_collect_db_instance_data() {
  aws-okta exec okta -- aws rds describe-db-instances --db-instance-identifier "$1" > /tmp/rds-instance.json &>/dev/null
  if [ $? -ne 0 ] ; then
    _echoerr "failed to collect db instance data for $1"
    return 1;
  fi
}

_collect_db_parameters_data() {
  aws-okta exec okta -- aws rds describe-db-parameters --db-parameter-group-name ${1} > /tmp/rds-instances-parameters.json &>/dev/null
  if [ $? -ne 0 ] ; then
    _echoerr "failed to collect db parameters data for $1"
  fi
}

_collect_parameters() {
  # get the shared_preload_libraries values currently applied to the DB
  PARAM_JSON=$(jq '.Parameters[] | select(.ParameterName == "shared_preload_libraries") |{ParameterValue: (if .ParameterValue != null then .ParameterValue else "none" end)}' < /tmp/rds-instances-parameters.json)
  echo "${PARAM_JSON//,/;}"
}

_collect_connection_info_all() {
  # get data by environment, and reset the admin password on each DB selected
  ALLOWED_ENVS="dev|staging|prod|sb1|tools|all"
  if [ -z "$1" ] || [[ ! ${1} =~ ${ALLOWED_ENVS} ]] ; then
    echo "usage: ./collect-connection-info ${ALLOWED_ENVS}"
    return 1
  fi

  _collect_db_instances_data
  unset csvFile
  local adminPassword=$(cat /dev/urandom | LC_CTYPE=C tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
  local envSelector="$1"
  for instance in $(jq -r --arg e "${envSelector}" '.DBInstances[] | select(.DBSubnetGroup.DBSubnetGroupName[4:] == $e)| @base64' < /tmp/rds-instances.json); do
    _collect_specific_values_decode() {
      echo "${1}" | base64 --decode | jq -r "${2}"
    }

    _collect_instance_info_decode() {
      echo "${instance}" | base64 --decode | jq -r --arg e "${adminPassword}" '{DBName: .DBName, DBParameterGroupName: .DBParameterGroups[].DBParameterGroupName, DBInstanceIdentifier: .DBInstanceIdentifier, StorageEncrypted: .StorageEncrypted, postgresVersion: .EngineVersion, env: .DBSubnetGroup.DBSubnetGroupName[4:], hostname: .Endpoint.Address, hostPort: .Endpoint.Port, username: .MasterUsername, password: $e }'
    }

    # Find ParameterGroupName from DBInstances
    DBParameterGroupName=$(_collect_specific_values_decode "${instance}" '.DBParameterGroups[].DBParameterGroupName')
    _echoerr "Collecting: ${DBParameterGroupName}"
    # Find parameters under parameterGroupName
    sleep 0.2
    _collect_db_parameters_data "${DBParameterGroupName}"
    # Combine all
    value=$(echo "$(_collect_instance_info_decode) $(_collect_parameters)" | jq -s add)
    csvFileRow=$(jq -r 'to_entries|map(.value)|@csv' <<< "${value}" | sed 's/,*\r*$//' | sed 's/\"//g' )
    echo "${csvFileRow}"
  done
  # write to csv
  _echoerr "Finished collecting, written '/tmp/dev-temp.csv'!"
}

_collect_connection_info_for() {
  local adminPassword=$(cat /dev/urandom | LC_CTYPE=C tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
  _collect_specific_values() {
    echo "${1}" | jq -r "${2}"
  }
   _collect_instance_info() {
    echo "${instanceJSON}" | jq -r --arg e "${adminPassword}" '{DBName: .DBName, DBParameterGroupName: .DBParameterGroups[].DBParameterGroupName, DBInstanceIdentifier: .DBInstanceIdentifier, StorageEncrypted: .StorageEncrypted, postgresVersion: .EngineVersion, env: .DBSubnetGroup.DBSubnetGroupName[4:], hostname: .Endpoint.Address, hostPort: .Endpoint.Port, username: .MasterUsername, password: $e }'
  }
  while IFS= read -r instance; do
    _collect_db_instance_data "${instance}"
    instanceJSON=$(jq '.DBInstances[]' < /tmp/rds-instance.json)
    DBParameterGroupName=$(_collect_specific_values "${instanceJSON}" '.DBParameterGroups[].DBParameterGroupName')
    _echoerr "Collecting: ${DBParameterGroupName}"
    _collect_db_parameters_data "${DBParameterGroupName}"
    value=$(echo "$(_collect_instance_info) $(_collect_parameters)" | jq -s add)
    csvFileRow=$(jq -r 'to_entries|map(.value)|@csv' <<< "${value}" | sed 's/,*\r*$//' | sed 's/\"//g' )
    echo "${csvFileRow}"
  done < "$1"
}
