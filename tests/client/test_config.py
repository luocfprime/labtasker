from __future__ import annotations

from pathlib import Path

import pytest

from labtasker.config import resolve_config
from labtasker.errors import ConfigError


def write_config(tmp_path: Path, text: str) -> Path:
    directory = tmp_path / ".labtasker"
    directory.mkdir()
    path = directory / "config.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_and_public_shape(tmp_path: Path) -> None:
    config = resolve_config(cwd=tmp_path, environment={})
    assert config.url is None
    assert config.queue == "default"
    assert config.token is None
    assert config.local is not None
    assert config.public_dict() == {
        "mode": "local",
        "directory": str(tmp_path),
        "database": str(tmp_path / ".labtasker/server.db"),
        "socket": str(config.local.socket),
        "url": None,
        "queue": "default",
        "token_configured": False,
    }
    assert not (tmp_path / ".labtasker").exists()


def test_local_mode_rejects_token_without_url(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        resolve_config(token="secret", cwd=tmp_path, environment={})
    assert raised.value.details == {"source": "constructor", "field": "token"}


def test_resolution_precedence_is_per_field(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        'url = "http://file.test/root/"\nqueue = "file"\ntoken = "file-secret"\n',
    )
    config = resolve_config(
        url="https://constructor.test/prefix/",
        cwd=tmp_path,
        environment={
            "LABTASKER_URL": "http://environment.test",
            "LABTASKER_QUEUE": "environment",
        },
    )
    assert config.url == "https://constructor.test/prefix"
    assert config.queue == "environment"
    assert config.token == "file-secret"
    assert config.public_dict()["token_configured"] is True


def test_present_empty_environment_value_is_invalid(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        resolve_config(cwd=tmp_path, environment={"LABTASKER_TOKEN": ""})
    assert raised.value.code == "invalid_config"
    assert raised.value.details == {"source": "environment", "field": "token"}


@pytest.mark.parametrize(
    ("text", "field"),
    [
        ('unknown = "x"\n', None),
        ("queue = 1\n", "queue"),
        ('queue = ""\n', "queue"),
        ('queue = "a"\nqueue = "b"\n', None),
        ("[profile]\nqueue = 'x'\n", None),
    ],
)
def test_invalid_config_file_has_one_stable_error(
    tmp_path: Path,
    text: str,
    field: str | None,
) -> None:
    path = write_config(tmp_path, text)
    with pytest.raises(ConfigError) as raised:
        resolve_config(cwd=tmp_path, environment={})
    assert raised.value.code == "invalid_config"
    assert raised.value.details["source"] == str(path)
    if field is not None:
        assert raised.value.details["field"] == field


def test_legacy_config_presence_stops_resolution(tmp_path: Path) -> None:
    directory = tmp_path / ".labtasker"
    directory.mkdir()
    legacy = directory / "client.toml"
    legacy.write_text("not parsed", encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        resolve_config(
            cwd=tmp_path,
            environment={"LABTASKER_URL": "https://environment.test"},
        )
    assert raised.value.code == "legacy_config_found"
    assert raised.value.details == {"source": str(legacy)}


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.test",
        "example.test",
        "http://user:password@example.test",
        "http://example.test?query=1",
        "http://example.test#fragment",
        "http://",
        "",
    ],
)
def test_invalid_urls_are_rejected(tmp_path: Path, url: str) -> None:
    with pytest.raises(ConfigError) as raised:
        resolve_config(url=url, cwd=tmp_path, environment={})
    assert raised.value.code == "invalid_config"
    assert raised.value.details == {"source": "constructor", "field": "url"}


def test_queue_and_constructor_token_are_strict(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as queue_error:
        resolve_config(queue="bad queue", cwd=tmp_path, environment={})
    assert queue_error.value.details == {"source": "constructor", "field": "queue"}

    with pytest.raises(ConfigError) as token_error:
        resolve_config(token="", cwd=tmp_path, environment={})
    assert token_error.value.details == {"source": "constructor", "field": "token"}
