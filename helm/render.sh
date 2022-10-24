if [ -e "values-${ENVIRONMENT}.yaml" ]; then
  ENVIRONMENT_YAML="-f values-${ENVIRONMENT}.yaml"
fi

helm3 template ${SERVICE_NAME} . --namespace=${NAMESPACE} \
    --set environment=${ENVIRONMENT} \
    ${ENVIRONMENT_YAML} \
    --set image.tag=${VERSION}