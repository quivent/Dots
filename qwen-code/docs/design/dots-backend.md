# Dots backend integration

[English](dots-backend.md) | [简体中文](dots-backend.zh-CN.md)

## Problem

Dots needs the complete Qwen terminal interface with its existing cloud Dot backend. Replacing only the model provider would retain the local coding-agent loop and could issue internal prompts or execute local tools.

## Design

An explicit `DOTS_BACKEND=1` process mode starts Qwen's actual Ink application, `AppContainer`, and default layout. A Python JSON-lines subprocess owns Dots authentication, saved identity resolution, messaging, polling, and delivery journals. The Qwen hook uses that transport instead of `useLlmStream`.

The Dots startup constructs a safe, bare Qwen configuration for presentation. Configuration initialization skips LLM initialization, hooks, MCP discovery, skills, and file checkpointing. Provider authentication is bypassed because credentials belong to Dots. User text and supported Dots commands go directly to the backend hook before Qwen's local agent admission path.

Shutdown waits for the Python worker to finish its current operation and release the conversation lock before Qwen's bounded cleanup begins. Attachments are rejected before the composer is cleared. Edited and deleted server messages update the existing transcript.

## Scope

Reuse Qwen's application layout, text buffer, input component, transcript rendering, terminal handling, and themes. Keep the existing Dots backend responsible for single sends and recovery. Do not add a model-provider adapter, execute local tools, automatically resume paused Dots, or automatically retry uncertain sends.

## Files

The change adds a Dots startup module, transport service, backend hook, and Python bridge. It updates the Qwen entry point, application container, and auth presentation for the explicit mode.

## Validation

Verify history loading, sending once, receiving updates while typing, paused and uncertain delivery behavior, slash-command routing, and shutdown with offline fixtures. Run focused Python and TypeScript tests, build, typecheck, and a terminal smoke test. Real provider sends require an intentional user message.

## Acceptance

The Dots command launches Qwen's existing TUI, displays the selected Dot's history, and routes a submitted message exclusively through Dots. Qwen provider authentication and its local model/tool loop do not run. Ordinary upstream Qwen startup remains available outside Dots mode.
