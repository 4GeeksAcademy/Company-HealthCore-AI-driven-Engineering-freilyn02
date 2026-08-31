const TOKEN_KEY = "access_token";

// Reads the token from localStorage.
// Returns null during server-side rendering, since localStorage doesn't exist there.
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

// Saves the token after a successful login or register.
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

// Removes the token — used on logout and on 401 responses.
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}