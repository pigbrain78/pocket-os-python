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
import { api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";

export default function ForgotPassword() {
  const router = useRouter();
  const params = useLocalSearchParams<{ email?: string }>();
  const [email, setEmail] = useState(params.email ?? "");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setErr("");
    if (!email.trim()) {
      setErr("Enter your email");
      return;
    }
    setBusy(true);
    try {
      await api("/api/auth/forgot-password", {
        method: "POST",
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      });
      setSent(true);
    } catch {
      // The endpoint intentionally returns 200 for both known and unknown
      // emails — but treat any real error as opaque to preserve enumeration
      // safety.
      setSent(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SafeAreaView style={styles.c} testID="forgot-password-screen">
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={{ flex: 1 }}
      >
        <ScrollView contentContainerStyle={styles.s} keyboardShouldPersistTaps="handled">
          <Pressable onPress={() => router.back()} testID="back-btn" hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>

          {!sent ? (
            <>
              <Text style={styles.h1}>Forgot password?</Text>
              <Text style={styles.sub}>
                Enter the email tied to your Pocket OS account. We&apos;ll send you a 6-digit
                code that expires in 15 minutes.
              </Text>

              <View style={styles.form}>
                <Text style={styles.lab}>Email</Text>
                <TextInput
                  testID="forgot-email"
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
                {err ? (
                  <Text style={styles.err} testID="forgot-error">
                    {err}
                  </Text>
                ) : null}
                <Pressable
                  testID="forgot-submit"
                  style={[styles.btn, busy && styles.btnDisabled]}
                  onPress={submit}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <Text style={styles.btnT}>Send reset code</Text>
                  )}
                </Pressable>
                <Pressable
                  onPress={() =>
                    router.replace({
                      pathname: "/auth/reset-password",
                      params: { email: email.trim() },
                    })
                  }
                  testID="already-have-code"
                >
                  <Text style={styles.switch}>I already have a code</Text>
                </Pressable>
              </View>
            </>
          ) : (
            <>
              <View style={styles.iconWrap}>
                <Ionicons name="mail-outline" size={48} color={colors.onSurface} />
              </View>
              <Text style={styles.h1}>Check your inbox</Text>
              <Text style={styles.sub}>
                If an account exists for <Text style={styles.mono}>{email.trim()}</Text>,
                we&apos;ve sent a 6-digit reset code. The code expires in 15 minutes and
                can only be used once.
              </Text>
              <Text style={styles.hint}>
                Don&apos;t see it? Check your spam folder, and make sure the email
                address is spelled correctly.
              </Text>
              <Pressable
                testID="continue-to-reset"
                style={styles.btn}
                onPress={() =>
                  router.replace({
                    pathname: "/auth/reset-password",
                    params: { email: email.trim() },
                  })
                }
              >
                <Text style={styles.btnT}>Enter code</Text>
              </Pressable>
              <Pressable
                onPress={() => {
                  setSent(false);
                }}
                testID="resend-code"
              >
                <Text style={styles.switch}>Use a different email</Text>
              </Pressable>
            </>
          )}
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
  hint: {
    color: colors.muted,
    fontSize: fs.base,
    marginTop: spacing.md,
    lineHeight: 20,
  },
  mono: { color: colors.onSurface, fontWeight: "600" },
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
  iconWrap: { alignItems: "center", marginTop: spacing.xl },
});
