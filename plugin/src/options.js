export class OptionsError extends Error {}

export const DEFAULT_MODEL = "anthropic/claude-opus-5"

export function resolveOptions(raw) {
  const model = raw?.model ?? DEFAULT_MODEL
  if (typeof model !== "string" || model.length === 0) {
    throw new OptionsError("opencode-adversarial-review: `model` must be a string of the form provider/model")
  }
  if (!/^[^/\s]+\/[^/\s]+/.test(model)) {
    throw new OptionsError(
      `opencode-adversarial-review: \`model\` must be provider/model, got ${JSON.stringify(model)}. ` +
      `Example: "anthropic/claude-opus-5"`,
    )
  }
  return { model }
}
