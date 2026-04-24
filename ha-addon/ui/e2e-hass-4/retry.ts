/**
 * Shared transient-socket-error retry wrapper for e2e-hass-4 specs.
 *
 * Laptop dual-homed NICs sporadically raise kernel-level socket errors
 * (`EADDRNOTAVAIL`, `EHOSTUNREACH`, `ECONNRESET`, `ECONNREFUSED`) during
 * long `expect.poll` loops — MacOS surfaces them when the source
 * interface's address churns mid-read. These are client-side flakes, not
 * product bugs. One short retry with backoff absorbs them; real outages
 * persist past the retry and still fail the containing `expect.poll`.
 * Bug #195b.
 */

const TRANSIENT = /EADDRNOTAVAIL|EHOSTUNREACH|ECONNRESET|ECONNREFUSED/;

export async function retryTransient<T>(fn: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try {
      return await fn();
    } catch (err) {
      const msg = String(err);
      if (attempt < 3 && TRANSIENT.test(msg)) {
        await new Promise(r => setTimeout(r, 500 * (attempt + 1)));
        continue;
      }
      throw err;
    }
  }
}
