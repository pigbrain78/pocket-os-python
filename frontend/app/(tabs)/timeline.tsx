import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, StyleSheet, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import TimeScrubber from "@/src/components/TimeScrubber";
import BookmarkChips, { Bookmark } from "@/src/components/BookmarkChips";

type Event = { id: string; kind: string; text: string; ref_id?: string; meta?: any; created_at: string };
type Bounds = { earliest?: string | null; latest?: string | null; now?: string };
type Replay = {
  at: string;
  now: string;
  bounds: { earliest: string | null; latest: string | null };
  state: {
    notes_created: number;
    notes_evolved: number;
    concepts_extracted: number;
    connections_made: number;
    memory_strength: number;
    council_runs: number;
    debates_started: number;
    syntheses_ratified: number;
    decisions_made: number;
    open_contradictions: number;
    operations_run: number;
  };
  events_seen: number;
  events_after: number;
};

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

  // Replay state
  const [bounds, setBounds] = useState<Bounds>({});
  const [atMs, setAtMs] = useState<number>(Date.now());
  const [replay, setReplay] = useState<Replay | null>(null);
  const [replayLoading, setReplayLoading] = useState(false);

  // Bookmarks
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([]);
  const [bookmarkSaving, setBookmarkSaving] = useState(false);
  const [bookmarkError, setBookmarkError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const [evs, bnds, bms] = await Promise.all([
        api<Event[]>("/api/timeline", { token }),
        api<Bounds>("/api/replay/bounds", { token }),
        api<Bookmark[]>("/api/replay/bookmarks", { token }),
      ]);
      setEvents(evs);
      setBounds(bnds);
      setBookmarks(bms);
      // Anchor at "latest" so first render is LIVE.
      if (bnds.latest) setAtMs(dayjs(bnds.latest).valueOf());
    } finally {
      setLoading(false);
    }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const fetchReplay = useCallback(
    async (ms: number | null) => {
      if (!token) return;
      setReplayLoading(true);
      try {
        // ms=null means "LIVE" — omit `at` so the server uses its own now with
        // full precision, avoiding millisecond truncation vs stored timestamps.
        const path = ms == null ? "/api/replay" : `/api/replay?at=${encodeURIComponent(new Date(ms).toISOString())}`;
        const r = await api<Replay>(path, { token });
        setReplay(r);
      } catch {
        // Silent — LIVE view remains valid.
      } finally {
        setReplayLoading(false);
      }
    },
    [token]
  );

  // Fetch initial replay after bounds are known (shows the "LIVE" snapshot).
  useEffect(() => {
    if (bounds.latest) {
      fetchReplay(null);
    }
  }, [bounds.latest, fetchReplay]);

  const returnToNow = () => {
    if (!bounds.latest) return;
    const ms = dayjs(bounds.latest).valueOf();
    setAtMs(ms);
    fetchReplay(null);
  };

  const jumpTo = (ms: number) => {
    setAtMs(ms);
    // If the target is essentially "now" (within 1s of the latest event),
    // omit `at` on the fetch so the server uses full-precision now — otherwise
    // millisecond truncation vs stored µs timestamps leaves 1 event orphaned
    // in "still to come" and the LIVE pill never re-appears.
    const latestMs = bounds.latest ? dayjs(bounds.latest).valueOf() : null;
    if (latestMs != null && Math.abs(latestMs - ms) < 1000) {
      fetchReplay(null);
    } else {
      fetchReplay(ms);
    }
  };

  const saveBookmark = async (label: string, atIso: string) => {
    if (!token) return;
    setBookmarkError(null);
    setBookmarkSaving(true);
    try {
      const bookmarkAt = isLive && bounds.latest ? bounds.latest : atIso;
      const created = await api<Bookmark>("/api/replay/bookmarks", {
        token,
        method: "POST",
        body: JSON.stringify({ label, at: bookmarkAt }),
      });
      // Insert in descending order by `at` to match server ordering.
      setBookmarks((prev) => [created, ...prev].sort((a, b) => (a.at < b.at ? 1 : -1)));
    } catch (e: any) {
      setBookmarkError(e?.message || "Save failed");
      throw e;
    } finally {
      setBookmarkSaving(false);
    }
  };

  const deleteBookmark = async (id: string) => {
    if (!token) return;
    try {
      await api(`/api/replay/bookmarks/${encodeURIComponent(id)}`, {
        token,
        method: "DELETE",
      });
      setBookmarks((prev) => prev.filter((b) => b.id !== id));
    } catch {
      // silent
    }
  };

  const isLive = replay ? replay.events_after === 0 : true;

  // Group events by day for the visual timeline, but let each event carry a
  // "past/future" flag relative to atMs so we can dim events beyond the
  // scrubber head without hiding them (users still see what's coming).
  const groups: Record<string, Event[]> = {};
  events.forEach(e => {
    const day = dayjs(e.created_at).format("YYYY-MM-DD");
    if (!groups[day]) groups[day] = [];
    groups[day].push(e);
  });

  const s = replay?.state;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="timeline-screen">
      <View style={styles.head}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Timeline</Text>
          <Text style={styles.sub}>Every thought. Every link. Chronological.</Text>
        </View>
        <Pressable style={styles.ledgerBtn} onPress={() => router.push("/ledger")} testID="open-ledger">
          <Ionicons name="shield-checkmark" size={14} color="#fff" />
          <Text style={styles.ledgerBtnT}>Ledger</Text>
        </Pressable>
      </View>

      {/* Replay card + scrubber. Only rendered when we actually have history. */}
      {bounds.earliest && bounds.latest ? (
        <View style={styles.replayCard} testID="replay-card">
          <View style={styles.replayHeader}>
            <View style={{ flex: 1 }}>
              <Text style={styles.replayLabel}>REALITY AS OF</Text>
              <Text style={styles.replayTs} testID="replay-timestamp">
                {isLive ? "Now" : dayjs(atMs).format("ddd, MMM D · HH:mm")}
              </Text>
            </View>
            {replayLoading ? <ActivityIndicator size="small" color={colors.onSurface} /> : null}
          </View>
          {s ? (
            <View style={styles.metricGrid}>
              <Metric icon="document-text-outline" label="Notes" value={s.notes_created} testID="metric-notes" />
              <Metric icon="pulse" label="Memory" value={`${s.memory_strength}%`} testID="metric-memory" />
              <Metric icon="flag-outline" label="Decisions" value={s.decisions_made} testID="metric-decisions" />
              <Metric icon="people-outline" label="Council" value={s.council_runs} testID="metric-council" />
              <Metric icon="git-network-outline" label="Debates" value={s.debates_started} testID="metric-debates" />
              <Metric
                icon="warning-outline"
                label="Contradictions"
                value={s.open_contradictions}
                warn={s.open_contradictions > 0}
                testID="metric-contradictions"
              />
            </View>
          ) : null}
          <TimeScrubber
            bounds={bounds}
            atMs={atMs}
            onChange={setAtMs}
            onCommit={fetchReplay}
            onReturnToNow={returnToNow}
          />
          <BookmarkChips
            bookmarks={bookmarks}
            atMs={atMs}
            isLive={isLive}
            onSelect={(b) => jumpTo(dayjs(b.at).valueOf())}
            onAdd={saveBookmark}
            onDelete={deleteBookmark}
            saveBusy={bookmarkSaving}
            saveError={bookmarkError}
          />
          {!isLive ? (
            <Text style={styles.replayFoot} testID="replay-footer">
              {replay?.events_seen ?? 0} events at or before this moment ·{" "}
              {replay?.events_after ?? 0} still to come
            </Text>
          ) : null}
        </View>
      ) : null}

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
              const evMs = dayjs(e.created_at).valueOf();
              const isFuture = !isLive && evMs > atMs;
              return (
                <Pressable
                  key={e.id}
                  style={[styles.row, isFuture && styles.rowFuture]}
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
                      {isFuture ? <Text style={styles.futureTag}>· not yet</Text> : null}
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

function Metric({
  icon, label, value, warn, testID,
}: { icon: string; label: string; value: number | string; warn?: boolean; testID?: string }) {
  return (
    <View style={styles.metric} testID={testID}>
      <Ionicons name={icon as any} size={14} color={warn ? colors.error : colors.muted} />
      <Text style={styles.metricLab}>{label}</Text>
      <Text style={[styles.metricVal, warn && { color: colors.error }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.md, backgroundColor: colors.surface },
  ledgerBtn: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.onSurface, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999 },
  ledgerBtnT: { color: "#fff", fontWeight: "800", fontSize: fs.sm },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 2 },

  replayCard: {
    marginHorizontal: spacing.xl,
    marginBottom: spacing.md,
    padding: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    gap: spacing.sm,
  },
  replayHeader: { flexDirection: "row", alignItems: "center" },
  replayLabel: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.6 },
  replayTs: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  replayFoot: { fontSize: fs.sm, color: colors.muted, textAlign: "center", paddingTop: spacing.xs },

  metricGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.xs },
  metric: {
    minWidth: 100,
    flexGrow: 1,
    flexBasis: "30%",
    backgroundColor: colors.surface,
    borderRadius: radius.sm,
    paddingVertical: 8,
    paddingHorizontal: 10,
  },
  metricLab: { fontSize: fs.sm, color: colors.muted, marginTop: 2, textTransform: "uppercase", letterSpacing: 0.4 },
  metricVal: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginTop: 2 },

  s: { paddingHorizontal: spacing.xl, paddingBottom: 140 },
  day: { fontSize: fs.sm, color: colors.muted, marginBottom: spacing.md, textTransform: "uppercase", letterSpacing: 0.6 },
  row: { flexDirection: "row", gap: spacing.md },
  rowFuture: { opacity: 0.3 },
  timeCol: { width: 60, alignItems: "center" },
  time: { fontSize: fs.sm, color: colors.muted, marginBottom: 4 },
  dotLine: { flex: 1, alignItems: "center" },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 4 },
  line: { flex: 1, width: 1, backgroundColor: colors.border, marginTop: 4 },
  card: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md },
  kind: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  futureTag: { fontSize: fs.sm, color: colors.muted, fontStyle: "italic" },
  text: { fontSize: fs.base, color: colors.onSurface, marginTop: 4 },
  strength: { marginTop: 8, gap: 4 },
  bar: { height: 4, backgroundColor: colors.border, borderRadius: 2, overflow: "hidden" },
  barFill: { height: 4, backgroundColor: colors.success },
  strengthT: { fontSize: fs.sm, color: colors.success, fontWeight: "700" },
  empty: { textAlign: "center", color: colors.muted, marginTop: 60 },
  fab: { position: "absolute", right: spacing.xl, bottom: 100, width: 56, height: 56, borderRadius: 28, backgroundColor: colors.onSurface, alignItems: "center", justifyContent: "center", shadowColor: "#000", shadowOpacity: 0.15, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6 },
});
