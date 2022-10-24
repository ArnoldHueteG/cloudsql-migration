module "cloudsql_instance" {
    source = "git@github.com:4ut0n0m1c-41/terraform-gcp-cloud-sql-db-instance.git?ref=v2.2.11"


    #
    # NOTE:
    # This is best effort. Please validate each field.
    # Full instructions: https://docs.google.com/document/d/12MhFCnd6PZdQC0s9pmOIjIB-hL2SiDhWXWV-hzfhb3g/edit#heading=h.2hyu7k9i1lxm
    #

    application_name            = "key-rotation-gateway"
    create_users                = false
    data_classification         = "private"
    data_pii                    = "standard"
    db_name                     = "keyrotationgateway"
    db_version                  = "POSTGRES_9_6"
    default_region              = "us-west1"
    disk_size                   = 20
    disk_type                   = "PD_SSD"
    environment                 = "dev"
    k8s_cluster_name            = "gke-d-tmc-01"
    k8s_namespace               = "inventory"
    project_id                  = "prj-d-inventory-9345"
    random_suffix               = false
    sql_name_suffix             = "?"
    ssl_mode                    = "disable"
    team_name                   = "cnc"
    tier                        = "db-custom-1-4096"
    zone                        = "?"
}