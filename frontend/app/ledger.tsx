import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, TextInput, Modal, Platform, Share } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type LedgerEvent = {
  id: string;
  kind: string;
  text: string;
  ref_id?: string;
  meta?: any;
  previous_hash?: string;
  payload_hash?: string;
  hash?: string;
  created_at: string;
  chain_position: number;
  verified: boolean;
  verify_reason?: string;
};
type LedgerResp = {
  events: LedgerEvent[];
  head_hash: string;
  total_events: number;
  verified_ok: number;
  chain_verified: boolean;
  available_kinds: string[];
};

const KIND_META: Record<string, { label: string; icon: string; color: string; group: "capture" | "council" | "debate" | "decision" | "other" }> = {
  note_created:          { label: "Note created",          icon: "document-text-outline", color: "#111",    group: "capture" },
  concepts_extracted:    { label: "Concepts extracted",    icon: "sparkles-outline",      color: "#5A3A00", group: "capture" },
  linked:                { label: "Linked",                icon: "link-outline",          color: "#1A4FA3", group: "capture" },
  memory_strengthened:   { label: "Memory strengthened",   icon: "pulse",                 color: "#0E7A2A", group: "capture" },
  idea_evolved:          { label: "Idea evolved",          icon: "git-branch-outline",    color: "#1A4FA3", group: "capture" },
  council_convened:      { label: "Council convened",      icon: "people-outline",        color: "#5A3A00", group: "council" },
  consensus_convened:    { label: "Consensus convened",    icon: "checkbox-outline",      color: "#5A3A00", group: "council" },
  debate_triggered:      { label: "Debate triggered",      icon: "flame-outline",         color: "#B41B10", group: "debate" },
  debate_turn_critic:    { label: "Critic turn",           icon: "close-circle-outline",  color: "#B41B10", group: "debate" },
  debate_turn_defender:  { label: "Defender turn",         icon: "shield-outline",        color: "#0E7A2A", group: "debate" },
  synthesis_proposed:    { label: "Synthesis proposed",    icon: "git-network-outline",   color: "#5A3A00", group: "debate" },
  synthesis_ratified:    { label: "Synthesis ratified",    icon: "shield-checkmark",      color: "#0E7A2A", group: "debate" },
  synthesis_rejected:    { label: "Synthesis rejected",    icon: "close-outline",         color: "#B41B10", group: "debate" },
  decision_made:         { label: "Decision made",         icon: "flag-outline",          color: "#B41B10", group: "decision" },
  execution_proposed:    { label: "Execution proposed",    icon: "play-outline",          color: "#1A4FA3", group: "decision" },
  agent_submitted:       { label: "Agent submitted",       icon: "cube-outline",          color: "#5A3A00", group: "other" },
};

const GROUP_FILTERS: { key: string; label: string; kinds: string[]; icon: string }[] = [
  { key: "all",      label: "All",       kinds: [], icon: "layers-outline" },
  { key: "debate",   label: "Debate",    kinds: ["debate_triggered", "debate_turn_critic", "debate_turn_defender", "synthesis_proposed", "synthesis_ratified", "synthesis_rejected"], icon: "flame-outline" },
  { key: "council",  label: "Council",   kinds: ["council_convened", "consensus_convened"], icon: "people-outline" },
  { key: "decision", label: "Decisions", kinds: ["decision_made", "execution_proposed"], icon: "flag-outline" },
  { key: "capture",  label: "Capture",   kinds: ["note_created", "concepts_extracted", "linked", "memory_strengthened", "idea_evolved"], icon: "document-text-outline" },
];

function shortHash(h?: string, n = 12) {
  if (!h) return "—";
  return h.slice(0, n) + "…" + h.slice(-4);
}

export default function LedgerScreen() {
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<LedgerResp | null>(null);
  const [group, setGroup] = useState<string>("debate");
  const [q, setQ] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [detail, setDetail] = useState<LedgerEvent | null>(null);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    if (!token) { setLoading(false); return; }
    setLoading(true);
    try {
      const g = GROUP_FILTERS.find(f => f.key === group);
      const params = new URLSearchParams();
      if (g && g.kinds.length > 0) params.set("kinds", g.kinds.join(","));
      if (q.trim()) params.set("q", q.trim());
      params.set("limit", "300");
      const r = await api<LedgerResp>(`/api/ledger/events?${params.toString()}`, { token });
      setData(r);
    } catch {
      // keep last state
    } finally {
      setLoading(false);
    }
  }, [token, group, q]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => { if (token) load(); }, [token, load]);

  const groups = useMemo(() => {
    if (!data) return {} as Record<string, LedgerEvent[]>;
    const g: Record<string, LedgerEvent[]> = {};
    data.events.forEach(e => {
      const d = dayjs(e.created_at).format("YYYY-MM-DD");
      if (!g[d]) g[d] = [];
      g[d].push(e);
    });
    return g;
  }, [data]);

  const openDetail = (e: LedgerEvent) => setDetail(e);
  const closeDetail = () => setDetail(null);
  const openRef = (e: LedgerEvent) => {
    if (e.ref_id) {
      closeDetail();
      router.push({ pathname: "/note/[id]", params: { id: e.ref_id } });
    }
  };
  const exportBundle = async () => {
    if (!token) return;
    setExporting(true);
    try {
      const bundle = await api<any>(`/api/ledger/export`, { token });
      if (Platform.OS === "web") {
        // Trigger a browser download of the JSON bundle
        const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `pocketos-audit-bundle-${dayjs().format("YYYYMMDD-HHmm")}.json`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { URL.revokeObjectURL(url); a.remove(); }, 200);
      } else {
        // Native: use built-in Share sheet with the manifest + head as the message so
        // the receiver has enough to independently verify (verify.py + jsonl are large,
        // so we surface them through a short manifest by default). Long-form share can
        // be added via expo-file-system in a later build.
        const short = {
          manifest: bundle.manifest,
          head: bundle.head,
          ledger_jsonl_lines: (bundle.ledger_jsonl || "").split("\n").length,
          note: "Full ledger.jsonl + verify.py available via web export.",
        };
        await Share.share({
          message: JSON.stringify(short, null, 2),
          title: "Pocket OS Audit Bundle",
        });
      }
    } catch (e: any) {
      alert(e.message || "Export failed");
    } finally {
      setExporting(false);
    }
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="ledger-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="ledger-back">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>Governance Ledger</Text>
        <Pressable onPress={exportBundle} disabled={exporting} hitSlop={10} testID="ledger-export">
          {exporting ? <ActivityIndicator size="small" color={colors.onSurface} /> : <Ionicons name="download-outline" size={22} color={colors.onSurface} />}
        </Pressable>
      </View>

      <View style={styles.headerCard}>
        <View style={styles.headerTop}>
          <Text style={styles.headerLab}>IMMUTABLE HASH CHAIN</Text>
          {data ? (
            <View style={[styles.verifyPill, { backgroundColor: data.chain_verified ? "#DCF7DC" : "#FFE9E7" }]}>
              <Ionicons name={data.chain_verified ? "shield-checkmark" : "warning"} size={12} color={data.chain_verified ? "#0E7A2A" : "#B41B10"} />
              <Text style={[styles.verifyT, { color: data.chain_verified ? "#0E7A2A" : "#B41B10" }]}>{data.chain_verified ? "VERIFIED" : "BROKEN"}</Text>
            </View>
          ) : null}
        </View>
        {data ? (
          <>
            <Text style={styles.headerLine}>{data.verified_ok} chained events · head <Text style={styles.headHash}>{shortHash(data.head_hash, 16)}</Text></Text>
            <Text style={styles.headerLine}>{data.total_events} total events · {data.available_kinds.length} kinds seen</Text>
          </>
        ) : (
          <Text style={styles.headerLine}>Loading chain…</Text>
        )}
      </View>

      <View style={styles.filterRow}>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingHorizontal: spacing.lg, gap: 6 }}>
          {GROUP_FILTERS.map(f => (
            <Pressable
              key={f.key}
              style={[styles.filterChip, group === f.key && styles.filterChipActive]}
              onPress={() => setGroup(f.key)}
              testID={`ledger-filter-${f.key}`}
            >
              <Ionicons name={f.icon as any} size={12} color={group === f.key ? "#fff" : colors.onSurface} />
              <Text style={[styles.filterChipT, group === f.key && { color: "#fff" }]}>{f.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      </View>

      <View style={styles.searchWrap}>
        <Ionicons name="search" size={14} color={colors.muted} />
        <TextInput
          style={styles.searchInput}
          placeholder="Search text or hash…"
          placeholderTextColor={colors.muted}
          value={q}
          onChangeText={setQ}
          onSubmitEditing={load}
          returnKeyType="search"
          autoCapitalize="none"
          autoCorrect={false}
          testID="ledger-search"
        />
        {q.length > 0 ? (
          <Pressable onPress={() => { setQ(""); load(); }} hitSlop={8}>
            <Ionicons name="close-circle" size={16} color={colors.muted} />
          </Pressable>
        ) : null}
      </View>

      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={async () => { setRefreshing(true); await load(); setRefreshing(false); }} />}
      >
        {loading && !data ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.onSurface} /> : null}
        {data && data.events.length === 0 && !loading ? (
          <Text style={styles.empty}>No events for this filter.</Text>
        ) : null}
        {Object.entries(groups).map(([day, evs]) => (
          <View key={day} style={{ marginBottom: spacing.xl }}>
            <Text style={styles.day}>{dayjs(day).isSame(dayjs(), "day") ? "Today" : dayjs(day).format("dddd, MMM D")}</Text>
            {evs.map((e, i) => {
              const meta = KIND_META[e.kind] || { label: e.kind, icon: "ellipse-outline", color: colors.muted, group: "other" };
              const isSynthesis = e.kind === "synthesis_proposed" || e.kind === "synthesis_ratified" || e.kind === "synthesis_rejected";
              const isTurn = e.kind === "debate_turn_critic" || e.kind === "debate_turn_defender";
              return (
                <Pressable
                  key={e.id}
                  style={styles.eventRow}
                  onPress={() => openDetail(e)}
                  testID={`ledger-event-${e.chain_position}`}
                >
                  <View style={styles.chainCol}>
                    <View style={[styles.chainDot, { backgroundColor: meta.color }]}>
                      <Ionicons name={meta.icon as any} size={10} color="#fff" />
                    </View>
                    {i < evs.length - 1 ? <View style={styles.chainLine} /> : null}
                  </View>
                  <View style={styles.card}>
                    <View style={styles.cardTop}>
                      <View style={[styles.kindPill, { backgroundColor: meta.color + "22" }]}>
                        <Text style={[styles.kindPillT, { color: meta.color }]}>{meta.label}</Text>
                      </View>
                      <Text style={styles.time}>{dayjs(e.created_at).format("HH:mm:ss")}</Text>
                    </View>
                    <Text style={styles.cardText} numberOfLines={2}>{e.text}</Text>
                    <View style={styles.chainMeta}>
                      <Text style={styles.chainLab}>prev</Text>
                      <Text style={styles.chainHash}>{shortHash(e.previous_hash, 10)}</Text>
                      <Ionicons name="arrow-forward" size={10} color={colors.muted} />
                      <Text style={styles.chainLab}>hash</Text>
                      <Text style={[styles.chainHash, { color: meta.color }]}>{shortHash(e.hash, 10)}</Text>
                    </View>
                    {(isSynthesis && e.meta?.synthesis_hash) ? (
                      <Text style={styles.metaExtra}>synthesis_hash · {shortHash(e.meta.synthesis_hash, 12)}</Text>
                    ) : null}
                    {(isTurn && e.meta?.argument_hash) ? (
                      <Text style={styles.metaExtra}>argument_hash · {shortHash(e.meta.argument_hash, 12)}</Text>
                    ) : null}
                    <View style={styles.footRow}>
                      <View style={[styles.verifyPillSmall, { backgroundColor: e.verified ? "#DCF7DC" : "#FFE9E7" }]}>
                        <Ionicons name={e.verified ? "shield-checkmark" : "warning"} size={9} color={e.verified ? "#0E7A2A" : "#B41B10"} />
                        <Text style={[styles.verifyTSmall, { color: e.verified ? "#0E7A2A" : "#B41B10" }]}>{e.verified ? "verified" : (e.verify_reason || "unchained")}</Text>
                      </View>
                      <Text style={styles.chainPosT}>#{e.chain_position}</Text>
                    </View>
                  </View>
                </Pressable>
              );
            })}
          </View>
        ))}
      </ScrollView>

      <Modal visible={!!detail} transparent animationType="slide" onRequestClose={closeDetail}>
        <Pressable style={styles.modalBg} onPress={closeDetail}>
          <Pressable style={styles.modalSheet} onPress={e => e.stopPropagation()}>
            {detail ? (
              <ScrollView>
                <View style={styles.modalHead}>
                  <Text style={styles.modalTitle}>{(KIND_META[detail.kind] || { label: detail.kind }).label}</Text>
                  <Pressable onPress={closeDetail} hitSlop={10}>
                    <Ionicons name="close" size={22} color={colors.onSurface} />
                  </Pressable>
                </View>
                <Text style={styles.modalText}>{detail.text}</Text>
                <Text style={styles.modalTime}>{dayjs(detail.created_at).format("YYYY-MM-DD HH:mm:ss")} · chain #{detail.chain_position}</Text>

                <View style={styles.modalBlock}>
                  <Text style={styles.modalLab}>PREVIOUS HASH</Text>
                  <Text style={styles.modalMono}>{detail.previous_hash || "—"}</Text>
                </View>
                <View style={styles.modalBlock}>
                  <Text style={styles.modalLab}>PAYLOAD HASH</Text>
                  <Text style={styles.modalMono}>{detail.payload_hash || "—"}</Text>
                </View>
                <View style={styles.modalBlock}>
                  <Text style={styles.modalLab}>EVENT HASH</Text>
                  <Text style={[styles.modalMono, { color: "#0E7A2A" }]}>{detail.hash || "—"}</Text>
                </View>
                {detail.meta && Object.keys(detail.meta).length > 0 ? (
                  <View style={styles.modalBlock}>
                    <Text style={styles.modalLab}>META</Text>
                    <Text style={styles.modalMono}>{JSON.stringify(detail.meta, null, 2)}</Text>
                  </View>
                ) : null}
                {detail.ref_id ? (
                  <Pressable style={styles.openBtn} onPress={() => openRef(detail)} testID="ledger-open-ref">
                    <Ionicons name="open-outline" size={16} color="#fff" />
                    <Text style={styles.openBtnT}>Open referenced note</Text>
                  </Pressable>
                ) : null}
                <View style={{ height: 40 }} />
              </ScrollView>
            ) : null}
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  headerCard: { marginHorizontal: spacing.lg, marginTop: spacing.md, backgroundColor: "#0F0F10", borderRadius: radius.md, padding: spacing.md, gap: 4 },
  headerTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  headerLab: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  headerLine: { color: "#fff", fontSize: fs.sm, marginTop: 2 },
  headHash: { color: "#7BE38B", fontFamily: "monospace" },
  verifyPill: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  verifyT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.6 },
  filterRow: { marginTop: spacing.md },
  filterChip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border },
  filterChipActive: { backgroundColor: colors.onSurface, borderColor: colors.onSurface },
  filterChipT: { fontSize: fs.sm, fontWeight: "700", color: colors.onSurface },
  searchWrap: { flexDirection: "row", alignItems: "center", gap: 6, marginHorizontal: spacing.lg, marginTop: spacing.sm, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 8 },
  searchInput: { flex: 1, color: colors.onSurface, fontSize: fs.sm, padding: 0 },
  s: { padding: spacing.lg, paddingBottom: 60 },
  empty: { color: colors.muted, textAlign: "center", marginTop: 40, fontSize: fs.base },
  day: { color: colors.muted, fontSize: 11, letterSpacing: 1.2, textTransform: "uppercase", fontWeight: "800", marginBottom: spacing.sm },
  eventRow: { flexDirection: "row", gap: 8 },
  chainCol: { width: 22, alignItems: "center" },
  chainDot: { width: 22, height: 22, borderRadius: 11, alignItems: "center", justifyContent: "center", marginTop: 4 },
  chainLine: { flex: 1, width: 1, backgroundColor: colors.border, marginTop: 2 },
  card: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.sm },
  cardTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  kindPill: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  kindPillT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  time: { color: colors.muted, fontSize: 11, fontFamily: "monospace" },
  cardText: { color: colors.onSurface, fontSize: fs.sm, lineHeight: 19 },
  chainMeta: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 6, flexWrap: "wrap" },
  chainLab: { color: colors.muted, fontSize: 9, letterSpacing: 0.6, fontWeight: "800", textTransform: "uppercase" },
  chainHash: { color: colors.onSurface, fontSize: 10, fontFamily: "monospace" },
  metaExtra: { color: colors.muted, fontSize: 10, fontFamily: "monospace", marginTop: 2 },
  footRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6 },
  verifyPillSmall: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 999 },
  verifyTSmall: { fontSize: 9, fontWeight: "800", letterSpacing: 0.5 },
  chainPosT: { color: colors.muted, fontSize: 10, fontFamily: "monospace" },
  modalBg: { flex: 1, backgroundColor: "rgba(0,0,0,0.4)", justifyContent: "flex-end" },
  modalSheet: { backgroundColor: colors.surface, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: spacing.lg, maxHeight: "82%" },
  modalHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: spacing.sm },
  modalTitle: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  modalText: { color: colors.onSurface, fontSize: fs.base, lineHeight: 22 },
  modalTime: { color: colors.muted, fontSize: fs.sm, marginTop: 4 },
  modalBlock: { marginTop: spacing.md },
  modalLab: { color: colors.muted, fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginBottom: 4 },
  modalMono: { color: colors.onSurface, fontFamily: "monospace", fontSize: 11, lineHeight: 16 },
  openBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.onSurface, paddingVertical: 12, borderRadius: radius.sm, marginTop: spacing.lg },
  openBtnT: { color: "#fff", fontWeight: "800", fontSize: fs.base },
});
