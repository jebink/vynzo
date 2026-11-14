import pytest
from fundamentals_worker.__main__ import JOBS, main


def test_jobs_registered():
    assert JOBS


def test_unknown_job_rejected():
    with pytest.raises(SystemExit):
        main(["no-such-job"])
