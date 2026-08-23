import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator, TextInput, Pressable, KeyboardAvoidingView, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useFocusEffect } from "expo-router";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";

type Shadow = { insights: string[]; top_patterns: { label: string; weight: number }[]; kind?: string; description?: string };
type Trait = { trait: string; score: number; confidence: number; evidence: { id: string; title: string }[]; evidence_count: number; counter_signal: { trait: string; hits: number; note: string } | null };
type DNA = { traits: Trait[]; total_signals: number; notes_analyzed: number; disclaimer: string };
type TwinResp = { prediction: string; confidence: number; evidence: { kind: string; id: string; title: string; number?: number }[]; evidence_count: number; ratified_precedents?: number; known_contradictions?: number; counter_signal: string | null; reasoning: string; kind: string };

export default function GenomeScreen() {
  const { token } = useAuth();
  const [shadow, setShadow] = useState<Shadow | null>(null);
  const [dna, setDna] = useState<DNA | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [question, setQuestion] = useState("What would I probably build next?");
  const [answer, setAnswer] = useState<TwinResp | null>(null);
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
    setBusy(true); setAnswer(null);
    try {
      const r = await api<TwinResp>("/api/twin/predict", { method: "POST", token, body: JSON.stringify({ question }) });
      setAnswer(r);
    } catch (e: any) { setAnswer({ prediction: "Twin unavailable: " + e.message, confidence: 0, evidence: [], evidence_count: 0, counter_signal: null, reasoning: "", kind: "ERROR" }); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="genome-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.s} keyboardShouldPersistTaps="handled">
          <Text style={styles.h1}>Genome</Text>
          <Text style={styles.sub}>Your Cognitive DNA, Shadow & Twin.</Text>

          {dna ? (
            <View style={styles.section}>
              <View style={styles.rowBetween}>
                <Text style={styles.sh}>Cognitive DNA</Text>
                <View style={styles.kindPill}><Text style={styles.kindPillT}>DERIVED FROM HISTORY</Text></View>
              </View>
              <Text style={styles.desc}>{dna.disclaimer}</Text>
              <Text style={styles.descMuted}>{dna.notes_analyzed} notes analyzed · {dna.total_signals} signals</Text>
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
                    <View style={styles.traitMetaRow}>
                      <Text style={styles.traitMeta}>confidence {Math.round(t.confidence * 100)}%</Text>
                      <Text style={styles.traitMeta}>evidence {t.evidence_count}</Text>
                      {t.counter_signal ? (
                        <Text style={[styles.traitMeta, { color: "#B41B10" }]}>counter · {t.counter_signal.trait}</Text>
                      ) : null}
                    </View>
                    {expanded === t.trait ? (
                      <View style={styles.evidence}>
                        <Text style={styles.evidenceLab}>Supporting notes</Text>
                        {t.evidence.length ? t.evidence.map(e => (
                          <Text key={e.id} style={styles.evidenceT}>· {e.title}</Text>
                        )) : <Text style={styles.evidenceT}>Insufficient evidence yet.</Text>}
                        {t.counter_signal ? (
                          <>
                            <Text style={[styles.evidenceLab, { marginTop: 8, color: "#B41B10" }]}>Counter-signal</Text>
                            <Text style={styles.evidenceT}>{t.counter_signal.note} ({t.counter_signal.trait}: {t.counter_signal.hits} hits)</Text>
                          </>
                        ) : null}
                      </View>
                    ) : null}
                  </Pressable>
                ))}
              </View>
            </View>
          ) : null}

          <View style={styles.section}>
            <View style={styles.rowBetween}>
              <Text style={styles.sh}>AI Shadow</Text>
              <View style={styles.kindPill}><Text style={styles.kindPillT}>DESCRIPTIVE MODEL</Text></View>
            </View>
            <Text style={styles.desc}>How you tend to think — descriptive, not predictive.</Text>
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
            <View style={styles.rowBetween}>
              <Text style={styles.twinH}>Cognitive Twin</Text>
              <View style={styles.kindPillDark}><Text style={styles.kindPillDarkT}>MODEL PREDICTION</Text></View>
            </View>
            <Text style={styles.descLight}>Ask what YOU would probably do next — reasoned from your history.</Text>
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
              {busy ? <ActivityIndicator color={colors.onSurface} /> : (
                <><Ionicons name="planet" size={18} color={colors.onSurface} /><Text style={styles.askT}>Ask Twin</Text></>
              )}
            </Pressable>
            {answer ? (
              <View style={styles.ans} testID="twin-answer">
                <Text style={styles.ansHeader}>PREDICTION · confidence {Math.round((answer.confidence || 0) * 100)}%</Text>
                <Text style={styles.ansT}>{answer.prediction}</Text>
                {answer.reasoning ? (
                  <>
                    <Text style={styles.ansHeader2}>Reasoning</Text>
                    <Text style={styles.ansT2}>{answer.reasoning}</Text>
                  </>
                ) : null}
                {answer.counter_signal ? (
                  <>
                    <Text style={[styles.ansHeader2, { color: "#FFB1B1" }]}>Counter-signal</Text>
                    <Text style={styles.ansT2}>{answer.counter_signal}</Text>
                  </>
                ) : null}
                {answer.evidence?.length ? (
                  <>
                    <Text style={styles.ansHeader2}>Evidence · {answer.evidence_count} items reasoned from</Text>
                    {answer.evidence.slice(0, 6).map((e, i) => (
                      <Text key={i} style={styles.ansT2}>· {e.kind === "decision" ? `Decision #${e.number}` : "Note"}: {e.title}</Text>
                    ))}
                  </>
                ) : null}
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
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  descMuted: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  descLight: { color: "#B8B8BD", fontSize: fs.base, marginTop: 4 },
  kindPill: { backgroundColor: "#E8F0FF", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  kindPillT: { color: "#1A4FA3", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  kindPillDark: { backgroundColor: "#333", paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  kindPillDarkT: { color: "#7BE38B", fontSize: 9, fontWeight: "800", letterSpacing: 0.8 },
  traitMetaRow: { flexDirection: "row", gap: 12, marginTop: 4, flexWrap: "wrap" },
  traitMeta: { color: colors.muted, fontSize: 10, fontWeight: "700", letterSpacing: 0.3 },
  ansHeader: { color: "#7BE38B", fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginBottom: 6 },
  ansHeader2: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.0, fontWeight: "700", marginTop: 10, marginBottom: 4 },
  ansT2: { color: "#DDD", fontSize: fs.sm, lineHeight: 19 },
});
