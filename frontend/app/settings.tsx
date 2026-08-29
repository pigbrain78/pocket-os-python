import React, { useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Alert, ActivityIndicator, TextInput, Platform } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

export default function Settings() {
  const router = useRouter();
  const { user, token, logout } = useAuth();
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);

  const askConfirmAndDelete = () => {
    if (Platform.OS === "web") {
      // Web has no native Alert with input, use inline confirm and window.confirm
      if (confirm.trim().toUpperCase() !== "DELETE") {
        window.alert("Type DELETE (uppercase) in the confirmation box above to proceed.");
        return;
      }
      if (!window.confirm("This will permanently delete your account and every note, decision, ledger event, and contradiction. Continue?")) return;
      doDelete();
      return;
    }
    if (confirm.trim().toUpperCase() !== "DELETE") {
      Alert.alert("Confirmation required", "Type DELETE (uppercase) in the confirmation box above to proceed.");
      return;
    }
    Alert.alert(
      "Delete account?",
      "This will permanently delete your account and every note, decision, ledger event, and contradiction. This cannot be undone.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Delete forever", style: "destructive", onPress: doDelete },
      ]
    );
  };

  const doDelete = async () => {
    setBusy(true);
    try {
      await api(`/api/auth/account`, { method: "DELETE", token });
      await logout();
      router.replace("/auth/welcome");
    } catch (e: any) {
      if (Platform.OS === "web") window.alert("Deletion failed: " + (e.message || "unknown"));
      else Alert.alert("Deletion failed", e.message || "unknown");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.c} edges={["top"]} testID="settings-screen">
      <View style={styles.head}>
        <Pressable onPress={() => router.back()} hitSlop={12} testID="settings-back">
          <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.hTitle}>Settings</Text>
        <View style={{ width: 26 }} />
      </View>

      <ScrollView contentContainerStyle={styles.s}>
        <View style={styles.card}>
          <Text style={styles.cardLab}>SIGNED IN AS</Text>
          <Text style={styles.email}>{user?.email || "—"}</Text>
          <Text style={styles.name}>{user?.name || ""}</Text>
        </View>

        <Pressable style={styles.logoutBtn} onPress={logout} testID="settings-logout">
          <Ionicons name="log-out-outline" size={18} color={colors.onSurface} />
          <Text style={styles.logoutT}>Log out</Text>
        </Pressable>

        <View style={styles.dangerCard}>
          <View style={styles.dangerHead}>
            <Ionicons name="warning" size={16} color="#B41B10" />
            <Text style={styles.dangerH}>Delete Account</Text>
          </View>
          <Text style={styles.dangerBody}>
            Permanently deletes your account and every associated note, decision, ledger event, contradiction, agent, and lease. This action is irreversible.
          </Text>
          <Text style={styles.dangerBody}>
            You may want to export your Immutable Event Ledger first via Timeline → Ledger → Download before continuing.
          </Text>
          <Text style={styles.confirmLab}>Type DELETE to confirm</Text>
          <TextInput
            testID="delete-confirm-input"
            value={confirm}
            onChangeText={setConfirm}
            autoCapitalize="characters"
            autoCorrect={false}
            placeholder="DELETE"
            placeholderTextColor="#B4756C"
            style={styles.confirmInput}
          />
          <Pressable
            testID="delete-account-btn"
            style={[styles.deleteBtn, (confirm.trim().toUpperCase() !== "DELETE" || busy) && { opacity: 0.5 }]}
            onPress={askConfirmAndDelete}
            disabled={busy || confirm.trim().toUpperCase() !== "DELETE"}
          >
            {busy ? <ActivityIndicator color="#fff" /> : (
              <>
                <Ionicons name="trash-outline" size={16} color="#fff" />
                <Text style={styles.deleteT}>Delete my account permanently</Text>
              </>
            )}
          </Pressable>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: spacing.lg, borderBottomWidth: 1, borderBottomColor: colors.border },
  hTitle: { fontSize: fs.lg, fontWeight: "700", color: colors.onSurface },
  s: { padding: spacing.lg, gap: spacing.lg },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg },
  cardLab: { color: colors.muted, fontSize: 10, letterSpacing: 1.5, fontWeight: "800" },
  email: { color: colors.onSurface, fontSize: fs.lg, fontWeight: "700", marginTop: 6 },
  name: { color: colors.muted, fontSize: fs.sm, marginTop: 2 },
  logoutBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  logoutT: { color: colors.onSurface, fontSize: fs.base, fontWeight: "700" },
  dangerCard: { marginTop: spacing.lg, backgroundColor: "#FFF7F5", borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: "#F5C5C0" },
  dangerHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  dangerH: { color: "#B41B10", fontSize: fs.base, fontWeight: "800", letterSpacing: 0.3 },
  dangerBody: { color: "#7A2A22", fontSize: fs.sm, lineHeight: 20, marginTop: 8 },
  confirmLab: { color: "#8A5350", fontSize: 10, letterSpacing: 1.2, fontWeight: "800", marginTop: spacing.md },
  confirmInput: { backgroundColor: "#fff", borderRadius: radius.sm, padding: spacing.md, marginTop: 6, fontSize: fs.base, color: "#B41B10", borderWidth: 1, borderColor: "#F5C5C0", fontWeight: "800", letterSpacing: 1 },
  deleteBtn: { flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8, backgroundColor: "#B41B10", padding: spacing.lg, borderRadius: radius.sm, marginTop: spacing.md },
  deleteT: { color: "#fff", fontSize: fs.base, fontWeight: "800" },
});
