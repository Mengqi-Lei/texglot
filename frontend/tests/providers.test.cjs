const test = require("node:test");
const assert = require("node:assert/strict");
const {
  providerId,
  normalizedEndpoint,
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
  assert.equal(providerId("https://api.deepseek.com.evil.example"), "custom");
  assert.equal(
    providerId("https://workspace.cn-beijing.maas.aliyuncs.com.evil.example"),
    "custom",
  );
  assert.equal(providerId("unfinished URL"), "custom");
});

test("saved key status matches backend endpoint normalization", () => {
  assert.equal(
    normalizedEndpoint(" https://api.deepseek.com/v1/chat/completions/ "),
    "https://api.deepseek.com/v1",
  );
  assert.notEqual(
    normalizedEndpoint("https://api.example/v1"),
    normalizedEndpoint("https://api.example/another"),
  );
});
