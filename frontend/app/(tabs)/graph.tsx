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

export default function GraphScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Node | null>(null);
  const { width } = useWindowDimensions();

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const g = await api<{ nodes: Node[]; edges: Edge[] }>("/api/graph", { token });
      setNodes(g.nodes); setEdges(g.edges);
    } finally { setLoading(false); }
  }, [token]);

  useFocusEffect(useCallback(() => { load(); }, [load]));

  const canvasH = 480;
  const noteCount = nodes.filter(n => n.kind === "note").length;
  const conceptCount = nodes.filter(n => n.kind === "concept").length;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="graph-screen">
      <View style={styles.head}>
        <Text style={styles.h1}>Living Graph</Text>
        <Text style={styles.sub}>{noteCount} notes · {conceptCount} concepts · {edges.length} links</Text>
      </View>
      <View style={styles.canvasWrap}>
        {loading ? <ActivityIndicator color={colors.onSurface} style={{ marginTop: 40 }} /> : (
          <GraphCanvas nodes={nodes} edges={edges} width={width - spacing.xl * 2} height={canvasH} selectedId={selected?.id} />
        )}
      </View>
      <ScrollView style={styles.list} contentContainerStyle={{ paddingBottom: 140 }}>
        <Text style={styles.listH}>Top concepts</Text>
        {nodes.filter(n => n.kind === "concept").sort((a, b) => b.weight - a.weight).slice(0, 12).map(n => (
          <Pressable
            key={n.id}
            style={[styles.chip, selected?.id === n.id && { backgroundColor: colors.onSurface }]}
            onPress={() => setSelected(selected?.id === n.id ? null : n)}
            testID={`concept-${n.label}`}
          >
            <Text style={[styles.chipT, selected?.id === n.id && { color: "#fff" }]}>{n.label} · {n.weight}</Text>
          </Pressable>
        ))}
        <Text style={styles.listH}>Notes</Text>
        {nodes.filter(n => n.kind === "note").map(n => (
          <Pressable
            key={n.id}
            style={styles.noteRow}
            onPress={() => router.push({ pathname: "/note/[id]", params: { id: n.id } })}
            testID={`graph-note-${n.id}`}
          >
            <Ionicons name="document-text-outline" size={16} color={colors.onSurface} />
            <Text style={styles.noteT}>{n.label}</Text>
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { paddingHorizontal: spacing.xl, paddingTop: spacing.md, paddingBottom: spacing.sm },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 2 },
  canvasWrap: { paddingHorizontal: spacing.xl, backgroundColor: colors.surface },
  list: { flex: 1, paddingHorizontal: spacing.xl },
  listH: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.lg, marginBottom: spacing.sm },
  chip: { alignSelf: "flex-start", backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6, marginRight: 6, marginBottom: 6 },
  chipT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  noteRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  noteT: { flex: 1, color: colors.onSurface, fontSize: fs.base },
});
