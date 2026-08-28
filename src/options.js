export class OptionsError extends Error {}

export const DEFAULT_MODEL = "anthropic/claude-opus-5"

// A valid opencode model reference is provider/model. The model id itself
// may contain further slashes - for example openrouter routes to
// "openrouter/anthropic/claude-3.5-sonnet", where the provider is
// "openrouter" and the model id is "anthropic/claude-3.5-sonnet" - so this
// deliberately does not require exactly two components. It only checks:
function isModelReference(model) {
  if (/\s/.test(model)) return false // no whitespace anywhere
  if (!model.includes("/")) return false // at least one slash
  if (model.startsWith("/") || model.endsWith("/")) return false // no leading or trailing slash
  if (model.split("/").some((part) => part.length === 0)) return false // no empty component, e.g. "a//b"
  return true
}

export function resolveOptions(raw) {
  const model = raw?.model ?? DEFAULT_MODEL
  if (typeof model !== "string" || model.length === 0) {
    throw new OptionsError(
      `opencode-adversarial-review: \`model\` must be a string of the form provider/model, got ${JSON.stringify(model)}`,
    )
  }
  if (!isModelReference(model)) {
    throw new OptionsError(
      `opencode-adversarial-review: \`model\` must be provider/model, got ${JSON.stringify(model)}. ` +
      `Example: "anthropic/claude-opus-5"`,
    )
  }
  return { model }
}
