import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, TextInput, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";

type Shadow = { insights: string[]; top_patterns: { label: string; weight: number }[] };
type Trait = { trait: string; score: number; evidence: { id: string; title: string }[] };
type DNA = { traits: Trait[]; total_signals: number };

export default function GenomeScreen() {
  const { token } = useAuth();
  const [shadow, setShadow] = useState<Shadow | null>(null);
  const [dna, setDna] = useState<DNA | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [question, setQuestion] = useState("What would I probably build next?");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);

  const loadShadow = useCallback(async () => {
    if (!token) return;
    // Load DNA immediately (fast, no LLM)
    api<DNA>("/api/cognitive-dna", { token }).then(setDna).catch(() => {});
    // Shadow can be slow (Gemini)
    api<Shadow>("/api/shadow", { token }).then(setShadow).catch(() => {});
  }, [token]);
  useFocusEffect(useCallback(() => { loadShadow(); }, [loadShadow]));

  const askTwin = async () => {
    setBusy(true); setAnswer("");
    try {
      const r = await api<{ answer: string }>("/api/twin/predict", { method: "POST", token, body: JSON.stringify({ question }) });
      setAnswer(r.answer);
    } catch (e: any) { setAnswer("Twin unavailable: " + e.message); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="genome-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.s} keyboardShouldPersistTaps="handled">
          <Text style={styles.h1}>Genome</Text>
          <Text style={styles.sub}>Your Cognitive DNA, Shadow & Twin.</Text>

          {dna ? (
            <View style={styles.section}>
              <Text style={styles.sh}>Cognitive DNA</Text>
              <Text style={styles.desc}>Your thinking style, scored from {dna.total_signals} signals.</Text>
              <View style={{ marginTop: spacing.md, gap: spacing.md }}>
                {dna.traits.map((t) => (
                  <Pressable key={t.trait} onPress={() => setExpanded(expanded === t.trait ? null : t.trait)} testID={`trait-${t.trait}`}>
                    <View style={styles.traitRow}>
                      <Text style={styles.traitName}>{t.trait}</Text>
                      <Text style={styles.traitScore}>{t.score}%</Text>
                    </View>
                    <View style={styles.traitBar}>
                      <View style={[styles.traitFill, { width: `${t.score}%` }]} />
                    </View>
                    {expanded === t.trait && t.evidence.length ? (
                      <View style={styles.evidence}>
                        <Text style={styles.evidenceLab}>Evidence</Text>
                        {t.evidence.map(e => (
                          <Text key={e.id} style={styles.evidenceT}>· {e.title}</Text>
                        ))}
                      </View>
                    ) : null}
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          <View style={styles.section}>
            <Text style={styles.sh}>AI Shadow</Text>
            <Text style={styles.desc}>How you think — not what you know.</Text>
            {!shadow ? <ActivityIndicator style={{ marginTop: 16 }} /> : (
              <View style={{ gap: spacing.sm, marginTop: spacing.md }}>
                {shadow.insights.map((ins, i) => (
                  <View key={i} style={styles.insightRow} testID={`shadow-insight-${i}`}>
                    <View style={styles.insightDot} />
                    <Text style={styles.insightT}>{ins}</Text>
                  </View>
                ))}
                {shadow.top_patterns.length ? (
                  <View style={{ marginTop: spacing.md }}>
                    <Text style={styles.subLab}>Top patterns</Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                      {shadow.top_patterns.map(p => (
                        <View key={p.label} style={styles.pat}><Text style={styles.patT}>{p.label} · {p.weight}</Text></View>
                      ))}
                    </View>
                  </View>
                ) : null}
              </View>
            )}
          </View>

          <View style={styles.twin}>
            <Text style={styles.twinH}>Cognitive Twin</Text>
            <Text style={styles.desc}>Ask what YOU would probably do next — reasoned from your history.</Text>
            <TextInput
              value={question}
              onChangeText={setQuestion}
              multiline
              style={styles.q}
              placeholder="What would I probably prioritize next?"
              placeholderTextColor={colors.muted}
              testID="twin-input"
            />
            <Pressable style={styles.askBtn} onPress={askTwin} disabled={busy} testID="twin-ask">
              {busy ? <ActivityIndicator color="#fff" /> : (
                <><Ionicons name="planet" size={18} color="#fff" /><Text style={styles.askT}>Ask Twin</Text></>
              )}
            </Pressable>
            {answer ? (
              <View style={styles.ans} testID="twin-answer">
                <Text style={styles.ansT}>{answer}</Text>
              </View>
            ) : null}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  s: { padding: spacing.xl, paddingBottom: 140, gap: spacing.md },
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  sub: { color: colors.muted, fontSize: fs.base, marginBottom: spacing.md },
  section: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl },
  sh: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  desc: { color: colors.muted, fontSize: fs.base, marginTop: 4 },
  insightRow: { flexDirection: "row", gap: spacing.sm, alignItems: "flex-start" },
  insightDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.onSurface, marginTop: 8 },
  insightT: { flex: 1, color: colors.onSurface, fontSize: fs.lg, lineHeight: 22 },
  subLab: { fontSize: fs.sm, color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  pat: { backgroundColor: "#fff", borderRadius: radius.pill, paddingHorizontal: 10, paddingVertical: 4 },
  patT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  twin: { backgroundColor: colors.onSurface, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.md },
  twinH: { color: "#fff", fontSize: fs.xl, fontWeight: "800" },
  q: { backgroundColor: "#111", color: "#fff", padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md, minHeight: 60, fontSize: fs.base, textAlignVertical: "top" },
  askBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: "#fff", padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md },
  askT: { color: colors.onSurface, fontWeight: "700", fontSize: fs.lg },
  ans: { marginTop: spacing.md, backgroundColor: "#111", padding: spacing.md, borderRadius: radius.md },
  ansT: { color: "#fff", fontSize: fs.base, lineHeight: 22 },
  traitRow: { flexDirection: "row", justifyContent: "space-between" },
  traitName: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  traitScore: { color: colors.onSurface, fontSize: fs.base, fontWeight: "800" },
  traitBar: { marginTop: 6, height: 6, backgroundColor: "#fff", borderRadius: 3, overflow: "hidden" },
  traitFill: { height: 6, backgroundColor: colors.onSurface, borderRadius: 3 },
  evidence: { marginTop: 8, paddingLeft: 8, borderLeftWidth: 2, borderLeftColor: colors.border },
  evidenceLab: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  evidenceT: { color: colors.onSurfaceSecondary, fontSize: fs.sm, marginTop: 2 },
});
