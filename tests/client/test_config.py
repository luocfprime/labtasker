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
        "connection": "socket",
        "managed_local": True,
        "labtasker_root": str(tmp_path / ".labtasker"),
        "database": str(tmp_path / ".labtasker/server.db"),
        "socket": str(config.local.socket),
        "url": None,
        "queue": "default",
        "token_configured": False,
        "auto_start_local_server": False,
    }
    assert not (tmp_path / ".labtasker").exists()


def test_socket_mode_ignores_unrelated_valid_token(tmp_path: Path) -> None:
    config = resolve_config(token="secret", cwd=tmp_path, environment={})
    assert config.managed_local is True
    assert config.token is None
    assert config.public_dict()["token_configured"] is False


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


@pytest.mark.parametrize("token", ["秘密", " leading", "trailing ", "line\nbreak", "tab\tvalue"])
def test_token_must_be_safe_for_an_http_bearer_header(tmp_path: Path, token: str) -> None:
    with pytest.raises(ConfigError, match="visible ASCII") as raised:
        resolve_config(
            cwd=tmp_path,
            environment={"LABTASKER_URL": "http://server.test", "LABTASKER_TOKEN": token},
        )
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
        "http://💩.test",
        "http://\ud800/",
        "http://example.test/\ud800",
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


def test_endpoint_layers_are_atomic_and_shadow_lower_semantic_errors(tmp_path: Path) -> None:
    write_config(tmp_path, 'url = "not a URL"\n')
    explicit_socket = tmp_path / "external.sock"
    config = resolve_config(
        socket=explicit_socket,
        cwd=tmp_path,
        environment={
            "LABTASKER_URL": "also invalid",
            "LABTASKER_SOCKET": "/conflicting.sock",
        },
    )
    assert config.socket == explicit_socket.resolve()
    assert config.managed_local is False

    with pytest.raises(ConfigError, match="mutually exclusive"):
        resolve_config(
            cwd=tmp_path,
            environment={
                "LABTASKER_URL": "http://server.test",
                "LABTASKER_SOCKET": "/server.sock",
            },
        )


def test_root_precedence_is_independent_from_endpoint(tmp_path: Path) -> None:
    environment_root = tmp_path / "environment-root"
    explicit_root = tmp_path / "explicit-root"
    explicit_root.mkdir()
    (explicit_root / "config.toml").write_text('queue = "from-root"\n', encoding="utf-8")
    config = resolve_config(
        url="http://server.test",
        labtasker_root=explicit_root,
        cwd=tmp_path,
        environment={"LABTASKER_ROOT": str(environment_root)},
    )
    assert config.labtasker_root == explicit_root.resolve()
    assert config.queue == "from-root"
    assert config.url == "http://server.test"


def test_default_root_never_discovers_parent_config(tmp_path: Path) -> None:
    write_config(tmp_path, 'url = "http://wrong-parent.test"\n')
    child = tmp_path / "nested" / "experiment"
    child.mkdir(parents=True)

    config = resolve_config(cwd=child, environment={})

    assert config.managed_local is True
    assert config.labtasker_root == (child / ".labtasker").resolve()
    assert not (child / ".labtasker").exists()


def test_auto_start_authority_is_managed_local_only(tmp_path: Path) -> None:
    managed = resolve_config(
        auto_start_local_server=True,
        cwd=tmp_path,
        environment={},
    )
    assert managed.auto_start_local_server is True

    with pytest.raises(ConfigError) as raised:
        resolve_config(
            url="http://server.test",
            auto_start_local_server=True,
            cwd=tmp_path,
            environment={},
        )
    assert raised.value.details == {
        "source": "constructor",
        "field": "auto_start_local_server",
    }
