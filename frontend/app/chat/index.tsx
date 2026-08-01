import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl, Alert } from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Session = { id: string; title: string; model: string; message_count: number; updated_at: string };

export default function ChatIndex() {
  const { token } = useAuth();
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try { setSessions(await api<Session[]>("/api/chat/sessions", { token })); } catch {}
  }, [token]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const newChat = async () => {
    setBusy(true);
    try {
      const s = await api<Session>("/api/chat/sessions", { method: "POST", token, body: JSON.stringify({}) });
      router.push({ pathname: "/chat/[id]", params: { id: s.id } });
    } catch (e: any) { Alert.alert("Error", e.message); } finally { setBusy(false); }
  };

  const del = async (sid: string) => {
    try { await api(`/api/chat/sessions/${sid}`, { method: "DELETE", token }); setSessions(sessions.filter(s => s.id !== sid)); } catch {}
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="chat-index">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>AI Chat</Text>
        <Pressable onPress={newChat} disabled={busy} hitSlop={12} testID="new-chat-btn">
          {busy ? <ActivityIndicator size="small" color={colors.onSurface} /> : <Ionicons name="create-outline" size={24} color={colors.onSurface} />}
        </Pressable>
      </View>
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} />}
      >
        <Text style={styles.tag}>GEMINI 3 FLASH · MULTI-TURN</Text>
        <Text style={styles.h1}>Chat with Pocket OS.</Text>
        <Text style={styles.sub}>Streaming, conversational, remembers this thread.</Text>

        <Pressable style={styles.cta} onPress={newChat} disabled={busy} testID="start-chat">
          <Ionicons name="chatbubbles" size={20} color="#fff" />
          <Text style={styles.ctaT}>Start a new chat</Text>
        </Pressable>

        {sessions.length > 0 ? <Text style={styles.section}>Recent</Text> : null}
        {sessions.map(s => (
          <Pressable
            key={s.id}
            style={styles.row}
            onPress={() => router.push({ pathname: "/chat/[id]", params: { id: s.id } })}
            onLongPress={() => Alert.alert("Delete chat?", s.title, [
              { text: "Cancel", style: "cancel" },
              { text: "Delete", style: "destructive", onPress: () => del(s.id) },
            ])}
            testID={`session-${s.id}`}
          >
            <View style={styles.rowIcon}><Ionicons name="chatbubble-outline" size={16} color={colors.onSurface} /></View>
            <View style={{ flex: 1 }}>
              <Text style={styles.rowT} numberOfLines={1}>{s.title}</Text>
              <Text style={styles.rowMeta}>{s.message_count} messages · {dayjs(s.updated_at).fromNow?.() || dayjs(s.updated_at).format("MMM D")}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </Pressable>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.xl, paddingBottom: 60 },
  tag: { fontSize: 10, color: colors.muted, letterSpacing: 1.5, fontWeight: "700" },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: 4 },
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 4 },
  cta: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, marginTop: spacing.xl },
  ctaT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  section: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing["2xl"], marginBottom: spacing.md },
  row: { flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  rowIcon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  rowT: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  rowMeta: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
});
