from config import DbConfig

def test_dbconfig_infers_database_name():
    cfg = DbConfig("test", {"aws-readwrite-secret-name": "x.y.z"})
    assert cfg['database-name'] == "y"


def test_dbconfig_overrides_database_name():
    cfg = DbConfig("test", {"database-name":"x", "aws-readwrite-secret-name": "x.y.z"})
    assert cfg['database-name'] == "x"


def test_validate_config_detect_missing():
    errors = DbConfig("test", {}).validate()
    assert len(errors) > 0


def test_validate_remote():
    props = {k: '' for k in DbConfig._required_fields}
    props['database-name'] = "x"
    errors = DbConfig("test", props).validate()
    assert len(errors) == 0

    # detect missing aws secret values
    props['gcp-migration-strategy'] = 'remote'
    errors = DbConfig("test", props).validate()
    assert len(errors) == 2

    props['aws-readonly-password'] = 'x'
    props['aws-readwrite-password'] = 'x'
    errors = DbConfig("test", props).validate()
    assert len(errors) == 0