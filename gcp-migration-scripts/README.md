# GCP Migration Script Shells

Shells to be used by orchestration team. These environment variables are obtained from config.yaml and gke_cluster.yaml.

- GCP_PROJECT
- GCP_GKE_CLUSTER
- GCP_GKE_NAMESPACE

## start.sh

```bash
bash ./gcp-migration-scripts/start.sh <service>
```

## check.sh

The current migration job phase.

PHASE | DESCRIPTION
--- | --- 
PHASE_UNSPECIFIED| The phase of the migration job is unknown.
FULL_DUMP| The migration job is in the full dump phase.
CDC| The migration job is CDC phase.
PROMOTE_IN_PROGRESS| The migration job is running the promote phase.
WAITING_FOR_SOURCE_WRITES_TO_STOP| Only RDS flow - waiting for source writes to stop
PREPARING_THE_DUMP| Only RDS flow - the sources writes stopped, waiting for dump to begin
COMPLETED| The migration job has been completed.

```bash
bash ./gcp-migration-scripts/check.sh <service>
```

## promote.sh

```bash
bash ./gcp-migration-scripts/promote.sh <service>
```