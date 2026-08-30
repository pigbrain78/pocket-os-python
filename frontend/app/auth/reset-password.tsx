import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  Pressable,
  StyleSheet,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { useRouter, useLocalSearchParams } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { api, useAuth } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

export default function ResetPassword() {
  const router = useRouter();
  const { login } = useAuth();
  const params = useLocalSearchParams<{ email?: string }>();
  const [email, setEmail] = useState(params.email ?? "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr("");
    if (!email.trim()) return setErr("Enter your email");
    if (!/^\d{6}$/.test(code.trim())) return setErr("Enter the 6-digit code from your email");
    if (password.length < 8) return setErr("Password must be at least 8 characters");
    if (password !== confirm) return setErr("Passwords don't match");
    setBusy(true);
    try {
      await api<{ ok: boolean; token: string; user: any }>(
        "/api/auth/reset-password",
        {
          method: "POST",
          body: JSON.stringify({
            email: email.trim().toLowerCase(),
            code: code.trim(),
            new_password: password,
          }),
        }
      );
      // Immediately sign in with the new password through the auth context
      // so useAuth() has a live session — router guards read from context,
      // not storage, until next app boot.
      await login(email.trim().toLowerCase(), password);
      router.replace("/(tabs)/console");
    } catch (e: any) {
      setErr(e?.message || "Reset failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.c} testID="reset-password-screen">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.s} keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => router.back()} testID="back-btn" hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>

          <Text style={styles.h1}>Reset password</Text>
          <Text style={styles.sub}>
            Enter the 6-digit code we emailed you, then choose a new password.
          </Text>

          <View style={styles.form}>
            <Text style={styles.lab}>Email</Text>
            <TextInput
              testID="reset-email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              style={styles.input}
              placeholder="you@domain.com"
              placeholderTextColor={colors.muted}
              editable={!busy}
            />

            <Text style={styles.lab}>6-digit code</Text>
            <TextInput
              testID="reset-code"
              value={code}
              onChangeText={(v) => setCode(v.replace(/[^\d]/g, "").slice(0, 6))}
              keyboardType="number-pad"
              maxLength={6}
              style={[styles.input, styles.codeInput]}
              placeholder="••••••"
              placeholderTextColor={colors.muted}
              editable={!busy}
            />

            <Text style={styles.lab}>New password</Text>
            <TextInput
              testID="reset-password-input"
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              style={styles.input}
              placeholder="At least 8 characters"
              placeholderTextColor={colors.muted}
              editable={!busy}
            />

            <Text style={styles.lab}>Confirm password</Text>
            <TextInput
              testID="reset-password-confirm"
              value={confirm}
              onChangeText={setConfirm}
              secureTextEntry
              style={styles.input}
              placeholder="Re-enter password"
              placeholderTextColor={colors.muted}
              editable={!busy}
            />

            {err ? (
              <Text style={styles.err} testID="reset-error">
                {err}
              </Text>
            ) : null}

            <Pressable
              testID="reset-submit"
              style={[styles.btn, busy && styles.btnDisabled]}
              onPress={submit}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.btnT}>Reset password &amp; sign in</Text>
              )}
            </Pressable>

            <Pressable
              onPress={() =>
                router.replace({
                  pathname: "/auth/forgot-password",
                  params: { email: email.trim() },
                })
              }
              testID="request-new-code"
            >
              <Text style={styles.switch}>Didn&apos;t get a code? Request a new one</Text>
            </Pressable>
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  c: { flex: 1, backgroundColor: colors.surface },
  s: { padding: spacing.xl, gap: spacing.md },
  h1: {
    fontSize: fs["3xl"],
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: spacing.lg,
  },
  sub: {
    color: colors.muted,
    fontSize: fs.lg,
    marginBottom: spacing.xl,
    lineHeight: 24,
  },
  form: { gap: spacing.sm },
  lab: {
    fontSize: fs.sm,
    color: colors.muted,
    marginTop: spacing.md,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    padding: spacing.lg,
    borderRadius: radius.md,
    fontSize: fs.lg,
    color: colors.onSurface,
  },
  codeInput: {
    fontSize: 28,
    fontWeight: "700",
    letterSpacing: 12,
    textAlign: "center",
  },
  btn: {
    backgroundColor: colors.onSurface,
    padding: spacing.lg,
    borderRadius: radius.md,
    alignItems: "center",
    marginTop: spacing.lg,
  },
  btnDisabled: { opacity: 0.6 },
  btnT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  switch: {
    color: colors.muted,
    textAlign: "center",
    marginTop: spacing.lg,
    fontSize: fs.base,
  },
  err: { color: colors.error, marginTop: spacing.sm },
});
