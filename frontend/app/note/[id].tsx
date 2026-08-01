import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs, agentColorMap } from "@/src/theme";
import Ring from "@/src/components/Ring";

type Note = {
  id: string; title: string; text: string; concepts: string[]; gravity: number;
  revenue: number; produced_projects: number; produced_tasks: number;
  produced_articles: number; produced_proposals: number; created_at: string;
};
type Version = { id: string; version: number; stage: string; text: string; created_at: string };
type Council = { agent: string; color_key: string; response: string };
type Decision = { id: string; number: number; title: string; affected_projects: number; produced_tasks: number; referenced_notes: number; influenced_agents: number; context_hash?: string; reasoning_hash?: string; governance_hash?: string; outcome_hash?: string; dna_root?: string };
type Operation = { id: string; command: string; label: string; output: string; created_at: string };

const OP_COMMANDS: { cmd: string; label: string; icon: string }[] = [
  { cmd: "summarize", label: "Summarize", icon: "reader-outline" },
  { cmd: "refactor", label: "Refactor", icon: "construct-outline" },
  { cmd: "generate_sop", label: "Generate SOP", icon: "list-outline" },
  { cmd: "find_gaps", label: "Find Gaps", icon: "search-outline" },
  { cmd: "next_actions", label: "Next Actions", icon: "flash-outline" },
];

const DnaRow = ({ label, hash, verified }: { label: string; hash?: string; verified?: boolean }) => (
  <View style={styles.dnaRow}>
    <View style={{ flex: 1 }}>
      <Text style={styles.dnaLabel}>{label}</Text>
      <Text style={styles.dnaHash}>{hash ? hash.slice(0, 20) + "…" : "—"}</Text>
    </View>
    <View style={styles.dnaBadge}>
      <Ionicons name="shield-checkmark" size={12} color={verified ? "#7BE38B" : "#B8B8BD"} />
      <Text style={[styles.dnaBadgeT, { color: verified ? "#7BE38B" : "#B8B8BD" }]}>{verified ? "Verified" : "—"}</Text>
    </View>
  </View>
);

export default function NoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<{ note: Note; versions: Version[]; council: Council[]; decisions: Decision[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(false);
  const [ops, setOps] = useState<Operation[]>([]);
  const [opBusy, setOpBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try { setData(await api(`/api/notes/${id}`, { token })); } catch {}
    try { setOps(await api<Operation[]>(`/api/notes/${id}/operations`, { token })); } catch {}
  }, [token, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const runOperation = async (cmd: string) => {
    setOpBusy(cmd);
    try {
      const r = await api<Operation>(`/api/notes/${id}/operations`, { method: "POST", token, body: JSON.stringify({ command: cmd }) });
      setOps((prev) => [r, ...prev]);
    } catch (e: any) { alert(e.message); } finally { setOpBusy(null); }
  };

  const runAllOperations = async () => {
    setOpBusy("all");
    try {
      const results: Operation[] = [];
      for (const c of OP_COMMANDS) {
        try {
          const r = await api<Operation>(`/api/notes/${id}/operations`, { method: "POST", token, body: JSON.stringify({ command: c.cmd }) });
          results.push(r);
          setOps((prev) => [r, ...prev]);
        } catch {}
      }
    } finally { setOpBusy(null); }
  };

  const chatAboutNote = async () => {
    try {
      const s = await api<{ id: string }>(`/api/chat/sessions`, {
        method: "POST", token,
        body: JSON.stringify({ note_context_id: id }),
      });
      router.push({ pathname: "/chat/[id]", params: { id: s.id } });
    } catch (e: any) { alert(e.message); }
  };

  const runCouncil = async () => {
    setBusy(true);
    try {
      await api(`/api/notes/${id}/council`, { method: "POST", token });
      await load();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  };

  const createDecision = async () => {
    try {
      await api(`/api/decisions`, { method: "POST", token, body: JSON.stringify({ title: `Decision from: ${data?.note.title}`, note_id: id }) });
      await load();
    } catch (e: any) { alert(e.message); }
  };

  const evolve = async () => {
    try {
      await api(`/api/notes/${id}/evolve`, { method: "POST", token, body: JSON.stringify({ text: data?.note.text || "" }) });
      await load();
    } catch (e: any) { alert(e.message); }
  };

  if (!data) return <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} /></SafeAreaView>;
  const { note, versions, council, decisions } = data;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="note-detail-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle} numberOfLines={1}>Note</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} />}
      >
        <Text style={styles.title}>{note.title}</Text>
        <Text style={styles.time}>{dayjs(note.created_at).format("MMM D · HH:mm")}</Text>
        <Text style={styles.body}>{note.text}</Text>

        <View style={styles.chips}>
          {note.concepts.map(c => (<View key={c} style={styles.chip}><Text style={styles.chipT}>{c}</Text></View>))}
        </View>

        <View style={styles.gravCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.lab}>Memory Gravity</Text>
            <Text style={styles.gravVal}>{note.gravity}</Text>
            <Text style={styles.sub}>How much this idea pulls the rest of your knowledge.</Text>
          </View>
          <Ring size={90} strokeWidth={10} percent={note.gravity} color={colors.onSurface} />
        </View>

        <Pressable style={styles.chatAboutBtn} onPress={chatAboutNote} testID="chat-about-note">
          <Ionicons name="chatbubbles-outline" size={18} color="#fff" />
          <Text style={styles.chatAboutT}>Chat about this note</Text>
        </Pressable>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <View style={{ flex: 1 }}>
              <Text style={styles.sh}>Operations</Text>
              <Text style={styles.subDim}>Issue commands to Pocket OS.</Text>
            </View>
            <Pressable
              style={[styles.smallBtn, opBusy === "all" && { opacity: 0.6 }]}
              onPress={runAllOperations}
              disabled={!!opBusy}
              testID="run-all-ops"
            >
              {opBusy === "all" ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={styles.smallBtnT}>Run all</Text>
              )}
            </Pressable>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md }} contentContainerStyle={{ gap: spacing.sm, paddingRight: spacing.md }}>
            {OP_COMMANDS.map(op => (
              <Pressable
                key={op.cmd}
                style={[styles.opChip, opBusy === op.cmd && { opacity: 0.6 }]}
                onPress={() => runOperation(op.cmd)}
                disabled={!!opBusy}
                testID={`op-${op.cmd}`}
              >
                {opBusy === op.cmd ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name={op.icon as any} size={14} color="#fff" />}
                <Text style={styles.opChipT}>{op.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
          {ops.length === 0 ? null : (
            <View style={{ marginTop: spacing.md, gap: spacing.md }}>
              {ops.slice(0, 5).map(o => (
                <View key={o.id} style={styles.opResult} testID={`op-result-${o.command}`}>
                  <View style={styles.opResultHead}>
                    <Text style={styles.opResultLab}>{o.label}</Text>
                    <Text style={styles.opResultTime}>{dayjs(o.created_at).format("HH:mm")}</Text>
                  </View>
                  <Text style={styles.opResultT}>{o.output}</Text>
                </View>
              ))}
            </View>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>AI Council</Text>
            <Pressable onPress={runCouncil} disabled={busy} style={styles.smallBtn} testID="run-council">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.smallBtnT}>{council.length ? "Rerun" : "Convene"}</Text>}
            </Pressable>
          </View>
          {council.length === 0 ? (
            <Text style={styles.subDim}>Five specialists (Research, Architect, Critic, Planner, Doc Steward) will review this note.</Text>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md }} contentContainerStyle={{ gap: spacing.md, paddingRight: spacing.md }}>
              {council.map((r, i) => (
                <View key={i} style={[styles.agentCard, { borderTopColor: agentColorMap[r.color_key] || colors.onSurface }]} testID={`council-${r.agent}`}>
                  <View style={[styles.agentDot, { backgroundColor: agentColorMap[r.color_key] || colors.onSurface }]} />
                  <Text style={styles.agentName}>{r.agent}</Text>
                  <Text style={styles.agentText}>{r.response}</Text>
                </View>
              ))}
            </ScrollView>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Idea Evolution</Text>
            <Pressable onPress={evolve} style={styles.smallBtn} testID="evolve-btn">
              <Text style={styles.smallBtnT}>Evolve</Text>
            </Pressable>
          </View>
          <View style={{ marginTop: spacing.md }}>
            {versions.map((v, i) => (
              <View key={v.id} style={styles.vRow}>
                <View style={styles.vCol}>
                  <View style={styles.vDot} />
                  {i < versions.length - 1 ? <View style={styles.vLine} /> : null}
                </View>
                <View style={{ flex: 1, paddingBottom: spacing.md }}>
                  <Text style={styles.vStage}>v{v.version} · {v.stage}</Text>
                  <Text style={styles.vTime}>{dayjs(v.created_at).format("MMM D HH:mm")}</Text>
                </View>
              </View>
            ))}
          </View>
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Decision DNA</Text>
            <Pressable onPress={createDecision} style={styles.smallBtn} testID="create-decision">
              <Text style={styles.smallBtnT}>Log Decision</Text>
            </Pressable>
          </View>
          {decisions.length === 0 ? (
            <Text style={styles.subDim}>Turn this note into a tracked decision to see its downstream lineage.</Text>
          ) : decisions.map(d => (
            <View key={d.id} style={styles.decCard} testID={`decision-${d.id}`}>
              <Text style={styles.decNum}>Decision #{d.number}</Text>
              <Text style={styles.decTitle}>{d.title}</Text>
              <View style={styles.decGrid}>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.affected_projects}</Text><Text style={styles.decLab}>Projects</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.produced_tasks}</Text><Text style={styles.decLab}>Tasks</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.referenced_notes}</Text><Text style={styles.decLab}>Notes</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.influenced_agents}</Text><Text style={styles.decLab}>Agents</Text></View>
              </View>
              {d.dna_root ? (
                <View style={styles.dnaBox}>
                  <Text style={styles.dnaHeader}>Decision DNA</Text>
                  <DnaRow label="Context" hash={d.context_hash} verified />
                  <DnaRow label="Reasoning" hash={d.reasoning_hash} verified />
                  <DnaRow label="Governance" hash={d.governance_hash} verified />
                  <DnaRow label="Outcome" hash={d.outcome_hash} verified />
                  <View style={styles.dnaRoot}>
                    <Text style={styles.dnaRootLab}>DNA ROOT</Text>
                    <Text style={styles.dnaRootHash}>{d.dna_root.slice(0, 40)}…</Text>
                  </View>
                </View>
              ) : null}
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Knowledge ROI</Text>
          <View style={styles.roiGrid}>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_projects}</Text><Text style={styles.roiLab}>Projects</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_tasks}</Text><Text style={styles.roiLab}>Tasks</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_articles}</Text><Text style={styles.roiLab}>Articles</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_proposals}</Text><Text style={styles.roiLab}>Proposals</Text></View>
            <View style={[styles.roiTile, { flexBasis: "100%", backgroundColor: colors.onSurface }]}>
              <Text style={[styles.roiVal, { color: "#fff" }]}>${note.revenue.toLocaleString()}</Text>
              <Text style={[styles.roiLab, { color: "#B8B8BD" }]}>Attributed Revenue</Text>
            </View>
          </View>
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
  title: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  time: { color: colors.muted, marginTop: 4, fontSize: fs.sm },
  body: { fontSize: fs.lg, color: colors.onSurface, marginTop: spacing.md, lineHeight: 24 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.md },
  chip: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  chipT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  gravCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.xl, gap: spacing.md },
  lab: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  gravVal: { fontSize: fs["4xl"], fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  sub: { color: colors.onSurfaceTertiary, fontSize: fs.sm, marginTop: 4 },
  subDim: { color: colors.muted, fontSize: fs.base, marginTop: 8 },
  section: { marginTop: spacing["2xl"] },
  sh: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  smallBtn: { backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill },
  smallBtnT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  agentCard: { width: 240, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderTopWidth: 3, gap: 6 },
  agentDot: { width: 8, height: 8, borderRadius: 4 },
  agentName: { fontWeight: "700", color: colors.onSurface, fontSize: fs.base },
  agentText: { color: colors.onSurfaceSecondary, fontSize: fs.sm, lineHeight: 18 },
  vRow: { flexDirection: "row", gap: spacing.md },
  vCol: { width: 20, alignItems: "center" },
  vDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.onSurface, marginTop: 4 },
  vLine: { flex: 1, width: 1, backgroundColor: colors.border },
  vStage: { fontSize: fs.base, fontWeight: "700", color: colors.onSurface },
  vTime: { fontSize: fs.sm, color: colors.muted },
  decCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginTop: spacing.md },
  decNum: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase" },
  decTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface, marginTop: 2 },
  decGrid: { flexDirection: "row", flexWrap: "wrap", marginTop: spacing.md, gap: spacing.sm },
  decMetric: { flexBasis: "47%", flexGrow: 1, backgroundColor: "#fff", padding: spacing.md, borderRadius: radius.sm },
  decVal: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  decLab: { fontSize: fs.sm, color: colors.muted },
  roiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.md },
  roiTile: { flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  roiVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface },
  roiLab: { fontSize: fs.sm, color: colors.muted, marginTop: 4 },
  opChip: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.pill },
  opChipT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  opResult: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  opResultHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  opResultLab: { color: colors.muted, fontSize: fs.sm, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  opResultTime: { color: colors.muted, fontSize: fs.sm },
  opResultT: { color: colors.onSurface, fontSize: fs.base, lineHeight: 22 },
  chatAboutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.onSurface, padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md },
  chatAboutT: { color: "#fff", fontSize: fs.base, fontWeight: "700" },
  dnaBox: { marginTop: spacing.md, backgroundColor: "#0F0F10", borderRadius: radius.sm, padding: spacing.md, gap: 6 },
  dnaHeader: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.5, fontWeight: "700", marginBottom: 4 },
  dnaRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#222" },
  dnaLabel: { color: "#fff", fontSize: fs.sm, fontWeight: "700" },
  dnaHash: { color: "#8E8E93", fontSize: 10, fontFamily: "monospace", marginTop: 2 },
  dnaBadge: { flexDirection: "row", alignItems: "center", gap: 4 },
  dnaBadgeT: { fontSize: 10, fontWeight: "700" },
  dnaRoot: { marginTop: 6, alignItems: "center", paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: "#333" },
  dnaRootLab: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  dnaRootHash: { color: "#7BE38B", fontFamily: "monospace", fontSize: 11, marginTop: 4 },
});
