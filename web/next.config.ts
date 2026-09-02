import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The dev-mode indicator is a dark circle in the corner. Harmless, but this gets
  // demoed live on a projector and it reads as a stray UI element.
  devIndicators: false,
};

export default nextConfig;
