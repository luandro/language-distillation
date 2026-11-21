---
name: xerj
description: Definition-first code search and reference navigation over locally indexed repos (xerj search, xerj def, xerj autoindex)
version: 1.1.0
---

# XERJ: Definition-First Code Search

XERJ provides instant, deterministic, definition-first symbol navigation and semantic passage search across the codebase.

## Mandatory Directives

- **Never rely on hallucinated or assumed file paths or function signatures.**
- Use XERJ instead of broad `grep` or file listings when locating classes, schemas, functions, or domain entities.
- Always cite the exact `file:line` returned by XERJ in your reasoning and commit messages.

## Core Commands

| Command | Purpose | When to Use |
|---|---|---|
| `xerj def "<symbol>"` | Precise definition lookup | When finding where a class, function, enum, or model is declared. Returns `file:line` + signature. |
| `xerj search "<query>"` | Ranked passage search | When investigating architectural concepts, error messages, or usage patterns. Ranked definition-first. |
| `xerj search "<query>" -n 10` | Top-N passage search | When a broad survey of implementations across modules is required. |
| `xerj search "<query>" --full 1500` | Extended context view | When viewing full functions or multiline docstrings directly in search output. |
| `xerj autoindex <folder>` | Index/re-index repository | Run once or incrementally after substantial branch updates or mass file creation. |

## MCP Integration

When operating under an MCP-enabled agent runner, invoke the tool:
- `xerj_search(query="<query>")`
