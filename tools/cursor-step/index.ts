// One X-ray pipeline step run by a Cursor SDK agent (https://cursor.com/docs/sdk/typescript).
// stdin: an XRayReport JSON. stdout: {"summary", "evidence_ids", "model", "ms"}.
// Node >= 23.6 runs this file directly (type stripping); no build step.
import { Agent } from "@cursor/sdk";

// In the prompt, not systemPrompt: the docs say systemPrompt access is enabled per account.
const SYSTEM =
  "You summarise a property-listing X-ray for a buyer. Use only the findings given. " +
  "Write at most four plain-English sentences, most serious first. After each fact, cite the " +
  "evidence ids it rests on in square brackets, e.g. [ev-epc-1]. Never cite an id not in the input. " +
  'Reply with JSON only: {"summary": string, "evidence_ids": string[]}.';

async function main(): Promise<void> {
  const apiKey = process.env.CURSOR_API_KEY;
  if (!apiKey) throw new Error("CURSOR_API_KEY is not set");
  const report = JSON.parse(await new Response(process.stdin as any).text());
  const input = {
    trust_score: report.trust_score,
    counts: report.counts,
    findings: (report.findings ?? []).map((f: any) => ({
      field: f.field, verdict: f.verdict, severity: f.severity,
      reasoning: f.reasoning, evidence_ids: f.evidence_ids,
    })),
  };
  const model = process.env.CURSOR_MODEL || "composer-2.5";
  const start = Date.now();
  const agent = await Agent.create({
    apiKey,
    name: "xray-summary",
    model: { id: model },
    tools: [], // a pure text step: no file, shell or web tools
    local: { cwd: process.cwd() },
  });
  try {
    const run = await agent.send(`${SYSTEM}\n\nX-ray:\n${JSON.stringify(input)}`);
    const result = await run.wait();
    if (result.status !== "finished") throw new Error(`cursor run ${result.status}: ${result.error?.message}`);
    const text = (result.result ?? "").trim().replace(/^```(?:json)?\s*|\s*```$/g, "");
    const out = JSON.parse(text);
    process.stdout.write(JSON.stringify({ ...out, model, ms: Date.now() - start }));
  } finally {
    await (agent as any)[Symbol.asyncDispose]?.();
  }
}

main().catch((e) => {
  process.stderr.write(`cursor-step: ${e?.message ?? e}\n`);
  process.exit(1);
});
