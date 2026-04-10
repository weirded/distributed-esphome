# Work Items — 1.5.0

Theme: **Editor and config management.** Turn the built-in editor into a real development environment with file browsing, config diffing, git integration, and URL import.

## File Tree Editor

Browse and edit any file in the ESPHome config directory, including subdirectories. VS Code-style file tree sidebar in the editor modal.

- [ ] **FT.1 `GET /ui/api/files`** — recursive directory listing, returns flat `[{path, size, binary}]`
- [ ] **FT.2 `GET /ui/api/files/{path:.+}`** — read file by relative path (path traversal prevention)
- [ ] **FT.3 `POST /ui/api/files/{path:.+}`** — write file (invalidates config cache for .yaml)
- [ ] **FT.4 Install `@headless-tree/core` + `@headless-tree/react`** — headless tree library
- [ ] **FT.5 `FileTree.tsx` component** — flat list → tree, expand/collapse, active highlight, binary grayed out
- [ ] **FT.6 Sidebar layout** — editor body flex row: `[file tree 240px] | [monaco flex-1]`, sidebar toggle
- [ ] **FT.7 File switching** — dirty check → load/save, language detection by extension
- [ ] **FT.8 Conditional buttons** — Save & Upgrade/Validate/Rename only for entry-point YAML; includes get Save only
- [ ] **FT.9 API functions** — `listFiles()`, `readFile()`, `writeFile()` in client.ts

## Config Diff

- [ ] **1.5a Store config snapshot** — save YAML at compile time to `/data/config_snapshots/`
- [ ] **1.5b Diff endpoint** — return unified diff between current and last-compiled
- [ ] **1.5c Diff viewer in editor** — Monaco diff editor or inline diff display

## Git Integration

Version history, commit, and push/pull for ESPHome configs — pairs with the File Tree Editor and Config Diff features to give power users full source-control visibility without leaving the UI.

- [ ] **GI.1 Git detection** — on startup, detect whether the config directory is a git repo; expose `git_enabled` flag in `/ui/api/info`
- [ ] **GI.2 Git status endpoint** — `GET /ui/api/git/status` — returns per-file status (modified, untracked, staged) for the config directory
- [ ] **GI.3 Git log endpoint** — `GET /ui/api/git/log` — recent commits (hash, message, author, date) for the config directory
- [ ] **GI.4 Git commit endpoint** — `POST /ui/api/git/commit` — stage changed files + commit with user-provided message
- [ ] **GI.5 Git pull/push endpoints** — `POST /ui/api/git/pull`, `POST /ui/api/git/push` — sync with remote (if configured)
- [ ] **GI.6 Git status indicators in File Tree** — modified/untracked badges on files in the FT sidebar
- [ ] **GI.7 Git history panel** — commit log viewer, per-file history, diff between commits

## Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

## Open Bugs & Tweaks

