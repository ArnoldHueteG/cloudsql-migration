parent_path=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
bash "$parent_path/init.sh" $1
docker run --rm -ti --volumes-from gcloud-config \
  -v "$(pwd)"/config.yaml:/home/cloudsdk/config.yaml \
  -e USER="$USER" \
  4ut0n0m1c-cloud-sdk:1.0 /bin/bash -c "python3 csm.py start_sync --service $1 --verbose"
