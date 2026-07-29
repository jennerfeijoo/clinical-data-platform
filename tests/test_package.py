import clinical_data_platform


def test_package_exposes_version() -> None:
    assert clinical_data_platform.__version__ == "0.11.0"
