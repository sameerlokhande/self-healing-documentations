# Self-Healing Technical Documentation System

A GitHub Action and CI/CD quality gate that detects documentation drift caused by code changes, evaluates semantic staleness using LLMs, and autonomously generates surgical doc repairs before stale documentation merges to main.

## Problem Statement
In fast-moving codebases, documentation constantly falls out of sync with code implementations. Parameter renames, default value changes, and signature shifts rarely trigger CI failures, leading to silent documentation debt. Manual reviews frequently miss markdown updates several directories away.

This tool solves this by treating documentation as a dependency graph of the codebase AST:
1. It indexes code entities (functions, classes) and maps them to markdown sections via symbol matching and vector embeddings.
2. On every PR, it inspects unified git diffs for semantic signature changes (ignoring whitespace and internal comments).
3. If an AST change impacts a documented section, an LLM evaluates staleness, drafts a surgical fix preserving voice and style, verifies the patch via a quality gate, and generates an automated fix.

## Architecture