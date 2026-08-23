import React, { useCallback, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { useLocalSearchParams, useRouter, useFocusEffect } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs, agentColorMap } from "@/src/theme";
import Ring from "@/src/components/Ring";

type Note = {
  id: string; title: string; text: string; concepts: string[]; gravity: number;
  revenue: number; produced_projects: number; produced_tasks: number;
  produced_articles: number; produced_proposals: number; created_at: string;
};
type Version = { id: string; version: number; stage: string; text: string; created_at: string };
type Council = { agent: string; color_key: string; response: string };
type Decision = { id: string; number: number; title: string; affected_projects: number; produced_tasks: number; referenced_notes: number; influenced_agents: number; context_hash?: string; reasoning_hash?: string; governance_hash?: string; outcome_hash?: string; dna_root?: string; reasoning_source?: string; reasoning_consensus_id?: string; reasoning_synthesis_id?: string };
type Operation = { id: string; command: string; label: string; output: string; created_at: string };
type Verdict = { agent: string; color_key: string; position: string; confidence: number; risk_score: number; reasoning: string; evidence: string[] };
type ConsensusScore = { score: number; recommendation: string; alignment: number; evidence_weight: number; risk_penalty: number; historical_success: number; avg_confidence: number; approve_count: number; reject_count: number; uncertain_count: number; needs_debate: boolean };
type RouterPlan = { intent: string; mode: string; steps: { agent_name: string; role: string; score: number; governance: any }[]; context_refs: any };
type Trigger = { kind: string; detail: string; weight: number };
type DebateTurn = { role: string; provider: string; model: string; against?: string; for?: string; argument: string; argument_hash: string; responds_to?: any };
type Synthesis = { resolution: string; conditions: string[]; escalate: boolean; escalate_reason: string; confidence: number; synthesis_position: string };
type DebateRecord = { id: string; note_id: string; consensus_id: string; triggers: Trigger[]; disagreement_stddev: number; majority: string; turns: DebateTurn[]; synthesis: Synthesis; synthesis_hash: string; ratified: boolean; ratified_at?: string; ratified_by?: string; rejected: boolean; rejected_at?: string; rejected_by?: string; created_at: string };
type TriggerResp = { triggers: Trigger[]; should_debate: boolean; disagreement_stddev: number; consensus_id?: string | null };
type Contradiction = {
  id: string;
  new_note_id: string;
  new_position: string;
  prior_note_id: string;
  prior_note_title?: string;
  prior_decision_id?: string;
  prior_decision_number?: number;
  prior_position: string;
  prior_synthesis_hash?: string;
  prior_ratified_at?: string;
  overlapping_concepts: string[];
  concept_overlap_score?: number;
  concept_overlap_jaccard?: number;
  concept_overlap_containment?: number;
  resolved: boolean;
  resolved_by?: string;
  created_at: string;
};

const TRIGGER_LABELS: Record<string, { label: string; color: string }> = {
  low_confidence: { label: "Low confidence", color: "#8A6D00" },
  agent_disagreement: { label: "Agent disagreement", color: "#B41B10" },
  high_risk: { label: "High risk", color: "#B41B10" },
  governance_domain: { label: "Governance domain", color: "#5A3A00" },
  prior_decision_conflict: { label: "Prior decision conflict", color: "#8A6D00" },
  insufficient_evidence: { label: "Insufficient evidence", color: "#8A6D00" },
  novel_decision: { label: "Novel decision", color: "#0E7A2A" },
  conflicting_positions: { label: "Conflicting positions", color: "#B41B10" },
};

const OP_COMMANDS: { cmd: string; label: string; icon: string }[] = [
  { cmd: "summarize", label: "Summarize", icon: "reader-outline" },
  { cmd: "refactor", label: "Refactor", icon: "construct-outline" },
  { cmd: "generate_sop", label: "Generate SOP", icon: "list-outline" },
  { cmd: "find_gaps", label: "Find Gaps", icon: "search-outline" },
  { cmd: "next_actions", label: "Next Actions", icon: "flash-outline" },
];

const DnaRow = ({ label, hash, verified, sublabel }: { label: string; hash?: string; verified?: boolean; sublabel?: string }) => (
  <View style={styles.dnaRow}>
    <View style={{ flex: 1 }}>
      <Text style={styles.dnaLabel}>{label}{sublabel ? <Text style={{ color: "#7BE38B" }}>  · {sublabel}</Text> : null}</Text>
      <Text style={styles.dnaHash}>{hash ? hash.slice(0, 20) + "…" : "—"}</Text>
    </View>
    <View style={styles.dnaBadge}>
      <Ionicons name="shield-checkmark" size={12} color={verified ? "#7BE38B" : "#B8B8BD"} />
      <Text style={[styles.dnaBadgeT, { color: verified ? "#7BE38B" : "#B8B8BD" }]}>{verified ? "Verified" : "—"}</Text>
    </View>
  </View>
);

export default function NoteDetail() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { token } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<{ note: Note; versions: Version[]; council: Council[]; decisions: Decision[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(false);
  const [ops, setOps] = useState<Operation[]>([]);
  const [opBusy, setOpBusy] = useState<string | null>(null);
  const [consensus, setConsensus] = useState<{ verdicts: Verdict[]; score: ConsensusScore } | null>(null);
  const [triggers, setTriggers] = useState<TriggerResp | null>(null);
  const [debate, setDebate] = useState<DebateRecord | null>(null);
  const [routerPlan, setRouterPlan] = useState<RouterPlan | null>(null);
  const [consensusBusy, setConsensusBusy] = useState(false);
  const [debateBusy, setDebateBusy] = useState(false);
  const [ratifyBusy, setRatifyBusy] = useState<"ratify" | "reject" | null>(null);
  const [routerBusy, setRouterBusy] = useState(false);
  const [contradictions, setContradictions] = useState<{ as_new: Contradiction[]; as_prior: Contradiction[] }>({ as_new: [], as_prior: [] });

  const load = useCallback(async () => {
    if (!token || !id) return;
    try { setData(await api(`/api/notes/${id}`, { token })); } catch {}
    try { setOps(await api<Operation[]>(`/api/notes/${id}/operations`, { token })); } catch {}
    try {
      const latest = await api<DebateRecord | null>(`/api/notes/${id}/debate/latest`, { token });
      if (latest && latest.id) setDebate(latest);
    } catch {}
    try {
      const cs = await api<{ as_new: Contradiction[]; as_prior: Contradiction[] }>(`/api/notes/${id}/contradictions`, { token });
      setContradictions(cs);
    } catch {}
  }, [token, id]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const runOperation = async (cmd: string) => {
    setOpBusy(cmd);
    try {
      const r = await api<Operation>(`/api/notes/${id}/operations`, { method: "POST", token, body: JSON.stringify({ command: cmd }) });
      setOps((prev) => [r, ...prev]);
    } catch (e: any) { alert(e.message); } finally { setOpBusy(null); }
  };

  const runAllOperations = async () => {
    setOpBusy("all");
    try {
      const results: Operation[] = [];
      for (const c of OP_COMMANDS) {
        try {
          const r = await api<Operation>(`/api/notes/${id}/operations`, { method: "POST", token, body: JSON.stringify({ command: c.cmd }) });
          results.push(r);
          setOps((prev) => [r, ...prev]);
        } catch {}
      }
    } finally { setOpBusy(null); }
  };

  const chatAboutNote = async () => {
    try {
      const s = await api<{ id: string }>(`/api/chat/sessions`, {
        method: "POST", token,
        body: JSON.stringify({ note_context_id: id }),
      });
      router.push({ pathname: "/chat/[id]", params: { id: s.id } });
    } catch (e: any) { alert(e.message); }
  };

  const runConsensus = async () => {
    setConsensusBusy(true); setDebate(null); setTriggers(null);
    try {
      const r = await api<{ verdicts: Verdict[]; score: ConsensusScore }>(`/api/notes/${id}/council/consensus`, { method: "POST", token });
      setConsensus(r);
      // Fetch trigger analysis for this fresh consensus
      try {
        const t = await api<TriggerResp>(`/api/notes/${id}/debate/triggers`, { token });
        setTriggers(t);
      } catch {}
      // Recompute DNA on all existing decisions for this note so their reasoning_hash now covers the fresh verdicts
      if (data?.decisions?.length) {
        await Promise.all(data.decisions.map(d => api(`/api/decisions/${d.id}/dna`, { token }).catch(() => {})));
        await load();
      }
      // Refresh contradictions (consensus may have detected new ones)
      try {
        const cs = await api<{ as_new: Contradiction[]; as_prior: Contradiction[] }>(`/api/notes/${id}/contradictions`, { token });
        setContradictions(cs);
      } catch {}
    } catch (e: any) { alert(e.message); } finally { setConsensusBusy(false); }
  };
  const runDebate = async () => {
    setDebateBusy(true);
    try {
      const r = await api<DebateRecord>(`/api/notes/${id}/council/debate`, { method: "POST", token });
      setDebate(r);
    } catch (e: any) { alert(e.message); } finally { setDebateBusy(false); }
  };
  const ratifySynthesis = async () => {
    if (!debate) return;
    setRatifyBusy("ratify");
    try {
      const r = await api<{ synthesis: DebateRecord; rebound_decisions: any[] }>(`/api/synthesis/${debate.id}/ratify`, { method: "POST", token });
      setDebate(r.synthesis);
      await load();
    } catch (e: any) { alert(e.message); } finally { setRatifyBusy(null); }
  };
  const rejectSynthesis = async () => {
    if (!debate) return;
    setRatifyBusy("reject");
    try {
      const r = await api<DebateRecord>(`/api/synthesis/${debate.id}/reject`, { method: "POST", token });
      setDebate(r);
    } catch (e: any) { alert(e.message); } finally { setRatifyBusy(null); }
  };
  const resolveContradiction = async (cid: string) => {
    try {
      await api(`/api/contradictions/${cid}/resolve`, { method: "POST", token });
      const cs = await api<{ as_new: Contradiction[]; as_prior: Contradiction[] }>(`/api/notes/${id}/contradictions`, { token });
      setContradictions(cs);
    } catch (e: any) { alert(e.message); }
  };
  const runRouter = async () => {
    setRouterBusy(true);
    try {
      const r = await api<RouterPlan>(`/api/router/route`, {
        method: "POST", token,
        body: JSON.stringify({ note_id: id, text: data?.note.text || "" }),
      });
      setRouterPlan(r);
    } catch (e: any) { alert(e.message); } finally { setRouterBusy(false); }
  };

  const runCouncil = async () => {
    setBusy(true);
    try {
      await api(`/api/notes/${id}/council`, { method: "POST", token });
      await load();
    } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  };

  const createDecision = async () => {
    try {
      await api(`/api/decisions`, { method: "POST", token, body: JSON.stringify({ title: `Decision from: ${data?.note.title}`, note_id: id }) });
      await load();
    } catch (e: any) { alert(e.message); }
  };

  const evolve = async () => {
    try {
      await api(`/api/notes/${id}/evolve`, { method: "POST", token, body: JSON.stringify({ text: data?.note.text || "" }) });
      await load();
    } catch (e: any) { alert(e.message); }
  };

  if (!data) return <SafeAreaView style={styles.c}><ActivityIndicator style={{ marginTop: 40 }} /></SafeAreaView>;
  const { note, versions, council, decisions } = data;

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="note-detail-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="back-btn">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle} numberOfLines={1}>Note</Text>
        <View style={{ width: 26 }} />
      </View>
      <ScrollView
        contentContainerStyle={styles.s}
        refreshControl={<RefreshControl refreshing={refresh} onRefresh={async () => { setRefresh(true); await load(); setRefresh(false); }} />}
      >
        <Text style={styles.title}>{note.title}</Text>
        <Text style={styles.time}>{dayjs(note.created_at).format("MMM D · HH:mm")}</Text>
        <Text style={styles.body}>{note.text}</Text>

        <View style={styles.chips}>
          {note.concepts.map(c => (<View key={c} style={styles.chip}><Text style={styles.chipT}>{c}</Text></View>))}
        </View>

        <View style={styles.gravCard}>
          <View style={{ flex: 1 }}>
            <Text style={styles.lab}>Memory Gravity</Text>
            <Text style={styles.gravVal}>{note.gravity}</Text>
            <Text style={styles.sub}>How much this idea pulls the rest of your knowledge.</Text>
          </View>
          <Ring size={90} strokeWidth={10} percent={note.gravity} color={colors.onSurface} />
        </View>

        <Pressable style={styles.chatAboutBtn} onPress={chatAboutNote} testID="chat-about-note">
          <Ionicons name="chatbubbles-outline" size={18} color="#fff" />
          <Text style={styles.chatAboutT}>Chat about this note</Text>
        </Pressable>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Council Consensus</Text>
            <Pressable style={styles.smallBtn} onPress={runConsensus} disabled={consensusBusy} testID="run-consensus">
              {consensusBusy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.smallBtnT}>{consensus ? "Rerun" : "Convene"}</Text>}
            </Pressable>
          </View>
          {!consensus ? (
            <Text style={styles.subDim}>Run a structured vote across the 5 agents (position + confidence + risk).</Text>
          ) : (
            <View style={styles.consBox}>
              <View style={styles.consHead}>
                <Text style={[styles.consRec, {
                  color: consensus.score.recommendation === "APPROVE" ? "#0E7A2A"
                    : consensus.score.recommendation === "REJECT" ? "#B41B10" : "#8A6D00"
                }]}>{consensus.score.recommendation}</Text>
                <Text style={styles.consScore}>score {consensus.score.score}</Text>
              </View>
              <View style={styles.consMeta}>
                <Text style={styles.consMetaT}>align {consensus.score.alignment} · evidence {consensus.score.evidence_weight} · risk {consensus.score.risk_penalty} · hist {consensus.score.historical_success}</Text>
                <Text style={styles.consMetaT}>{consensus.score.approve_count} approve · {consensus.score.reject_count} reject · {consensus.score.uncertain_count} uncertain</Text>
              </View>
              {consensus.verdicts.map(v => (
                <View key={v.agent} style={styles.vRowC} testID={`verdict-${v.agent}`}>
                  <View style={[styles.posBadge, {
                    backgroundColor: v.position === "APPROVE" ? "#DCF7DC" : v.position === "REJECT" ? "#FFE9E7" : "#FFF4CC"
                  }]}>
                    <Text style={[styles.posT, {
                      color: v.position === "APPROVE" ? "#0E7A2A" : v.position === "REJECT" ? "#B41B10" : "#8A6D00"
                    }]}>{v.position}</Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.vAgent}>{v.agent}</Text>
                    <Text style={styles.vReason} numberOfLines={2}>{v.reasoning}</Text>
                  </View>
                  <View style={{ alignItems: "flex-end" }}>
                    <Text style={styles.vNum}>{Math.round(v.confidence * 100)}%</Text>
                    <Text style={styles.vRisk}>risk {v.risk_score}</Text>
                  </View>
                </View>
              ))}
            </View>
          )}

          {triggers && triggers.triggers.length > 0 ? (
            <View style={styles.triggersBox} testID="debate-triggers">
              <Text style={styles.triggersLab}>DEBATE TRIGGERS · {triggers.triggers.length} signal{triggers.triggers.length === 1 ? "" : "s"}</Text>
              <View style={styles.triggerChips}>
                {triggers.triggers.map((t, i) => (
                  <View key={i} style={[styles.triggerChip, { borderColor: (TRIGGER_LABELS[t.kind]?.color || "#B8B8BD") + "66", backgroundColor: (TRIGGER_LABELS[t.kind]?.color || "#B8B8BD") + "15" }]} testID={`trigger-${t.kind}`}>
                    <Text style={[styles.triggerChipT, { color: TRIGGER_LABELS[t.kind]?.color || "#333" }]}>
                      {TRIGGER_LABELS[t.kind]?.label || t.kind}
                    </Text>
                    <Text style={styles.triggerChipDetail} numberOfLines={1}>{t.detail}</Text>
                  </View>
                ))}
              </View>
              <Text style={styles.triggerFoot}>disagreement σ {triggers.disagreement_stddev} · escalation required</Text>
            </View>
          ) : null}

          {(triggers?.should_debate || consensus?.score.needs_debate) && !debate ? (
            <Pressable style={styles.debateBtn} onPress={runDebate} disabled={debateBusy} testID="run-debate">
              {debateBusy ? <ActivityIndicator color="#fff" size="small" /> : (
                <><Ionicons name="git-branch" size={14} color="#fff" /><Text style={styles.debateT}>Run Council Debate (Critic · Defender · Synthesis)</Text></>
              )}
            </Pressable>
          ) : null}

          {debate ? (
                <View style={styles.debateBox} testID="debate-box">
                  <View style={styles.debateHead}>
                    <Text style={styles.debateLab}>COUNCIL DEBATE</Text>
                    {debate.ratified ? (
                      <View style={[styles.debateStatus, { backgroundColor: "#DCF7DC" }]}>
                        <Ionicons name="shield-checkmark" size={11} color="#0E7A2A" />
                        <Text style={[styles.debateStatusT, { color: "#0E7A2A" }]}>RATIFIED</Text>
                      </View>
                    ) : debate.rejected ? (
                      <View style={[styles.debateStatus, { backgroundColor: "#FFE9E7" }]}>
                        <Ionicons name="close-circle" size={11} color="#B41B10" />
                        <Text style={[styles.debateStatusT, { color: "#B41B10" }]}>REJECTED</Text>
                      </View>
                    ) : (
                      <View style={[styles.debateStatus, { backgroundColor: "#FFF4CC" }]}>
                        <Ionicons name="time" size={11} color="#8A6D00" />
                        <Text style={[styles.debateStatusT, { color: "#8A6D00" }]}>UNRATIFIED</Text>
                      </View>
                    )}
                  </View>

                  {debate.turns.map((turn, i) => (
                    <View key={i} style={styles.turnCard} testID={`debate-turn-${turn.role}`}>
                      <View style={styles.turnHead}>
                        <Text style={[styles.turnRole, {
                          color: turn.role === "critic" ? "#B41B10" : turn.role === "defender" ? "#0E7A2A" : "#5A3A00"
                        }]}>{turn.role.toUpperCase()}</Text>
                        <Text style={styles.turnModel}>{turn.provider} · {turn.model}</Text>
                      </View>
                      <Text style={styles.turnBody}>{turn.argument}</Text>
                      <Text style={styles.turnHash}>hash {turn.argument_hash.slice(0, 16)}…</Text>
                    </View>
                  ))}

                  <View style={styles.synthCard} testID="synthesis-proposal">
                    <View style={styles.turnHead}>
                      <Text style={[styles.turnRole, { color: "#000" }]}>SYNTHESIS PROPOSAL</Text>
                      <View style={[styles.posBadge, {
                        backgroundColor: debate.synthesis.synthesis_position === "APPROVE" ? "#DCF7DC"
                          : debate.synthesis.synthesis_position === "REJECT" ? "#FFE9E7"
                          : debate.synthesis.synthesis_position === "CONDITIONAL_APPROVE" ? "#E8F0FF"
                          : "#FFF4CC",
                      }]}>
                        <Text style={[styles.posT, {
                          color: debate.synthesis.synthesis_position === "APPROVE" ? "#0E7A2A"
                            : debate.synthesis.synthesis_position === "REJECT" ? "#B41B10"
                            : debate.synthesis.synthesis_position === "CONDITIONAL_APPROVE" ? "#1A4FA3"
                            : "#8A6D00",
                        }]}>{debate.synthesis.synthesis_position}</Text>
                      </View>
                    </View>
                    <Text style={styles.synthRow}><Text style={styles.synthK}>Resolution: </Text>{debate.synthesis.resolution || "(no resolution parsed)"}</Text>
                    {debate.synthesis.conditions.length > 0 ? (
                      <View style={{ marginTop: 4 }}>
                        <Text style={styles.synthK}>Conditions:</Text>
                        {debate.synthesis.conditions.map((c, i) => (
                          <Text key={i} style={styles.synthRow}>• {c}</Text>
                        ))}
                      </View>
                    ) : null}
                    <Text style={styles.synthRow}>
                      <Text style={styles.synthK}>Escalate to human: </Text>
                      {debate.synthesis.escalate ? "YES" : "NO"}
                      {debate.synthesis.escalate_reason ? ` — ${debate.synthesis.escalate_reason}` : ""}
                    </Text>
                    <Text style={styles.synthRow}>
                      <Text style={styles.synthK}>Synthesizer confidence: </Text>{Math.round(debate.synthesis.confidence * 100)}%
                    </Text>
                    <Text style={styles.synthHash}>synthesis_hash · {debate.synthesis_hash.slice(0, 40)}…</Text>

                    {!debate.ratified && !debate.rejected ? (
                      <View style={styles.ratifyRow}>
                        <Pressable style={[styles.ratifyBtn, styles.ratifyApprove]} onPress={ratifySynthesis} disabled={!!ratifyBusy} testID="ratify-synthesis">
                          {ratifyBusy === "ratify" ? <ActivityIndicator color="#fff" size="small" /> : (
                            <><Ionicons name="shield-checkmark" size={14} color="#fff" /><Text style={styles.ratifyBtnT}>Ratify (bind to DNA)</Text></>
                          )}
                        </Pressable>
                        <Pressable style={[styles.ratifyBtn, styles.ratifyReject]} onPress={rejectSynthesis} disabled={!!ratifyBusy} testID="reject-synthesis">
                          {ratifyBusy === "reject" ? <ActivityIndicator color="#B41B10" size="small" /> : (
                            <><Ionicons name="close" size={14} color="#B41B10" /><Text style={[styles.ratifyBtnT, { color: "#B41B10" }]}>Reject</Text></>
                          )}
                        </Pressable>
                      </View>
                    ) : debate.ratified ? (
                      <Text style={styles.ratifiedFoot}>Ratified by {debate.ratified_by} · reasoning_hash now covers this synthesis</Text>
                    ) : (
                      <Text style={styles.rejectedFoot}>Rejected by {debate.rejected_by} · retained for audit only</Text>
                    )}
                  </View>
                </View>
              ) : null}
        </View>

        {(contradictions.as_new.length > 0 || contradictions.as_prior.length > 0) ? (
          <View style={styles.section}>
            <Text style={styles.sh}>Contradictions</Text>
            <Text style={styles.subDim}>Semantic conflicts with ratified precedents. Evidence-only; nothing has been rewritten.</Text>
            {contradictions.as_new.map(c => (
              <Pressable
                key={c.id}
                style={[styles.contraCard, c.resolved && { opacity: 0.55 }]}
                onPress={() => c.prior_note_id && router.push({ pathname: "/note/[id]", params: { id: c.prior_note_id } })}
                testID={`contradiction-${c.id}`}
              >
                <View style={styles.contraHead}>
                  <View style={styles.contraChip}>
                    <Ionicons name="flash-outline" size={11} color="#B41B10" />
                    <Text style={styles.contraChipT}>
                      Contradicts {c.prior_decision_number != null ? `Decision #${c.prior_decision_number}` : "prior ratified decision"}
                    </Text>
                  </View>
                  {c.resolved ? (
                    <View style={styles.contraResolved}>
                      <Ionicons name="checkmark-circle" size={11} color="#0E7A2A" />
                      <Text style={styles.contraResolvedT}>Resolved</Text>
                    </View>
                  ) : null}
                </View>
                <Text style={styles.contraTitle} numberOfLines={2}>{c.prior_note_title || "Unnamed prior note"}</Text>
                <View style={styles.contraPosRow}>
                  <View style={[styles.miniPos, { backgroundColor: c.new_position === "APPROVE" ? "#DCF7DC" : c.new_position === "REJECT" ? "#FFE9E7" : "#FFF4CC" }]}>
                    <Text style={[styles.miniPosT, { color: c.new_position === "APPROVE" ? "#0E7A2A" : c.new_position === "REJECT" ? "#B41B10" : "#8A6D00" }]}>THIS · {c.new_position}</Text>
                  </View>
                  <Ionicons name="swap-horizontal" size={12} color={colors.muted} />
                  <View style={[styles.miniPos, { backgroundColor: c.prior_position === "APPROVE" || c.prior_position === "CONDITIONAL_APPROVE" ? "#DCF7DC" : c.prior_position === "REJECT" ? "#FFE9E7" : "#FFF4CC" }]}>
                    <Text style={[styles.miniPosT, { color: c.prior_position === "APPROVE" || c.prior_position === "CONDITIONAL_APPROVE" ? "#0E7A2A" : c.prior_position === "REJECT" ? "#B41B10" : "#8A6D00" }]}>PRIOR · {c.prior_position}</Text>
                  </View>
                </View>
                <View style={styles.contraConcepts}>
                  {c.overlapping_concepts.slice(0, 5).map((cc, i) => (
                    <View key={i} style={styles.contraConcept}><Text style={styles.contraConceptT}>{cc}</Text></View>
                  ))}
                </View>
                <View style={styles.contraFoot}>
                  <Text style={styles.contraFootT}>overlap {Math.round(((c.concept_overlap_score ?? c.concept_overlap_jaccard) || 0) * 100)}% · jaccard {c.concept_overlap_jaccard} · containment {c.concept_overlap_containment ?? "—"}</Text>
                  {!c.resolved ? (
                    <Pressable onPress={() => resolveContradiction(c.id)} hitSlop={8} testID={`contradiction-resolve-${c.id}`}>
                      <Text style={styles.contraResolveBtn}>Mark resolved</Text>
                    </Pressable>
                  ) : (
                    <Text style={styles.contraResolvedFoot}>by {c.resolved_by}</Text>
                  )}
                </View>
              </Pressable>
            ))}
            {contradictions.as_prior.length > 0 ? (
              <View style={styles.contraPriorBox}>
                <Text style={styles.contraPriorLab}>THIS NOTE IS CITED AS PRECEDENT BY</Text>
                {contradictions.as_prior.map(c => (
                  <Pressable
                    key={c.id}
                    style={styles.contraPriorRow}
                    onPress={() => c.new_note_id && router.push({ pathname: "/note/[id]", params: { id: c.new_note_id } })}
                    testID={`contradiction-as-prior-${c.id}`}
                  >
                    <Ionicons name="arrow-back" size={13} color={colors.muted} />
                    <Text style={styles.contraPriorT} numberOfLines={1}>Challenged by a newer note ({c.new_position}) · {dayjs(c.created_at).format("MMM D")}</Text>
                  </Pressable>
                ))}
              </View>
            ) : null}
          </View>
        ) : null}

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Cognitive Router</Text>
            <Pressable style={styles.smallBtn} onPress={runRouter} disabled={routerBusy} testID="run-router">
              {routerBusy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.smallBtnT}>Route</Text>}
            </Pressable>
          </View>
          {!routerPlan ? (
            <Text style={styles.subDim}>Classify intent, pick agents, and assemble governed context.</Text>
          ) : (
            <View style={styles.routerBox}>
              <View style={styles.routerHead}>
                <Text style={styles.routerIntent}>{routerPlan.intent}</Text>
                <Text style={styles.routerMode}>{routerPlan.mode.toUpperCase()}</Text>
              </View>
              {routerPlan.steps.map((s, i) => (
                <View key={i} style={styles.routeRow} testID={`route-step-${s.agent_name}`}>
                  <Text style={styles.routeIdx}>{i + 1}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.routeAgent}>{s.agent_name}</Text>
                    <Text style={styles.routeRole}>{s.role}</Text>
                  </View>
                  <View style={[styles.leaseDot, { backgroundColor: s.governance.active_lease ? "#7BE38B" : "#FF3B30" }]} />
                  <Text style={styles.routeScore}>{s.score}</Text>
                </View>
              ))}
              <Text style={styles.routeCtx}>Context: {routerPlan.context_refs.notes.length} notes · {routerPlan.context_refs.decisions.length} decisions</Text>
            </View>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <View style={{ flex: 1 }}>
              <Text style={styles.sh}>Operations</Text>
              <Text style={styles.subDim}>Issue commands to Pocket OS.</Text>
            </View>
            <Pressable
              style={[styles.smallBtn, opBusy === "all" && { opacity: 0.6 }]}
              onPress={runAllOperations}
              disabled={!!opBusy}
              testID="run-all-ops"
            >
              {opBusy === "all" ? <ActivityIndicator color="#fff" size="small" /> : (
                <Text style={styles.smallBtnT}>Run all</Text>
              )}
            </Pressable>
          </View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md }} contentContainerStyle={{ gap: spacing.sm, paddingRight: spacing.md }}>
            {OP_COMMANDS.map(op => (
              <Pressable
                key={op.cmd}
                style={[styles.opChip, opBusy === op.cmd && { opacity: 0.6 }]}
                onPress={() => runOperation(op.cmd)}
                disabled={!!opBusy}
                testID={`op-${op.cmd}`}
              >
                {opBusy === op.cmd ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name={op.icon as any} size={14} color="#fff" />}
                <Text style={styles.opChipT}>{op.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
          {ops.length === 0 ? null : (
            <View style={{ marginTop: spacing.md, gap: spacing.md }}>
              {ops.slice(0, 5).map(o => (
                <View key={o.id} style={styles.opResult} testID={`op-result-${o.command}`}>
                  <View style={styles.opResultHead}>
                    <Text style={styles.opResultLab}>{o.label}</Text>
                    <Text style={styles.opResultTime}>{dayjs(o.created_at).format("HH:mm")}</Text>
                  </View>
                  <Text style={styles.opResultT}>{o.output}</Text>
                </View>
              ))}
            </View>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>AI Council</Text>
            <Pressable onPress={runCouncil} disabled={busy} style={styles.smallBtn} testID="run-council">
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.smallBtnT}>{council.length ? "Rerun" : "Convene"}</Text>}
            </Pressable>
          </View>
          {council.length === 0 ? (
            <Text style={styles.subDim}>Five specialists (Research, Architect, Critic, Planner, Doc Steward) will review this note.</Text>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: spacing.md }} contentContainerStyle={{ gap: spacing.md, paddingRight: spacing.md }}>
              {council.map((r, i) => (
                <View key={i} style={[styles.agentCard, { borderTopColor: agentColorMap[r.color_key] || colors.onSurface }]} testID={`council-${r.agent}`}>
                  <View style={[styles.agentDot, { backgroundColor: agentColorMap[r.color_key] || colors.onSurface }]} />
                  <Text style={styles.agentName}>{r.agent}</Text>
                  <Text style={styles.agentText}>{r.response}</Text>
                </View>
              ))}
            </ScrollView>
          )}
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Idea Evolution</Text>
            <Pressable onPress={evolve} style={styles.smallBtn} testID="evolve-btn">
              <Text style={styles.smallBtnT}>Evolve</Text>
            </Pressable>
          </View>
          <View style={{ marginTop: spacing.md }}>
            {versions.map((v, i) => (
              <View key={v.id} style={styles.vRow}>
                <View style={styles.vCol}>
                  <View style={styles.vDot} />
                  {i < versions.length - 1 ? <View style={styles.vLine} /> : null}
                </View>
                <View style={{ flex: 1, paddingBottom: spacing.md }}>
                  <Text style={styles.vStage}>v{v.version} · {v.stage}</Text>
                  <Text style={styles.vTime}>{dayjs(v.created_at).format("MMM D HH:mm")}</Text>
                </View>
              </View>
            ))}
          </View>
        </View>

        <View style={styles.section}>
          <View style={styles.rowBetween}>
            <Text style={styles.sh}>Decision DNA</Text>
            <Pressable onPress={createDecision} style={styles.smallBtn} testID="create-decision">
              <Text style={styles.smallBtnT}>Log Decision</Text>
            </Pressable>
          </View>
          {decisions.length === 0 ? (
            <Text style={styles.subDim}>Turn this note into a tracked decision to see its downstream lineage.</Text>
          ) : decisions.map(d => (
            <View key={d.id} style={styles.decCard} testID={`decision-${d.id}`}>
              <Text style={styles.decNum}>Decision #{d.number}</Text>
              <Text style={styles.decTitle}>{d.title}</Text>
              <View style={styles.decGrid}>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.affected_projects}</Text><Text style={styles.decLab}>Projects</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.produced_tasks}</Text><Text style={styles.decLab}>Tasks</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.referenced_notes}</Text><Text style={styles.decLab}>Notes</Text></View>
                <View style={styles.decMetric}><Text style={styles.decVal}>{d.influenced_agents}</Text><Text style={styles.decLab}>Agents</Text></View>
              </View>
              {d.dna_root ? (
                <View style={styles.dnaBox}>
                  <Text style={styles.dnaHeader}>Decision DNA</Text>
                  <DnaRow label="Context" hash={d.context_hash} verified />
                  <DnaRow label="Reasoning" hash={d.reasoning_hash} verified sublabel={d.reasoning_source === "synthesis" ? "bound to synthesis" : d.reasoning_source === "consensus" ? "bound to consensus" : d.reasoning_source === "raw_council" ? "raw council" : undefined} />
                  <DnaRow label="Governance" hash={d.governance_hash} verified />
                  <DnaRow label="Outcome" hash={d.outcome_hash} verified />
                  <View style={styles.dnaRoot}>
                    <Text style={styles.dnaRootLab}>DNA ROOT</Text>
                    <Text style={styles.dnaRootHash}>{d.dna_root.slice(0, 40)}…</Text>
                  </View>
                </View>
              ) : null}
            </View>
          ))}
        </View>

        <View style={styles.section}>
          <Text style={styles.sh}>Knowledge ROI</Text>
          <View style={styles.roiGrid}>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_projects}</Text><Text style={styles.roiLab}>Projects</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_tasks}</Text><Text style={styles.roiLab}>Tasks</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_articles}</Text><Text style={styles.roiLab}>Articles</Text></View>
            <View style={styles.roiTile}><Text style={styles.roiVal}>{note.produced_proposals}</Text><Text style={styles.roiLab}>Proposals</Text></View>
            <View style={[styles.roiTile, { flexBasis: "100%", backgroundColor: colors.onSurface }]}>
              <Text style={[styles.roiVal, { color: "#fff" }]}>${note.revenue.toLocaleString()}</Text>
              <Text style={[styles.roiLab, { color: "#B8B8BD" }]}>Attributed Revenue</Text>
            </View>
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.xl, paddingBottom: 60 },
  title: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface },
  time: { color: colors.muted, marginTop: 4, fontSize: fs.sm },
  body: { fontSize: fs.lg, color: colors.onSurface, marginTop: spacing.md, lineHeight: 24 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: spacing.md },
  chip: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.pill, paddingHorizontal: 12, paddingVertical: 6 },
  chipT: { color: colors.onSurface, fontSize: fs.sm, fontWeight: "600" },
  gravCard: { flexDirection: "row", alignItems: "center", backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg, padding: spacing.xl, marginTop: spacing.xl, gap: spacing.md },
  lab: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  gravVal: { fontSize: fs["4xl"], fontWeight: "800", color: colors.onSurface, marginTop: 2 },
  sub: { color: colors.onSurfaceTertiary, fontSize: fs.sm, marginTop: 4 },
  subDim: { color: colors.muted, fontSize: fs.base, marginTop: 8 },
  section: { marginTop: spacing["2xl"] },
  sh: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  smallBtn: { backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill },
  smallBtnT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  agentCard: { width: 240, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md, borderTopWidth: 3, gap: 6 },
  agentDot: { width: 8, height: 8, borderRadius: 4 },
  agentName: { fontWeight: "700", color: colors.onSurface, fontSize: fs.base },
  agentText: { color: colors.onSurfaceSecondary, fontSize: fs.sm, lineHeight: 18 },
  vRow: { flexDirection: "row", gap: spacing.md },
  vCol: { width: 20, alignItems: "center" },
  vDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.onSurface, marginTop: 4 },
  vLine: { flex: 1, width: 1, backgroundColor: colors.border },
  vStage: { fontSize: fs.base, fontWeight: "700", color: colors.onSurface },
  vTime: { fontSize: fs.sm, color: colors.muted },
  decCard: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, marginTop: spacing.md },
  decNum: { color: colors.muted, fontSize: fs.sm, textTransform: "uppercase" },
  decTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface, marginTop: 2 },
  decGrid: { flexDirection: "row", flexWrap: "wrap", marginTop: spacing.md, gap: spacing.sm },
  decMetric: { flexBasis: "47%", flexGrow: 1, backgroundColor: "#fff", padding: spacing.md, borderRadius: radius.sm },
  decVal: { fontSize: fs.xl, fontWeight: "800", color: colors.onSurface },
  decLab: { fontSize: fs.sm, color: colors.muted },
  roiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.md, marginTop: spacing.md },
  roiTile: { flexBasis: "47%", flexGrow: 1, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  roiVal: { fontSize: fs["2xl"], fontWeight: "800", color: colors.onSurface },
  roiLab: { fontSize: fs.sm, color: colors.muted, marginTop: 4 },
  opChip: { flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.onSurface, paddingHorizontal: 14, paddingVertical: 10, borderRadius: radius.pill },
  opChipT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  opResult: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  opResultHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 6 },
  opResultLab: { color: colors.muted, fontSize: fs.sm, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.5 },
  opResultTime: { color: colors.muted, fontSize: fs.sm },
  opResultT: { color: colors.onSurface, fontSize: fs.base, lineHeight: 22 },
  chatAboutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.onSurface, padding: spacing.md, borderRadius: radius.md, marginTop: spacing.md },
  chatAboutT: { color: "#fff", fontSize: fs.base, fontWeight: "700" },
  dnaBox: { marginTop: spacing.md, backgroundColor: "#0F0F10", borderRadius: radius.sm, padding: spacing.md, gap: 6 },
  dnaHeader: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.5, fontWeight: "700", marginBottom: 4 },
  dnaRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: "#222" },
  dnaLabel: { color: "#fff", fontSize: fs.sm, fontWeight: "700" },
  dnaHash: { color: "#8E8E93", fontSize: 10, fontFamily: "monospace", marginTop: 2 },
  dnaBadge: { flexDirection: "row", alignItems: "center", gap: 4 },
  dnaBadgeT: { fontSize: 10, fontWeight: "700" },
  dnaRoot: { marginTop: 6, alignItems: "center", paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: "#333" },
  dnaRootLab: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.5, fontWeight: "700" },
  dnaRootHash: { color: "#7BE38B", fontFamily: "monospace", fontSize: 11, marginTop: 4 },
  consBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  consHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline" },
  consRec: { fontSize: fs.xl, fontWeight: "800", letterSpacing: 0.5 },
  consScore: { color: colors.onSurface, fontSize: fs.lg, fontWeight: "700" },
  consMeta: { marginTop: 4, marginBottom: spacing.md },
  consMetaT: { color: colors.muted, fontSize: fs.sm },
  vRowC: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border },
  posBadge: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, minWidth: 68, alignItems: "center" },
  posT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.6 },
  vAgent: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  vReason: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  vNum: { color: colors.onSurface, fontSize: fs.base, fontWeight: "800" },
  vRisk: { color: colors.muted, fontSize: fs.sm },
  debateBtn: { marginTop: spacing.md, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, backgroundColor: colors.onSurface, paddingVertical: 10, borderRadius: radius.sm },
  debateT: { color: "#fff", fontWeight: "700", fontSize: fs.sm },
  debateBox: { marginTop: spacing.md, backgroundColor: "#0F0F10", borderRadius: radius.sm, padding: spacing.md, gap: 6 },
  debateLab: { color: "#B8B8BD", fontSize: 10, letterSpacing: 1.2, fontWeight: "700" },
  debateRow: { color: "#fff", fontSize: fs.sm, lineHeight: 20 },
  debateK: { color: "#7BE38B", fontWeight: "700" },
  routerBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  routerHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", marginBottom: spacing.sm },
  routerIntent: { color: colors.onSurface, fontSize: fs.xl, fontWeight: "800", letterSpacing: 0.5 },
  routerMode: { color: colors.muted, fontSize: fs.sm, fontWeight: "700", letterSpacing: 0.8 },
  routeRow: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8, borderTopWidth: 1, borderTopColor: colors.border },
  routeIdx: { color: colors.muted, fontSize: fs.sm, fontWeight: "700", width: 16 },
  routeAgent: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  routeRole: { color: colors.muted, fontSize: fs.sm },
  leaseDot: { width: 8, height: 8, borderRadius: 4 },
  routeScore: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700", minWidth: 32, textAlign: "right" },
  routeCtx: { color: colors.muted, fontSize: fs.sm, marginTop: spacing.md, paddingTop: spacing.sm, borderTopWidth: 1, borderTopColor: colors.border },
  triggersBox: { marginTop: spacing.md, backgroundColor: "#FFF9E6", borderRadius: radius.sm, padding: spacing.md, borderWidth: 1, borderColor: "#F5D97A" },
  triggersLab: { color: "#5A3A00", fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginBottom: 8 },
  triggerChips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  triggerChip: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999, borderWidth: 1, maxWidth: "100%" },
  triggerChipT: { fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
  triggerChipDetail: { fontSize: 10, color: "#666", flexShrink: 1 },
  triggerFoot: { marginTop: 8, color: "#8A6D00", fontSize: 11, fontWeight: "600" },
  debateHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 4 },
  debateStatus: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  debateStatusT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  turnCard: { backgroundColor: "#1A1A1C", borderRadius: 6, padding: spacing.sm, marginTop: 8, gap: 4 },
  turnHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  turnRole: { fontSize: 11, fontWeight: "800", letterSpacing: 0.6 },
  turnModel: { color: "#8E8E93", fontSize: 10 },
  turnBody: { color: "#fff", fontSize: fs.sm, lineHeight: 20 },
  turnHash: { color: "#5A5A5F", fontSize: 9, fontFamily: "monospace", marginTop: 2 },
  synthCard: { marginTop: 10, backgroundColor: "#fff", borderRadius: 6, padding: spacing.md, gap: 6 },
  synthRow: { color: "#0A0A0B", fontSize: fs.sm, lineHeight: 20 },
  synthK: { color: "#0E7A2A", fontWeight: "800" },
  synthHash: { color: "#8E8E93", fontSize: 9, fontFamily: "monospace", marginTop: 6 },
  ratifyRow: { flexDirection: "row", gap: 8, marginTop: spacing.sm },
  ratifyBtn: { flex: 1, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6, paddingVertical: 10, borderRadius: radius.sm, borderWidth: 1 },
  ratifyApprove: { backgroundColor: "#0E7A2A", borderColor: "#0E7A2A" },
  ratifyReject: { backgroundColor: "#fff", borderColor: "#FFC5C0" },
  ratifyBtnT: { color: "#fff", fontWeight: "800", fontSize: fs.sm },
  ratifiedFoot: { marginTop: spacing.sm, color: "#0E7A2A", fontSize: 11, fontWeight: "700" },
  rejectedFoot: { marginTop: spacing.sm, color: "#B41B10", fontSize: 11, fontWeight: "700" },
  contraCard: { marginTop: spacing.md, backgroundColor: "#FFF7F5", borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: "#F5C5C0", gap: 6 },
  contraHead: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  contraChip: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999, backgroundColor: "#FFE9E7" },
  contraChipT: { color: "#B41B10", fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
  contraResolved: { flexDirection: "row", alignItems: "center", gap: 3, paddingHorizontal: 6, paddingVertical: 2, backgroundColor: "#DCF7DC", borderRadius: 999 },
  contraResolvedT: { color: "#0E7A2A", fontSize: 10, fontWeight: "800" },
  contraTitle: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700", marginTop: 4 },
  contraPosRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 4 },
  miniPos: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 999 },
  miniPosT: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  contraConcepts: { flexDirection: "row", flexWrap: "wrap", gap: 4, marginTop: 4 },
  contraConcept: { backgroundColor: "#fff", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3, borderWidth: 1, borderColor: "#F5C5C0" },
  contraConceptT: { color: "#B41B10", fontSize: 10, fontWeight: "700" },
  contraFoot: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginTop: 6, paddingTop: 6, borderTopWidth: 1, borderTopColor: "#F5C5C0" },
  contraFootT: { color: "#8A5350", fontSize: 10, fontFamily: "monospace", flex: 1 },
  contraResolveBtn: { color: "#0E7A2A", fontSize: 11, fontWeight: "800", textDecorationLine: "underline" },
  contraResolvedFoot: { color: "#0E7A2A", fontSize: 10, fontWeight: "700" },
  contraPriorBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.sm, padding: spacing.sm },
  contraPriorLab: { color: colors.muted, fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginBottom: 4 },
  contraPriorRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  contraPriorT: { color: colors.onSurface, fontSize: fs.sm, flex: 1 },
});
