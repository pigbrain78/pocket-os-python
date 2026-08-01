import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, KeyboardAvoidingView, Platform } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Msg = { id: string; role: "user" | "assistant"; content: string; created_at: string; streaming?: boolean };

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [title, setTitle] = useState("New Chat");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<ScrollView>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const scrollToEnd = () => setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 60);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try {
      const r = await fetch(`${BACKEND}/api/chat/sessions/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      const d = await r.json();
      if (r.ok) {
        setTitle(d.session.title);
        setMessages(d.messages);
        scrollToEnd();
      }
    } finally { setLoading(false); }
  }, [id, token]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => () => { xhrRef.current?.abort(); }, []);

  const send = () => {
    const text = input.trim();
    if (!text || streaming) return;
    setInput("");
    const tempUserId = "u-" + Date.now();
    const tempAssistId = "a-" + Date.now();
    setMessages(prev => [
      ...prev,
      { id: tempUserId, role: "user", content: text, created_at: new Date().toISOString() },
      { id: tempAssistId, role: "assistant", content: "", created_at: new Date().toISOString(), streaming: true },
    ]);
    setStreaming(true);
    scrollToEnd();

    const xhr = new XMLHttpRequest();
    xhrRef.current = xhr;
    let lastLen = 0;
    xhr.open("POST", `${BACKEND}/api/chat/sessions/${id}/stream`, true);
    xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.setRequestHeader("Accept", "text/event-stream");

    const processChunk = (raw: string) => {
      // raw is a full SSE fragment: `data: {...}\n\n`
      const lines = raw.split("\n");
      for (const l of lines) {
        if (!l.startsWith("data:")) continue;
        const payload = l.slice(5).trim();
        if (!payload) continue;
        try {
          const evt = JSON.parse(payload);
          if (evt.type === "delta" && evt.content) {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, content: m.content + evt.content } : m));
            scrollToEnd();
          } else if (evt.type === "error") {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, content: (m.content || "") + `\n\n[Error: ${evt.error}]`, streaming: false } : m));
          } else if (evt.type === "done") {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, streaming: false } : m));
          }
        } catch {}
      }
    };

    xhr.onprogress = () => {
      const text = xhr.responseText;
      if (text.length > lastLen) {
        const delta = text.slice(lastLen);
        lastLen = text.length;
        processChunk(delta);
      }
    };
    xhr.onload = () => {
      const remaining = xhr.responseText.slice(lastLen);
      if (remaining) processChunk(remaining);
      setStreaming(false);
    };
    xhr.onerror = () => {
      setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, content: m.content || "[Network error]", streaming: false } : m));
      setStreaming(false);
    };
    xhr.send(JSON.stringify({ text }));
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="chat-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1, alignItems: "center" }}>
          <Text style={styles.hTitle} numberOfLines={1}>{title}</Text>
          <Text style={styles.hSub}>Gemini 3 Flash</Text>
        </View>
        <View style={{ width: 26 }} />
      </View>

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }} keyboardVerticalOffset={80}>
        <ScrollView
          ref={scrollRef}
          contentContainerStyle={styles.list}
          keyboardShouldPersistTaps="handled"
          onContentSizeChange={scrollToEnd}
        >
          {loading ? <ActivityIndicator color={colors.onSurface} style={{ marginTop: 40 }} /> : null}
          {!loading && messages.length === 0 ? (
            <View style={styles.empty}>
              <Ionicons name="chatbubbles-outline" size={40} color={colors.muted} />
              <Text style={styles.emptyT}>Ask anything about your knowledge.</Text>
              <Text style={styles.emptySub}>Try: "What have I been working on this week?"</Text>
            </View>
          ) : null}
          {messages.map((m) => (
            <View key={m.id} style={[styles.msgRow, m.role === "user" ? styles.msgRowUser : styles.msgRowAssistant]} testID={`msg-${m.role}`}>
              <View style={[styles.bubble, m.role === "user" ? styles.bubbleUser : styles.bubbleAssistant]}>
                <Text style={m.role === "user" ? styles.bubbleUserT : styles.bubbleAssistantT}>
                  {m.content}
                  {m.streaming ? <Text style={styles.caret}>▍</Text> : null}
                </Text>
              </View>
            </View>
          ))}
        </ScrollView>

        <View style={styles.inputBar}>
          <TextInput
            testID="chat-input"
            value={input}
            onChangeText={setInput}
            placeholder="Message Pocket OS…"
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            editable={!streaming}
            onSubmitEditing={send}
          />
          <Pressable
            style={[styles.send, (!input.trim() || streaming) && { opacity: 0.4 }]}
            onPress={send}
            disabled={!input.trim() || streaming}
            testID="chat-send"
          >
            {streaming ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="arrow-up" size={20} color="#fff" />}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  hSub: { fontSize: fs.sm, color: colors.muted, marginTop: 2 },
  list: { padding: spacing.lg, paddingBottom: spacing.xl, gap: spacing.md },
  empty: { alignItems: "center", justifyContent: "center", padding: spacing["3xl"], gap: 6 },
  emptyT: { color: colors.onSurface, fontSize: fs.lg, fontWeight: "700", marginTop: spacing.md },
  emptySub: { color: colors.muted, fontSize: fs.base },
  msgRow: { flexDirection: "row" },
  msgRowUser: { justifyContent: "flex-end" },
  msgRowAssistant: { justifyContent: "flex-start" },
  bubble: { maxWidth: "82%", padding: spacing.md, borderRadius: radius.lg },
  bubbleUser: { backgroundColor: colors.onSurface, borderBottomRightRadius: 6 },
  bubbleAssistant: { backgroundColor: colors.surfaceSecondary, borderBottomLeftRadius: 6 },
  bubbleUserT: { color: "#fff", fontSize: fs.base, lineHeight: 22 },
  bubbleAssistantT: { color: colors.onSurface, fontSize: fs.base, lineHeight: 22 },
  caret: { color: colors.muted },
  inputBar: { flexDirection: "row", alignItems: "flex-end", gap: spacing.sm, padding: spacing.md, borderTopWidth: 1, borderTopColor: colors.border, backgroundColor: colors.surface },
  input: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.md, fontSize: fs.base, color: colors.onSurface, maxHeight: 120 },
  send: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.onSurface, alignItems: "center", justifyContent: "center" },
});
