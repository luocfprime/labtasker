from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from labtasker_server.name_search import name_matches_fuzzy


@pytest.mark.parametrize(
    ("name", "query", "expected"),
    [
        ("train_model_eval", "  tr ev  ", True),
        ("train_model_eval", "EV\tTR", True),
        ("train_model_eval", "tml", True),
        ("train_model_eval", "rt", False),
        ("train_model_eval", "tr missing", False),
        ("a", "aa", False),
        ("a", "a a", True),
        ("Straße_训练模型", "STRASSE 训型", True),
        ("train_model_eval", "^tr", False),
        ("a%_!^$'|b", "%_!^$'|", True),
        (None, "tr", False),
        ("", "tr", False),
        (None, " \t\n ", True),
        ("", "", True),
    ],
)
def test_literal_subsequence_matching(name: str | None, query: str, expected: bool) -> None:
    assert name_matches_fuzzy(name, query) is expected


def test_fuzzy_http_selection_pagination_count_and_exact(client: TestClient) -> None:
    path = "/api/v2/queues/default/tasks"
    names = ["train_model_eval", "other", "TRAIN_model_EVAL", None, "", "ev_train"]
    for index, name in enumerate(names):
        assert client.put(f"{path}/t_{index:012d}", json={"name": name}).status_code == 201
    assert client.put("/api/v2/queues/other").status_code == 201
    assert (
        client.put("/api/v2/queues/other/tasks/t_999999999999", json={"name": names[0]}).status_code
        == 201
    )
    params = {"name_fuzzy": " ev TR ", "order_by": "id", "descending": "false", "limit": 1}
    first = client.get(path, params=params)
    assert first.status_code == 200
    page = first.json()
    assert [task["name"] for task in page["items"]] == [names[0]]
    cursor = page["next_cursor"]
    rest = client.get(path, params={**params, "cursor": cursor, "limit": 10}).json()
    assert [task["name"] for task in rest["items"]] == [names[2], names[5]]
    assert rest["next_cursor"] is None
    assert client.get(path + "/count", params={"name_fuzzy": " ev TR "}).json() == {"count": 3}
    for selectors, expected in [
        ({"name": names[0], "name_fuzzy": "tr ev"}, 1),
        ({"name": names[0], "name_fuzzy": "missing"}, 0),
        ({"name_fuzzy": "tr ev", "filter": 'name == "TRAIN_model_EVAL"'}, 1),
        ({"name_fuzzy": "tr ev", "status": "failed"}, 0),
        ({"name_fuzzy": " \t "}, 6),
        ({"name": ""}, 1),
    ]:
        assert client.get(path + "/count", params=selectors).json() == {"count": expected}
        assert len(client.get(path, params=selectors).json()["items"]) == expected
    for changed in [{"name_fuzzy": "other"}, {"name_fuzzy": None}]:
        response = client.get(path, params={**params, **changed, "cursor": cursor})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "invalid_cursor"
    schema = client.get("/openapi.json").json()
    for endpoint in [
        path.replace("default", "{queue}"),
        path.replace("default", "{queue}") + "/count",
    ]:
        parameters = schema["paths"][endpoint]["get"]["parameters"]
        assert any(p["name"] == "name_fuzzy" and p["in"] == "query" for p in parameters)
