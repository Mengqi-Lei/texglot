"""Native checks for model reasoning that must never reach the paper."""

import json

import httpx

from app.config import Settings
from app.latex import segments
from app.llm import Translator, strip_reasoning
from app.translation import cached_translation


def test_reasoning_block_is_removed_from_the_answer():
    assert (
        strip_reasoning("<think>We need Chinese.\nReason more.</think>译文内容。")
        == "译文内容。"
    )
    assert strip_reasoning("<reasoning>hidden</reasoning>译文内容。") == "译文内容。"
    assert strip_reasoning("<answer>译文内容。</answer>") == "译文内容。"
    assert strip_reasoning("译文内容。") == "译文内容。"
    # An unterminated block means the model never reached its answer.
    assert strip_reasoning("<think>still reasoning") == ""
    assert strip_reasoning("译文内容。<think>trailing") == "译文内容。"


async def test_model_reasoning_never_reaches_the_translation():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>\nWe must translate this paragraph.\n"
                                "Keep every token.\n</think>大型语言模型表现出色。"
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    translator = Translator(Settings(context_guidance=False))
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        output = await translator.complete([{"role": "user", "content": "test"}])
        assert output == "大型语言模型表现出色。"
        assert "think" not in output and "translate" not in output
    finally:
        await translator.close()


async def test_slot_repair_accepts_a_leading_reasoning_block():
    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        result = {key: "译文内容。" for key in payload["slots"]}
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "<think>The slots are numbered.</think>"
                                + json.dumps(result, ensure_ascii=False)
                            )
                        },
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    translator = Translator(Settings(context_guidance=False))
    await translator.client.aclose()
    translator.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        item = segments("The model works.")[0]
        output = await translator.translate_slots(item)
        assert "译文内容。" in output
        assert "think" not in output
    finally:
        await translator.close()


def test_cached_translation_drops_a_stored_reasoning_block():
    settings = Settings(target_language="简体中文", context_guidance=False)
    item = segments("The result is correct.")[0]
    restored = cached_translation(
        "<think>The paragraph is short.</think>结果是正确的。", item, settings
    )
    assert restored == "结果是正确的。"
    assert "think" not in restored
