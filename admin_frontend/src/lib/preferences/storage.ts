import { browser } from '$app/environment';

export function readLocalString(key: string): string | null {
  if (!browser) return null;
  return localStorage.getItem(key);
}

export function writeLocalString(key: string, value: string) {
  if (!browser) return;
  localStorage.setItem(key, value);
}

export function readLocalBoolean(key: string, fallback: boolean): boolean {
  const raw = readLocalString(key);
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  return fallback;
}

export function writeLocalBoolean(key: string, value: boolean) {
  writeLocalString(key, String(value));
}

export function readSessionString(key: string): string | null {
  if (!browser) return null;
  return sessionStorage.getItem(key);
}

export function writeSessionString(key: string, value: string) {
  if (!browser) return;
  sessionStorage.setItem(key, value);
}
