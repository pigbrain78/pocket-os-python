import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Agent = { id: string; name: string; author: string; version: string; manifest: string; risk: string; trust_score: number; capabilities: string[]; public_key: string; stats?: any };
type Lease = { id: string; capabilities: string[]; scope: string; status: string; issued_at: string; expires_at: string };
type Contract = { id: string; name: string; policies: { rule: string; enforced: any }[] };
type Execution = { id: string; action: string; capability: string; state: string; created_at: string; evidence?: any };

const STATE_COLORS: Record<string, string> = {
  PROPOSED: colors.warning, APPROVED: colors.info, EXECUTED: colors.success, REVERSED: colors.error, ARCHIVED: colors.muted,
};
const RISK_COLOR: Record<string, string> = { low: colors.success, medium: colors.warning, high: colors.error };

export default function AgentDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<{ agent: Agent; leases: Lease[]; contracts: Contract[]; executions: Execution[] } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try { setData(await api(`/api/agents/${id}`, { token })); } catch {}
  }, [token, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const proposeAction = async () => {
    setBusy("propose");
    try {
      const cap = data?.agent.capabilities[0] || "memory.read";
      await api(`/api/agents/${id}/executions`, { method: "POST", token, body: JSON.stringify({ action: `Simulated ${cap} action`, capability: cap }) });
      await load();
    } catch (e: any) { alert(e.message); } finally { setBusy(null); }
  };

  const revokeLease = async (lid: string) => {
    setBusy(lid);
    try { await api(`/api/leases/${lid}/revoke`, { method: "POST", token }); await load(); }
    catch (e: any) { alert(e.message); } finally { setBusy(null); }
  };

  const executeAction = async (eid: string) => {
    setBusy(eid);
    try { await api(`/api/executions/${eid}/approve`, { method: "POST", token }); await load(); }
    catch (e: any) { alert(e.message); } finally { setBusy(null); }
  };

  const reverseAction = async (eid: string) => {
    setBusy(eid + "-rev");
    try { await api(`/api/executions/${eid}/reverse`, { method: "POST", token }); await load(); }
    catch (e: any) { alert(e.message); } finally { setBusy(null); }
  };

  if (!data) return <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} /></SafeAreaView>;
  const { agent, leases, contracts, executions } = data;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="agent-detail">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>Agent</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={styles.s}>
        <View style={styles.hero}>
          <View style={{ flex: 1 }}>
            <View style={styles.riskRow}>
              <View style={[styles.riskDot, { backgroundColor: RISK_COLOR[agent.risk] || colors.muted }]} />
              <Text style={styles.riskLab}>{agent.risk.toUpperCase()} RISK · v{agent.version}</Text>
            </View>
            <Text style={styles.name}>{agent.name}</Text>
            <Text style={styles.author}>{agent.author}</Text>
            <Text style={styles.pk} testID="agent-pubkey">{agent.public_key}</Text>
          </View>
          <View style={styles.trust}>
            <Text style={styles.trustVal}>{agent.trust_score}</Text>
            <Text style={styles.trustLab}>TRUST</Text>
          </View>
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Manifest</Text>
          <Text style={styles.manifest}>{agent.manifest}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Declared Capabilities</Text>
          <View style={styles.caps}>
            {agent.capabilities.map(c => (
              <View key={c} style={styles.cap}><Text style={styles.capT}>{c}</Text></View>
            ))}
          </View>
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Capability Leases</Text>
            <Pressable style={styles.smallBtn} onPress={proposeAction} disabled={busy === "propose"} testID="propose-action-btn">
              {busy === "propose" ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.smallBtnT}>Propose action</Text>}
            </Pressable>
          </View>
          {leases.map(l => (
            <View key={l.id} style={styles.leaseCard} testID={`lease-${l.id}`}>
              <View style={styles.rowBetween}>
                <Text style={[styles.leaseStatus, { color: l.status === "active" ? colors.success : colors.error }]}>{l.status.toUpperCase()}</Text>
                {l.status === "active" ? (
                  <Pressable onPress={() => revokeLease(l.id)} disabled={busy === l.id} testID={`revoke-${l.id}`}>
                    <Text style={styles.revokeT}>{busy === l.id ? "…" : "Revoke"}</Text>
                  </Pressable>
                ) : null}
              </View>
              <Text style={styles.leaseCaps}>{l.capabilities.join(", ")}</Text>
              <Text style={styles.leaseMeta}>Scope: {l.scope} · issued {dayjs(l.issued_at).format("MMM D")} · expires {dayjs(l.expires_at).format("MMM D")}</Text>
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Governance Contracts</Text>
          {contracts.map(ct => (
            <View key={ct.id} style={styles.contractCard} testID={`contract-${ct.id}`}>
              <Text style={styles.contractName}>{ct.name}</Text>
              {ct.policies.map((p, i) => (
                <View key={i} style={styles.policyRow}>
                  <Ionicons name={p.enforced ? "checkmark-circle" : "close-circle-outline"} size={16} color={p.enforced ? colors.success : colors.muted} />
                  <Text style={styles.policyT}>{p.rule}</Text>
                </View>
              ))}
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Provenance Ledger</Text>
          {executions.length === 0 ? (
            <Text style={styles.subDim}>No executions yet. Tap "Propose action" to create one.</Text>
          ) : executions.map(e => (
            <View key={e.id} style={styles.exCard} testID={`execution-${e.id}`}>
              <View style={styles.rowBetween}>
                <Text style={[styles.exState, { color: STATE_COLORS[e.state] || colors.muted }]}>{e.state}</Text>
                <Text style={styles.exTime}>{dayjs(e.created_at).format("HH:mm")}</Text>
              </View>
              <Text style={styles.exAction}>{e.action}</Text>
              <Text style={styles.exCap}>via {e.capability}</Text>
              {e.evidence ? (
                <View style={styles.evidence}>
                  <Text style={styles.evidenceLab}>Evidence · {e.evidence.hash}</Text>
                </View>
              ) : null}
              <View style={{ flexDirection: "row", gap: 6, marginTop: spacing.sm }}>
                {(e.state === "PROPOSED" || e.state === "APPROVED") ? (
                  <Pressable onPress={() => executeAction(e.id)} disabled={busy === e.id} style={styles.exBtn} testID={`execute-${e.id}`}>
                    {busy === e.id ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.exBtnT}>Approve & Execute</Text>}
                  </Pressable>
                ) : null}
                {e.state === "EXECUTED" ? (
                  <Pressable onPress={() => reverseAction(e.id)} disabled={busy === e.id + "-rev"} style={[styles.exBtn, { backgroundColor: colors.error }]} testID={`reverse-${e.id}`}>
                    {busy === e.id + "-rev" ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.exBtnT}>Reverse</Text>}
                  </Pressable>
                ) : null}
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.xl, paddingBottom: 60 },
  hero: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  riskRow: { flexDirection: "row", alignItems: "center", gap: 6 },
  riskDot: { width: 8, height: 8, borderRadius: 4 },
  riskLab: { fontSize: 10, color: colors.muted, letterSpacing: 1.2, fontWeight: "700" },
  name: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  author: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  pk: { fontFamily: "monospace", fontSize: fs.sm, color: colors.muted, marginTop: 4 },
  trust: { alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, minWidth: 72 },
  trustVal: { color: colors.onSurface, fontSize: fs["2xl"], fontWeight: "800" },
  trustLab: { color: colors.muted, fontSize: 10, letterSpacing: 0.8 },
  section: { marginTop: spacing["2xl"] },
  sh: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md },
  manifest: { color: colors.onSurface, fontSize: fs.base, lineHeight: 22 },
  caps: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  cap: { backgroundColor: colors.surfaceSecondary, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  capT: { fontFamily: "monospace", fontSize: fs.sm, color: colors.onSurface },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  smallBtn: { backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill, minWidth: 100, alignItems: "center" },
  smallBtnT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  leaseCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  leaseStatus: { fontSize: fs.sm, fontWeight: "800", letterSpacing: 0.5 },
  revokeT: { color: colors.error, fontWeight: "700", fontSize: fs.sm },
  leaseCaps: { color: colors.onSurface, fontSize: fs.base, marginTop: 6, fontFamily: "monospace" },
  leaseMeta: { color: colors.muted, fontSize: fs.sm, marginTop: 4 },
  contractCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  contractName: { fontWeight: "700", color: colors.onSurface, fontSize: fs.base, marginBottom: 6 },
  policyRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  policyT: { color: colors.onSurface, fontSize: fs.sm, fontFamily: "monospace" },
  exCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  exState: { fontSize: fs.sm, fontWeight: "800", letterSpacing: 0.5 },
  exTime: { color: colors.muted, fontSize: fs.sm },
  exAction: { color: colors.onSurface, fontSize: fs.base, marginTop: 4, fontWeight: "600" },
  exCap: { color: colors.muted, fontSize: fs.sm, marginTop: 2, fontFamily: "monospace" },
  evidence: { marginTop: 8, paddingTop: 8, borderTopWidth: 1, borderTopColor: colors.border },
  evidenceLab: { color: colors.muted, fontSize: fs.sm, fontFamily: "monospace" },
  exBtn: { backgroundColor: colors.onSurface, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.sm, minWidth: 120, alignItems: "center" },
  exBtnT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  subDim: { color: colors.muted, fontSize: fs.base },
});
