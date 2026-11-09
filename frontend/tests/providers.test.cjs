const test = require("node:test");
const assert = require("node:assert/strict");
const {
  providerId,
  normalizedEndpoint,
  providerErrorMessage,
} = require("../../tmp/reader-tests/providers.js");

test("provider selection distinguishes official hosts from lookalikes", () => {
  assert.equal(
    providerId(
      "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    ),
    "qwen",
  );
  assert.equal(
    providerId("https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "qwen",
  );
  assert.equal(providerId("https://api.deepseek.com"), "deepseek");
  assert.equal(providerId("https://api.deepl.com"), "deepl");
  assert.equal(providerId("https://api-free.deepl.com/v2/translate"), "deepl");
  assert.equal(providerId("https://api.deepl.com.evil.example"), "custom");
  assert.equal(providerId("https://api.deepseek.com.evil.example"), "custom");
  assert.equal(
    providerId("https://workspace.cn-beijing.maas.aliyuncs.com.evil.example"),
    "custom",
  );
  assert.equal(providerId("unfinished URL"), "custom");
});

test("official OpenAI and Claude endpoints retain saved-key matching", () => {
  for (const host of ["api.openai.com", "api.anthropic.com"]) {
    for (const suffix of [
      "",
      "/",
      "/v1/",
      "/chat/completions/",
      "/v1/chat/completions/",
    ]) {
      assert.equal(
        normalizedEndpoint(`https://${host}${suffix}`),
        `https://${host}/v1`,
      );
    }
    assert.equal(providerId(`https://${host}/v1`), "custom");
  }
  for (const url of [
    "https://api.openai.com.attacker.example",
    "https://api.openai.com:8443",
    "https://api.openai.com/v1/responses",
    "https://api.anthropic.com/v1/messages",
    "https://api.openai.com?test=1",
  ])
    assert.equal(normalizedEndpoint(url), url);
});

test("provider diagnostics translate the UI wrapper while preserving server detail", () => {
  const en = require("../src/en.json");
  const message =
    "模型拒绝请求（HTTP 400），请检查模型设置：Invalid model: example";
  const error = providerErrorMessage(message);
  assert.ok(error);
  const result = en[error.key].replace(
    /\{(\w+)\}/g,
    (_, name) => error.values[name],
  );
  assert.equal(
    result,
    "The provider rejected the request (HTTP 400); check your model settings: Invalid model: example",
  );
  const plain = providerErrorMessage(
    "模型拒绝请求（HTTP 422），请检查模型设置",
  );
  assert.equal(plain.values.detail, "");
  const address = providerErrorMessage(
    "请使用官方 Chat Completions 兼容地址：https://api.anthropic.com/v1",
  );
  assert.ok(en[address.key]);
  assert.equal(address.values.url, "https://api.anthropic.com/v1");
  assert.equal(providerErrorMessage("Other failure"), undefined);
});

test("saved key status matches backend endpoint normalization", () => {
  assert.equal(
    normalizedEndpoint(" https://api.deepl.com/v2/translate/ "),
    "https://api.deepl.com",
  );
  assert.notEqual(
    normalizedEndpoint("https://api.deepl.com"),
    normalizedEndpoint("https://api-free.deepl.com"),
  );
  assert.equal(
    normalizedEndpoint(" https://api.deepseek.com/v1/chat/completions/ "),
    "https://api.deepseek.com/v1",
  );
  assert.notEqual(
    normalizedEndpoint("https://api.example/v1"),
    normalizedEndpoint("https://api.example/another"),
  );
});
