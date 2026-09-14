from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.services.utils import video_processing as vp
from src.services.utils import upload_content as uploads


def test_decoder_error_is_rejected_even_with_success_exit(monkeypatch):
    monkeypatch.setattr(vp, "_ffmpeg_available", lambda: True)
    run = Mock(return_value=SimpleNamespace(returncode=0, stderr="error decoding H264 frame"))
    monkeypatch.setattr(vp.subprocess, "run", run)
    with pytest.raises(ValueError, match="damaged"):
        vp.validate_video_decode("lesson.mp4")
    args = run.call_args.args[0]
    assert "-xerror" in args and "explode" in args
    assert "0:v:0" in args and "0:a?" in args


def test_clean_decode_accepted_and_nonvideo_skipped(monkeypatch):
    monkeypatch.setattr(vp, "_ffmpeg_available", lambda: True)
    run = Mock(return_value=SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr(vp.subprocess, "run", run)
    vp.validate_video_decode("lesson.MP4")
    vp.validate_video_decode("workbook.pdf")
    assert run.call_count == 1


@pytest.mark.parametrize("storage", ["filesystem", "s3api"])
@pytest.mark.parametrize("failure,status", [(ValueError("bad frame"), 422), (RuntimeError("no decoder"), 503)])
async def test_bad_upload_is_not_published(monkeypatch, tmp_path, storage, failure, status):
    monkeypatch.chdir(tmp_path)
    cfg = SimpleNamespace(hosting_config=SimpleNamespace(content_delivery=SimpleNamespace(
        type=storage, s3api=SimpleNamespace(endpoint_url="https://storage.invalid", bucket_name="test"))))
    monkeypatch.setattr(uploads, "get_learnhouse_config", lambda: cfg)
    s3 = Mock()
    monkeypatch.setattr(uploads.boto3, "client", lambda *a, **k: s3)
    monkeypatch.setattr(uploads, "validate_video_decode", Mock(side_effect=failure))
    faststart = Mock()
    monkeypatch.setattr(uploads, "ensure_faststart", faststart)
    with pytest.raises(HTTPException) as e:
        await uploads.upload_content("courses/c/video", "orgs", "org_test", b"bad", "lesson.mp4")
    assert e.value.status_code == status
    assert not list(tmp_path.rglob("*.mp4"))
    s3.upload_file.assert_not_called()
    faststart.assert_not_called()
