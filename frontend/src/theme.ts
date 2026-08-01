export const colors = {
  surface: "#FFFFFF",
  onSurface: "#000000",
  surfaceSecondary: "#F2F2F7",
  onSurfaceSecondary: "#1C1C1E",
  surfaceTertiary: "#E5E5EA",
  onSurfaceTertiary: "#3A3A3C",
  surfaceInverse: "#000000",
  onSurfaceInverse: "#FFFFFF",
  brand: "#000000",
  border: "#E5E5EA",
  borderStrong: "#C7C7CC",
  divider: "#E5E5EA",
  success: "#34C759",
  warning: "#FFCC00",
  error: "#FF3B30",
  info: "#00C7BE",
  agentResearch: "#34C759",
  agentArchitect: "#FFCC00",
  agentCritic: "#FF3B30",
  agentPlanner: "#8A9A5B",
  agentDocSteward: "#00C7BE",
  muted: "#8E8E93",
};

export const spacing = {
  xs: 4, sm: 8, md: 12, lg: 16, xl: 24, "2xl": 32, "3xl": 48,
};

export const radius = { sm: 6, md: 12, lg: 20, pill: 999 };

export const fs = { sm: 12, base: 14, lg: 16, xl: 20, "2xl": 24, "3xl": 34, "4xl": 48 };

export const agentColorMap: Record<string, string> = {
  agentResearch: colors.agentResearch,
  agentArchitect: colors.agentArchitect,
  agentCritic: colors.agentCritic,
  agentPlanner: colors.agentPlanner,
  agentDocSteward: colors.agentDocSteward,
};
