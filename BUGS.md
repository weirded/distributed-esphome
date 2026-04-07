## 1.2.0

90. FIXED (1.2.0-dev.3) - Validate 502 "Cannot save". Made updateDirtyDecorations errors non-fatal (.catch(() => {})) so async diff failures don't bubble up as save errors.

91. FIXED (1.2.0-dev.4) - Validate log modal popped under editor. Added `stacked` CSS class (z-index 500) to LogModal when editor is open, so validation output appears over the editor.

92. FIXED (1.2.0-dev.6) - ESPHome logo huge and columns dropdown blanking screen. Root cause: Tailwind preflight reset was overriding img sizing and injecting base styles. Fixed by importing only tailwindcss/theme + tailwindcss/utilities (skipping preflight), since we have our own CSS reset.

93. FIXED (1.2.0-dev.7) - Columns button blanked screen. Root cause: DropdownMenuLabel requires being inside DropdownMenuGroup (Base UI error #31: "MenuGroupRootContext is missing"). Missing wrapper crashed React. Fixed by wrapping label + items in DropdownMenuGroup.

94. FIXED (1.2.0-dev.8) - shadcn/ui dropdown not honoring dark mode. Root cause: shadcn variables in :root were set to light zinc values. Fixed by mapping shadcn variables (--popover, --foreground, etc.) to app theme variables via var() references, so they automatically adapt to dark/light mode.

95. FIXED (1.2.0-dev.8) - Table limited to 1400px width. Removed max-width constraint on main element so table uses full browser width.

96. FIXED (1.2.0-dev.8) - Devices not refreshing after YAML edit. Editor onClose now triggers fetchDevicesAndTargets() so changes appear immediately.

97. FIXED (1.2.0-dev.8) - "Upgrade on" worker list now sorted alphabetically (case-insensitive), matching Workers tab sort.

98. FIXED (1.2.0-dev.8) - Hamburger menu restructured into sections: "Device" (Live Logs, Restart, Copy API Key), "Config" (Rename, Delete), and "Upgrade on..." as a submenu.

99. FIXED (1.2.0-dev.8) - Hamburger menu converted from custom CSS dropdown to shadcn DropdownMenu, consistent with columns picker. Both menus now use same Base UI primitives and theme.

100. VERIFIED (1.2.0-dev.9) - Copy API Key works correctly. Playwright confirmed: endpoint returns 200 with 44-char base64 key for devices with api.encryption.key configured. Button is disabled for devices without keys. Clipboard copy works.

101. FIXED (1.2.0-dev.10) - Slots +/- moved to dedicated "Slots" column in Workers tab. Minimum lowered from 1 to 0 (0 = paused, worker accepts no jobs). Server validation updated to accept 0-32. Client spawns no worker threads at 0.

102. FIXED (1.2.0-dev.10) - Local worker runs inside the add-on container. Server spawns client.py as subprocess on startup with 0 slots (paused by default). Users increase slots via Workers tab to activate. Uses /data/esphome-versions for builds. Terminated cleanly on shutdown.

103. FIXED (1.2.0-dev.10) - Disk space reporting added to worker system info. Workers report disk_total, disk_free, disk_used_pct for the /esphome-versions volume. Displayed in Workers tab Platform column as "Disk: X/Y free". Turns yellow >75% used, red >90%.

104. FIXED (1.2.0-dev.11) - Server crash on startup. Root cause: `cfg.server_token` should be `cfg.token` (AppConfig attribute name). Typo in local worker spawn code.

105. FIXED (1.2.0-dev.11) - Updated DOCS.md and README.md: removed obsolete package-client.sh/start.sh/stop.sh references, simplified worker setup (just Connect Worker button + docker-compose option), documented local worker, updated Web UI features (Monaco editor, live logs, configurable columns, HA integration, dark/light theme, etc.), updated repo layout (added ui/, removed dist-scripts/). Added docs update reminder to CLAUDE.md release checklist.

106. FIXED (1.2.0-dev.12) - Local worker code was correct (MAX_PARALLEL_JOBS=0), but `max_parallel_jobs || 1` in UI defaulted 0 to 1. Changed to `?? 0`. Also marked backlog #6 done.

107. FIXED (1.2.0-dev.12) - Local worker row highlighted with surface2 background, "built-in" badge, always sorted to top of workers list regardless of sort order. Remove button hidden for local worker.

108. FIXED (1.2.0-dev.12) - Slot +/- controls debounced with 600ms delay. Rapid clicks accumulate locally, single API call fires after user stops clicking.

109. FIXED (1.2.0-dev.12) - Disk space on separate line: "Disk: X / Y (Z% free)". Orange when >80% used, red when >90% used.

110. INVESTIGATED (1.2.0-dev.12) - Yes, worker restart is required to change slot count (heartbeat sends new value, client does os.execv restart). This is automatic and takes ~2-3 seconds.

111. FIXED (1.2.0-dev.12) - Toast now shows worker hostname (e.g. "lenovo-1 disabled"). Row height stabilized with consistent styling.

112. FIXED (1.2.0-dev.12) - Version manager evicts unused ESPHome versions when disk free drops below MIN_FREE_DISK_PCT (default 10%). Runs before each install. Keeps at least 1 version (the active one).

113. FIXED (1.2.0-dev.13) - Devices header consolidated into single row: DEVICES title, search box, Upgrade dropdown (All, All Online, Outdated, Selected), and gear icon for column picker. Removed second header row.

114. FIXED (1.2.0-dev.13) - DS.2 started: migrated toast system from custom ToastContainer to shadcn Sonner. Installed dialog and badge components.

115. FIXED (1.2.0-dev.14) - Gear icon enlarged from default to fontSize 16px.

116. FIXED (1.2.0-dev.14) - Area not read for configs with git package dependencies. Root cause: _resolve_esphome_config fails silently when git clone fails (e.g. race condition, network). Added fallback: simple yaml.safe_load reads area/comment/name directly from the YAML file when full resolution fails.

117. FIXED (1.2.0-dev.14) - Upgrade All Online not firing. Root cause: Base UI Menu.Item uses `onClick`, not `onSelect`. Changed all DropdownMenuItem handlers from onSelect to onClick.

118. FIXED (1.2.0-dev.14) - DS.2 toast migrated to Sonner, dropdowns done. Buttons/badges/dialog migration deferred (see WORKITEMS.md).

119. FIXED (1.2.0-dev.15) - Area still missing for 11 devices. Two root causes: (1) yaml.safe_load fallback choked on !include/!secret tags — fixed with permissive YAML loader that passes through unknown tags. (2) Some configs define area in substitutions but not in esphome: block — added fallback to check substitutions.area.

120. FIXED (1.2.0-dev.16) - DS status notes moved to WORKITEMS.md.

121. FIXED (1.2.0-dev.16) - Device name resolution broken by raw YAML fallback returning unresolved ${name} literals. Restructured: full ESPHome resolution is always primary (handles names/substitutions/packages). Raw YAML fallback only fills MISSING fields (area, comment, project) with LITERAL values (skips anything containing ${...}). Never overwrites resolved values.

122. FIXED (1.2.0-dev.17) - "Upgrade on..." pinned jobs never started. Root cause: performance-based scheduling deferred ALL jobs when a faster worker existed, including pinned jobs. Fix: pinned jobs bypass the defer check in claim_next — they can only be claimed by the designated worker, so deferring made them stuck.

123. FIXED (1.2.0-dev.17) - Kauf-plug devices missing name/comment. Root cause: full ESPHome config resolution fails for these (git package clone issue), and the raw YAML fallback didn't resolve ${substitutions}. Fix: fallback now resolves simple ${key} substitutions from the substitutions block before extracting metadata.

124. FIXED (1.2.0-dev.18) - Validation jobs filtered from queue display and tab counts. displayQueue excludes validate_only jobs. LogModal still sees full queue for streaming. Auto-pruning handles cleanup.

125. FIXED (1.2.0-dev.18) - Workers with 0 slots excluded from "Upgrade on..." submenu (filtered by max_parallel_jobs > 0).

126. FIXED (1.2.0-dev.18) - Queue buttons grouped into two shadcn dropdowns: "Retry" (Retry All Failed, Retry Selected, Cancel Selected) and "Clear" (Clear Succeeded, Clear All Finished).

127. FIXED (1.2.0-dev.18) - Search boxes added to Queue and Workers tabs, matching Devices layout. Queue filters by device name, target, state, worker. Workers filters by hostname, OS, CPU, version.

128. FIXED (1.2.0-dev.18) - Pinned worker preserved on retry. Previously only OTA failures preserved the pin. Now all retried jobs keep their original pinned_client_id.

129. FIXED (1.2.0-dev.18) - Queue rows now use same device-name/device-filename CSS classes as Devices tab for consistent rendering.

130. FIXED (1.2.0-dev.18) - Empty queue shows "0" in tab badge instead of empty/dash.

131. FIXED (1.2.0-dev.18) - ESPHome version selector converted from custom dropdown to shadcn DropdownMenu. Removed versionDropdownOpen state and manual click-outside handler.

132. FIXED (1.2.0-dev.19) - Archive management: added GET /ui/api/archive (list), POST /ui/api/archive/{f}/restore, DELETE /ui/api/archive/{f} (permanent delete) endpoints. Delete modal now has double confirmation for permanent delete (first click shows "Delete Permanently", second screen confirms "Yes, Delete Forever"). API client functions added for archive operations. UI archive viewer deferred to future iteration.

133. FIXED (1.2.0-dev.19) - Removed Disable/Enable button entirely. Workers are now paused by setting slots to 0 (single concept). Status shows "Paused" instead of "Disabled". Row dims at 0 slots. Remove button only shows for offline non-local workers.

134. FIXED (1.2.0-dev.27) - Upgrade dropdown too narrow. Added min-w-[180px] to ensure options don't wrap.

135. NOT A BUG - Hamburger menu already uses shadcn DropdownMenu (migrated in 1.2.0-dev.8).

136. FIXED (1.2.0-dev.27) - Live logs and compile logs showing empty terminal. Root cause: Dialog portal mounts DOM asynchronously, but xterm useEffect ran before containerRef was populated. Fix: callback ref pattern — containerCallbackRef triggers state change when DOM node mounts, which re-fires the xterm initialization effect.

137. FIXED (1.2.0-dev.27) - Editor/log modals too tall (buttons off-screen). Changed dialog-lg height to min(80vh, calc(100vh - 4rem)) and dialog-xl to min(90vh, calc(100vh - 2rem)).

138. FIXED (1.2.0-dev.27) - Renamed "Running" column to "Version" in both table header and column picker.

139. FIXED (1.2.0-dev.31) - Docker command light mode contrast. Changed hardcoded `color: #e2e8f0` to `color: var(--text)` so it adapts to theme.

140. FIXED (1.2.0-dev.32) - Validate log modal: Edit and Retry buttons hidden when job.validate_only is true.

141. FIXED (1.2.0-dev.33) - Copy to Clipboard button added to LogModal and DeviceLogModal headers (next to Download). Extracts terminal text and copies via navigator.clipboard.

142. FIXED (1.2.0-dev.33) - Removed Rename button from editor header. Rename is still available via the hamburger menu.

143. FIXED (1.2.0-dev.33) - Close (✕) button added to all modals. Removed showCloseButton={false} from all 6 Dialog usages — shadcn Dialog's default close button (absolute top-right) now renders on every modal.

144. FIXED (1.2.0-dev.34) - Copy buttons not working. Root cause: navigator.clipboard requires secure context (HTTPS). Added textarea fallback for HTTP/Ingress contexts.

145. FIXED (1.2.0-dev.34) - X and Download buttons overlapping. Fix: added pr-12 right padding to DialogHeader so content doesn't extend under the library's absolute-positioned close button. All modals use the default close button — no custom overrides.

146. FIXED (1.2.0-dev.35) - Editor X button overlapping header buttons. Added right padding (3rem) to .editor-header CSS so buttons don't extend under the close button.

147. FIXED (1.2.0-dev.35) - Toast feedback on copy. Both LogModal and DeviceLogModal now show "Copied to clipboard" toast via Sonner after successful copy.

148. FIXED (1.2.0-dev.35) - Connect Worker modal scrollbar. Removed maxHeight constraint on content div — Dialog handles height naturally.

149. FIXED (1.2.0-dev.38) - Local worker missing git and build dependencies. Added `apk add git gcc musl-dev libffi-dev openssl-dev` to server Dockerfile. Also installed client requirements.txt in server image so local worker has all Python deps.

150. FIXED (1.2.0-dev.40) - Header icon buttons inconsistent size. Theme and streamer toggles now use fixed 28x28 rounded circles. Streamer toggle shows only icon (👁/🔒) instead of changing text length. Active state highlights with accent color.

151. FIXED (1.2.0-dev.41) - Polling refresh closes open hamburger menu. Wrapped DeviceMenu in React.memo so it doesn't re-render on every poll cycle. Base UI portal keeps dropdown open across parent re-renders.

152. FIXED (1.2.0-dev.41) - Editor closes without warning when there are unsaved changes. Added confirm dialog: "You have unsaved changes. Close anyway?" when dirtyLineCount > 0.

153. FIXED (1.2.0-dev.41) - Local worker: xtensa-lx106-elf-g++ not found (ESP8266 cross-compiler). Root cause: PlatformIO downloads glibc-compiled toolchains but Alpine uses musl. Added `gcompat` (glibc compatibility layer) to Dockerfile.

154. FIXED (1.2.0-dev.50) - Hamburger menu closing on refresh. Root cause: TanStack Table recreates row DOM on SWR data change, unmounting DropdownMenu. Fix: menu rendered as fixed-positioned overlay outside the table with left-opening hover submenu for worker list. Playwright verified: opens instantly, positioned correctly, submenu within viewport, stays open 20+ seconds across polls.

155. FIXED (1.2.0-dev.42) - Editor unsaved warning uses native window.confirm. Replaced with shadcn Dialog showing "Unsaved Changes" with Cancel/Discard Changes buttons, rendered at z-index 600 above the editor.

156. FIXED (1.2.0-dev.42) - Local worker slot count lost on restart. Persisted to /data/local_worker_slots. Server reads on startup, UI writes on change.

157-158. FIXED (1.2.0-dev.60) - Local worker compilation failures. Root cause: Alpine base image's musl libc can't run PlatformIO's glibc cross-compiler toolchains (segfault with gcompat). Fix: hardcoded `FROM python:3.11-slim` (Debian) in Dockerfile — same proven base as the client image. HA Supervisor overrides BUILD_FROM arg, so hardcoding was necessary. Includes gcc, libffi-dev, libssl-dev, git.

159. FIXED (1.3.0-dev.4) - Duplicate device rows for configs with hyphens in esphome.name. (GitHub issue #2) Root cause: ESPHome normalizes device names for mDNS — hyphens become underscores. `_map_target()` did exact string comparison. Fix: added hyphen/underscore normalization in `_map_target()` (tries normalized lookup on both name_to_target map and filename stems) and `build_name_to_target_map()` (adds underscore-normalized variant of hyphenated names to the map).

160. FIXED (1.3.0-dev.4) - OTA diagnostics reports wrong device name. (GitHub issue #15) Root cause: `_ota_network_diagnostics()` used a naive regex matching the first `name:` in the YAML (e.g. a neopixel light). Fix: replaced regex with yaml.safe_load to extract esphome.name properly, with a fallback that only looks under the esphome: block.

161. FIXED (1.3.0-dev.4) - Hamburger menu drops off-screen when opened near bottom-right corner. Fix: added viewport boundary detection via callback ref — flips menu upward when it would extend below viewport, and removes translateX(-100%) when menu would extend past the left edge.

162. DUPLICATE of #161 — hamburger menu bottom-right corner issue. Already fixed in 1.3.0-dev.4.

163. WONTFIX - When the UI is open and a new upgrade is deployed, HA shows an "add-on is offline" dialog instead of the app reloading gracefully. This is HA Ingress behavior — the proxy intercepts the connection before our app can handle it. SWR already retries and the version-change detector triggers a reload once the server is back.

164. FIXED (1.3.0-dev.9) - "Upgrade on..." submenu drops off-screen when opened near viewport edge. Fix: added callback ref with viewport detection — opens to the right if insufficient space on the left, flips upward if extending below viewport.

165. FIXED (1.3.0-dev.9) - Clean Cache button layout broken (flex on td) and missing global button. Fix: removed flex from td, added "Clean All Caches" button in Workers tab header.



---

<details>
<summary>Archive: 1.0.0 + 1.1.0 (bugs 1–89)</summary>

1. FIXED (1.1.0-dev.4) - In the queue, we aren't correctly handling some of the states.

2. FIXED (1.1.0-dev.4) - Colors - Upgrade Outdated should be green.

3. FIXED (1.1.0-dev.4) - Button states for disabled buttons.

4. FIXED (1.1.0-dev.6) - Disabled button styling inconsistent.

5. FIXED (1.1.0-dev.6) - API key option in hamburger menu.

6. FIXED (1.1.0-dev.6) - IP address link styling.

7. FIXED (1.1.0-dev.6) - Only link IP if web_server configured.

8. FIXED (1.1.0-dev.7) - PowerShell docker command.

9. FIXED (1.1.0-dev.7) - Button disabled mechanics.

10. FIXED (1.1.0-dev.7) - Sortable table columns.

11. FIXED (1.1.0-dev.7) - Workers tab alphabetical sort.

12. FIXED (1.1.0-dev.7) - Queue entry time instead of ID.

13. FIXED (1.1.0-dev.7) - Singular/plural toast messages.

14. FIXED (1.1.0-dev.8) - Duplicate device when filename != esphome.name.

15. FIXED (1.1.0-dev.8) - Disabled buttons + header pill styling.

16. FIXED (1.1.0-dev.11) - Toast "0 jobs" messages.

17. FIXED (1.1.0-dev.11) - Disabled buttons with !important.

18. FIXED (1.1.0-dev.11) - Editor content wiped on poll cycle.

19. FIXED (1.1.0-dev.12) - No validate button for secrets.yaml.

20. FIXED (1.1.0-dev.12) - Validate stays in editor.

21. FIXED (1.1.0-dev.13) - Save closes editor.

22. FIXED (1.1.0-dev.13) - Autocomplete from real ESPHome components.

23. FIXED (1.1.0-dev.14) - Toast auto-dismiss timing.

24. FIXED (1.1.0-dev.14) - Validation result toasts.

25. FIXED (1.1.0-dev.15) - Per-component autocomplete from schema.esphome.io.

26. FIXED (1.1.0-dev.15) - CI mypy types-PyYAML.

27. FIXED (1.1.0-dev.16) - Root-level autocomplete triggering.

28. FIXED (1.1.0-dev.18) - Rename React modal.

29. FIXED (1.1.0-dev.18) - Delete React modal with Archive/Permanent.

30. FIXED (1.1.0-dev.18) - Modal drag-select closing.

31. FIXED (1.1.0-dev.18) - Rename OTA targets old device address.

32. FIXED (1.1.0-dev.19) - Device list doesn't refresh after rename/edit. Server forces config rescan after rename. Config cache invalidated after save.

33. FIXED (1.1.0-dev.19) - Device logs "asyncio not defined". Stale Docker image. Forced clean rebuild.

34. FIXED (1.1.0-dev.19) - Live Logs modal drag-select close issue. Applied same mousedown tracking fix as #30.

35. FIXED (1.1.0-dev.19) - Edit buttons in Queue rows and log modal header.

36. FIXED (1.1.0-dev.19) - "Save & Upgrade" button in YAML editor — saves, triggers compile, switches to Queue tab.

37. FIXED (1.1.0-dev.19) - Duplicate device after rename. Old device entry explicitly removed from poller on rename.

38. FIXED (1.1.0-dev.19) - Same IP = same device filter in unmanaged device list.

39. FIXED (1.1.0-dev.19) - Light mode editor modals. CSS variables for modal themes, button color adjustments.

40. FIXED (1.1.0-dev.19) - "Checking..." state with pulsing dot instead of showing offline on startup.

41. FIXED (1.1.0-dev.20) - Rename button says "Rename and Flash" → "Rename & Upgrade" for consistency.

42. FIXED (1.1.0-dev.20) - Rename button added to Editor modal header.

43. FIXED (1.1.0-dev.20) - Editor hover tooltips for validation errors. Enabled hover + glyphMargin in Monaco options.

44. FIXED (1.1.0-dev.20) - Editor highlights unsaved changes with background color on modified lines.

45. FIXED (1.1.0-dev.20) - HA status as dedicated column in devices table. Implemented 4.2c: HA connected state used as additional online signal.

46. FIXED (1.1.0-dev.20) - Light mode header kept dark so ESPHome logo stays readable.

47. FIXED (1.1.0-dev.21) - Validation failure opens log modal automatically. Improved toast message.

48. FIXED (1.1.0-dev.21) - Validate button saves editor content first, then validates against current text.

49. FIXED (1.1.0-dev.21) - Dirty line highlight color made more visible (0.08 → 0.15 opacity).

50. FIXED (1.1.0-dev.21) - Editor footer shows "n lines changed" when there are unsaved changes.

51. FIXED (1.1.0-dev.21) - Clear button on each finished job row in Queue tab.

52. FIXED (1.1.0-dev.21) - HA status not populating. Entity registry REST API doesn't exist; switched to /api/states with binary_sensor device_class=connectivity filter.

53. FIXED (1.1.0-dev.21) - Dark mode checkboxes use color-scheme: dark.

54. FIXED (1.1.0-dev.22) - aioesphomeapi.connection log level set to ERROR (expected when devices offline).

55. FIXED (1.1.0-dev.22) - "Detected HA ESPHome add-on version" changed to DEBUG level.

56. FIXED (1.1.0-dev.22) - PyPI version limit increased from 10 to 50.

57. FIXED (1.1.0-dev.22) - Validate opens streaming log modal directly. No more toasts for validation flow.

58. FIXED (1.1.0-dev.22) - Diagnostic INFO log on first HA poll cycle. Led to fix in #59.

59. FIXED (1.1.0-dev.23) - HA state slow to populate. First poll was delayed 30s; now polls immediately on startup.

60. FIXED (1.1.0-dev.23) - Restart device button in hamburger menu. Calls HA REST API button.press on button.<name>_restart entity.

61. FIXED (1.1.0-dev.23) - Logs button moved to hamburger menu as "Live Logs".

62. FIXED (1.1.0-dev.23) - Hamburger menu icon changed to vertical ellipsis, styled as plain text not button.

63. FIXED (1.1.0-dev.23) - Device polling now uses asyncio.gather for concurrent status checks instead of sequential.

64. FIXED (1.1.0-dev.24) - Restart button uses friendly_name for HA entity matching (was using esphome.name which doesn't match HA's naming).

65. FIXED (1.1.0-dev.24) - Live logs now include boot log (dump_config=True in subscribe_logs).

66. FIXED (1.1.0-dev.24) - Git clone caching regression. Config resolver now uses skip_update=True after first resolution per target.

67. FIXED (1.1.0-dev.24) - HA status matching now tries friendly_name first, then esphome.name, then filename stem. Should match most devices.

68. FIXED (1.1.0-dev.24) - Live Logs and Restart no longer disabled when device appears offline.

69. FIXED (1.1.0-dev.24) - "esphome:" marked unknown. Added core keys (esphome, substitutions, packages, external_components) to component list.

70. FIXED (1.1.0-dev.24) - DeprecationWarning on app state. Changed to clear()+update() on existing dict instead of reassigning.

71. FIXED (1.1.0-dev.24) - HA entity matching uses friendly_name (e.g. "Nespresso Machine" → "nespresso_machine") instead of esphome.name.

72. FIXED (1.1.0-dev.25) - HA device detection without _status sensor. Now uses template API (integration_entities('esphome')) to find ALL ESPHome entities, then cross-references with _status sensors for connectivity. Devices without _status show as "Configured" instead of "—".

73. FIXED (1.1.0-dev.26) - Template API logging upgraded to WARNING level. Led to investigations resolved in subsequent fixes.

74. FIXED (1.1.0-dev.26) - Editor diff uses Monaco's built-in diff computation with common prefix/suffix fallback. Shifted lines no longer marked as changed.

75. FIXED (1.1.0-dev.26) - Restart uses native API first (aioesphomeapi: list entities → find restart button → button_command), falls back to HA REST API.

76. FIXED (1.1.0-dev.26) - Live log lines include [HH:MM:SS] timestamps.

77. FIXED (1.1.0-dev.26) - Compile logs colorized via ANSI escapes: INFO=green, WARNING=yellow, ERROR=red.

78. FIXED (1.1.0-dev.26) - OTA always passes --device with known IP. Server populates ota_address from device poller for all compile jobs.

79. FIXED (1.1.0-dev.26) - Editor diff uses Monaco's diff API with prefix/suffix fallback (replaced custom LCS).

80. FIXED (1.1.0-dev.26) - Switched from separate compile+upload to `esphome run --no-logs` (single process, same as native ESPHome UI).

81. FIXED (1.1.0-dev.27) - Terminal default text color changed from green to white (#e2e8f0).

82. FIXED (1.1.0-dev.27) - HA column now shows only "Yes" / "—" (configured or not). _status connectivity still feeds into online/offline column via 4.2c.

83. FIXED (1.1.0-dev.30) - HA matching for devices with non-standard HA entity names. Root cause: Screek sensors register with firmware names containing MAC fragments. Fix: added MAC fragment match + fixed _normalize_for_ha to strip special chars.

84. FIXED (1.1.0-dev.28) - Light mode connect worker form inputs. Changed hardcoded #0d1117 to var(--bg).

85. FIXED (1.1.0-dev.28) - Timezone mismatch causing different config_hash. Server now sends its TZ in job response; worker sets TZ in subprocess env.

86. FIXED (1.1.0-dev.28) - OTA retry restored. If esphome run fails after compile success, retries with esphome upload after 5s delay.

87. FIXED (1.1.0-dev.29) - OTA retry keeps job in WORKING state until final result. If worker dies during retry, timeout checker re-queues to another worker.

88. FIXED (1.1.0-dev.29) - MAC address matching for HA devices. Device poller captures MAC from device_info(). HA entity poller queries device identifiers via template API. Matching tries MAC first, then name fallback.

89. FIXED (1.1.0-dev.32) - ESPHome install errors now streamed to job log in real time (red ANSI). pip stderr included in error detail.

</details>
