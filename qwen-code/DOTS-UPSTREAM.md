# Qwen Code in Dots

This directory contains the complete upstream source from
https://github.com/QwenLM/qwen-code at commit
`338f13366c1d86e586f7e0785942740da3503887` (upstream version 0.26.1).
It is vendored source tracked by the enclosing Dots repository, rather than a
nested Git checkout. Upstream license and copyright notices are retained.

Dots uses the upstream Ink application, container, layout, composer, transcript,
text buffer, keyboard handling, and themes. The Dots-specific startup connects
those components to `../cli/tui_bridge.py` over subprocess JSON lines, replacing
the local Qwen model/tool loop with the existing cloud Dot client.

Install the pinned dependencies with `pnpm install --frozen-lockfile`, then
build with `npm run build -- --cli-only`. Launch from the Dots CLI with
`dots chat NAME`, or use the selected saved Dot with `dots chat`.
`dots auth` and `dots import --source chatgpt` retain their existing roles.

The design and verification details are in
[the backend design](docs/design/dots-backend.md).
