import React, { useCallback, useState } from "react";
import { View, Text, ScrollView, StyleSheet, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Event = { id: string; kind: string; text: string; ref_id?: string; meta?: any; created_at: string };

const kindIcon: Record<string, [string, string]> = {
  note_created: ["document-text-outline", colors.onSurface],
  concepts_extracted: ["sparkles-outline", colors.agentDocSteward],
  linked: ["link-outline", colors.agentPlanner],
  memory_strengthened: ["pulse", colors.success],
  council_convened: ["people-outline", colors.agentArchitect],
  decision_made: ["flag-outline", colors.agentCritic],
  idea_evolved: ["git-branch-outline", colors.info],
};

export default function TimelineScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const [events, setEvents] = useState<Event[]>([]);
  const [refresh, setRefresh] = useState(false);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const evs = await api<Event[]>("/api/timeline", { token });
      setEvents(evs);
    } finally { setLoading(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const groups: Record<string, Event[]> = {};
  events.forEach(e => {
    const day = dayjs(e.created_at).format("YYYY-MM-DD");
    if (!groups[day]) groups[day] = [];
    groups[day].push(e);
  });

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="timeline-screen">
      <View style={styles.head}>
        <Text style={styles.h1}>Timeline</Text>
        <Text style={styles.sub}>Every thought. Every link. Chronological.</Text>
      </View>
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} tintColor={colors.onSurface} />}
      >
        {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.onSurface} /> : null}
        {events.length === 0 && !loading ? (
          <Text style={styles.empty}>Log your first thought to see the replay.</Text>
        ) : null}
        {Object.entries(groups).map(([day, evs]) => (
          <View key={day} style={{ marginBottom: spacing.xl }}>
            <Text style={styles.day}>{dayjs(day).isSame(dayjs(), "day") ? "Today" : dayjs(day).format("dddd, MMM D")}</Text>
            {evs.map((e, i) => {
              const [icon, color] = kindIcon[e.kind] || ["ellipse-outline", colors.muted];
              return (
                <Pressable
                  key={e.id}
                  style={styles.row}
                  onPress={() => e.ref_id && e.kind !== "decision_made" ? router.push({ pathname: "/note/[id]", params: { id: e.ref_id } }) : undefined}
                  testID={`event-${e.kind}-${i}`}
                >
                  <View style={styles.timeCol}>
                    <Text style={styles.time}>{dayjs(e.created_at).format("HH:mm")}</Text>
                    <View style={styles.dotLine}>
                      <View style={[styles.dot, { backgroundColor: color }]} />
                      {i < evs.length - 1 ? <View style={styles.line} /> : null}
                    </View>
                  </View>
                  <View style={styles.card}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                      <Ionicons name={icon as any} size={14} color={color} />
                      <Text style={styles.kind}>{e.kind.replace(/_/g, " ")}</Text>
                    </View>
                    <Text style={styles.text}>{e.text}</Text>
                    {e.meta?.after && e.meta?.before ? (
                      <View style={styles.strength}>
                        <View style={styles.bar}>
                          <View style={[styles.barFill, { width: `${e.meta.after}%` }]} />
                        </View>
                        <Text style={styles.strengthT}>{e.meta.before}% → {e.meta.after}%</Text>
                      </View>
                    ) : null}
                  </View>
                </Pressable>
              );
            })}
          </View>
        ))}
      </ScrollView>
      <Pressable style={styles.fab} onPress={() => router.push("/note/new")} testID="new-capture-fab">
        <Ionicons name="add" size={28} color="#fff" />
      </Pressable>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md, backgroundColor: colors.surface },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 2 },
  s: { paddingHorizontal: spacing.xl, paddingBottom: 140 },
  day: { fontSize: fs.sm, color: colors.muted, marginBottom: spacing.md, textTransform: "uppercase", letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.md },
  timeCol: { width: 60, alignItems: "center" },
  time: { fontSize: fs.sm, color: colors.muted, marginBottom: 4 },
  dotLine: { flex: 1, alignItems: "center" },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 4 },
  line: { flex: 1, width: 1, backgroundColor: colors.border, marginTop: 4 },
  card: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  kind: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  text: { fontSize: fs.base, color: colors.onSurface, marginTop: 4 },
  strength: { marginTop: 8, gap: 4 },
  bar: { height: 4, backgroundColor: colors.border, borderRadius: 2, overflow: "hidden" },
  barFill: { height: 4, backgroundColor: colors.success },
  strengthT: { fontSize: fs.sm, color: colors.success, fontWeight: "700" },
  empty: { textAlign: "center", color: colors.muted, marginTop: 60 },
  fab: { position: "absolute", right: spacing.xl, bottom: 100, width: 56, height: 56, borderRadius: 28, backgroundColor: colors.onSurface, alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6 },
});
