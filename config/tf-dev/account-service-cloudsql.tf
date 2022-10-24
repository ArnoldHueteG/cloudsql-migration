module "cloudsql_instance" {
    source = "git@github.com:4ut0n0m1c-41/terraform-gcp-cloud-sql-db-instance.git?ref=v2.2.11"


    # WARNING:
    # WARNING: the generation script found multiple cloudSQL instances with the same prefix. Validate the correct sql_name_suffix was chosen!!!

    #
    # NOTE:
    # This is best effort. Please validate each field.
    # Full instructions: https://docs.google.com/document/d/12MhFCnd6PZdQC0s9pmOIjIB-hL2SiDhWXWV-hzfhb3g/edit#heading=h.2hyu7k9i1lxm
    #
    # To replace state, run this in your terraform folder
    /*
        DB_PATH=projects/prj-d-tmc-iam-d9d2/instances/sql-d-p-account-service-20210825t103529
        DB_RES_ADDR=module.cloudsql_instance.module.postgres.google_sql_database_instance.default
        rm -rf .terraform ; terraform init ; terraform import $DB_RES_ADDR $DB_PATH

        # USE WITH CAUTION!
        terraform apply
    */

    application_name            = "account-service"
    create_users                = false
    data_classification         = "private"
    data_pii                    = "standard"
    db_name                     = "accountservice"
    db_version                  = "POSTGRES_11"
    default_region              = "us-west1"
    disk_size                   = 200
    disk_type                   = "PD_SSD"
    environment                 = "dev"
    k8s_cluster_name            = "gke-d-tmc-01"
    k8s_namespace               = "tmc-iam"
    project_id                  = "prj-d-tmc-iam-d9d2"
    random_suffix               = false
    sql_name_suffix             = "20210825t103529"
    ssl_mode                    = "disable"
    team_name                   = "accounts-identity"
    tier                        = "db-custom-2-10240"
    zone                        = "a"
}