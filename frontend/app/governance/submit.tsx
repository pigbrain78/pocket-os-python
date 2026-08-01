import React, { useState } from "react";
import { View, Text, TextInput, StyleSheet, Pressable, ScrollView, ActivityIndicator, KeyboardAvoidingView, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

type Step = { step: string; status: string; detail: string };

const STATUS_COLOR: Record<string, string> = { ok: colors.success, warning: colors.warning, error: colors.error };
const STATUS_ICON: Record<string, string> = { ok: "checkmark-circle", warning: "alert-circle", error: "close-circle" };

export default function SubmitAgent() {
  const { token } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [author, setAuthor] = useState("Community");
  const [manifest, setManifest] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ agent: any; pipeline: Step[] } | null>(null);

  const submit = async () => {
    if (!name.trim() || !manifest.trim()) return;
    setBusy(true);
    try {
      const r = await api("/api/agents/submit", { method: "POST", token, body: JSON.stringify({ name, author, manifest }) });
      setResult(r);
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  };

  if (result) {
    return (
      <SafeAreaView style={styles.c} testID="submit-result">
        <View style={styles.head}>
          <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="chevron-back" size={26} color={colors.onSurface} /></Pressable>
          <Text style={styles.hTitle}>Admission Pipeline</Text>
          <View style={{ width: 26 }} />
        </View>
        <ScrollView contentContainerStyle={styles.s}>
          <Text style={styles.wow}>{result.agent.name}</Text>
          <Text style={styles.sub}>Trust {result.agent.trust_score} · Risk {result.agent.risk}</Text>
          <View style={{ marginTop: spacing.xl }}>
            {result.pipeline.map((p, i) => (
              <View key={i} style={styles.stepRow} testID={`pipeline-step-${i}`}>
                <View style={styles.stepCol}>
                  <Ionicons name={STATUS_ICON[p.status] as any} size={20} color={STATUS_COLOR[p.status]} />
                  {i < result.pipeline.length - 1 ? <View style={styles.stepLine} /> : null}
                </View>
                <View style={{ flex: 1, paddingBottom: spacing.lg }}>
                  <Text style={styles.stepName}>{p.step}</Text>
                  <Text style={styles.stepDetail}>{p.detail}</Text>
                </View>
              </View>
            ))}
          </View>
          <Pressable style={styles.primary} onPress={() => router.replace({ pathname: "/governance/agent/[id]", params: { id: result.agent.id } })} testID="open-agent-btn">
            <Text style={styles.primaryT}>Open agent</Text>
          </Pressable>
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.c} testID="submit-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <View style={styles.head}>
          <Pressable onPress={() => router.back()} hitSlop={12}><Ionicons name="chevron-back" size={26} color={colors.onSurface} /></Pressable>
          <Text style={styles.hTitle}>Submit Agent</Text>
          <View style={{ width: 26 }} />
        </View>
        <ScrollView contentContainerStyle={styles.s} keyboardShouldPersistTaps="handled">
          <Text style={styles.tag}>MARKETPLACE ADMISSION</Text>
          <Text style={styles.h1}>Register a new agent.</Text>
          <Text style={styles.sub}>Manifest is auto-analyzed for capabilities, risk, and policy compliance.</Text>

          <Text style={styles.lab}>Name</Text>
          <TextInput testID="sub-name" style={styles.input} value={name} onChangeText={setName} placeholder="e.g. Meeting Summarizer" placeholderTextColor={colors.muted} />
          <Text style={styles.lab}>Author</Text>
          <TextInput testID="sub-author" style={styles.input} value={author} onChangeText={setAuthor} placeholder="Your name / org" placeholderTextColor={colors.muted} />
          <Text style={styles.lab}>Manifest</Text>
          <TextInput
            testID="sub-manifest"
            style={[styles.input, { minHeight: 140, textAlignVertical: "top" }]}
            value={manifest}
            onChangeText={setManifest}
            multiline
            placeholder="What does this agent do? Which memories does it read or write? Does it need network access?"
            placeholderTextColor={colors.muted}
          />
          <Pressable testID="sub-submit" style={styles.primary} onPress={submit} disabled={busy || !name.trim() || !manifest.trim()}>
            {busy ? <ActivityIndicator color="#fff" /> : (<><Ionicons name="shield-checkmark" size={18} color="#fff" /><Text style={styles.primaryT}>Run Admission Pipeline</Text></>)}
          </Pressable>
        </ScrollView>
      </KeyboardAvoidingView>
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
  sub: { color: colors.muted, fontSize: fs.base, marginTop: 4, marginBottom: spacing.md },
  lab: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5, marginTop: spacing.lg, marginBottom: 6 },
  input: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, fontSize: fs.base, color: colors.onSurface },
  primary: { flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center", backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, marginTop: spacing.xl },
  primaryT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  wow: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: spacing.md },
  stepRow: { flexDirection: "row", gap: spacing.md },
  stepCol: { width: 24, alignItems: "center" },
  stepLine: { flex: 1, width: 1, backgroundColor: colors.border, marginTop: 4 },
  stepName: { fontWeight: "700", color: colors.onSurface, fontSize: fs.base },
  stepDetail: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
});
