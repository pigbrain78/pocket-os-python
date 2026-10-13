import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, RefreshControl, Pressable } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs, fonts } from "@/src/theme";
import Ring from "@/src/components/Ring";

type Health = {
  overall: number; density: number; coverage: number; freshness: number;
  duplicate_risk: number; unlinked: number;
  totals: { notes: number; edges: number; decisions: number; concepts: number };
};

export default function HealthScreen() {
  const { token } = useAuth();
  const [d, setD] = useState<Health | null>(null);
  const [refresh, setRefresh] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    setError(null);
    try { setD(await api<Health>("/api/health-dashboard", { token })); }
    catch { setError("Data sync error"); }
    finally { setLoading(false); }
  }, [token]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (loading && !d) return <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} /></SafeAreaView>;
  if (!d) return (
    <SafeAreaView style={styles.c} edges={["top"]}>
      <View style={styles.emptyWrap}>
        <Text style={styles.h1}>Memory Health</Text>
        <Text style={styles.sub}>{error || "Data sync error"}</Text>
        <Pressable style={styles.retry} onPress={() => { setLoading(true); load(); }} testID="health-retry">
          <Text style={styles.retryT}>Retry</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="health-screen">
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} />}
      >
        <View style={styles.head}>
          <Text style={styles.h1}>Memory Health</Text>
          <Text style={styles.sub}>Your knowledge, measured.</Text>
        </View>

        {d.totals.notes === 0 ? (
          <Text style={styles.emptyPrompt}>Capture more notes to fill these rings.</Text>
        ) : null}
        <View style={styles.hero}>
          <View style={styles.ringWrap}>
            <Ring size={200} strokeWidth={16} percent={d.totals.notes === 0 ? 0 : d.density} color={colors.agentResearch} />
            <View style={styles.ringAbs}>
              <Ring size={160} strokeWidth={14} percent={d.totals.notes === 0 ? 0 : d.coverage} color={colors.agentArchitect} />
            </View>
            <View style={styles.ringAbs}>
              <Ring size={120} strokeWidth={12} percent={d.totals.notes === 0 ? 0 : d.freshness} color={colors.agentDocSteward} />
            </View>
          </View>
          <View style={styles.overall}>
            <Text style={styles.overallLab}>Overall</Text>
            <Text style={styles.overallVal}>{d.overall}%</Text>
          </View>
        </View>

        <View style={styles.legend}>
          <LegendRow color={colors.agentResearch} label="Knowledge Density" val={d.density + "%"} />
          <LegendRow color={colors.agentArchitect} label="Decision Coverage" val={d.coverage + "%"} />
          <LegendRow color={colors.agentDocSteward} label="Documentation Freshness" val={d.freshness + "%"} />
        </View>

        <View style={styles.grid}>
          <MetricTile label="Duplicate Risk" val={d.duplicate_risk + "%"} accent={colors.warning} testID="metric-duplicate" />
          <MetricTile label="Unlinked" val={String(d.unlinked)} accent={colors.error} testID="metric-unlinked" />
          <MetricTile label="Notes" val={String(d.totals.notes)} accent={colors.onSurface} testID="metric-notes" />
          <MetricTile label="Concepts" val={String(d.totals.concepts)} accent={colors.agentPlanner} testID="metric-concepts" />
          <MetricTile label="Connections" val={String(d.totals.edges)} accent={colors.info} testID="metric-edges" />
          <MetricTile label="Decisions" val={String(d.totals.decisions)} accent={colors.agentCritic} testID="metric-decisions" />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const LegendRow = ({ color, label, val }: any) => (
  <View style={styles.legRow}>
    <View style={[styles.legDot, { backgroundColor: color }]} />
    <Text style={styles.legLab}>{label}</Text>
    <Text style={styles.legVal}>{val}</Text>
  </View>
);
const MetricTile = ({ label, val, accent, testID }: any) => (
  <View style={styles.tile} testID={testID}>
    <View style={[styles.tileAccent, { backgroundColor: accent }]} />
    <Text style={styles.tileVal}>{val}</Text>
    <Text style={styles.tileLab}>{label}</Text>
  </View>
);
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  s: { padding: spacing.xl, paddingBottom: 140 },
  head: { marginBottom: spacing.md },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 2 },
  hero: { alignItems: "center", justifyContent: "center", marginTop: spacing["2xl"], height: 220 },
  ringWrap: { width: 200, height: 200, alignItems: "center", justifyContent: "center" },
  overall: { position: "absolute", alignItems: "center", justifyContent: "center" },
  overallLab: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase" },
  overallVal: { fontSize: 40, fontWeight: "800", color: colors.onSurface, fontFamily: fonts.mono },
  ringAbs: { position: "absolute", alignItems: "center", justifyContent: "center" },
  emptyWrap: { padding: spacing["2xl"], gap: spacing.md },
  emptyPrompt: { textAlign: "center", color: colors.muted, marginTop: spacing.lg },
  retry: { alignSelf: "flex-start", backgroundColor: colors.onSurface, borderRadius: radius.pill, paddingHorizontal: 16, paddingVertical: 10 },
  retryT: { color: "#fff", fontWeight: "700" },
  legend: { marginTop: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: spacing.sm },
  legRow: { flexDirection: "row", alignItems: "center", gap: 10 },
  legDot: { width: 10, height: 10, borderRadius: 5 },
  legLab: { flex: 1, color: colors.onSurface, fontSize: fs.base },
  legVal: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  grid: { marginTop: spacing.xl, flexDirection: "row", flexWrap: "wrap", gap: spacing.md },
  tile: { flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, overflow: "hidden" },
  tileAccent: { position: "absolute", left: 0, top: 0, bottom: 0, width: 3 },
  tileVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface, fontFamily: fonts.mono },
  tileLab: { color: colors.muted, fontSize: fs.sm, marginTop: 4 },
});
