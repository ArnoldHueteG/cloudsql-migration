module "cloudsql_instance" {
    source = "git@github.com:4ut0n0m1c-41/terraform-gcp-cloud-sql-db-instance.git?ref=v2.2.11"


    #
    # NOTE:
    # This is best effort. Please validate each field.
    # Full instructions: https://docs.google.com/document/d/12MhFCnd6PZdQC0s9pmOIjIB-hL2SiDhWXWV-hzfhb3g/edit#heading=h.2hyu7k9i1lxm
    #

    application_name            = "fuel-volume"
    create_users                = false
    data_classification         = "private"
    data_pii                    = "standard"
    db_name                     = "fuelvolume"
    db_version                  = "POSTGRES_9_6"
    default_region              = "us-west1"
    disk_size                   = 5
    disk_type                   = "PD_SSD"
    environment                 = "dev"
    k8s_cluster_name            = "gke-d-tmc-01"
    k8s_namespace               = "ftcp-adaptor"
    project_id                  = "prj-d-ftcp-adaptor-c8b2"
    random_suffix               = false
    sql_name_suffix             = "?"
    ssl_mode                    = "disable"
    team_name                   = "tms"
    tier                        = "db-custom-8-32768"
    zone                        = "?"
}