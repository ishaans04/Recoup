import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /*
   * Next 16's dev server otherwise writes agent-instruction files into
   * frontend/ on every `next dev` start. This repo keeps its cross-session
   * working-context file gitignored on purpose and it must never be committed
   * (a repo-wide rule) — disabling this here is simpler and more durable than
   * remembering to delete the generated file after every dev session.
   */
  agentRules: false,
};

export default nextConfig;
