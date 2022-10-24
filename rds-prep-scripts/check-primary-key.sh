#name=account-service.accountservice.rw
name=$1
secret_body="$(kubectl get secrets "$name" --output json)"

_get_secret() {
  echo "$secret_body" | tr '\r\n' ' ' | jq -r $1 | base64 --decode
}

host="$(_get_secret .data.host)"
dbname="$(_get_secret .data.dbname)"
username="$(_get_secret .data.username)"
password="$(_get_secret .data.password)"

#get number of tables without primary keys
query_pk=$(cat <<EOF
select count(*) from information_schema.tables tab
  left join information_schema.table_constraints tco on tab.table_schema = tco.table_schema
    and tab.table_name = tco.table_name and tco.constraint_type = 'PRIMARY KEY'
  where tab.table_type = 'BASE TABLE'
    and tab.table_schema not in ('pg_catalog', 'information_schema')
    and tco.constraint_name is null;
EOF
)

get_pk_count="$(kubectl run psql-client --rm -i --restart=Never --quiet \
    --image postgres -- env PGPASSWORD="$password" psql -qAt -h "$host" -U "$username" -d "$dbname" -c "$query_pk")"

#get db size
query_size=$(cat <<EOF
  SELECT pg_database_size('$dbname');
EOF
)

get_db_size="$(kubectl run psql-client --rm -i --restart=Never \
  --quiet --image postgres -- env PGPASSWORD="$password" psql -qAt -h "$host" -U "$username" -d "$dbname" -c "$query_size")"

#get hasLargeObjects
query_hasLargeObjects=$(cat <<EOF
  select count(*) from pg_largeobject_metadata;
EOF
)

get_hasLargeObjects="$(kubectl run psql-client --rm -i --restart=Never \
  --quiet --image postgres -- env PGPASSWORD="$password" psql -qAt -h "$host" -U "$username" -d "$dbname" -c "$query_hasLargeObjects")"

#get hasMaterializedViews
query_materialized_views=$(cat <<EOF
  select count(*) from pg_matviews;
EOF
)

get_hasMaterializedViews="$(kubectl run psql-client --rm -i --restart=Never \
  --quiet --image postgres -- env PGPASSWORD="$password" psql -qAt -h "$host" -U "$username" -d "$dbname" -c "$query_materialized_views")"

echo "$name , $get_pk_count , $get_db_size , $get_hasLargeObjects , $get_hasMaterializedViews" >> single-csv-row.txt
