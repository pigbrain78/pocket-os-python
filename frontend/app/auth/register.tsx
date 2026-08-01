import React, { useState } from "react";
import { View, Text, TextInput, Pressable, StyleSheet, KeyboardAvoidingView, Platform, ScrollView, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth, api } from "@/src/lib/auth";
import { colors, spacing, radius, fs } from "@/src/theme";
import { Ionicons } from "@expo/vector-icons";

export default function Register() {
  const router = useRouter();
  const { register, token } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(""); setBusy(true);
    try {
      await register(name.trim(), email.trim(), password);
      // Seed demo asynchronously; don't block
      try {
        const t = (await import("expo-secure-store")).getItemAsync;
        // Actually reuse auth ctx token via api call inside effect below is easier
      } catch {}
      router.replace("/(tabs)/console");
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={styles.c} testID="register-screen">
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={styles.s}>
          <Pressable onPress={() => router.back()} testID="back-btn" hitSlop={12}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Create your Genome.</Text>
          <Text style={styles.sub}>We'll seed demo knowledge so you feel the wow instantly.</Text>
          <View style={styles.form}>
            <Text style={styles.lab}>Name</Text>
            <TextInput testID="reg-name" value={name} onChangeText={setName} style={styles.input} placeholder="Your name" placeholderTextColor={colors.muted} />
            <Text style={styles.lab}>Email</Text>
            <TextInput testID="reg-email" value={email} onChangeText={setEmail} autoCapitalize="none" keyboardType="email-address" style={styles.input} placeholder="you@domain.com" placeholderTextColor={colors.muted} />
            <Text style={styles.lab}>Password</Text>
            <TextInput testID="reg-password" value={password} onChangeText={setPassword} secureTextEntry style={styles.input} placeholder="min 6 characters" placeholderTextColor={colors.muted} />
            {err ? <Text style={styles.err} testID="reg-error">{err}</Text> : null}
            <Pressable testID="reg-submit" style={styles.btn} onPress={submit} disabled={busy}>
              {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.btnT}>Create Genome</Text>}
            </Pressable>
            <Pressable onPress={() => router.replace("/auth/login")} testID="switch-to-login">
              <Text style={styles.switch}>Already have an account? Sign in</Text>
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
  h1: { fontSize: fs["3xl"], fontWeight: "800", color: colors.onSurface, marginTop: spacing.lg },
  sub: { color: colors.muted, fontSize: fs.lg, marginBottom: spacing.xl },
  form: { gap: spacing.sm },
  lab: { fontSize: fs.sm, color: colors.muted, marginTop: spacing.md, textTransform: "uppercase", letterSpacing: 0.5 },
  input: { backgroundColor: colors.surfaceSecondary, padding: spacing.lg, borderRadius: radius.md, fontSize: fs.lg, color: colors.onSurface },
  btn: { backgroundColor: colors.onSurface, padding: spacing.lg, borderRadius: radius.md, alignItems: "center", marginTop: spacing.lg },
  btnT: { color: "#fff", fontSize: fs.lg, fontWeight: "700" },
  switch: { color: colors.muted, textAlign: "center", marginTop: spacing.lg, fontSize: fs.base },
  err: { color: colors.error, marginTop: spacing.sm },
});
