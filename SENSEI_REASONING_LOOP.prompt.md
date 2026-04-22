# Sensei Reasoning Loop — Source Prompt

**What this is:** the exact prompt Elijah used to generate the Sensei Reasoning Loop design. The output (spec + implementation) lives in `SENSEI_REASONING_LOOP.md` + `sensei_reasoning_loop.py`. This file preserves the original request so the pipeline can be re-generated or updated later against the same brief.

**Saved:** 2026-04-19

---

You are an expert AI systems architect and software engineer.

Design a local AI reasoning system inspired by Claude-style multi-step cognition, intended to run on lightweight local LLMs (7B–14B class models such as Qwen, Llama, or similar via Ollama).

The system is called "Sensei Reasoning Loop".

## Goal
Create a structured pipeline that improves reasoning quality of small-to-medium LLMs by forcing multi-pass thinking instead of single-pass responses.

The system must decompose reasoning into four sequential stages:

1. PLANNER STAGE
- Break the user's request into structured steps
- Identify assumptions, constraints, and required sub-tasks
- DO NOT solve the problem

2. SOLVER STAGE
- Execute each step from the planner
- Show intermediate reasoning clearly
- Produce a complete raw solution

3. CRITIC / REVIEW STAGE
- Evaluate the solver output
- Identify logical errors, missing cases, weak reasoning, or contradictions
- Suggest corrections or improvements

4. FINALIZER STAGE
- Produce a clean, user-facing final answer
- Remove internal reasoning artifacts
- Optimize clarity and correctness

## Requirements
- The system must work with local LLM APIs (Ollama-style or REST inference)
- Must support reuse of the SAME model across all stages OR allow model swapping per stage
- Must define how data flows between stages (structured JSON or markdown blocks)
- Must include prompt templates for each stage
- Must support optional memory persistence between stages
- Must be optimized for low latency (7B models preferred)
- Must NOT require cloud services

## Output format

You must return TWO sections:

### 1. MARKDOWN DESIGN SPEC
- Explain architecture clearly
- Include pipeline diagram in text form
- Show data flow between stages
- Include example input and full multi-stage transformation

### 2. IMPLEMENTATION CODE
Provide a working example in ONE of the following:
- Python (preferred)
- Node.js

The code must include:
- function per stage (planner, solver, critic, finalizer)
- prompt templates embedded as strings
- simple orchestrator function that runs the pipeline
- ability to pass a user query through the full system
- optional configuration for model selection per stage

## Optional enhancements (include if possible)
- JSON schema for intermediate outputs
- caching or memory layer
- "fast mode" that skips critic stage
- "deep mode" that always runs all stages

## Design philosophy
This system is meant to simulate higher-level reasoning (similar to Claude Opus behavior) by forcing structured cognitive decomposition in smaller models rather than relying on parameter scale.

Be practical, implementation-focused, and avoid theoretical descriptions without code.
