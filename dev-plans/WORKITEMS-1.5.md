# Work Items — 1.5.0

Theme: **Power-user features that go beyond stock ESPHome.** Better ways to manage large device fleets, track config changes, and get AI assistance.

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

## Device Organization

- [ ] **6.3 Device groups/tags** — JSON sidecar metadata, filter/group UI in Devices tab
- [ ] **6.6 Bulk operations** — extend multi-select: bulk delete, bulk validate, bulk tag

## Config Diff

- [ ] **1.5a Store config snapshot** — save YAML at compile time to `/data/config_snapshots/`
- [ ] **1.5b Diff endpoint** — return unified diff between current and last-compiled
- [ ] **1.5c Diff viewer in editor** — Monaco diff editor or inline diff display

## Import

- [ ] **2.1c Create device: import from URL** — fetch config from GitHub/project URL

## AI/LLM Editor

- [ ] **1.4a Server config** — add-on options for LLM provider, API key, model, endpoint
- [ ] **1.4b Completion endpoint** — `POST /ui/api/ai/complete` proxies to LLM with YAML context
- [ ] **1.4c Inline ghost text** — display LLM suggestions as Monaco inline completions
- [ ] **1.4d Chat endpoint** — `POST /ui/api/ai/chat` for natural language → YAML
- [ ] **1.4e Chat panel in editor** — side panel for prompting, accept/reject generated changes
