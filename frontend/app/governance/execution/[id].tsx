import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Alert, Platform } from "react-native";
import { useRouter, useLocalSearchParams, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import dayjs from "dayjs";

type Execution = {
  id: string;
  agent_id: string;
  agent_name?: string;
  agent_risk?: string;
  action: string;
  capability: string;
  note_id?: string | null;
  lease_id?: string;
  contract_id?: string | null;
  state: string;
  state_history?: { state: string; at: string; by?: string }[];
  evidence?: { outcome: string; hash: string; sealed_at: string } | null;
  created_at: string;
};

const RISK_COLOR: Record<string, string> = { low: "#0E7A2A", medium: "#8A6D00", high: "#B41B10" };

export default function ExecutionDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [exec, setExec] = useState<Execution | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<null | "approve" | "reverse">(null);

  const load = useCallback(async () => {
    if (!token || !id) return;
    setLoading(true);
    try {
      // The pending list gives us all fields we need; fetch that then filter.
      const pending = await api<Execution[]>(`/api/executions/pending`, { token });
      const found = pending.find((e) => e.id === id);
      if (found) setExec(found);
      else {
        // Not pending anymore — pull all executions (best effort)
        try {
          const all = await api<Execution[]>(`/api/executions`, { token });
          const f2 = all.find((e) => e.id === id);
          if (f2) setExec(f2);
        } catch {}
      }
    } finally {
      setLoading(false);
    }
  }, [token, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const notify = (title: string, body: string) => {
    if (Platform.OS === "web") window.alert(`${title}\n\n${body}`);
    else Alert.alert(title, body);
  };

  const approve = async () => {
    if (!exec) return;
    setBusy("approve");
    try {
      const r = await api<{ status: string; evidence: any }>(`/api/executions/${exec.id}/approve`, { method: "POST", token });
      notify("Execution sealed", `Outcome: ${r.evidence?.outcome} · hash ${r.evidence?.hash}`);
      await load();
    } catch (e: any) {
      notify("Approval failed", e.message || "unknown");
    } finally {
      setBusy(null);
    }
  };

  const reverse = async () => {
    if (!exec) return;
    setBusy("reverse");
    try {
      await api(`/api/executions/${exec.id}/reverse`, { method: "POST", token });
      notify("Execution reversed", "Recorded in ledger as reversed. Agent trust score updated.");
      await load();
    } catch (e: any) {
      notify("Reversal failed", e.message || "unknown");
    } finally {
      setBusy(null);
    }
  };

  if (loading) return (
    <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} color={colors.onSurface} /></SafeAreaView>
  );
  if (!exec) return (
    <SafeAreaView style={styles.c} edges={["top"]}>
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="exec-back"><Ionicons name="chevron-back" size={26} color={colors.onSurface} /></Pressable>
        <Text style={styles.hTitle}>Execution</Text><View style={{ width: 26 }} />
      </View>
      <Text style={styles.empty}>Execution not found or no longer pending.</Text>
    </SafeAreaView>
  );

  const isPending = exec.state === "PROPOSED" || exec.state === "APPROVED";
  const isExecuted = exec.state === "EXECUTED";
  const isReversed = exec.state === "REVERSED";

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="execution-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="exec-back">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>Execution</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView contentContainerStyle={styles.s}>
        <View style={styles.card}>
          <View style={styles.stateRow}>
            <View style={[styles.statePill, {
              backgroundColor: isPending ? "#FFF4CC" : isExecuted ? "#DCF7DC" : isReversed ? "#FFE9E7" : colors.surfaceSecondary,
            }]}>
              <Text style={[styles.statePillT, {
                color: isPending ? "#8A6D00" : isExecuted ? "#0E7A2A" : isReversed ? "#B41B10" : colors.onSurface,
              }]}>{exec.state}</Text>
            </View>
            <View style={[styles.riskDot, { backgroundColor: RISK_COLOR[exec.agent_risk || "medium"] || colors.muted }]} />
            <Text style={styles.risk}>{(exec.agent_risk || "medium").toUpperCase()} RISK</Text>
          </View>
          <Text style={styles.action}>{exec.action}</Text>
          <Text style={styles.agent}>by {exec.agent_name || exec.agent_id}</Text>
          <View style={styles.metaRow}>
            <Text style={styles.metaLab}>Capability</Text>
            <Text style={styles.metaVal}>{exec.capability}</Text>
          </View>
          <View style={styles.metaRow}>
            <Text style={styles.metaLab}>Proposed</Text>
            <Text style={styles.metaVal}>{dayjs(exec.created_at).format("MMM D, HH:mm")}</Text>
          </View>
          {exec.note_id ? (
            <View style={styles.metaRow}>
              <Text style={styles.metaLab}>Bound note</Text>
              <Pressable onPress={() => router.push({ pathname: "/note/[id]", params: { id: exec.note_id as string } })}>
                <Text style={[styles.metaVal, styles.link]}>{exec.note_id.slice(0, 8)}…</Text>
              </Pressable>
            </View>
          ) : null}
        </View>

        {exec.state_history?.length ? (
          <View style={styles.card}>
            <Text style={styles.cardLab}>STATE HISTORY</Text>
            {exec.state_history.map((h, i) => (
              <View key={i} style={styles.histRow}>
                <View style={styles.histDot} />
                <Text style={styles.histState}>{h.state}</Text>
                <Text style={styles.histAt}>{dayjs(h.at).format("MMM D, HH:mm")}</Text>
                {h.by ? <Text style={styles.histBy}>· {h.by}</Text> : null}
              </View>
            ))}
          </View>
        ) : null}

        {exec.evidence ? (
          <View style={styles.card}>
            <Text style={styles.cardLab}>EXECUTION EVIDENCE</Text>
            <Text style={styles.evRow}><Text style={styles.evK}>Outcome: </Text>{exec.evidence.outcome}</Text>
            <Text style={styles.evRow}><Text style={styles.evK}>Hash: </Text>{exec.evidence.hash}</Text>
            <Text style={styles.evRow}><Text style={styles.evK}>Sealed at: </Text>{dayjs(exec.evidence.sealed_at).format("MMM D, HH:mm:ss")}</Text>
          </View>
        ) : null}

        {isPending ? (
          <Pressable style={styles.approveBtn} onPress={approve} disabled={!!busy} testID="approve-execution">
            {busy === "approve" ? <ActivityIndicator color="#fff" /> : (
              <><Ionicons name="shield-checkmark" size={16} color="#fff" /><Text style={styles.approveT}>Approve & seal execution</Text></>
            )}
          </Pressable>
        ) : null}

        {isExecuted ? (
          <Pressable style={styles.reverseBtn} onPress={reverse} disabled={!!busy} testID="reverse-execution">
            {busy === "reverse" ? <ActivityIndicator color="#B41B10" /> : (
              <><Ionicons name="arrow-undo" size={16} color="#B41B10" /><Text style={styles.reverseT}>Reverse execution</Text></>
            )}
          </Pressable>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.lg, gap: spacing.md, paddingBottom: 60 },
  empty: { color: colors.muted, textAlign: "center", marginTop: 40 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: 4 },
  stateRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  statePill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  statePillT: { fontSize: 11, fontWeight: "800", letterSpacing: 0.5 },
  riskDot: { width: 10, height: 10, borderRadius: 5 },
  risk: { fontSize: 10, fontWeight: "800", letterSpacing: 1, color: colors.muted },
  action: { color: colors.onSurface, fontSize: fs.xl, fontWeight: "800", marginTop: 8 },
  agent: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  metaRow: { flexDirection: "row", justifyContent: "space-between", marginTop: 6 },
  metaLab: { color: colors.muted, fontSize: fs.sm },
  metaVal: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  link: { textDecorationLine: "underline" },
  cardLab: { color: colors.muted, fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginBottom: 6 },
  histRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3 },
  histDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.onSurface },
  histState: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "700", minWidth: 90 },
  histAt: { color: colors.muted, fontSize: fs.sm },
  histBy: { color: colors.muted, fontSize: fs.sm },
  evRow: { color: colors.onSurface, fontSize: fs.sm, fontFamily: "monospace", marginTop: 2 },
  evK: { color: colors.muted, fontWeight: "700" },
  approveBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#0E7A2A", padding: spacing.lg, borderRadius: radius.sm, marginTop: spacing.md },
  approveT: { color: "#fff", fontSize: fs.base, fontWeight: "800" },
  reverseBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#fff", padding: spacing.lg, borderRadius: radius.sm, marginTop: spacing.md, borderWidth: 1, borderColor: "#FFC5C0" },
  reverseT: { color: "#B41B10", fontSize: fs.base, fontWeight: "800" },
});
