import React, { useCallback, useEffect, useRef, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, KeyboardAvoidingView, Platform, Modal } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Msg = { id: string; role: "user" | "assistant"; content: string; created_at: string; streaming?: boolean };
type Session = { id: string; title: string; model: string; note_context_id: string | null };
type Model = { id: string; provider: string; label: string; hint: string };
type NoteLite = { id: string; title: string };

const BACKEND = process.env.EXPO_PUBLIC_BACKEND_URL;

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [streaming, setStreaming] = useState(false);
  const [models, setModels] = useState<Model[]>([]);
  const [showModelPicker, setShowModelPicker] = useState(false);
  const [showNotePicker, setShowNotePicker] = useState(false);
  const [notes, setNotes] = useState<NoteLite[]>([]);
  const [ctxNote, setCtxNote] = useState<NoteLite | null>(null);
  const scrollRef = useRef<ScrollView>(null);
  const xhrRef = useRef<XMLHttpRequest | null>(null);

  const scrollToEnd = () => setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 60);

  const load = useCallback(async () => {
    if (!token || !id) return;
    try {
      const r = await fetch(`${BACKEND}/api/chat/sessions/${id}`, { headers: { Authorization: `Bearer ${token}` } });
      const d = await r.json();
      if (r.ok) {
        setSession(d.session);
        setMessages(d.messages);
        scrollToEnd();
        if (d.session.note_context_id) {
          try {
            const n = await api<{ note: NoteLite }>(`/api/notes/${d.session.note_context_id}`, { token });
            setCtxNote({ id: n.note.id, title: n.note.title });
          } catch {}
        } else {
          setCtxNote(null);
        }
      }
    } finally { setLoading(false); }
  }, [id, token]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api<Model[]>("/api/chat/models", { token }).then(setModels).catch(() => {});
    return () => { xhrRef.current?.abort(); };
  }, [token]);

  const openNotePicker = async () => {
    try {
      const ns = await api<{ id: string; title: string }[]>("/api/notes", { token });
      setNotes(ns.map(n => ({ id: n.id, title: n.title })));
    } catch {}
    setShowNotePicker(true);
  };

  const patchSession = async (updates: any) => {
    try {
      const fresh = await api<Session>(`/api/chat/sessions/${id}`, { method: "PATCH", token, body: JSON.stringify(updates) });
      setSession(fresh);
      if (fresh.note_context_id) {
        const n = await api<{ note: NoteLite }>(`/api/notes/${fresh.note_context_id}`, { token });
        setCtxNote({ id: n.note.id, title: n.note.title });
      } else {
        setCtxNote(null);
      }
    } catch (e: any) { alert(e.message); }
  };

  const currentModel = models.find(m => m.id === session?.model);

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

    const process = (raw: string) => {
      for (const l of raw.split("\n")) {
        if (!l.startsWith("data:")) continue;
        const p = l.slice(5).trim(); if (!p) continue;
        try {
          const e = JSON.parse(p);
          if (e.type === "delta" && e.content) {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, content: m.content + e.content } : m));
            scrollToEnd();
          } else if (e.type === "error") {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, content: (m.content || "") + `\n\n[Error: ${e.error}]`, streaming: false } : m));
          } else if (e.type === "done") {
            setMessages(prev => prev.map(m => m.id === tempAssistId ? { ...m, streaming: false } : m));
          }
        } catch {}
      }
    };
    xhr.onprogress = () => {
      const t = xhr.responseText;
      if (t.length > lastLen) { process(t.slice(lastLen)); lastLen = t.length; }
    };
    xhr.onload = () => { const r = xhr.responseText.slice(lastLen); if (r) process(r); setStreaming(false); };
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
          <Text style={styles.hTitle} numberOfLines={1}>{session?.title || "Chat"}</Text>
          <Pressable onPress={() => setShowModelPicker(true)} testID="open-model-picker">
            <Text style={styles.modelPill}>{currentModel?.label || "Loading…"} ▾</Text>
          </Pressable>
        </View>
        <View style={{ width: 26 }} />
      </View>

      {ctxNote ? (
        <View style={styles.ctxBar} testID="ctx-bar">
          <Ionicons name="link" size={14} color={colors.onSurface} />
          <Text style={styles.ctxT} numberOfLines={1}>Context: {ctxNote.title}</Text>
          <Pressable onPress={() => patchSession({ note_context_id: "" })} testID="detach-note" hitSlop={10}>
            <Ionicons name="close" size={16} color={colors.muted} />
          </Pressable>
        </View>
      ) : null}

      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }} keyboardVerticalOffset={80}>
        <ScrollView ref={scrollRef} contentContainerStyle={styles.list} keyboardShouldPersistTaps="handled" onContentSizeChange={scrollToEnd}>
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
          <Pressable onPress={openNotePicker} testID="attach-note-btn" style={styles.attachBtn}>
            <Ionicons name="attach" size={20} color={colors.onSurface} />
          </Pressable>
          <TextInput
            testID="chat-input"
            value={input}
            onChangeText={setInput}
            placeholder="Message Pocket OS…"
            placeholderTextColor={colors.muted}
            style={styles.input}
            multiline
            editable={!streaming}
          />
          <Pressable
            style={[styles.send, (!input.trim() || streaming) && { opacity: 0.4 }]}
            onPress={send} disabled={!input.trim() || streaming}
            testID="chat-send"
          >
            {streaming ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="arrow-up" size={20} color="#fff" />}
          </Pressable>
        </View>
      </KeyboardAvoidingView>

      {/* Model picker */}
      <Modal visible={showModelPicker} transparent animationType="slide" onRequestClose={() => setShowModelPicker(false)}>
        <Pressable style={styles.backdrop} onPress={() => setShowModelPicker(false)} />
        <View style={styles.sheet}>
          <View style={styles.sheetHandle} />
          <Text style={styles.sheetH}>Choose model</Text>
          {models.map(m => (
            <Pressable
              key={m.id}
              style={[styles.mRow, session?.model === m.id && styles.mRowActive]}
              onPress={async () => { await patchSession({ model: m.id }); setShowModelPicker(false); }}
              testID={`model-${m.id}`}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.mLabel}>{m.label}</Text>
                <Text style={styles.mHint}>{m.hint} · {m.provider}</Text>
              </View>
              {session?.model === m.id ? <Ionicons name="checkmark" size={20} color={colors.onSurface} /> : null}
            </Pressable>
          ))}
        </View>
      </Modal>

      {/* Note picker */}
      <Modal visible={showNotePicker} transparent animationType="slide" onRequestClose={() => setShowNotePicker(false)}>
        <Pressable style={styles.backdrop} onPress={() => setShowNotePicker(false)} />
        <View style={styles.sheet}>
          <View style={styles.sheetHandle} />
          <Text style={styles.sheetH}>Attach a note as context</Text>
          <ScrollView style={{ maxHeight: 400 }}>
            {notes.map(n => (
              <Pressable
                key={n.id}
                style={[styles.mRow, session?.note_context_id === n.id && styles.mRowActive]}
                onPress={async () => { await patchSession({ note_context_id: n.id }); setShowNotePicker(false); }}
                testID={`note-opt-${n.id}`}
              >
                <Ionicons name="document-text-outline" size={16} color={colors.onSurface} />
                <Text style={styles.mLabel} numberOfLines={1}>{n.title}</Text>
                {session?.note_context_id === n.id ? <Ionicons name="checkmark" size={18} color={colors.onSurface} /> : null}
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  modelPill: { fontSize: fs.sm, color: colors.muted, marginTop: 2, fontWeight: "600" },
  ctxBar: { flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, backgroundColor: colors.surfaceSecondary, borderBottomWidth: 1, borderBottomColor: colors.border },
  ctxT: { flex: 1, color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
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
  attachBtn: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surfaceSecondary, alignItems: "center", justifyContent: "center" },
  input: { flex: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.md, fontSize: fs.base, color: colors.onSurface, maxHeight: 120 },
  send: { width: 40, height: 40, borderRadius: 20, backgroundColor: colors.onSurface, alignItems: "center", justifyContent: "center" },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.4)" },
  sheet: { position: "absolute", left: 0, right: 0, bottom: 0, backgroundColor: colors.surface, borderTopLeftRadius: radius.lg, borderTopRightRadius: radius.lg, padding: spacing.lg, paddingBottom: spacing["3xl"] },
  sheetHandle: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md },
  sheetH: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.md },
  mRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm, paddingVertical: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.border },
  mRowActive: { backgroundColor: colors.surfaceSecondary },
  mLabel: { flex: 1, color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  mHint: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
});
