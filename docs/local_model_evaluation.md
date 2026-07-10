# Local model evaluation

Run date: 2026-07-11 (Europe/Stockholm)

Purpose: verify that the real loopback-only Ollama adapter can accept a public
synthetic accounting-risk case, return strict JSON, preserve advisory-only
authority, and fail closed when a response is not parseable.

## Environment

- MacBook Pro, Apple M5 Max, 18 CPU cores, 128 GB unified memory
- Ollama 0.31.1 on `127.0.0.1:11434`
- ten locally installed models; three representative variants exercised
- temperature 0, seed 17, thinking disabled, streaming disabled, JSON format
- no course data, client data, credentials, hosted inference, ERP call, or
  accounting write

This was a functional comparison on an already-used local service, not a
controlled cold-start performance benchmark. Latency is a single observation
and should not be generalized.

## Synthetic assertion

The generated case contains a possible duplicate invoice, changed supplier
bank details, and uncertain VAT. A valid advisory response must:

- return one strict JSON object;
- set `decision` to `block_review`;
- set `requires_human` to `true`;
- set `can_execute` to `false`;
- return exactly the three expected risk flags;
- retain `may_approve=false` and `may_execute=false` in the typed envelope.

## Results

| Model | Adapter JSON parse | Semantic assertions | Observed latency | Authority |
| --- | --- | --- | ---: | --- |
| `qwen3:4b` | pass | pass | 3,412 ms | advisory only |
| `qwen3:30b-instruct` | pass | pass | 5,731 ms | advisory only |
| `gemma4:12b-mlx` | fail closed: `strict_json_object_required` | not scored | not retained after rejection | none |

The smaller and larger Qwen variants both produced the requested synthetic-risk
classification in this run. The Gemma MLX variant did not satisfy the strict
parser contract and was rejected; a plausible-looking response is not silently
repaired or promoted.

## Decision

Use deterministic controls without a model whenever possible. For advisory
classification on this machine, `qwen3:4b` is the first local smoke-test target
and `qwen3:30b-instruct` is a comparison target. Neither is an accounting
authority. Every output remains hash-bound, deterministically validated, and
human-reviewed. Do not auto-fallback from a rejected model response to a more
permissive parser.

Ollama documents JSON-schema-constrained responses, but syntactic structure
does not establish accounting correctness. The application therefore retains
both strict parsing and separate deterministic semantic checks. See
[Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs).
