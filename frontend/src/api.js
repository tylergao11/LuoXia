const BASE = "";

async function req(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

export const api = {
  health: () => req("/api/health"),
  worlds: () => req("/api/worlds"),
  listGames: (limit = 10) => req(`/api/games?limit=${limit}`),
  createGame: (world_id = "luoxia") =>
    req("/api/games", { method: "POST", body: JSON.stringify({ world_id }) }),
  getGame: (id) => req(`/api/games/${id}`),
  action: (id, body) =>
    req(`/api/games/${id}/actions`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
