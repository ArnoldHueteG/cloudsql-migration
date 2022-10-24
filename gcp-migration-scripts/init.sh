if [ -e config.yaml ]
then 
yq() {
  docker run --user="root" --rm -i -v "${PWD}":/workdir mikefarah/yq "$@"
}
GCP_PROJECT=$(yq e ".$1.gcp-project-name" config.yaml)
GCP_GKE_ENV=$(yq e ".$1.k8s-env" config.yaml)
GCP_GKE_CLUSTER=$(yq e ".${GCP_GKE_ENV}" gke_cluster.yaml)
GCP_GKE_NAMESPACE=$(yq e ".$1.k8s-namespace" config.yaml)

docker image inspect 4ut0n0m1c-cloud-sdk:1.0 >/dev/null 2>&1 || docker build -t 4ut0n0m1c-cloud-sdk:1.0 .
# check if we can access 
echo "check if we can access k8s pods"
get_pods=$(docker run --rm -ti --volumes-from gcloud-config 4ut0n0m1c-cloud-sdk:1.0 /bin/bash -c "kubectl get pods" 2>/dev/null)
# If we can't access k8s, authenticate
if [ $? -ne 0 ] ; then
    echo "creating gcloud-config docker image"
    docker rm gcloud-config || true

    # TODO: these (prj-d-tmc-iam-d9d2, gke-d-tmc-01, tmc-iam) need to be variables dependant on the service being migrated
    docker run -ti --name gcloud-config 4ut0n0m1c-cloud-sdk:1.0 /bin/bash -c \
      "gcloud auth login --update-adc \
        && gcloud config set project ${GCP_PROJECT} \
        && bash configure-gke-clusters \
        && kubectl config use-context ${GCP_GKE_CLUSTER} \
        && kubectl config set-context --current --namespace=${GCP_GKE_NAMESPACE}"
fi;
else
  echo "The config.yaml file does no exist in parent folder"
fi