// Temporary backport for https://github.com/paperclipai/paperclip/issues/9901.
// Remove this overlay when the pinned upstream image includes the fix.
import { createHash } from "node:crypto";
import { chmodSync, readFileSync, renameSync, writeFileSync } from "node:fs";

const [sourcePath, outputPath] = process.argv.slice(2);
if (!sourcePath || !outputPath || process.argv.length !== 4) {
  throw new Error("Usage: patch-hermes-gateway.mjs SOURCE OUTPUT");
}

const source = readFileSync(sourcePath, "utf8");
const expectedHash = "f21b1a4b1b805ed027023a36f58ec40dc2c10506d3e7fdd1d4c2aaf46171d752";
if (createHash("sha256").update(source).digest("hex") !== expectedHash) {
  throw new Error("Hermes adapter source changed; revalidate or remove the temporary streaming patch before updating Paperclip");
}

const before = [
  '  await ctx.onLog(',
  '    "stdout",',
  '    `[hermes-gateway:event] run=${state.runId} event=${eventName ?? "message"} data=${stringifyForLog(redactForLog(parsed, [], 0, redactText), 8_000)}\\n`,',
  '  );',
  '',
  '  const delta = nonEmpty(record?.delta) ?? nonEmpty(record?.text_delta);',
  '  if (eventName === "message.delta" && delta) {',
  '    const sanitizedDelta = redactText(delta);',
  '    state.outputChunks.push(sanitizedDelta);',
  '    await ctx.onLog("stdout", sanitizedDelta);',
  '  }',
].join("\n");

const after = [
  '  const delta = typeof record?.delta === "string"',
  '    ? record.delta',
  '    : typeof record?.text_delta === "string" ? record.text_delta : null;',
  '  const sanitizedDelta = eventName === "message.delta" && delta !== null ? redactText(delta) : null;',
  '  // One complete JSON event per delta, including whitespace and long fragments.',
  '  const logData = sanitizedDelta !== null',
  '    ? JSON.stringify({ delta: sanitizedDelta })',
  '    : stringifyForLog(redactForLog(parsed, [], 0, redactText), 8_000);',
  '  await ctx.onLog(',
  '    "stdout",',
  '    `[hermes-gateway:event] run=${state.runId} event=${eventName ?? "message"} data=${logData}\\n`,',
  '  );',
  '',
  '  if (sanitizedDelta !== null) {',
  '    state.outputChunks.push(sanitizedDelta);',
  '  }',
].join("\n");

if (source.split(before).length !== 2) {
  throw new Error("Expected exactly one Hermes streaming block; refusing to patch");
}
// Write only after both guards pass. The init container can safely run again.
const temporaryPath = `${outputPath}.tmp`;
writeFileSync(temporaryPath, source.replace(before, after), { mode: 0o644 });
renameSync(temporaryPath, outputPath);
chmodSync(outputPath, 0o444);
console.log("Applied the pinned Hermes gateway streaming backport");
