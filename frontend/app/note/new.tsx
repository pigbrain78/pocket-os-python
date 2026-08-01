import React, { useState } from "react";
import { View, Text, StyleSheet, TextInput, Pressable, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator, Animated as RNAnimated } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import Ring from "@/src/components/Ring";

export default function NewNote() {
  const { token } = useAuth();
  const router = useRouter();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try {
      const r = await api("/api/notes", { method: "POST", token, body: JSON.stringify({ text }) });
      setResult(r);
    } catch (e: any) {
      alert(e.message);
    } finally { setBusy(false); }
  };

  if (result) {
    return (
      <SafeAreaView style={styles.c} testID="capture-result">
        <ScrollView contentContainerStyle={styles.s}>
          <Text style={styles.wow}>Memory Strengthened</Text>
          <View style={styles.ringRow}>
            <View style={styles.ringCol}>
              <Ring size={110} strokeWidth={11} percent={result.memory.before} color={colors.muted} />
              <Text style={styles.beforeLab}>Before</Text>
              <Text style={styles.beforeVal}>{result.memory.before}%</Text>
            </View>
            <Ionicons name="arrow-forward" size={22} color={colors.onSurface} />
            <View style={styles.ringCol}>
              <Ring size={110} strokeWidth={11} percent={result.memory.after} color={colors.success} />
              <Text style={styles.afterLab}>After</Text>
              <Text style={styles.afterVal}>{result.memory.after}%</Text>
            </View>
          </View>
          <Text style={styles.newLab}>AI extracted concepts</Text>
          <View style={styles.chips}>
            {result.note.concepts.map((c: string) => (
              <View key={c} style={styles.chip}><Text style={styles.chipT}>{c}</Text></View>
            ))}
          </View>
          {result.new_connections?.length ? (
            <>
              <Text style={styles.newLab}>New connections</Text>
              <View style={styles.chips}>
                {result.new_connections.map((c: string) => (
                  <View key={c} style={[styles.chip, { backgroundColor: colors.onSurface }]}><Text style={[styles.chipT, { color: "#fff" }]}>↔ {c}</Text></View>
                ))}
              </View>
            </>
          ) : null}
          <Pressable style={styles.openBtn} onPress={() => router.replace({ pathname: "/note/[id]", params: { id: result.note.id } })} testID="open-note">
            <Text style={styles.openT}>Open note & run AI Council</Text>
          </Pressable>
          <Pressable style={styles.closeBtn} onPress={() => router.back()}>
            <Text style={styles.closeT}>Done</Text>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.c} testID="new-note-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.head}>
          <Pressable onPress={() => router.back()} hitSlop={12} testID="close-new">
            <Ionicons name="close" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.hTitle}>New Capture</Text>
          <View style={{ width: 26 }} />
        </View>
        <TextInput
          testID="capture-input"
          value={text}
          onChangeText={setText}
          placeholder="Type an idea, paste a URL, dump a thought…"
          placeholderTextColor={colors.muted}
          multiline
          style={styles.input}
          autoFocus
        />
        <Pressable testID="capture-submit" style={styles.submit} onPress={submit} disabled={busy || !text.trim()}>
          {busy ? <ActivityIndicator color="#fff" /> : (
            <><Ionicons name="sparkles" size={18} color="#fff" /><Text style={styles.submitT}>Fingerprint & Connect</Text></>
          )}
        </Pressable>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  input: { flex: 1, padding: spacing.xl, fontSize: fs.xl, color: colors.onSurface, textAlignVertical: "top" },
  submit: { flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", backgroundColor: colors.onSurface, padding: spacing.lg, margin: spacing.lg, borderRadius: radius.md },
  submitT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  s: { padding: spacing.xl, paddingBottom: 60 },
  wow: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, textAlign: "center", marginTop: spacing.xl },
  ringRow: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: spacing.lg, marginTop: spacing.xl },
  ringCol: { alignItems: "center" },
  beforeLab: { color: colors.muted, fontSize: fs.sm, marginTop: 8 },
  beforeVal: { color: colors.muted, fontSize: fs.xl, fontWeight: "700" },
  afterLab: { color: colors.success, fontSize: fs.sm, marginTop: 8 },
  afterVal: { color: colors.success, fontSize: fs.xl, fontWeight: "800" },
  newLab: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.xl },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.sm },
  chip: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  chipT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  openBtn: { backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, marginTop: spacing.xl, alignItems: "center" },
  openT: { color: "#fff", fontWeight: "700", fontSize: fs.lg },
  closeBtn: { padding: spacing.md, marginTop: spacing.sm, alignItems: "center" },
  closeT: { color: colors.muted },
});
