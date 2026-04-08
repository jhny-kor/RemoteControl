# DESIGN.md Integration

This repository is not itself a product website. It is an operational manager for Telegram and Codex-driven tasks.

Still, Codex can use a root `DESIGN.md` as a style contract whenever this workspace generates:

- landing pages
- internal dashboards
- docs microsites
- admin interfaces
- HTML previews or mockups

## Current Setup

- Root guide: [`/Users/plo/Documents/remoteBot/DESIGN.md`](/Users/plo/Documents/remoteBot/DESIGN.md)
- Inspiration source: [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)
- Imported style direction: Apple-inspired premium minimal web UI

## Recommended Workflow

1. Keep the workspace-level `DESIGN.md` short and executable.
2. Ask Codex to use that file explicitly when doing UI work.
3. Keep product logic and layout constraints in the task prompt, not in `DESIGN.md`.

Example prompt:

```text
프로젝트 루트의 DESIGN.md를 기준으로 애플풍 랜딩 페이지를 만들어줘.
기존 기능은 유지하고 레이아웃, 타이포, 여백, 버튼 스타일만 정리해줘.
```

## Updating From The Upstream Repository

If you want to refresh the style source later:

```bash
git clone https://github.com/VoltAgent/awesome-design-md.git /tmp/awesome-design-md
```

Then compare the upstream Apple profile with the local root guide and update only the parts you actually want to enforce.

Do not copy the full upstream file blindly if:

- the current workspace has established UI conventions
- the target is an admin tool rather than a marketing page
- the user wants Apple-inspired, not Apple-clone

## Why This Shape

The upstream file is useful as inspiration, but Codex follows local project files more reliably than remote URLs.

Putting a concise `DESIGN.md` in the repository root gives you:

- predictable local context
- easier iteration
- less prompt repetition
- simpler customization for this workspace
