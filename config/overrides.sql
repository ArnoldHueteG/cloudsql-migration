update databases set app = "vsdn-migration-command-tracker" where app = "aba-swap-detector";
update databases set app = "ftcp-correlation-mapper" where app = "cloud-to-ftcp-converter";
update databases set app = "tenantless-geofence-crud", team="realtime-data-processing" where app = "tenantless-geofence-crud-service";
update databases set app = "ftcp-device-readiness" where app = "ftcp-connectivity";
update databases set app = "mqtt-credentials-manager" where app = "mqtt-credentials";
update databases set app = "chat-command-api" where app = "command-api";
update databases set app = "oem-command-service" where app = "command-frontend";

update services set app = "goldwatch-grafana" where name = "goldwatch-grafana";
update services set app = "vsdn-migration-command-tracker" where name = "vsdn-migration-command-tracker-cron";
delete from services where app = "kpsql";