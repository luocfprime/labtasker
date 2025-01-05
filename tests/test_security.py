from typing import Any, Dict

import pytest
from fastapi import HTTPException

from labtasker.security import SecurityManager


def test_password_hashing():
    security = SecurityManager(pepper="test_pepper")
    password = "test_password"
    hashed = security.hash_password(password)

    assert hashed != password
    assert security.verify_password(password, hashed)
    assert not security.verify_password("wrong_password", hashed)


def test_pepper_affects_hash():
    security1 = SecurityManager(pepper="pepper1")
    security2 = SecurityManager(pepper="pepper2")

    password = "test_password"
    hash1 = security1.hash_password(password)
    hash2 = security2.hash_password(password)

    # Same password should produce different hashes with different peppers
    assert hash1 != hash2
    # Each security manager should only verify its own hashes
    assert security1.verify_password(password, hash1)
    assert not security1.verify_password(password, hash2)


def test_password_length_validation(mock_db):
    """Test minimum password length requirement."""
    from labtasker.config import ServerConfig

    config = ServerConfig()
    security = SecurityManager(pepper="test_pepper")

    # Test short password
    short_password = "short"
    with pytest.raises(ValueError, match="Password must be at least"):
        security.hash_password(short_password)

    # Test valid password
    valid_password = "long_enough_password"
    hashed = security.hash_password(valid_password)
    assert security.verify_password(valid_password, hashed)


def test_pepper_change_new_passwords(mock_db):
    """Test that new pepper affects new password hashes."""
    security = SecurityManager(pepper="old_pepper")
    password = "test_password"
    old_hash = security.hash_password(password)

    # Change pepper
    security.pepper = "new_pepper"
    new_hash = security.hash_password(password)

    # Verify hashes are different with different peppers
    assert old_hash != new_hash
    # Verify new password works with new pepper
    assert security.verify_password(password, new_hash)
