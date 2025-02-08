import pytest

from labtasker.security import hash_password, verify_password


@pytest.mark.unit
def test_hash_and_verify_password():
    password = "password"
    hashed_password = hash_password(password)
    assert hashed_password != password
    assert len(hashed_password) > 0

    assert verify_password(password, hashed_password)

    false_password = "false_password"
    assert not verify_password(false_password, hashed_password)
