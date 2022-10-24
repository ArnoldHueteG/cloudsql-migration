FROM google/cloud-sdk
WORKDIR /home/cloudsdk/

# kubectl and other deps
RUN apt-get -y install jq apt-transport-https ca-certificates curl
# can't download this inside ci, so copied locally:
# RUN curl -fsSLo /usr/share/keyrings/kubernetes-archive-keyring.gpg https://packages.cloud.google.com/apt/doc/apt-key.gpg
COPY kubernetes-archive-keyring.gpg /usr/share/keyrings/
RUN echo "deb [signed-by=/usr/share/keyrings/kubernetes-archive-keyring.gpg] https://apt.kubernetes.io/ kubernetes-xenial main" | tee /etc/apt/sources.list.d/kubernetes.list
RUN apt-get update && apt-get install -y kubectl

# app
COPY csm.py gcp.py kube.py config.py server.py psql-commands.sh configure-gke-clusters requirements.txt ./
RUN pip install -r requirements.txt
