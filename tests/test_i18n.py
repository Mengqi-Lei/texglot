import copy

import httpx

from app.i18n import localize_payload


def test_localization_preserves_user_content_and_saved_messages():
    original = {
        "name": "翻译完成",
        "language": "简体中文",
        "message": "正在翻译 · 2 / 10 段落",
        "logs": [{"message": "PDF 已生成 · 14 页 · 1,234 tokens"}],
        "warnings": ["有一段译文未通过结构检查，保留原文：排版结构标记被重排"],
        "config": {"glossary": "注意力"},
    }
    saved = copy.deepcopy(original)
    en = localize_payload(original)
    assert en["message"] == "Translating · 2 / 10 paragraphs"
    assert en["logs"][0]["message"] == "PDF ready · 14 pages · 1,234 tokens"
    assert "Layout structure" in en["warnings"][0]
    assert en["name"] == original["name"]
    assert en["config"] == original["config"]
    assert en["language"] == "简体中文"
    assert original == saved


async def test_api_defaults_to_chinese_and_localizes_english_errors():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        zh = await client.get("/api/jobs/missing")
        en = await client.get(
            "/api/jobs/missing", headers={"Accept-Language": "en-US,en;q=0.9"}
        )
        assert zh.json()["detail"] == "任务不存在"
        assert en.json()["detail"] == "Task not found"
        assert en.status_code == 404
        assert en.headers["vary"] == "Accept-Language"
        invalid = await client.post(
            "/api/jobs/arxiv", json={"url": "bad"}, headers={"Accept-Language": "en"}
        )
        assert invalid.status_code == 400
        assert "Invalid arXiv" in invalid.json()["detail"]
        blocked = await client.put(
            "/api/settings",
            json={},
            headers={"Accept-Language": "en", "Origin": "https://evil.test"},
        )
        assert blocked.status_code == 403
        assert (
            blocked.json()["detail"] == "Only same-origin local requests are accepted"
        )
