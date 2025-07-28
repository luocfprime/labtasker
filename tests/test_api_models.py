import pydantic
import pytest

from labtasker.api_models import QueueGetResponse
from labtasker.utils import get_current_time

pytestmark = [pytest.mark.unit]


def test_validate_metadata_key():
    with pytest.raises(pydantic.ValidationError):
        QueueGetResponse(
            queue_id="test",
            queue_name="test",
            created_at=get_current_time(),
            last_modified=get_current_time(),
            metadata={".": "foo"},  # invalid key
        )
