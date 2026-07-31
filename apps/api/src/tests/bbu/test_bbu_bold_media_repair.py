"""Project BOLD course copies use their copied media records."""

from types import SimpleNamespace

from src.bbu_migration.groupings import _repair_cloned_activity_content


def _block(block_id, uuid, activity_id, course_id, activity_uuid, file_id):
    return SimpleNamespace(
        id=block_id,
        block_type=SimpleNamespace(value="BLOCK_VIDEO"),
        content={
            "activity_uuid": activity_uuid,
            "file_id": file_id,
            "file_format": "mp4",
        },
        org_id=1,
        course_id=course_id,
        chapter_id=3,
        activity_id=activity_id,
        block_uuid=uuid,
        creation_date="now",
        update_date="now",
    )


def test_repair_rebinds_embedded_media_to_the_bold_clone():
    source_activity = SimpleNamespace(activity_uuid="activity_source")
    target_activity = SimpleNamespace(
        activity_uuid="activity_bold",
        content={
            "type": "doc",
            "content": [{
                "type": "videoBlock",
                "attrs": {
                    "blockObject": {
                        "block_uuid": "block_source",
                        "course_id": 7,
                        "activity_id": 10,
                        "content": {
                            "activity_uuid": "activity_source",
                            "file_id": "file_source",
                        },
                    }
                },
            }],
        },
    )
    source_block = _block(1, "block_source", 10, 7, "activity_source", "file_source")
    target_block = _block(2, "block_bold", 20, 8, "activity_bold", "file_bold")

    repaired, error = _repair_cloned_activity_content(
        source_activity, target_activity, [source_block], [target_block]
    )
    block_object = repaired["content"][0]["attrs"]["blockObject"]

    assert error == ""
    assert block_object["block_uuid"] == "block_bold"
    assert block_object["course_id"] == 8
    assert block_object["activity_id"] == 20
    assert block_object["content"]["activity_uuid"] == "activity_bold"
    assert block_object["content"]["file_id"] == "file_bold"
