"""预拉放行水位（runner.write_response_count）纯函数单测。

三轮评审 🔴 根因：水位曾以 observed **总条数**比较，页面加载/轮询的 GET
响应即抬高水位，写按钮真被前端校验拦下（零写请求）也被"预拉放行"成 pass。
水位只认写方法响应。
"""
from app.replay.runner import WRITE_METHODS, write_response_count


def _resp(method: str, url: str = "http://mock.local/x") -> dict:
    return {"url": url, "status": 200, "method": method, "body": ""}


def test_empty_stream_is_zero():
    assert write_response_count([]) == 0


def test_get_noise_never_counts():
    assert write_response_count([_resp("GET")] * 50) == 0


def test_write_methods_counted():
    assert WRITE_METHODS == ("POST", "PUT", "PATCH")
    stream = [_resp("GET"), _resp("POST"), _resp("GET"),
              _resp("PUT"), _resp("PATCH"), _resp("DELETE"), _resp("GET")]
    assert write_response_count(stream) == 3


def test_missing_method_key_tolerated():
    assert write_response_count([{"url": "http://mock.local/x", "status": 200}]) == 0
