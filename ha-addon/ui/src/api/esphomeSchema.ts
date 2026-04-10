/**
 * ESPHome component schema fetcher.
 *
 * Pulled out of EditorModal.tsx in C.5 — CLAUDE.md says all `fetch()` calls
 * must live in api/. The schema source is the public schema.esphome.io
 * service (not our server), so this is the only file in api/ that talks to
 * a third-party host.
 *
 * Caches results in a module-level dict — schemas are immutable per
 * ESPHome version, and the cache lives for the lifetime of the page.
 */

const _schemaCache: Record<string, unknown> = {};

export async function fetchComponentSchema(
  component: string,
  esphomeVersion: string,
): Promise<unknown> {
  const key = `${esphomeVersion}/${component}`;
  if (_schemaCache[key] !== undefined) return _schemaCache[key];

  // Try version-specific first, fall back to 'dev' which always exists.
  for (const ver of [esphomeVersion, 'dev']) {
    try {
      const r = await fetch(`https://schema.esphome.io/${ver}/${component}.json`);
      if (r.ok) {
        const data: unknown = await r.json();
        _schemaCache[key] = data;
        return data;
      }
    } catch {
      // Network error — try next version or give up.
    }
  }

  // Cache negative result so we don't retry on every keystroke.
  _schemaCache[key] = null;
  return null;
}
