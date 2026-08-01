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
type Decision = { id: string; number: number; title: string; affected_projects: number; produced_tasks: number; referenced_notes: number; influenced_agents: number };

export default function NoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<{ note: Note; versions: Version[]; council: Council[]; decisions: Decision[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(false);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try { setData(await api(`/api/notes/${id}`, { token })); } catch {}
  }, [token, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

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
});
