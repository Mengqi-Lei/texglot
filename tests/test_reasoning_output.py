"""Response envelopes must not leak or remove authored text."""

import json
from contextlib import asynccontextmanager

import httpx
import pytest

from app.config import Settings
from app.i18n import english
from app.latex import MARKER, segments
from app.llm import INCOMPLETE_RESPONSE, Translator, strip_reasoning
from app.translation import normalize_cached_translation


@asynccontextmanager
async def response_client(handler, settings=None):
    client = Translator(settings or Settings(context_guidance=False))
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        yield client
    finally:
        await client.close()


def answer(content, **message_fields):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"content": content, **message_fields},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 11},
        },
    )


@pytest.mark.parametrize(
    "tag", ["think", "thinking", "reasoning", "thought", "scratchpad"]
)
def test_leading_reasoning_blocks_are_removed(tag):
    assert strip_reasoning(f"<{tag}>test reasoning</{tag}>最终译文。") == "最终译文。"


@pytest.mark.parametrize(
    "text",
    [
        "  <THINK>test</THINK>\n<answer>最终译文。</answer>  ",
        '<think stage="a>b">test</think>最终译文。',
        "<think>outer<think>inner</think>outer</think>最终译文。",
        "<think>Mention an <answer> tag here.</think>最终译文。",
        "<think>test</think><reasoning>test</reasoning>最终译文。",
        "<answer><answer>最终译文。</answer></answer>",
        "<answer>最终译文。</answer>",
        "最终译文。",
    ],
)
def test_nested_and_multiple_response_envelopes(text):
    assert strip_reasoning(text) == "最终译文。"
    assert strip_reasoning(strip_reasoning(text)) == "最终译文。"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "<think>unfinished",
        "<think>only reasoning</think>",
        "<think",
        "</think>译文。",
        "部分译文。<think>unfinished",
        "部分译文。<think>test</think>另一部分。",
        "<answer>unfinished",
        "<answer>译文。</answer>additional text",
        "<think>outer<think>inner</think>missing close",
    ],
)
def test_incomplete_or_ambiguous_answers_are_rejected(text):
    with pytest.raises(ValueError):
        strip_reasoning(text)


def test_response_nesting_is_bounded():
    assert strip_reasoning("<answer>" * 8 + "译文。" + "</answer>" * 8) == "译文。"
    with pytest.raises(ValueError, match="标记不完整"):
        strip_reasoning("<answer>" * 9 + "译文。" + "</answer>" * 9)


@pytest.mark.parametrize(
    "text",
    [
        "正文使用 <think>推理内容</think> 标签作为示例。",
        "<think>这本身就是论文内容。</think>",
        "原文讨论不闭合标签 <think>",
        "<answer>原文使用的标签。</answer>",
        '原文使用 <think data="value">文字</think>。',
    ],
)
def test_authored_tags_are_preserved(text):
    assert strip_reasoning(text, source_text=text) == text


def test_unknown_tags_are_not_treated_as_response_metadata():
    text = "正文 <thinking-model>文字</thinking-model>。"
    assert strip_reasoning(text) == text


@pytest.mark.parametrize("text", [" word ", "\nword ", " next", "last "])
def test_slot_boundary_whitespace_is_preserved(text):
    assert strip_reasoning(text) == text
    assert strip_reasoning("<think>test</think>" + text) == text
    assert strip_reasoning("<answer>" + text + "</answer>") == text


def test_outer_json_envelopes_do_not_modify_string_values():
    text = json.dumps({"0": "正文 <think>需保留</think>。"}, ensure_ascii=False)
    assert strip_reasoning(text, json_output=True) == text
    # Literal tags in slots do not authorize non-JSON tags outside the object.
    assert (
        strip_reasoning(
            "<think>test</think><answer>" + text + "</answer>",
            source_text="The tag <think>text</think>.",
            json_output=True,
        )
        == text
    )


async def test_complete_ignores_separate_reasoning_fields_and_counts_usage():
    async with response_client(
        lambda _: answer("最终译文。", reasoning_content="TEST_REASONING")
    ) as client:
        output = await client.complete([{"role": "user", "content": "test"}])
        assert output == "最终译文。"
        assert client.tokens == 11 and client.requests == 1


async def test_plain_translation_uses_source_to_protect_literal_tags():
    item = segments("The tag <think>reasoning</think> is part of this paper.")[0]
    translated = "标签 <think>推理</think> 是本文的一部分。"
    async with response_client(lambda _: answer(translated)) as client:
        output = await client.translate(item)
    assert output == translated
    assert "<think>" in item.restore(output)


async def test_protected_code_and_math_survive_leading_reasoning():
    item = segments(r"The code \texttt{<think>} uses $x+1$ in our method.")[0]

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        output = "译文内容。" + "".join(MARKER.findall(payload["paragraph"]))
        return answer("<think>TEST_REASONING</think>" + output)

    async with response_client(handler) as client:
        output = await client.translate(item)
    restored = item.restore(output)
    assert r"\texttt{<think>}" in restored and "$x+1$" in restored
    assert "TEST_REASONING" not in restored


async def test_slot_repair_preserves_authored_tags_inside_json():
    item = segments("The tag <think>reasoning</think> is part of this paper.")[0]

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        values = {key: "标签 <think>推理</think> 是正文。" for key in payload["slots"]}
        return answer(
            "<think>TEST_REASONING</think>" + json.dumps(values, ensure_ascii=False)
        )

    async with response_client(handler) as client:
        output = await client.translate_slots(item)
    assert "<think>推理</think>" in output
    assert "TEST_REASONING" not in output


async def test_slot_value_envelopes_and_invalid_slot_retry_are_isolated():
    item = segments("The model $x$ works.")[0]
    requested_keys = []

    def handler(request):
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])
        requested_keys.append(set(payload["slots"]))
        values = {
            key: "<think>test</think><answer>译文内容。</answer>"
            for key in payload["slots"]
        }
        if len(requested_keys) == 1:
            values["0"] = "<think>unfinished"
        return answer(json.dumps(values, ensure_ascii=False))

    async with response_client(handler) as client:
        output = await client.translate_slots(item)
    assert requested_keys == [{"0", "1"}, {"0"}]
    assert "<think>" not in output and "<answer>" not in output
    assert "$x$" in item.restore(output)


@pytest.mark.parametrize("body", ["<think>unfinished", "<think>only reasoning</think>"])
async def test_invalid_complete_is_a_repairable_value_error(body):
    async with response_client(lambda _: answer(body)) as client:
        with pytest.raises(ValueError):
            await client.complete([{"role": "user", "content": "test"}])


def test_old_cache_is_normalized_before_restoring():
    settings = Settings(target_language="简体中文", context_guidance=False)
    item = segments("The scientific result is correct and useful.")[0]
    value = normalize_cached_translation(
        "<think>TEST_REASONING</think><answer>科學結果正確且有用。</answer>",
        item,
        settings,
    )
    assert item.restore(value) == "科学结果正确且有用。"


def test_cached_authored_tags_and_deepl_are_preserved():
    settings = Settings(target_language="English")
    item = segments("<think>This is quoted paper content.</think>")[0]
    assert normalize_cached_translation(item.masked, item, settings) == item.masked
    deepl = Settings(
        base_url="https://api-free.deepl.com/v2", target_language="English"
    )
    plain = segments("Paper text.")[0]
    text = "<think>Literal translated content.</think>"
    assert normalize_cached_translation(text, plain, deepl) == text


def test_unfinished_cached_output_must_be_retranslated():
    item = segments("Paper text.")[0]
    with pytest.raises(ValueError, match=INCOMPLETE_RESPONSE):
        normalize_cached_translation(
            "<think>unfinished", item, Settings(target_language="English")
        )


@pytest.mark.parametrize(
    "message", [INCOMPLETE_RESPONSE, "结构修复片段 2 未返回完整译文"]
)
def test_response_validation_errors_have_english_messages(message):
    assert not any("\u4e00" <= char <= "\u9fff" for char in english(message))
