// Single source of truth for 2026 team color tokens (from VISUAL_STYLE_GUIDE.md).
// Previously this map was copy-pasted independently into DriverCard.tsx,
// DriverStandingsChart.tsx, TeamStandingsChart.tsx, and Dashboardhome.tsx, so
// updates to one never propagated to the others.
export const TEAM_COLORS: Record<string, string> = {
  "Red Bull Racing": "#1E41FF",
  "McLaren": "#FF8000",
  "Ferrari": "#E8002D",
  "Mercedes": "#00D2BE",
  "Aston Martin": "#006F62",
  "Alpine": "#0093CC",
  "Williams": "#005AFF",
  "Racing Bulls": "#1434CB",
  "RB": "#1434CB",
  "Haas": "#B6BABD",
  "Kick Sauber": "#00E701",
  "Cadillac": "#CC0000",
  "Audi": "#C0C0C0",
};

const SUBSTRING_ALIASES: Array<[string, string]> = [
  ["red bull", "Red Bull Racing"],
  ["ferrari", "Ferrari"],
  ["mclaren", "McLaren"],
  ["mercedes", "Mercedes"],
  ["aston martin", "Aston Martin"],
  ["alpine", "Alpine"],
  ["williams", "Williams"],
  ["racing bulls", "Racing Bulls"],
  ["rb", "RB"],
  ["sauber", "Kick Sauber"],
  ["stake", "Kick Sauber"],
  ["haas", "Haas"],
  ["cadillac", "Cadillac"],
  ["audi", "Audi"],
];

// Exact match first (handles the canonical 2026 names), then a substring
// fallback (handles API variants like "Oracle Red Bull Racing" or "Scuderia Ferrari").
export function getTeamColor(teamName: string): string {
  if (TEAM_COLORS[teamName]) return TEAM_COLORS[teamName];

  const lower = teamName.toLowerCase();
  for (const [needle, key] of SUBSTRING_ALIASES) {
    if (lower.includes(needle)) return TEAM_COLORS[key];
  }

  return "#888888";
}
