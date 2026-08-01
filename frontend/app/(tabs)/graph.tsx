import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect, useRouter } from "expo-router";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import GraphCanvas from "@/src/components/GraphCanvas";
import { useWindowDimensions } from "react-native";
import { Ionicons } from "@expo/vector-icons";

type Node = { id: string; kind: string; label: string; weight: number };
type Edge = { src: string; dst: string; kind: string };
type NodeDetail = {
  node: Node;
  gravity: number;
  connected_notes: number;
  connected_concepts: number;
  decisions: number;
  neighbors: Node[];
  edge_count: number;
};

export default function GraphScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Node | null>(null);
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const { width } = useWindowDimensions();

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const g = await api<{ nodes: Node[]; edges: Edge[] }>("/api/graph", { token });
      setNodes(g.nodes); setEdges(g.edges);
    } finally { setLoading(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const selectNode = async (n: Node | null) => {
    setSelected(n);
    setDetail(null);
    if (!n) return;
    setDetailBusy(true);
    try {
      const d = await api<NodeDetail>(`/api/graph/node/${n.id}`, { token });
      setDetail(d);
    } catch {} finally { setDetailBusy(false); }
  };

  const canvasH = 480;
  const noteCount = nodes.filter(n => n.kind === "note").length;
  const conceptCount = nodes.filter(n => n.kind === "concept").length;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="graph-screen">
      <View style={styles.head}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Living Graph</Text>
          <Text style={styles.sub}>{noteCount} notes · {conceptCount} concepts · {edges.length} links</Text>
        </View>
        {selected ? (
          <Pressable onPress={() => selectNode(null)} testID="graph-clear-selection" style={styles.clearBtn}>
            <Ionicons name="close" size={16} color="#fff" />
            <Text style={styles.clearT}>Clear</Text>
          </Pressable>
        ) : null}
      </View>
      <View style={styles.canvasWrap}>
        {loading ? <ActivityIndicator color={colors.onSurface} style={{ marginTop: 40 }} /> : (
          <GraphCanvas
            nodes={nodes}
            edges={edges}
            width={width - spacing.xl * 2}
            height={canvasH}
            selectedId={selected?.id}
            onNodePress={(n) => selectNode(n)}
          />
        )}
      </View>

      {selected ? (
        <View style={styles.sheet} testID="graph-detail-sheet">
          <View style={styles.sheetHandle} />
          <View style={styles.sheetHead}>
            <View style={[styles.kindDot, { backgroundColor: selected.kind === "note" ? colors.onSurface : colors.agentPlanner }]} />
            <View style={{ flex: 1 }}>
              <Text style={styles.sheetKind}>{selected.kind.toUpperCase()}</Text>
              <Text style={styles.sheetTitle} numberOfLines={2}>{selected.label}</Text>
            </View>
            {selected.kind === "note" ? (
              <Pressable
                style={styles.openBtn}
                onPress={() => router.push({ pathname: "/note/[id]", params: { id: selected.id } })}
                testID="graph-open-note"
              >
                <Text style={styles.openT}>Open</Text>
              </Pressable>
            ) : null}
          </View>
          {detailBusy ? (
            <ActivityIndicator style={{ marginTop: 12 }} color={colors.onSurface} />
          ) : detail ? (
            <>
              <View style={styles.sheetGrid}>
                <View style={styles.sheetMetric}>
                  <Text style={styles.sheetVal}>{detail.connected_notes}</Text>
                  <Text style={styles.sheetLab}>Notes</Text>
                </View>
                <View style={styles.sheetMetric}>
                  <Text style={styles.sheetVal}>{detail.connected_concepts}</Text>
                  <Text style={styles.sheetLab}>Concepts</Text>
                </View>
                {selected.kind === "note" ? (
                  <>
                    <View style={styles.sheetMetric}>
                      <Text style={styles.sheetVal}>{detail.decisions}</Text>
                      <Text style={styles.sheetLab}>Decisions</Text>
                    </View>
                    <View style={styles.sheetMetric}>
                      <Text style={styles.sheetVal}>{detail.gravity}</Text>
                      <Text style={styles.sheetLab}>Gravity</Text>
                    </View>
                  </>
                ) : (
                  <View style={styles.sheetMetric}>
                    <Text style={styles.sheetVal}>{detail.edge_count}</Text>
                    <Text style={styles.sheetLab}>Links</Text>
                  </View>
                )}
              </View>
              {detail.neighbors.length ? (
                <>
                  <Text style={styles.neighH}>Connected to</Text>
                  <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 6, paddingRight: spacing.md }}>
                    {detail.neighbors.map(n => (
                      <Pressable
                        key={n.id}
                        style={[styles.neighChip, n.kind === "note" && { backgroundColor: colors.onSurface }]}
                        onPress={() => selectNode(n)}
                        testID={`neighbor-${n.id}`}
                      >
                        <Text style={[styles.neighT, n.kind === "note" && { color: "#fff" }]} numberOfLines={1}>
                          {n.label.slice(0, 20)}
                        </Text>
                      </Pressable>
                    ))}
                  </ScrollView>
                </>
              ) : null}
            </>
          ) : null}
        </View>
      ) : (
        <ScrollView style={styles.list} contentContainerStyle={{ paddingBottom: 140 }}>
          <Text style={styles.listH}>Top concepts</Text>
          {nodes.filter(n => n.kind === "concept").sort((a, b) => b.weight - a.weight).slice(0, 12).map(n => (
            <Pressable key={n.id} style={styles.chip} onPress={() => selectNode(n)} testID={`concept-${n.label}`}>
              <Text style={styles.chipT}>{n.label} · {n.weight}</Text>
            </Pressable>
          ))}
          <Text style={styles.listH}>Notes</Text>
          {nodes.filter(n => n.kind === "note").map(n => (
            <Pressable
              key={n.id}
              style={styles.noteRow}
              onPress={() => selectNode(n)}
              testID={`graph-note-${n.id}`}
            >
              <Ionicons name="document-text-outline" size={16} color={colors.onSurface} />
              <Text style={styles.noteT}>{n.label}</Text>
              <Ionicons name="chevron-forward" size={16} color={colors.muted} />
            </Pressable>
          ))}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm, flexDirection: "row", alignItems: "flex-end" },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 2 },
  clearBtn: { flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.onSurface, paddingHorizontal: 10, paddingVertical: 6, borderRadius: radius.pill },
  clearT: { color: "#fff", fontSize: fs.sm, fontWeight: "700" },
  canvasWrap: { paddingHorizontal: spacing.xl, backgroundColor: colors.surface },
  list: { flex: 1, paddingHorizontal: spacing.xl },
  listH: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.lg, marginBottom: spacing.sm },
  chip: { alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6, marginRight: 6, marginBottom: 6 },
  chipT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  noteRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  noteT: { flex: 1, color: colors.onSurface, fontSize: fs.base },
  sheet: { marginHorizontal: spacing.xl, marginTop: spacing.md, marginBottom: 100, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.lg },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md },
  sheetHead: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  kindDot: { width: 10, height: 10, borderRadius: 5 },
  sheetKind: { fontSize: 10, color: colors.muted, letterSpacing: 1.2, fontWeight: "700" },
  sheetTitle: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  openBtn: { backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill },
  openT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  sheetGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm, marginTop: spacing.md },
  sheetMetric: { flexBasis: "22%", flexGrow: 1, backgroundColor: "#fff", padding: spacing.sm, borderRadius: radius.sm, alignItems: "center" },
  sheetVal: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  sheetLab: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  neighH: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.md, marginBottom: spacing.sm },
  neighChip: { backgroundColor: "#fff", borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 6, borderWidth: 1, borderColor: colors.border },
  neighT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600", maxWidth: 140 },
});
