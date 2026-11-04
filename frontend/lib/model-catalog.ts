import type { ProviderLogoId } from "@/components/provider-logo";

export interface ModelProvider {
  id: string; name: string; logo: ProviderLogoId; models: string[];
  subscription?: boolean;
  unavailable?: { name: string; reason: string }[];
}

export const providers: ModelProvider[] = [
  { id: "codex", name: "Codex (ChatGPT)", logo: "openai", subscription: true, models: ["gpt-6.1-sol"] },
  { id: "claude", name: "Claude (subscription)", logo: "anthropic", subscription: true, models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
  { id: "openai", name: "OpenAI", logo: "openai", models: ["gpt-6.1-sol", "gpt-6.1-terra", "gpt-6.1-luna"] },
  { id: "anthropic", name: "Anthropic", logo: "anthropic", models: ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] },
  // Gemini IDs from ai.google.dev/gemini-api/docs/models (stable releases).
  { id: "gemini", name: "Gemini", logo: "gemini", models: ["gemini-4-argon", "gemini-3.8-flash", "gemini-3.5-flash-lite"] },
  // Meta IDs from dev.meta.ai/docs/models; Wonder Full has no Model API ID (Muse Code only).
  { id: "meta", name: "Meta", logo: "meta", models: ["muse-spark-1.3", "muse-spark-1.3-contributor", "muse-wonder-1.0"], unavailable: [{ name: "muse-wonder-full", reason: "Muse Code only" }] },
  { id: "kimi", name: "Kimi", logo: "kimi", models: ["kimi-k3.1-pro"] },
  { id: "qwen", name: "Qwen", logo: "qwen", models: ["qwen3.8-max"] },
  { id: "deepseek", name: "DeepSeek", logo: "deepseek", models: ["deepseek-v4.1-pro", "deepseek-v4.1-flash"] },
  // xAI, Z.ai and MiniMax IDs from each provider's model docs; Mistral uses its documented -latest aliases.
  { id: "xai", name: "xAI", logo: "xai", models: ["grok-4.7", "grok-4.6"] },
  { id: "mistral", name: "Mistral", logo: "mistral", models: ["mistral-large-latest", "mistral-medium-latest", "codestral-latest"] },
  { id: "zai", name: "Z.ai", logo: "zai", models: ["glm-5.3", "glm-5.3-flash"] },
  { id: "minimax", name: "MiniMax", logo: "minimax", models: ["MiniMax-M3", "MiniMax-M3.1-Flash"] },
];

export const keyProviders = providers.filter((provider) => !provider.subscription);
