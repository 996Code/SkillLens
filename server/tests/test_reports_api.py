"""Task 4（S9 块C）：GET /api/v1/reports/{id} 只读端点——delta_report 行的四分类数据。

报告数据只由 POST /expected-deltas/{id}/report 写入，此前无任何读取端点；
工作台报告页（C2）需要它。先红后绿。
"""
from app.db import SessionLocal
from app.models import DeltaReport


def _add_report(expected_delta_id: int = 1, observed_delta_id: int = 1) -> int:
    db = SessionLocal()
    try:
        row = DeltaReport(
            expected_delta_id=expected_delta_id, observed_delta_id=observed_delta_id,
            expected=[{"type": "api_status", "value": "/api/save: 200"}],
            missing=[{"type": "ui_action", "value": "点击[提交]"}],
            unexpected=[{"type": "api_call", "value": "DELETE /api/items/9"}],
            drift=[{"type": "api_status", "value": "/api/save: 200 -> 500"}],
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


async def test_report_full_fields(client):
    report_id = _add_report(expected_delta_id=7, observed_delta_id=8)

    resp = await client.get(f"/api/v1/reports/{report_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"id", "expected_delta_id", "observed_delta_id",
                         "expected", "missing", "unexpected", "drift", "created_at"}
    assert body["id"] == report_id
    assert body["expected_delta_id"] == 7
    assert body["observed_delta_id"] == 8
    assert body["expected"] == [{"type": "api_status", "value": "/api/save: 200"}]
    assert body["missing"] == [{"type": "ui_action", "value": "点击[提交]"}]
    assert body["unexpected"] == [{"type": "api_call", "value": "DELETE /api/items/9"}]
    assert body["drift"] == [{"type": "api_status", "value": "/api/save: 200 -> 500"}]
    assert body["created_at"]  # 非空时间戳


async def test_report_404(client):
    assert (await client.get("/api/v1/reports/99999")).status_code == 404
