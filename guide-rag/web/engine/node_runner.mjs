// Runs the JS port under node for the cross-check (tests/test_crosscheck.py): reads index/*.json
// and web/data/dictionary.json from the repository, answers the questions of a JSON file
// ([{question, page}] or a list of strings) and prints one JSON array of GenerationResults.
//
//   node web/engine/node_runner.mjs <questions.json> [repo root]

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { ask, load_dictionary, load_tables } from "./cli.js";

const here = dirname(fileURLToPath(import.meta.url));
const questionsPath = process.argv[2];
const root = resolve(process.argv[3] || join(here, "..", ".."));
if (!questionsPath) {
  process.stderr.write("usage: node web/engine/node_runner.mjs <questions.json> [repo root]\n");
  process.exit(2);
}

const readJson = (p) => JSON.parse(readFileSync(p, "utf8"));
const index = {};
for (const name of ["page_df", "line_df", "toc_df", "row_df", "cross_ref_df", "corpus_index", "coverage"]) {
  index[name] = readJson(join(root, "index", `${name}.json`));
}
const tables = load_tables(index);
const assets = load_dictionary(readJson(join(root, "web", "data", "dictionary.json")));

const questions = readJson(resolve(questionsPath)).map((q) => (typeof q === "string" ? { question: q, page: null } : q));
const out = [];
for (const q of questions) {
  const t0 = performance.now();
  const { result, plan } = await ask(q.question, { tables, assets, page: q.page ?? null });
  out.push({ question: q.question, page: q.page ?? null, elapsed_ms: Math.round(performance.now() - t0), result, plan_full: plan });
}
process.stdout.write(JSON.stringify(out) + "\n");
