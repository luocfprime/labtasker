import datetime

import pydantic
import pytest

from labtasker.api_models import QueueGetResponse

pytestmark = [pytest.mark.unit]


def test_validate_metadata_key():
    with pytest.raises(pydantic.ValidationError):
        QueueGetResponse(
            _id="test",
            queue_name="test",
            created_at=datetime.datetime.now(),
            last_modified=datetime.datetime.now(),
            metadata={".": "foo"},  # invalid key
        )
