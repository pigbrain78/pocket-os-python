import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Summary = {
  agents: number; active_leases: number; pending_approvals: number;
  executed: number; reversed: number; contracts: number;
};
type Agent = {
  id: string; name: string; author: string; version: string;
  risk: string; trust_score: number; capabilities: string[]; status: string;
  stats?: { successful: number; reversed: number; proposed: number };
};
type Pending = { id: string; action: string; agent_name: string; agent_risk: string; capability: string; created_at: string };

const RISK_COLOR: Record<string, string> = { low: colors.success, medium: colors.warning, high: colors.error };

export default function GovernanceIndex() {
  const { token } = useAuth();
  const router = useRouter();
  const [sum, setSum] = useState<Summary | null>(null);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [refresh, setRefresh] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [s, a, p] = await Promise.all([
        api<Summary>("/api/governance/summary", { token }),
        api<Agent[]>("/api/agents", { token }),
        api<Pending[]>("/api/executions/pending", { token }),
      ]);
      setSum(s); setAgents(a); setPending(p);
    } catch {}
  }, [token]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  if (!sum) return <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} /></SafeAreaView>;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="governance-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>Governance</Text>
        <Pressable onPress={() => router.push("/governance/submit")} testID="submit-agent-btn" hitSlop={12}>
          <Ionicons name="add" size={26} color={colors.onSurface} />
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} />}
      >
        <Text style={styles.tag}>CONSTITUTIONAL LAYER</Text>
        <Text style={styles.h1}>Every action is governed.</Text>

        <View style={styles.grid}>
          <Tile val={sum.agents} label="Agents" testID="gov-agents" />
          <Tile val={sum.active_leases} label="Active Leases" testID="gov-leases" />
          <Tile val={sum.pending_approvals} label="Pending" accent={colors.warning} testID="gov-pending" />
          <Tile val={sum.contracts} label="Contracts" testID="gov-contracts" />
          <Tile val={sum.executed} label="Executed" accent={colors.success} testID="gov-executed" />
          <Tile val={sum.reversed} label="Reversed" accent={colors.error} testID="gov-reversed" />
        </View>

        {pending.length > 0 ? (
          <View style={styles.approvals}>
            <Text style={styles.sh}>Awaiting Approval</Text>
            {pending.map(p => (
              <Pressable
                key={p.id}
                style={styles.pendRow}
                onPress={() => router.push({ pathname: "/governance/execution/[id]", params: { id: p.id } })}
                testID={`pending-${p.id}`}
              >
                <View style={[styles.riskDot, { backgroundColor: RISK_COLOR[p.agent_risk] || colors.muted }]} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.pendAgent}>{p.agent_name}</Text>
                  <Text style={styles.pendAction}>{p.action}</Text>
                  <Text style={styles.pendCap}>Requires: {p.capability}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        ) : null}

        <View style={styles.sectionRow}>
          <Text style={styles.sh}>Registered Agents</Text>
          <Text style={styles.subLab}>{agents.length}</Text>
        </View>
        {agents.map(a => (
          <Pressable
            key={a.id}
            style={styles.agentCard}
            onPress={() => router.push({ pathname: "/governance/agent/[id]", params: { id: a.id } })}
            testID={`agent-${a.id}`}
          >
            <View style={styles.agentTop}>
              <View style={[styles.riskDot, { backgroundColor: RISK_COLOR[a.risk] || colors.muted }]} />
              <View style={{ flex: 1 }}>
                <Text style={styles.agentName}>{a.name}</Text>
                <Text style={styles.agentAuthor}>{a.author} · v{a.version} · risk {a.risk}</Text>
              </View>
              <View style={styles.trust}>
                <Text style={styles.trustVal}>{a.trust_score}</Text>
                <Text style={styles.trustLab}>trust</Text>
              </View>
            </View>
            <View style={styles.caps}>
              {a.capabilities.slice(0, 4).map(c => (
                <View key={c} style={styles.cap}><Text style={styles.capT}>{c}</Text></View>
              ))}
              {a.capabilities.length > 4 ? <Text style={styles.capMore}>+{a.capabilities.length - 4}</Text> : null}
            </View>
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const Tile = ({ val, label, accent, testID }: any) => (
  <View style={styles.tile} testID={testID}>
    {accent ? <View style={[styles.tileAccent, { backgroundColor: accent }]} /> : null}
    <Text style={styles.tileVal}>{val}</Text>
    <Text style={styles.tileLab}>{label}</Text>
  </View>
);

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.xl, paddingBottom: 60 },
  tag: { fontSize: 10, color: colors.muted, letterSpacing: 1.5, fontWeight: "700" },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.xl },
  tile: { flexBasis: "30%", flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, overflow: "hidden" },
  tileAccent: { position: "absolute", left: 0, top: 0, bottom: 0, width: 3 },
  tileVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface },
  tileLab: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  approvals: { marginTop: spacing["2xl"], backgroundColor: colors.onSurface, borderRadius: radius.lg, padding: spacing.lg },
  sh: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md },
  subLab: { fontSize: fs.sm, color: colors.muted },
  pendRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: "#333" },
  riskDot: { width: 10, height: 10, borderRadius: 5 },
  pendAgent: { color: "#fff", fontWeight: "700", fontSize: fs.base },
  pendAction: { color: "#B8B8BD", fontSize: fs.sm, marginTop: 2 },
  pendCap: { color: "#8E8E93", fontSize: fs.sm, marginTop: 2 },
  sectionRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginTop: spacing["2xl"], marginBottom: spacing.md },
  agentCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginBottom: spacing.md },
  agentTop: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  agentName: { color: colors.onSurface, fontWeight: "700", fontSize: fs.lg },
  agentAuthor: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  trust: { alignItems: "center", backgroundColor: "#fff", borderRadius: radius.sm, padding: spacing.sm, minWidth: 56 },
  trustVal: { color: colors.onSurface, fontSize: fs.xl, fontWeight: "800" },
  trustLab: { color: colors.muted, fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5 },
  caps: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.md, alignItems: "center" },
  cap: { backgroundColor: "#fff", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1, borderColor: colors.border },
  capT: { color: colors.onSurface, fontSize: fs.sm, fontFamily: "monospace" },
  capMore: { color: colors.muted, fontSize: fs.sm },
});
