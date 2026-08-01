import React, { useCallback, useEffect, useState } from "react";
import { View, Text, ScrollView, StyleSheet, Pressable, RefreshControl, ActivityIndicator } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import Ring from "@/src/components/Ring";

type Console = {
  greeting_name: string;
  brain_activity: number;
  inbox: number;
  new_knowledge: number;
  council_recommendations: number;
  decisions_pending: number;
  opportunities: number;
  compounding_delta: number;
  pocket_score: {
    knowledge_assets: number; connections: number; reusable: number;
    decisions_preserved: number; ideas_implemented: number;
    compounding: number; cognitive_capacity_delta: number;
  };
  focus: { title: string; gravity: number; note_id: string | null };
};

export default function ConsoleScreen() {
  const { token, user, logout } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<Console | null>(null);
  const [missions, setMissions] = useState<Mission[]>([]);
  const [opps, setOpps] = useState<Opp[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [seeding, setSeeding] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const c = await api<Console>("/api/console", { token });
      setData(c);
      if (c.inbox === 0 && !seeding) {
        setSeeding(true);
        try { await api("/api/seed-demo", { method: "POST", token }); } catch {}
        const c2 = await api<Console>("/api/console", { token });
        setData(c2);
        setSeeding(false);
      }
      const [m, o] = await Promise.all([
        api<Mission[]>("/api/missions", { token }),
        api<Opp[]>("/api/opportunities", { token }),
      ]);
      setMissions(m); setOpps(o);
    } catch {}
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const onRefresh = async () => { setRefreshing(true); await load(); setRefreshing(false); };

  if (!data) return (
    <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} color={colors.onSurface} /></SafeAreaView>
  );

  const stats = [
    { icon: "mail-outline", label: "Inbox", val: data.inbox, testID: "stat-inbox" },
    { icon: "link-outline", label: "New Knowledge", val: data.new_knowledge, suffix: " links", testID: "stat-new-knowledge" },
    { icon: "people-outline", label: "AI Council", val: data.council_recommendations, suffix: " recs", testID: "stat-council" },
    { icon: "alert-circle-outline", label: "Decisions Pending", val: data.decisions_pending, testID: "stat-decisions" },
    { icon: "bulb-outline", label: "Opportunities", val: data.opportunities, testID: "stat-opps" },
    { icon: "trending-up", label: "Compounding", val: `+${data.compounding_delta}%`, testID: "stat-compounding" },
  ];

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="console-screen">
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.onSurface} />}
      >
        <View style={styles.header}>
          <View style={{ flex: 1 }}>
            <Text style={styles.osTag}>POCKET OS · COMMAND CENTER</Text>
            <Text style={styles.name}>{data.greeting_name || user?.name || "you"}.</Text>
          </View>
          <Pressable onPress={logout} hitSlop={12} testID="logout-btn">
            <Ionicons name="log-out-outline" size={22} color={colors.muted} />
          </Pressable>
        </View>

        <View style={styles.brainCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.brainLab}>Brain Activity</Text>
            <Text style={styles.brainVal}>{data.brain_activity}%</Text>
            <Text style={styles.brainSub}>Cognitive capacity ↑ +{data.pocket_score.cognitive_capacity_delta}% this week</Text>
          </View>
          <Ring size={110} strokeWidth={11} percent={data.brain_activity} color={colors.onSurface} />
        </View>

        <View style={styles.grid}>
          {stats.map((st) => (
            <View key={st.label} style={styles.tile} testID={st.testID}>
              <Ionicons name={st.icon as any} size={18} color={colors.muted} />
              <Text style={styles.tileVal}>{typeof st.val === "number" ? st.val : st.val}{st.suffix || ""}</Text>
              <Text style={styles.tileLab}>{st.label}</Text>
            </View>
          ))}
        </View>

        {missions.length > 0 ? (
          <Pressable
            style={styles.focusCard}
            onPress={() => router.push({ pathname: "/note/[id]", params: { id: missions[0].note_id } })}
            testID="mission-card"
          >
            <View style={styles.focusRow}>
              <Text style={styles.focusLab}>Today's Mission</Text>
              <View style={styles.gravityBadge}>
                <Text style={styles.gravityText}>{missions[0].progress}% · +{missions[0].reward}</Text>
              </View>
            </View>
            <Text style={styles.focusTitle}>{missions[0].title.replace(/^Complete '(.*)'$/, "$1")}</Text>
            <View style={{ marginTop: spacing.md, gap: 4 }}>
              {missions[0].checklist.map((c, i) => (
                <View key={i} style={styles.checkRow} testID={`mission-check-${i}`}>
                  <Ionicons name={c.done ? "checkmark-circle" : "ellipse-outline"} size={16} color={c.done ? "#7BE38B" : "#B8B8BD"} />
                  <Text style={[styles.checkT, c.done && { color: "#B8B8BD", textDecorationLine: "line-through" }]}>{c.label}</Text>
                </View>
              ))}
            </View>
          </Pressable>
        ) : null}

        {opps.length > 0 ? (
          <View style={styles.oppWrap}>
            <View style={styles.oppHead}>
              <Text style={styles.oppH}>Opportunity Engine</Text>
              <Text style={styles.oppSub}>{opps.length} gaps detected</Text>
            </View>
            {opps.slice(0, 4).map((o, i) => (
              <Pressable
                key={i}
                style={styles.oppRow}
                testID={`opportunity-${i}`}
                onPress={() => o.kind !== "unlinked_concept" && router.push({ pathname: "/note/[id]", params: { id: o.target_id } })}
              >
                <View style={styles.oppIcon}>
                  <Ionicons name="bulb-outline" size={16} color={colors.onSurface} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.oppTitle}>{o.title}</Text>
                  <Text style={styles.oppSuggest}>{o.suggestion}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        ) : null}

        <View style={styles.pocket}>
          <Text style={styles.pocketH}>Pocket Score</Text>
          <View style={styles.pocketRow}>
            <View style={styles.pocketMetric}>
              <Text style={styles.pocketVal}>{data.pocket_score.knowledge_assets}</Text>
              <Text style={styles.pocketLab}>Knowledge Assets</Text>
            </View>
            <View style={styles.pocketMetric}>
              <Text style={styles.pocketVal}>{data.pocket_score.connections}</Text>
              <Text style={styles.pocketLab}>Connections</Text>
            </View>
          </View>
          <View style={styles.pocketRow}>
            <View style={styles.pocketMetric}>
              <Text style={styles.pocketVal}>{data.pocket_score.decisions_preserved}</Text>
              <Text style={styles.pocketLab}>Decisions Preserved</Text>
            </View>
            <View style={styles.pocketMetric}>
              <Text style={styles.pocketVal}>{data.pocket_score.ideas_implemented}</Text>
              <Text style={styles.pocketLab}>Ideas Implemented</Text>
            </View>
          </View>
          <View style={styles.compoundBar}>
            <Text style={styles.compoundLab}>Knowledge Compounding</Text>
            <Text style={styles.compoundVal}>{data.pocket_score.compounding}%</Text>
          </View>
        </View>

        <Pressable style={styles.newCta} onPress={() => router.push("/note/new")} testID="new-capture-btn">
          <Ionicons name="add-circle" size={22} color="#fff" />
          <Text style={styles.newCtaT}>New Capture</Text>
        </Pressable>

        <Pressable style={styles.govCta} onPress={() => router.push("/governance")} testID="open-governance-btn">
          <View style={{ flex: 1 }}>
            <Text style={styles.govLab}>Constitutional Layer</Text>
            <Text style={styles.govTitle}>Governance</Text>
            <Text style={styles.govSub}>Agents · Leases · Contracts · Approvals</Text>
          </View>
          <Ionicons name="shield-checkmark-outline" size={28} color={colors.onSurface} />
        </Pressable>

        <Pressable style={styles.govCta} onPress={() => router.push("/chat")} testID="open-chat-btn">
          <View style={{ flex: 1 }}>
            <Text style={styles.govLab}>GEMINI 3 FLASH</Text>
            <Text style={styles.govTitle}>AI Chat</Text>
            <Text style={styles.govSub}>Streaming multi-turn conversation.</Text>
          </View>
          <Ionicons name="chatbubbles-outline" size={28} color={colors.onSurface} />
        </Pressable>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  s: { padding: spacing.xl, paddingBottom: 120 },
  header: { flexDirection: "row", alignItems: "center", marginBottom: spacing.lg },
  osTag: { fontSize: 10, color: colors.muted, letterSpacing: 1.5, fontWeight: "700" },
  name: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  checkT: { color: "#fff", fontSize: fs.base },
  oppWrap: { marginTop: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg },
  oppHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginBottom: spacing.md },
  oppH: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  oppSub: { fontSize: fs.sm, color: colors.muted },
  oppRow: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderTopWidth: 1, borderTopColor: colors.border },
  oppIcon: { width: 32, height: 32, borderRadius: 16, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  oppTitle: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  oppSuggest: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  brainCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.md, gap: spacing.md },
  brainLab: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  brainVal: { fontSize: fs["4xl"], fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  brainSub: { color: colors.onSurfaceTertiary, fontSize: fs.sm, marginTop: 4 },
  grid: { flexDirection: "row", flexWrap: "wrap", marginTop: spacing.lg, gap: spacing.md },
  tile: { flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, gap: 4 },
  tileVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface, marginTop: spacing.xs },
  tileLab: { color: colors.muted, fontSize: fs.sm },
  focusCard: { backgroundColor: colors.onSurface, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.lg },
  focusRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  focusLab: { color: "#B8B8BD", fontSize: fs.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  gravityBadge: { backgroundColor: "#FFFFFF20", borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  gravityText: { color: "#fff", fontSize: fs.sm, fontWeight: "700" },
  focusTitle: { color: "#fff", fontSize: fs["2xl"], fontWeight: "800", marginTop: spacing.md },
  focusCta: { color: "#B8B8BD", marginTop: spacing.md },
  pocket: { marginTop: spacing.xl, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl },
  pocketH: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md },
  pocketRow: { flexDirection: "row", justifyContent: "space-between", marginTop: spacing.md },
  pocketMetric: { flex: 1 },
  pocketVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface },
  pocketLab: { fontSize: fs.sm, color: colors.muted, marginTop: 2 },
  compoundBar: { marginTop: spacing.lg, paddingTop: spacing.md, borderTopWidth: 1, borderTopColor: colors.border, flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  compoundLab: { color: colors.onSurfaceSecondary, fontSize: fs.base },
  compoundVal: { color: colors.success, fontSize: fs.xl, fontWeight: "800" },
  newCta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.sm, backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, marginTop: spacing.xl },
  newCtaT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  govCta: { flexDirection: "row", alignItems: "center", gap: spacing.md, backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md, marginTop: spacing.md, borderWidth: 1, borderColor: colors.border },
  govLab: { fontSize: 10, color: colors.muted, letterSpacing: 1.2, fontWeight: "700" },
  govTitle: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  govSub: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
});
