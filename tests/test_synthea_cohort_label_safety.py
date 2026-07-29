from pathlib import Path

import pytest

from clinical_data_platform.synthea_cohorts import (
    SyntheaCohortError,
    compare_synthea_cohorts,
)


@pytest.mark.parametrize(
    "unsafe_label",
    [
        "",
        ".",
        "..",
        "../shared",
        "x/../cohort_a",
        "cohort/a",
        "/tmp/cohort_a",
        "C:\\cohort_a",
        "cohort.a",
        "-cohort_a",
    ],
)
def test_comparison_rejects_labels_that_are_not_safe_path_components(
    unsafe_label: str,
) -> None:
    with pytest.raises(SyntheaCohortError, match="safe single path components"):
        compare_synthea_cohorts(
            Path("missing-a"),
            Path("missing-b"),
            Path("unused-output"),
            cohort_a_label=unsafe_label,
            cohort_b_label="cohort_b",
        )


def test_comparison_rejects_labels_equal_after_whitespace_normalization() -> None:
    with pytest.raises(SyntheaCohortError, match="distinct after normalization"):
        compare_synthea_cohorts(
            Path("missing-a"),
            Path("missing-b"),
            Path("unused-output"),
            cohort_a_label="cohort_a",
            cohort_b_label="  cohort_a  ",
        )
