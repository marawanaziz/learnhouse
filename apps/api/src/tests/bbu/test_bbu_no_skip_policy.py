from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bbu_migration.router import (
    _is_doula_training_no_skip,
    no_skip_courses,
)


class _ScalarResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


def test_standard_doula_training_with_tests_is_no_skip():
    assert _is_doula_training_no_skip(
        "Certified Birth Doula Training",
        {
            "bbu_credential_type": "birth",
            "bbu_layout": "certification",
            "certification_type": "professional",
            "bbu_no_skip": True,
        },
        has_tests=True,
    )


def test_bold_doula_training_with_tests_is_no_skip():
    assert _is_doula_training_no_skip(
        "BOLD-Certified Postpartum Doula Training",
        {
            "bbu_layout": "certification",
            "certification_type": "professional",
            "certification_name": "BOLD-Certified Postpartum Doula Training",
        },
        has_tests=True,
    )


def test_doula_training_without_tests_allows_skipping():
    assert not _is_doula_training_no_skip(
        "Doula Agency Owner Mentorship",
        {
            "bbu_layout": "certification",
            "certification_type": "professional",
        },
        has_tests=False,
    )


def test_family_course_allows_skipping():
    assert not _is_doula_training_no_skip(
        "Intro to Childbirth",
        {
            "bbu_layout": "completion",
            "certification_type": "completion",
        },
        has_tests=False,
    )


def test_perinatal_professional_course_allows_skipping_despite_legacy_flag():
    assert not _is_doula_training_no_skip(
        "Breastfeeding for Perinatal Professionals",
        {
            "bbu_layout": "completion",
            "certification_type": "continuing",
            "bbu_ceu_value": 3,
            "bbu_no_skip": True,
        },
        has_tests=True,
    )


def test_unrelated_professional_certification_allows_skipping():
    assert not _is_doula_training_no_skip(
        "Professional Childbirth Educator",
        {
            "bbu_layout": "certification",
            "certification_type": "professional",
        },
        has_tests=True,
    )


@pytest.mark.asyncio
async def test_endpoint_returns_only_tested_doula_training_courses():
    certifications = [
        SimpleNamespace(
            course_id=1,
            config={
                "bbu_credential_type": "birth",
                "bbu_layout": "certification",
                "certification_type": "professional",
            },
        ),
        SimpleNamespace(
            course_id=2,
            config={
                "bbu_layout": "completion",
                "certification_type": "completion",
            },
        ),
        SimpleNamespace(
            course_id=3,
            config={
                "bbu_layout": "completion",
                "certification_type": "continuing",
                "bbu_no_skip": True,
            },
        ),
        SimpleNamespace(
            course_id=4,
            config={
                "bbu_layout": "certification",
                "certification_type": "professional",
                "certification_name": "BOLD-Certified Postpartum Doula Training",
            },
        ),
    ]
    courses = [
        SimpleNamespace(id=1, name="Certified Birth Doula Training", course_uuid="course_doula"),
        SimpleNamespace(id=2, name="Intro to Childbirth", course_uuid="course_family"),
        SimpleNamespace(
            id=3,
            name="Breastfeeding for Perinatal Professionals",
            course_uuid="course_perinatal",
        ),
        SimpleNamespace(
            id=4,
            name="BOLD-Certified Postpartum Doula Training",
            course_uuid="course_bold_doula",
        ),
    ]
    session = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _ScalarResult(certifications),
                _ScalarResult([1, 3, 4]),
                _ScalarResult(courses),
            ]
        )
    )

    assert await no_skip_courses(session) == {
        "course_uuids": ["course_doula", "course_bold_doula"]
    }
