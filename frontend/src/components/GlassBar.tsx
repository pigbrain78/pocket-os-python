import React from "react";
import { Platform, StyleSheet, View, ViewStyle } from "react-native";
import { BlurView } from "expo-blur";
import { colors } from "@/src/theme";

type Props = {
  children?: React.ReactNode;
  style?: ViewStyle | ViewStyle[];
  intensity?: number;
  testID?: string;
};

/** Frosted on iOS. Solid secondary surface everywhere else, including low-end Android. */
export default function GlassBar({ children, style, intensity = 80, testID }: Props) {
  if (Platform.OS === "ios") {
    return (
      <BlurView intensity={intensity} tint="light" style={style} testID={testID}>
        {children}
      </BlurView>
    );
  }
  return <View style={[styles.solid, style]} testID={testID}>{children}</View>;
}

const styles = StyleSheet.create({
  solid: { backgroundColor: colors.surfaceSecondary },
});
