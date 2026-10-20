// Run inside the chart's pinned Paperclip image; only synthetic in-process I/O.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const chart = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const patch = join(chart, "files/patch-hermes-gateway.mjs");
const source = "/app/packages/adapters/hermes/src/gateway/server/execute.ts";
const fixture = join(dirname(source), `execute.streaming-fixture-${process.pid}.ts`);
const temporary = mkdtempSync(join(tmpdir(), "paperclip-stream-"));
const originalFetch = globalThis.fetch;

function patchFile(input, output) {
  return spawnSync(process.execPath, [patch, input, output], { encoding: "utf8" });
}

try {
  // Check the image's production package actually resolves to the overlaid source.
  const requireFromServer = createRequire("/app/server/package.json");
  assert.equal(requireFromServer.resolve("@paperclipai/hermes-paperclip-adapter/gateway/server"),
    "/app/packages/adapters/hermes/src/gateway/server/index.ts");
  assert.match(readFileSync(join(dirname(source), "index.ts"), "utf8"), /from "\.\/execute\.js"/);

  const changedSource = join(temporary, "changed.ts");
  const refusedOutput = join(temporary, "refused.ts");
  writeFileSync(changedSource, readFileSync(source, "utf8") + "\n// unexpected upstream change\n");
  writeFileSync(refusedOutput, "existing output must survive a failed guard");
  const refused = patchFile(changedSource, refusedOutput);
  assert.notEqual(refused.status, 0);
  assert.match(refused.stderr, /source changed/);
  assert.equal(readFileSync(refusedOutput, "utf8"), "existing output must survive a failed guard");

  for (let attempt = 0; attempt < 2; attempt++) {
    const prepared = patchFile(source, fixture);
    assert.equal(prepared.status, 0, prepared.stderr);
  }
  assert.notEqual(patchFile(fixture, join(temporary, "double.ts")).status, 0);
  console.log("PASS: production adapter resolution, hash guard, output preservation, repeat init and double-patch refusal");

  const { execute } = await import(pathToFileURL(fixture));
  const { parseHermesGatewayStdoutLine } = await import("/app/packages/adapters/hermes/src/gateway/ui/parse-stdout.ts");
  const { buildTranscript } = await import("/app/ui/src/adapters/transcript.ts");

  async function runCase(name, deltas, { fallback = false, alternate = false, failed = false } = {}) {
    const expected = deltas.join("");
    const terminal = failed
      ? { status: "failed", error: "synthetic gateway failure" }
      : { status: "completed", ...(fallback ? {} : { output: expected }) };
    const frames = deltas.map(delta => ({
      event: "message.delta", data: alternate ? { text_delta: delta } : { delta },
    }));
    frames.push({ event: `run.${terminal.status}`, data: terminal });
    const bytes = new TextEncoder().encode(frames.map(f =>
      `event: ${f.event}\ndata: ${JSON.stringify(f.data)}\n\n`).join(""));
    const logs = [];
    globalThis.fetch = async url => {
      if (String(url).endsWith("/v1/runs")) {
        return new Response(JSON.stringify({ run_id: "fixture-remote-run", status: "started" }));
      }
      if (String(url).endsWith("/events")) {
        // Split frames and UTF-8 code points across arbitrary network boundaries.
        const stream = new ReadableStream({ start(controller) {
          for (let offset = 0; offset < bytes.length; offset += 37) {
            controller.enqueue(bytes.slice(offset, offset + 37));
          }
          controller.close();
        } });
        return new Response(stream, { headers: { "content-type": "text/event-stream" } });
      }
      return new Response(JSON.stringify(terminal));
    };
    const config = { apiBaseUrl: "http://127.0.0.1:8642", apiKey: "fixture-gateway-credential", timeoutSec: 5 };
    const result = await execute({
      runId: "fixture-run", agent: {
        id: "fixture-agent", companyId: "fixture-company", name: "Ashely",
        adapterType: "hermes_gateway", adapterConfig: config,
      },
      runtime: { sessionId: null, sessionParams: null, sessionDisplayId: null, taskKey: null },
      config, context: { issueId: "fixture-issue", wakeReason: "manual" },
      onLog: async (stream, chunk) => logs.push({ stream, chunk, ts: "2026-10-20T00:00:00Z" }),
      onMeta: async () => {},
    });
    const events = logs.filter(l => l.chunk.startsWith("[hermes-gateway:event]") && l.chunk.includes("event=message.delta "));
    assert.equal(events.length, deltas.length, name);
    assert.equal(logs.filter(l => l.stream === "stdout" && l.chunk.trim()
      && !l.chunk.startsWith("[hermes-gateway")).length, 0, "duplicate raw stdout");
    for (const event of events) JSON.parse(event.chunk.split(" data=")[1]);
    const transcript = buildTranscript(logs, parseHermesGatewayStdoutLine);
    const text = transcript.filter(e => e.kind === "assistant").map(e => e.text).join("");
    if (failed) {
      assert.equal(result.exitCode, 1);
      assert.ok(transcript.some(e => e.kind === "stderr" && e.text === terminal.error));
    } else {
      assert.equal(result.exitCode, 0);
      const redacted = expected.replaceAll(config.apiKey, "");
      if (expected === redacted) {
        assert.equal(text, expected, `${name}: live text`);
        assert.equal(result.summary, expected.slice(0, 2000), `${name}: final text`);
      } else {
        assert.ok(!JSON.stringify(logs).includes(config.apiKey), "secret leaked to event logs");
        assert.ok(!text.includes(config.apiKey), "secret leaked to transcript");
        assert.ok(!result.summary.includes(config.apiKey), "secret leaked to result");
      }
    }
    console.log(`PASS: ${name}`);
  }

  await runCase("word fragments, whitespace-only deltas, newlines and Unicode", ["I", " ", "have", " the", "\n", "full\t", "answer. 😀"]);
  await runCase("fallback result preserves spaces without terminal output", ["One", " ", "two", "\n\n", "three"], { fallback: true });
  await runCase("complete long JSON frames without preview truncation", ["A".repeat(9000), "\nEnd"]);
  await runCase("text_delta compatibility", ["Hello", " ", "world"], { alternate: true, fallback: true });
  await runCase("secret redaction retained", ["credential=", "fixture-gateway-credential", " done"], { fallback: true });
  await runCase("failed runs remain failures", [], { failed: true });
} finally {
  globalThis.fetch = originalFetch;
  rmSync(fixture, { force: true });
  rmSync(temporary, { recursive: true, force: true });
}
