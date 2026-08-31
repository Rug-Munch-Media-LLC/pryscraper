// RugMunch fleet commitlint — canonical config (2026-08-23)
// Types match AGENTS.md convention. NOTE: ops: and security: are
// FLEET-MANDATED types (AGENTS.md, fleet-infra rules) — do not remove
// them or convention-compliant commits fail CI.
//
// The extends below is OPTIONAL: this repo ships no package.json, so
// @commitlint/config-conventional may be unresolvable — and a throwing
// extends makes commitlint silently discard this ENTIRE config (falling
// back to built-in defaults where ops: is invalid and subject-case
// blocks uppercase subjects). Resolve it when present; our explicit
// rules always apply either way.
let extendsConfig = [];
try {
	require.resolve("@commitlint/config-conventional");
	extendsConfig = ["@commitlint/config-conventional"];
} catch {
	// not installed — the explicit rules below carry the fleet contract.
}

module.exports = {
	extends: extendsConfig,
	rules: {
		"type-enum": [
			2,
			"always",
			[
				"feat",
				"fix",
				"docs",
				"style",
				"refactor",
				"perf",
				"test",
				"build",
				"ci",
				"chore",
				"revert",
				"ops",
				"security",
			],
		],
		"scope-case": [2, "always", "lower-case"],
		"subject-case": [0, "never"],
		"subject-empty": [2, "never"],
		"type-empty": [2, "never"],
		"header-max-length": [2, "always", 120],
		"subject-full-stop": [2, "never", "."],
		"body-max-line-length": [1, "always", 200],
	},
};
