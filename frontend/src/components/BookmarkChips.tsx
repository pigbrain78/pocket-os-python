import React, { useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  StyleSheet,
  Modal,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import dayjs from "dayjs";
import { colors, spacing, radius, fs } from "@/src/theme";

export type Bookmark = {
  id: string;
  label: string;
  at: string;
  created_at: string;
};

type Props = {
  bookmarks: Bookmark[];
  atMs: number;
  isLive: boolean;
  onSelect: (bookmark: Bookmark) => void;
  onAdd: (label: string, atIso: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  saveBusy?: boolean;
  saveError?: string | null;
};

/**
 * Horizontal chip row for saved replay bookmarks + a "+ Save moment" action
 * that opens a small modal to name the current scrubber position.
 *
 * Long-press a chip to prompt for deletion (with a web-safe confirm fallback).
 */
export default function BookmarkChips({
  bookmarks,
  atMs,
  isLive,
  onSelect,
  onAdd,
  onDelete,
  saveBusy,
  saveError,
}: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const [label, setLabel] = useState("");
  const currentIso = useMemo(() => new Date(atMs).toISOString(), [atMs]);

  const openSave = () => {
    setLabel("");
    setModalOpen(true);
  };

  const confirmSave = async () => {
    const trimmed = label.trim();
    if (!trimmed) return;
    await onAdd(trimmed, currentIso);
    setModalOpen(false);
    setLabel("");
  };

  const askDelete = (b: Bookmark) => {
    if (Platform.OS === "web") {
      // window.confirm is the standard web UX. Alert.alert on RN Web
      // silently no-ops, so we have to fall back explicitly.
      if (window.confirm(`Delete bookmark "${b.label}"?`)) {
        onDelete(b.id);
      }
      return;
    }
    Alert.alert(
      "Delete bookmark?",
      `"${b.label}" will be removed. The ledger itself is not affected.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: () => onDelete(b.id) },
      ]
    );
  };

  return (
    <View style={styles.wrap} testID="bookmark-chips">
      <ScrollView
        horizontal
        showsHorizontalScrollIndicator={false}
        contentContainerStyle={styles.row}
        keyboardShouldPersistTaps="handled"
      >
        <Pressable
          style={[styles.chip, styles.addChip]}
          onPress={openSave}
          testID="bookmark-add"
          hitSlop={6}
        >
          <Ionicons name="bookmark" size={14} color="#fff" />
          <Text style={styles.addChipT}>
            {isLive ? "Save this moment" : `Save · ${dayjs(atMs).format("MMM D · HH:mm")}`}
          </Text>
        </Pressable>
        {bookmarks.map((b) => (
          <Pressable
            key={b.id}
            style={styles.chip}
            onPress={() => onSelect(b)}
            onLongPress={() => askDelete(b)}
            delayLongPress={400}
            testID={`bookmark-chip-${b.id}`}
          >
            <Ionicons name="bookmark-outline" size={12} color={colors.onSurface} />
            <Text style={styles.chipT} numberOfLines={1}>
              {b.label}
            </Text>
            <Text style={styles.chipTs}>{dayjs(b.at).format("MMM D")}</Text>
          </Pressable>
        ))}
      </ScrollView>

      <Modal
        visible={modalOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setModalOpen(false)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalBg}
        >
          <Pressable style={styles.modalBackdrop} onPress={() => setModalOpen(false)} />
          <View style={styles.modalCard} testID="bookmark-modal">
            <Text style={styles.modalTitle}>Bookmark this moment</Text>
            <Text style={styles.modalTs}>
              {dayjs(atMs).format("dddd, MMM D · HH:mm")}
            </Text>
            <TextInput
              value={label}
              onChangeText={setLabel}
              placeholder="e.g. The day I decided to launch"
              placeholderTextColor={colors.muted}
              style={styles.input}
              autoFocus
              maxLength={80}
              onSubmitEditing={confirmSave}
              returnKeyType="done"
              testID="bookmark-label-input"
            />
            <Text style={styles.hint}>{label.length}/80</Text>
            {saveError ? (
              <Text style={styles.err} testID="bookmark-error">
                {saveError}
              </Text>
            ) : null}
            <View style={styles.actions}>
              <Pressable
                style={styles.btnGhost}
                onPress={() => setModalOpen(false)}
                testID="bookmark-cancel"
              >
                <Text style={styles.btnGhostT}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.btn, (!label.trim() || saveBusy) && styles.btnDisabled]}
                onPress={confirmSave}
                disabled={!label.trim() || !!saveBusy}
                testID="bookmark-save"
              >
                {saveBusy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <Text style={styles.btnT}>Save</Text>
                )}
              </Pressable>
            </View>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingTop: spacing.xs, paddingBottom: spacing.sm },
  row: { paddingHorizontal: spacing.md, gap: spacing.sm, alignItems: "center" },
  chip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    maxWidth: 220,
  },
  chipT: { color: colors.onSurface, fontSize: fs.base, fontWeight: "600" },
  chipTs: { color: colors.muted, fontSize: fs.sm, marginLeft: 4 },
  addChip: {
    backgroundColor: colors.onSurface,
    borderColor: colors.onSurface,
  },
  addChipT: { color: "#fff", fontSize: fs.base, fontWeight: "700" },

  modalBg: { flex: 1, justifyContent: "center", padding: spacing.xl },
  modalBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.xl,
    gap: spacing.sm,
  },
  modalTitle: {
    fontSize: fs["2xl"],
    fontWeight: "800",
    color: colors.onSurface,
  },
  modalTs: { fontSize: fs.base, color: colors.muted, marginBottom: spacing.sm },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
    fontSize: fs.lg,
    color: colors.onSurface,
  },
  hint: { fontSize: fs.sm, color: colors.muted, textAlign: "right" },
  err: { color: colors.error, fontSize: fs.base, marginTop: spacing.xs },
  actions: {
    flexDirection: "row",
    justifyContent: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  btn: {
    backgroundColor: colors.onSurface,
    paddingHorizontal: spacing.xl,
    paddingVertical: 12,
    borderRadius: radius.md,
    minWidth: 96,
    alignItems: "center",
  },
  btnDisabled: { opacity: 0.4 },
  btnT: { color: "#fff", fontSize: fs.base, fontWeight: "800" },
  btnGhost: {
    paddingHorizontal: spacing.xl,
    paddingVertical: 12,
  },
  btnGhostT: { color: colors.muted, fontSize: fs.base, fontWeight: "700" },
});
