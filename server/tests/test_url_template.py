from app.ingestion.url_template import split_url, templatize_path


def test_numeric_segment():
    assert templatize_path("/order/92382/submit") == (
        "/order/{id}/submit",
        [{"name": "id_0", "value": "92382"}],
    )


def test_uuid_segment():
    tpl, params = templatize_path("/api/3f2b8c4e-1a2b-4c3d-9e8f-0a1b2c3d4e5f/detail")
    assert tpl == "/api/{id}/detail"
    assert params[0]["value"] == "3f2b8c4e-1a2b-4c3d-9e8f-0a1b2c3d4e5f"


def test_no_dynamic_segment():
    assert templatize_path("/codeBack/role/list") == ("/codeBack/role/list", [])


def test_multiple_numeric_segments():
    tpl, params = templatize_path("/a/1/b/22")
    assert tpl == "/a/{id}/b/{id}"
    assert [p["name"] for p in params] == ["id_0", "id_1"]
    assert [p["value"] for p in params] == ["1", "22"]


def test_split_url_relative_and_absolute():
    assert split_url("/x/y?code=cesh") == ("/x/y", "code=cesh")
    assert split_url("http://h:8080/x/1/y?q=2") == ("/x/1/y", "q=2")
    assert split_url("/x/y") == ("/x/y", "")
