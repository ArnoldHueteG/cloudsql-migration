# Config Tools

> Tools to create the `config.yaml` file required to run csm.py.

You'll need access to the pgg-cloudsql-tigerteam aws group.

# Usage
```bash
# log in to all the things
kubectl get pods
# use role arn:aws:iam::058711591523:role/gg-tt-database-engineers-na.samlrole
aws-okta exec okta -- aws rds
~/workspace/gcp-scripts/gcloud-login

# then run
python config.py create-yaml
```