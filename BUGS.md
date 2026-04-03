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

58. INVESTIGATING (1.1.0-dev.22) - Added diagnostic INFO log on first HA poll cycle showing total states, status sensors found, and matching details. Deploy and check logs to identify root cause.

59. FIXED (1.1.0-dev.23) - HA state slow to populate. First poll was delayed 30s; now polls immediately on startup.

60. FIXED (1.1.0-dev.23) - Restart device button in hamburger menu. Calls HA REST API button.press on button.<name>_restart entity.

61. FIXED (1.1.0-dev.23) - Logs button moved to hamburger menu as "Live Logs".

62. FIXED (1.1.0-dev.23) - Hamburger menu icon changed to vertical ellipsis (&#8942;), styled as plain text not button.

63. FIXED (1.1.0-dev.23) - Device polling now uses asyncio.gather for concurrent status checks instead of sequential.


